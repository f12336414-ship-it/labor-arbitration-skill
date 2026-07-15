import copy
import json
import os
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

from case_collection_ledger import (  # noqa: E402
    CaseCollectionRefusal,
    LEDGER_FILENAME,
    LOCK_FILENAME,
    MAX_LEDGER_BYTES,
    reserve_official_case_fetch,
)
from frozen_source_store import (  # noqa: E402
    calculate_frozen_record_snapshot,
    freeze_fetched_source,
)
from official_case_policy import (  # noqa: E402
    OfficialCaseRecordError,
    build_official_case_record,
    calculate_official_case_record_snapshot,
    validate_official_case_record,
)
from source_fetch_policy import FetchedSource  # noqa: E402


CASE_URL = "https://www.court.gov.cn/zixun/xiangqing/synthetic.html"


def make_fetched(body=b"synthetic public case body"):
    return FetchedSource(
        body=body,
        final_url=CASE_URL,
        media_type="text/html",
        network_hops=[
            {
                "url": CASE_URL,
                "status": 200,
                "peer_ip": "93.184.216.34",
                "tls_version": "TLSv1.3",
                "tls_cipher": "TLS_AES_256_GCM_SHA384",
                "peer_certificate_sha256": "a" * 64,
                "redirect_location": None,
            }
        ],
        response_headers={
            "content_type": "text/html; charset=utf-8",
            "content_length": str(len(body)),
            "date": "Wed, 15 Jul 2026 04:00:00 GMT",
            "etag": None,
            "last_modified": None,
        },
        status=200,
    )


def freeze_case(root, *, purpose="OFFICIAL_CASE"):
    return freeze_fetched_source(
        root,
        requested_url=CASE_URL,
        publisher_code="SUPREME_PEOPLES_COURT",
        purpose=purpose,
        fetched=make_fetched(),
        fetched_at="2026-07-15T04:00:00Z",
    )


def build_case(record):
    return build_official_case_record(
        record,
        dispute_categories=["WAGE_OR_WAGE_DIFFERENCE"],
        document_type="PUBLIC_JUDGMENT",
        procedural_stage="SECOND_INSTANCE",
        jurisdiction_scope="NATIONAL",
        classified_at="2026-07-15T04:05:00Z",
    )


