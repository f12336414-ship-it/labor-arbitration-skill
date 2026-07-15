import copy
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIRECTORY = SKILL_ROOT / "scripts"
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from frozen_source_store import (  # noqa: E402
    FrozenSourceStoreError,
    calculate_frozen_record_snapshot,
    freeze_fetched_source,
    validate_frozen_source_record,
)
from official_source_fetch import fetch_official_source  # noqa: E402
from source_fetch_policy import FetchRefusal, FetchedSource  # noqa: E402
import fetch_official_case as case_fetch_cli  # noqa: E402
import fetch_official_source as source_fetch_cli  # noqa: E402
from case_collection_ledger import CaseCollectionRefusal  # noqa: E402


VALID_URL = "https://flk.npc.gov.cn/detail?id=synthetic"
VALID_CERTIFICATE = b"synthetic-certificate"
VALID_CERTIFICATE_SHA256 = (
    "be6f6a10a8f6e9526f38bea1cefef1cd2f1fbee75c0d5f4cb27e3b6d788014bd"
)


class FakeSocket:
    def __init__(self, peer_ip="93.184.216.34", tls_version="TLSv1.3"):
        self.peer_ip = peer_ip
        self.tls_version = tls_version

    def getpeername(self):
        return (self.peer_ip, 443)

    def version(self):
        return self.tls_version

    def cipher(self):
        return ("TLS_AES_256_GCM_SHA384", "TLSv1.3", 256)

    def getpeercert(self, binary_form=False):
        return VALID_CERTIFICATE if binary_form else {}