class CaseCollectionRateLimitTests(unittest.TestCase):
    def test_minimum_interval_is_persisted_and_enforced(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = reserve_official_case_fetch(
                root,
                "SUPREME_PEOPLES_COURT",
                reserved_at="2026-07-15T04:00:00Z",
            )
            with self.assertRaises(CaseCollectionRefusal) as too_soon:
                reserve_official_case_fetch(
                    root,
                    "SUPREME_PEOPLES_COURT",
                    reserved_at="2026-07-15T04:00:09Z",
                )
            second = reserve_official_case_fetch(
                root,
                "SUPREME_PEOPLES_COURT",
                reserved_at="2026-07-15T04:00:10Z",
            )

        self.assertEqual(first["minimum_interval_seconds"], 10)
        self.assertEqual(too_soon.exception.code, "CASE_RATE_LIMIT_EXCEEDED")
        self.assertNotEqual(first["reservation_id"], second["reservation_id"])

    def test_clock_rollback_is_refused(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reserve_official_case_fetch(
                root,
                "SUPREME_PEOPLES_COURT",
                reserved_at="2026-07-15T04:00:10Z",
            )
            with self.assertRaises(CaseCollectionRefusal) as context:
                reserve_official_case_fetch(
                    root,
                    "SUPREME_PEOPLES_COURT",
                    reserved_at="2026-07-15T04:00:00Z",
                )

        self.assertEqual(context.exception.code, "CASE_RATE_LIMIT_CLOCK_ROLLBACK")

    def test_existing_lock_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / LOCK_FILENAME).write_text("busy", encoding="utf-8")
            with self.assertRaises(CaseCollectionRefusal) as context:
                reserve_official_case_fetch(
                    root,
                    "SUPREME_PEOPLES_COURT",
                    reserved_at="2026-07-15T04:00:00Z",
                )

        self.assertEqual(context.exception.code, "CASE_RATE_LIMIT_BUSY")

    def test_publisher_without_case_purpose_is_refused(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(CaseCollectionRefusal) as context:
                reserve_official_case_fetch(
                    Path(temp_dir),
                    "NATIONAL_LAWS_REGULATIONS_DATABASE",
                    reserved_at="2026-07-15T04:00:00Z",
                )

        self.assertEqual(
            context.exception.code, "CASE_COLLECTION_PUBLISHER_NOT_ALLOWED"
        )

    def test_corrupt_or_ambiguous_ledger_is_refused(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "official-case-rate-limit.json").write_text(
                '{"schema_version":"1.0","schema_version":"1.0"}',
                encoding="utf-8",
            )
            with self.assertRaises(CaseCollectionRefusal) as context:
                reserve_official_case_fetch(
                    root,
                    "SUPREME_PEOPLES_COURT",
                    reserved_at="2026-07-15T04:00:00Z",
                )

        self.assertEqual(context.exception.code, "CASE_RATE_LIMIT_LEDGER_INVALID")

    def test_invalid_time_and_unsafe_ledger_root_are_refused(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with self.assertRaises(CaseCollectionRefusal) as captured:
                reserve_official_case_fetch(
                    root, "SUPREME_PEOPLES_COURT", reserved_at="not-a-time"
                )
            self.assertEqual(captured.exception.code, "CASE_RATE_LIMIT_TIME_INVALID")

            unsafe_root = root / "plain-file"
            unsafe_root.write_text("not a directory", encoding="utf-8")
            with self.assertRaises(CaseCollectionRefusal) as captured:
                reserve_official_case_fetch(
                    unsafe_root,
                    "SUPREME_PEOPLES_COURT",
                    reserved_at="2026-07-15T04:00:00Z",
                )
            self.assertEqual(captured.exception.code, "CASE_RATE_LIMIT_PATH_UNSAFE")

    def test_oversized_or_structurally_invalid_ledger_is_refused(self):
        payloads = [
            b"x" * (MAX_LEDGER_BYTES + 1),
            b"[]",
            b'{"value":NaN}',
        ]
        for payload in payloads:
            with self.subTest(size=len(payload)), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                (root / LEDGER_FILENAME).write_bytes(payload)
                with self.assertRaises(CaseCollectionRefusal) as captured:
                    reserve_official_case_fetch(
                        root,
                        "SUPREME_PEOPLES_COURT",
                        reserved_at="2026-07-15T04:00:00Z",
                    )
                self.assertEqual(
                    captured.exception.code, "CASE_RATE_LIMIT_LEDGER_INVALID"
                )

    def test_invalid_publisher_reservation_is_refused(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reserve_official_case_fetch(
                root,
                "SUPREME_PEOPLES_COURT",
                reserved_at="2026-07-15T04:00:00Z",
            )
            ledger_path = root / LEDGER_FILENAME
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            ledger["entries"]["SUPREME_PEOPLES_COURT"]["reservation_id"] = "invalid"
            from case_collection_ledger import calculate_case_collection_ledger_snapshot

            ledger["ledger_snapshot_sha256"] = calculate_case_collection_ledger_snapshot(
                ledger
            )
            ledger_path.write_text(json.dumps(ledger), encoding="utf-8")

            with self.assertRaises(CaseCollectionRefusal) as captured:
                reserve_official_case_fetch(
                    root,
                    "SUPREME_PEOPLES_COURT",
                    reserved_at="2026-07-15T04:00:20Z",
                )
        self.assertEqual(captured.exception.code, "CASE_RATE_LIMIT_LEDGER_INVALID")

    def test_persistence_failure_does_not_leave_lock(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch("case_collection_ledger.os.replace", side_effect=OSError):
                with self.assertRaises(CaseCollectionRefusal) as captured:
                    reserve_official_case_fetch(
                        root,
                        "SUPREME_PEOPLES_COURT",
                        reserved_at="2026-07-15T04:00:00Z",
                    )
            self.assertEqual(
                captured.exception.code, "CASE_RATE_LIMIT_LEDGER_WRITE_FAILED"
            )
            self.assertFalse((root / LOCK_FILENAME).exists())


class OfficialCaseRecordTests(unittest.TestCase):
    def test_case_record_is_privacy_gated_and_never_redistributable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            _path, frozen = freeze_case(Path(temp_dir))
            record = build_case(frozen)

        report = validate_official_case_record(record)

        self.assertTrue(report["allowed"], report["findings"])
        self.assertEqual(record["redistribution_status"], "BLOCKED")
        self.assertFalse(report["redistribution_allowed"])
        self.assertFalse(report["submission_ready"])

    def test_normative_source_cannot_be_relabelled_as_case(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            _path, frozen = freeze_case(Path(temp_dir), purpose="NORMATIVE_LEGAL_SOURCE")
            with self.assertRaises(OfficialCaseRecordError) as context:
                build_case(frozen)

        self.assertEqual(
            context.exception.code, "OFFICIAL_CASE_FROZEN_SOURCE_INVALID"
        )

    def test_off_allowlist_source_is_blocked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            _path, frozen = freeze_case(Path(temp_dir))
            record = build_case(frozen)
        record["source_binding"]["final_url"] = "https://example.com/case"
        record["case_record_snapshot_sha256"] = (
            calculate_official_case_record_snapshot(record)
        )

        codes = {
            item["code"]
            for item in validate_official_case_record(record)["findings"]
        }
        self.assertIn("OFFICIAL_CASE_SOURCE_NOT_ALLOWLISTED", codes)

    def test_categories_must_be_sorted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            _path, frozen = freeze_case(Path(temp_dir))
            record = build_case(frozen)
        record["classification"]["dispute_categories"] = [
            "WAGE_OR_WAGE_DIFFERENCE",
            "OVERTIME_PAY",
        ]
        record["case_record_snapshot_sha256"] = (
            calculate_official_case_record_snapshot(record)
        )

        codes = {
            item["code"]
            for item in validate_official_case_record(record)["findings"]
        }
        self.assertIn("OFFICIAL_CASE_CLASSIFICATION_ORDER_INVALID", codes)

    def test_mutation_without_new_snapshot_is_blocked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            _path, frozen = freeze_case(Path(temp_dir))
            record = build_case(frozen)
        record["classification"]["procedural_stage"] = "FIRST_INSTANCE"

        codes = {
            item["code"]
            for item in validate_official_case_record(record)["findings"]
        }
        self.assertIn("OFFICIAL_CASE_SNAPSHOT_MISMATCH", codes)

    def test_rehashed_classification_change_still_invalidates_artifact_id(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            _path, frozen = freeze_case(Path(temp_dir))
            record = build_case(frozen)
        record["classification"]["procedural_stage"] = "FIRST_INSTANCE"
        record["case_record_snapshot_sha256"] = (
            calculate_official_case_record_snapshot(record)
        )

        codes = {
            item["code"]
            for item in validate_official_case_record(record)["findings"]
        }
        self.assertIn("OFFICIAL_CASE_ARTIFACT_ID_MISMATCH", codes)

    def test_build_and_validate_clis_use_frozen_case(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            record_path, _frozen = freeze_case(root)
            built = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_DIRECTORY / "build_official_case_record.py"),
                    str(record_path),
                    "--store",
                    str(root),
                    "--category",
                    "WAGE_OR_WAGE_DIFFERENCE",
                    "--document-type",
                    "PUBLIC_JUDGMENT",
                    "--procedural-stage",
                    "SECOND_INSTANCE",
                    "--jurisdiction-scope",
                    "NATIONAL",
                ],
                cwd=SKILL_ROOT,
                capture_output=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            case_path = root / "case-record.json"
            case_path.write_text(built.stdout, encoding="utf-8")
            validated = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_DIRECTORY / "validate_official_case_record.py"),
                    str(case_path),
                ],
                cwd=SKILL_ROOT,
                capture_output=True,
                encoding="utf-8",
                check=False,
            )

        self.assertEqual(validated.returncode, 0, validated.stdout + validated.stderr)
        self.assertFalse(json.loads(validated.stdout)["redistribution_allowed"])


if __name__ == "__main__":
    unittest.main()