class FakeResponse:
    def __init__(self, *, status=200, body=b"synthetic official body", headers=None):
        self.status = status
        self.body = body
        self.offset = 0
        self.headers = {
            "Content-Type": "text/html; charset=utf-8",
            "Content-Length": str(len(body)),
            "Date": "Wed, 15 Jul 2026 02:00:00 GMT",
            **(headers or {}),
        }

    def getheader(self, name):
        return self.headers.get(name)

    def read(self, size=-1):
        if size < 0:
            size = len(self.body) - self.offset
        chunk = self.body[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk


class FakeConnection:
    def __init__(self, response, *, peer_ip="93.184.216.34", tls_version="TLSv1.3"):
        self.response = response
        self.sock = FakeSocket(peer_ip, tls_version)
        self.request_data = None
        self.closed = False

    def connect(self):
        return None

    def request(self, method, target, headers):
        self.request_data = (method, target, headers)

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


def connection_factory(*connections):
    queue = list(connections)

    def factory(_host, _timeout):
        return queue.pop(0)

    return factory


def make_fetched(body=b"synthetic official body"):
    return FetchedSource(
        body=body,
        final_url=VALID_URL,
        media_type="text/html",
        network_hops=[
            {
                "url": VALID_URL,
                "status": 200,
                "peer_ip": "93.184.216.34",
                "tls_version": "TLSv1.3",
                "tls_cipher": "TLS_AES_256_GCM_SHA384",
                "peer_certificate_sha256": VALID_CERTIFICATE_SHA256,
                "redirect_location": None,
            }
        ],
        response_headers={
            "content_type": "text/html; charset=utf-8",
            "content_length": str(len(body)),
            "date": "Wed, 15 Jul 2026 02:00:00 GMT",
            "etag": None,
            "last_modified": None,
        },
        status=200,
    )


class OfficialSourceTransportTests(unittest.TestCase):
    def test_fetches_one_allowlisted_identity_encoded_response(self):
        connection = FakeConnection(FakeResponse())

        fetched = fetch_official_source(
            VALID_URL,
            "NATIONAL_LAWS_REGULATIONS_DATABASE",
            "NORMATIVE_LEGAL_SOURCE",
            connection_factory=connection_factory(connection),
        )

        self.assertEqual(fetched.body, b"synthetic official body")
        self.assertEqual(fetched.media_type, "text/html")
        self.assertEqual(fetched.network_hops[0]["peer_ip"], "93.184.216.34")
        self.assertEqual(connection.request_data[0], "GET")
        self.assertEqual(connection.request_data[2]["Accept-Encoding"], "identity")
        self.assertTrue(connection.closed)

    def test_redirect_must_remain_inside_exact_publisher_allowlist(self):
        response = FakeResponse(
            status=302,
            body=b"",
            headers={"Location": "https://example.com/not-official"},
        )
        connection = FakeConnection(response)

        with self.assertRaises(FetchRefusal) as captured:
            fetch_official_source(
                VALID_URL,
                "NATIONAL_LAWS_REGULATIONS_DATABASE",
                "NORMATIVE_LEGAL_SOURCE",
                connection_factory=connection_factory(connection),
            )

        self.assertEqual(captured.exception.code, "FETCH_TARGET_NOT_ALLOWLISTED")

    def test_private_network_peer_is_refused_before_http_request(self):
        connection = FakeConnection(FakeResponse(), peer_ip="127.0.0.1")

        with self.assertRaises(FetchRefusal) as captured:
            fetch_official_source(
                VALID_URL,
                "NATIONAL_LAWS_REGULATIONS_DATABASE",
                "NORMATIVE_LEGAL_SOURCE",
                connection_factory=connection_factory(connection),
            )

        self.assertEqual(captured.exception.code, "FETCH_PRIVATE_NETWORK_REFUSED")
        self.assertIsNone(connection.request_data)

    def test_non_identity_content_encoding_is_refused(self):
        connection = FakeConnection(
            FakeResponse(headers={"Content-Encoding": "gzip"})
        )

        with self.assertRaises(FetchRefusal) as captured:
            fetch_official_source(
                VALID_URL,
                "NATIONAL_LAWS_REGULATIONS_DATABASE",
                "NORMATIVE_LEGAL_SOURCE",
                connection_factory=connection_factory(connection),
            )

        self.assertEqual(captured.exception.code, "FETCH_CONTENT_ENCODING_REFUSED")

    def test_declared_and_streamed_response_limits_are_enforced(self):
        declared = FakeConnection(FakeResponse(body=b"12345"))
        with self.assertRaises(FetchRefusal) as captured:
            fetch_official_source(
                VALID_URL,
                "NATIONAL_LAWS_REGULATIONS_DATABASE",
                "NORMATIVE_LEGAL_SOURCE",
                max_response_bytes=4,
                connection_factory=connection_factory(declared),
            )
        self.assertEqual(captured.exception.code, "FETCH_RESPONSE_TOO_LARGE")

    def test_truncated_response_and_nan_timeout_are_refused(self):
        truncated = FakeConnection(
            FakeResponse(body=b"1234", headers={"Content-Length": "5"})
        )
        with self.assertRaises(FetchRefusal) as captured:
            fetch_official_source(
                VALID_URL,
                "NATIONAL_LAWS_REGULATIONS_DATABASE",
                "NORMATIVE_LEGAL_SOURCE",
                connection_factory=connection_factory(truncated),
            )
        self.assertEqual(captured.exception.code, "FETCH_CONTENT_LENGTH_MISMATCH")

        with self.assertRaises(FetchRefusal) as captured:
            fetch_official_source(
                VALID_URL,
                "NATIONAL_LAWS_REGULATIONS_DATABASE",
                "NORMATIVE_LEGAL_SOURCE",
                timeout_seconds=float("nan"),
            )
        self.assertEqual(captured.exception.code, "FETCH_TIMEOUT_INVALID")

        streamed_response = FakeResponse(
            body=b"12345", headers={"Content-Length": None}
        )
        streamed = FakeConnection(streamed_response)
        with self.assertRaises(FetchRefusal) as captured:
            fetch_official_source(
                VALID_URL,
                "NATIONAL_LAWS_REGULATIONS_DATABASE",
                "NORMATIVE_LEGAL_SOURCE",
                max_response_bytes=4,
                connection_factory=connection_factory(streamed),
            )
        self.assertEqual(captured.exception.code, "FETCH_RESPONSE_TOO_LARGE")

    def test_old_tls_and_unregistered_url_are_refused(self):
        old_tls = FakeConnection(FakeResponse(), tls_version="TLSv1.1")
        with self.assertRaises(FetchRefusal) as captured:
            fetch_official_source(
                VALID_URL,
                "NATIONAL_LAWS_REGULATIONS_DATABASE",
                "NORMATIVE_LEGAL_SOURCE",
                connection_factory=connection_factory(old_tls),
            )
        self.assertEqual(captured.exception.code, "FETCH_TLS_POLICY_REFUSED")

        with self.assertRaises(FetchRefusal) as captured:
            fetch_official_source(
                "https://example.com/law",
                "NATIONAL_LAWS_REGULATIONS_DATABASE",
                "NORMATIVE_LEGAL_SOURCE",
            )
        self.assertEqual(captured.exception.code, "FETCH_TARGET_NOT_ALLOWLISTED")

    def test_malformed_response_metadata_is_refused(self):
        cases = [
            (
                FakeConnection(FakeResponse(status=500)),
                {},
                "FETCH_HTTP_STATUS_REFUSED",
            ),
            (
                FakeConnection(FakeResponse(headers={"Content-Type": None})),
                {},
                "FETCH_MEDIA_TYPE_MISSING",
            ),
            (
                FakeConnection(FakeResponse(headers={"Content-Type": "image/png"})),
                {},
                "FETCH_MEDIA_TYPE_REFUSED",
            ),
            (
                FakeConnection(FakeResponse(headers={"Content-Length": "invalid"})),
                {},
                "FETCH_CONTENT_LENGTH_INVALID",
            ),
            (
                FakeConnection(FakeResponse(headers={"ETag": "x" * 1001})),
                {},
                "FETCH_RESPONSE_HEADER_TOO_LARGE",
            ),
        ]
        for connection, kwargs, expected in cases:
            with self.subTest(expected=expected):
                with self.assertRaises(FetchRefusal) as captured:
                    fetch_official_source(
                        VALID_URL,
                        "NATIONAL_LAWS_REGULATIONS_DATABASE",
                        "NORMATIVE_LEGAL_SOURCE",
                        connection_factory=connection_factory(connection),
                        **kwargs,
                    )
                self.assertEqual(captured.exception.code, expected)

    def test_invalid_transport_and_redirect_metadata_are_refused(self):
        missing_socket = FakeConnection(FakeResponse())
        missing_socket.sock = None
        invalid_peer = FakeConnection(FakeResponse(), peer_ip="not-an-ip")
        missing_location = FakeConnection(
            FakeResponse(status=302, body=b"", headers={"Location": None})
        )
        cases = [
            (missing_socket, "FETCH_TLS_CONNECTION_MISSING"),
            (invalid_peer, "FETCH_PEER_IP_INVALID"),
            (missing_location, "FETCH_REDIRECT_LOCATION_MISSING"),
        ]
        for connection, expected in cases:
            with self.subTest(expected=expected):
                with self.assertRaises(FetchRefusal) as captured:
                    fetch_official_source(
                        VALID_URL,
                        "NATIONAL_LAWS_REGULATIONS_DATABASE",
                        "NORMATIVE_LEGAL_SOURCE",
                        connection_factory=connection_factory(connection),
                    )
                self.assertEqual(captured.exception.code, expected)

        with self.assertRaises(FetchRefusal) as captured:
            fetch_official_source(
                VALID_URL,
                "NATIONAL_LAWS_REGULATIONS_DATABASE",
                "NORMATIVE_LEGAL_SOURCE",
                max_response_bytes=0,
            )
        self.assertEqual(captured.exception.code, "FETCH_SIZE_LIMIT_INVALID")

    def test_redirect_limit_is_enforced(self):
        redirect_url = "https://flk.npc.gov.cn/detail?id=next"
        connections = [
            FakeConnection(
                FakeResponse(status=302, body=b"", headers={"Location": redirect_url})
            )
            for _ in range(4)
        ]
        with self.assertRaises(FetchRefusal) as captured:
            fetch_official_source(
                VALID_URL,
                "NATIONAL_LAWS_REGULATIONS_DATABASE",
                "NORMATIVE_LEGAL_SOURCE",
                connection_factory=connection_factory(*connections),
            )
        self.assertEqual(captured.exception.code, "FETCH_REDIRECT_LIMIT_EXCEEDED")


class FrozenSourceStoreTests(unittest.TestCase):
    def freeze(self, root):
        return freeze_fetched_source(
            root,
            requested_url=VALID_URL,
            publisher_code="NATIONAL_LAWS_REGULATIONS_DATABASE",
            purpose="NORMATIVE_LEGAL_SOURCE",
            fetched=make_fetched(),
            fetched_at="2026-07-15T02:00:00Z",
        )

    def test_freeze_and_offline_replay_validate_exact_bytes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            record_path, record = self.freeze(root)

            report = validate_frozen_source_record(record, root)

            self.assertTrue(report["allowed"], report["findings"])
            self.assertTrue(record_path.is_file())
            object_path = root.joinpath(*Path(record["object_relative_path"]).parts)
            self.assertEqual(object_path.read_bytes(), make_fetched().body)
            self.assertFalse(report["submission_ready"])

    def test_same_fetch_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first_path, first_record = self.freeze(root)
            second_path, second_record = self.freeze(root)

            self.assertEqual(first_path, second_path)
            self.assertEqual(first_record, second_record)

    def test_mutated_object_fails_offline_replay(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _record_path, record = self.freeze(root)
            object_path = root.joinpath(*Path(record["object_relative_path"]).parts)
            object_path.write_bytes(b"tampered official body!")

            report = validate_frozen_source_record(record, root)

            self.assertIn(
                "FROZEN_OBJECT_HASH_MISMATCH",
                {item["code"] for item in report["findings"]},
            )

    def test_mutated_record_snapshot_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _record_path, record = self.freeze(root)
            record["media_type"] = "text/plain"

            report = validate_frozen_source_record(record, root)

            self.assertIn(
                "FROZEN_RECORD_SNAPSHOT_MISMATCH",
                {item["code"] for item in report["findings"]},
            )

    def test_stored_redirect_cannot_escape_allowlist(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _record_path, record = self.freeze(root)
            record["network_hops"][0]["url"] = "https://example.com/law"
            record["record_snapshot_sha256"] = calculate_frozen_record_snapshot(record)

            report = validate_frozen_source_record(record, root)

            self.assertIn(
                "FROZEN_NETWORK_HOP_NOT_ALLOWLISTED",
                {item["code"] for item in report["findings"]},
            )

    def test_invalid_time_and_immutable_conflicts_are_refused(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with self.assertRaises(FrozenSourceStoreError) as captured:
                freeze_fetched_source(
                    root / "bad-time",
                    requested_url=VALID_URL,
                    publisher_code="NATIONAL_LAWS_REGULATIONS_DATABASE",
                    purpose="NORMATIVE_LEGAL_SOURCE",
                    fetched=make_fetched(),
                    fetched_at="not-a-time",
                )
            self.assertEqual(captured.exception.code, "FROZEN_FETCH_TIME_INVALID")

            record_path, record = self.freeze(root / "record-conflict")
            record_path.write_text("{}", encoding="utf-8")
            with self.assertRaises(FrozenSourceStoreError) as captured:
                self.freeze(root / "record-conflict")
            self.assertEqual(captured.exception.code, "FROZEN_RECORD_CONFLICT")

            object_root = root / "object-conflict"
            digest = make_fetched().body
            import hashlib

            object_hash = hashlib.sha256(digest).hexdigest()
            object_path = object_root / "objects" / object_hash[:2] / f"{object_hash}.bin"
            object_path.parent.mkdir(parents=True)
            object_path.write_bytes(b"wrong synthetic bytes!!")
            with self.assertRaises(FrozenSourceStoreError) as captured:
                self.freeze(object_root)
            self.assertEqual(captured.exception.code, "FROZEN_OBJECT_CONFLICT")

    def test_record_path_redirect_size_and_missing_store_damage_are_detected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _record_path, original = self.freeze(root)

            damaged = copy.deepcopy(original)
            damaged["object_relative_path"] = "objects/00/" + "0" * 64 + ".bin"
            damaged["redirect_count"] = 1
            damaged["record_snapshot_sha256"] = calculate_frozen_record_snapshot(damaged)
            damaged_report = validate_frozen_source_record(damaged, root)

            size_damage = copy.deepcopy(original)
            size_damage["content_length"] += 1
            size_damage["record_snapshot_sha256"] = calculate_frozen_record_snapshot(
                size_damage
            )
            size_report = validate_frozen_source_record(size_damage, root)

            missing_report = validate_frozen_source_record(original, root / "missing")

        damaged_codes = {item["code"] for item in damaged_report["findings"]}
        self.assertIn("FROZEN_OBJECT_PATH_MISMATCH", damaged_codes)
        self.assertIn("FROZEN_REDIRECT_COUNT_MISMATCH", damaged_codes)
        self.assertIn(
            "FROZEN_OBJECT_SIZE_MISMATCH",
            {item["code"] for item in size_report["findings"]},
        )
        self.assertIn(
            "FROZEN_STORE_PATH_UNSAFE",
            {item["code"] for item in missing_report["findings"]},
        )

    def test_generated_record_schema_failure_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "frozen_source_store.validate_published_frozen_source_record",
            return_value=[{"code": "synthetic"}],
        ):
            with self.assertRaises(FrozenSourceStoreError) as captured:
                self.freeze(Path(temp_dir))
        self.assertEqual(captured.exception.code, "FROZEN_RECORD_GENERATION_INVALID")

    def test_offline_cli_replays_published_record_and_object(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            record_path, _record = self.freeze(root)
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_DIRECTORY / "validate_frozen_source.py"),
                    str(record_path),
                    "--store",
                    str(root),
                ],
                cwd=SKILL_ROOT,
                capture_output=True,
                encoding="utf-8",
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                json.loads(result.stdout)["allowed_scope"],
                "OFFLINE_FROZEN_RESPONSE_BODY_INTEGRITY_ONLY",
            )


class OfficialSourceFetchCliTests(unittest.TestCase):
    def run_source_cli(self, root, **patches):
        record = {
            "content_sha256": "a" * 64,
            "fetch_id": "FETCH-20260715T020000Z-aaaaaaaaaaaaaaaa",
            "object_relative_path": "objects/aa/" + "a" * 64 + ".bin",
        }
        report = {
            "allowed": True,
            "validation_scope": {"verified": [], "not_verified": []},
        }
        argv = [
            "fetch_official_source.py",
            VALID_URL,
            "--publisher-code",
            "NATIONAL_LAWS_REGULATIONS_DATABASE",
            "--purpose",
            "NORMATIVE_LEGAL_SOURCE",
            "--store",
            str(root),
        ]
        defaults = {
            "fetch": make_fetched(),
            "freeze": (root / "records" / "record.json", record),
            "report": report,
        }
        defaults.update(patches)
        output = io.StringIO()
        with patch.object(sys, "argv", argv), patch.object(
            source_fetch_cli, "fetch_official_source", side_effect=(
                defaults["fetch"] if isinstance(defaults["fetch"], BaseException) else None
            ), return_value=(
                None if isinstance(defaults["fetch"], BaseException) else defaults["fetch"]
            )
        ), patch.object(
            source_fetch_cli,
            "freeze_fetched_source",
            return_value=defaults["freeze"],
        ), patch.object(
            source_fetch_cli,
            "validate_frozen_source_record",
            return_value=defaults["report"],
        ), contextlib.redirect_stdout(output):
            code = source_fetch_cli.main()
        return code, json.loads(output.getvalue())

    def test_source_fetch_cli_success_and_validation_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            code, result = self.run_source_cli(root)
            blocked_code, blocked = self.run_source_cli(
                root, report={"allowed": False, "findings": []}
            )

        self.assertEqual(code, 0)
        self.assertTrue(result["allowed"])
        self.assertEqual(blocked_code, 2)
        self.assertFalse(blocked["allowed"])

    def test_source_fetch_cli_policy_and_dependency_failures(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            policy_code, policy = self.run_source_cli(
                root, fetch=FetchRefusal("FETCH_SYNTHETIC_REFUSAL", "refused")
            )
            dependency_code, dependency = self.run_source_cli(
                root, fetch=RuntimeError("synthetic dependency failure")
            )

        self.assertEqual(policy_code, 2)
        self.assertEqual(policy["error"]["code"], "FETCH_SYNTHETIC_REFUSAL")
        self.assertEqual(dependency_code, 2)
        self.assertEqual(
            dependency["error"]["code"], "FETCH_NETWORK_DEPENDENCY_FAILED"
        )

    def run_case_cli(self, root, **patches):
        record = {
            "content_sha256": "b" * 64,
            "fetch_id": "FETCH-20260715T020000Z-bbbbbbbbbbbbbbbb",
        }
        defaults = {
            "target_error": None,
            "reservation": {
                "reservation_id": "CASE-RESERVE-SYNTHETIC",
                "minimum_interval_seconds": 10,
            },
            "fetch": make_fetched(),
            "freeze": (root / "records" / "case.json", record),
            "report": {"allowed": True},
        }
        defaults.update(patches)
        argv = [
            "fetch_official_case.py",
            "https://www.court.gov.cn/synthetic-case",
            "--publisher-code",
            "SUPREME_PEOPLES_COURT",
            "--store",
            str(root),
            "--rate-limit-ledger",
            str(root / "ledger"),
        ]
        output = io.StringIO()
        with patch.object(sys, "argv", argv), patch.object(
            case_fetch_cli,
            "validate_fetch_target",
            side_effect=defaults["target_error"],
        ), patch.object(
            case_fetch_cli,
            "reserve_official_case_fetch",
            side_effect=(
                defaults["reservation"]
                if isinstance(defaults["reservation"], BaseException)
                else None
            ),
            return_value=(
                None
                if isinstance(defaults["reservation"], BaseException)
                else defaults["reservation"]
            ),
        ), patch.object(
            case_fetch_cli, "fetch_official_source", return_value=defaults["fetch"]
        ), patch.object(
            case_fetch_cli,
            "freeze_fetched_source",
            return_value=defaults["freeze"],
        ), patch.object(
            case_fetch_cli,
            "validate_frozen_source_record",
            return_value=defaults["report"],
        ), contextlib.redirect_stdout(output):
            code = case_fetch_cli.main()
        return code, json.loads(output.getvalue())

    def test_case_fetch_cli_success_policy_failure_and_invalid_replay(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            code, result = self.run_case_cli(root)
            refused_code, refused = self.run_case_cli(
                root,
                reservation=CaseCollectionRefusal(
                    "CASE_RATE_LIMIT_EXCEEDED", "too soon"
                ),
            )
            blocked_code, blocked = self.run_case_cli(
                root, report={"allowed": False, "findings": []}
            )

        self.assertEqual(code, 0)
        self.assertTrue(result["allowed"])
        self.assertEqual(refused_code, 2)
        self.assertEqual(refused["error"]["code"], "CASE_RATE_LIMIT_EXCEEDED")
        self.assertEqual(blocked_code, 2)
        self.assertFalse(blocked["allowed"])

    def test_case_fetch_cli_hides_unexpected_dependency_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            code, result = self.run_case_cli(
                root, target_error=RuntimeError("synthetic")
            )

        self.assertEqual(code, 2)
        self.assertEqual(
            result["error"]["code"], "CASE_FETCH_NETWORK_DEPENDENCY_FAILED"
        )


if __name__ == "__main__":
    unittest.main()
