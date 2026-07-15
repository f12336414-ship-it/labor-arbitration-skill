import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = SKILL_ROOT.parent
SCRIPT_DIRECTORY = SKILL_ROOT / "scripts"
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from legal_freshness_policy import (  # noqa: E402
    build_legal_freshness_check,
    calculate_legal_freshness_snapshot,
    validate_legal_freshness_check,
)
from frozen_source_store import freeze_fetched_source  # noqa: E402
from source_fetch_policy import FetchedSource  # noqa: E402


EXAMPLE_PATH = (
    REPOSITORY_ROOT
    / "examples"
    / "legal-sources"
    / "synthetic-freshness-unchanged.json"
)
SCRIPT = SCRIPT_DIRECTORY / "validate_legal_freshness.py"
BUILD_SCRIPT = SCRIPT_DIRECTORY / "build_legal_freshness.py"


def load_example():
    return json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))


def lock(check):
    check["check_snapshot_sha256"] = calculate_legal_freshness_snapshot(check)
    return check


def finding_codes(check):
    return {item["code"] for item in validate_legal_freshness_check(check)["findings"]}


def fetched(body):
    url = "https://flk.npc.gov.cn/detail?id=synthetic"
    return FetchedSource(
        body=body,
        final_url=url,
        media_type="text/html",
        network_hops=[
            {
                "url": url,
                "status": 200,
                "peer_ip": "93.184.216.34",
                "tls_version": "TLSv1.3",
                "tls_cipher": "TLS_AES_256_GCM_SHA384",
                "peer_certificate_sha256": "a" * 64,
                "redirect_location": None,
            }
        ],
        response_headers={
            "content_type": "text/html",
            "content_length": str(len(body)),
            "date": None,
            "etag": None,
            "last_modified": None,
        },
        status=200,
    )


class LegalFreshnessTests(unittest.TestCase):
    def run_cli(self, payload):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "freshness.json"
            if isinstance(payload, str):
                path.write_text(payload, encoding="utf-8")
            else:
                path.write_text(json.dumps(payload), encoding="utf-8")
            return subprocess.run(
                [sys.executable, str(SCRIPT), str(path)],
                cwd=SKILL_ROOT,
                capture_output=True,
                encoding="utf-8",
                check=False,
            )

    def test_unchanged_example_passes_without_granting_promotion(self):
        report = validate_legal_freshness_check(load_example())

        self.assertTrue(report["allowed"], report["findings"])
        self.assertFalse(report["allows_formal_promotion"])
        self.assertFalse(report["submission_ready"])
        self.assertIn("LEGAL_CURRENTNESS", report["validation_scope"]["not_verified"])

    def test_changed_content_requires_review_and_draft(self):
        check = load_example()
        check["observation"]["content_sha256"] = "a" * 64
        check["response_change"] = "CHANGED"
        check["technical_freshness_status"] = "CHANGE_DETECTED_REVIEW_REQUIRED"
        lock(check)

        report = validate_legal_freshness_check(check)

        self.assertTrue(report["allowed"], report["findings"])
        self.assertEqual(report["required_output_state"], "DRAFT")

    def test_unavailable_check_requires_no_observation_and_draft(self):
        check = load_example()
        check["network_status"] = "UNAVAILABLE"
        check["observation"] = None
        check["response_change"] = "UNKNOWN"
        check["technical_freshness_status"] = "UNAVAILABLE_DRAFT_ONLY"
        lock(check)

        report = validate_legal_freshness_check(check)

        self.assertTrue(report["allowed"], report["findings"])
        self.assertEqual(report["required_output_state"], "DRAFT")

    def test_builder_derives_unchanged_changed_and_unavailable_states(self):
        template = load_example()
        cases = [
            (copy.deepcopy(template["observation"]), "UNCHANGED_RESPONSE_BODY_CANDIDATE"),
            (copy.deepcopy(template["observation"]), "CHANGE_DETECTED_REVIEW_REQUIRED"),
            (None, "UNAVAILABLE_DRAFT_ONLY"),
        ]
        cases[1][0]["content_sha256"] = "a" * 64
        for observation, expected in cases:
            check = build_legal_freshness_check(
                document_id=template["document_id"],
                publisher_code=template["publisher_code"],
                baseline=copy.deepcopy(template["baseline"]),
                observation=observation,
                checked_at=template["checked_at"],
                max_age_hours=template["max_age_hours"],
            )
            with self.subTest(expected=expected):
                self.assertEqual(check["technical_freshness_status"], expected)
                self.assertTrue(validate_legal_freshness_check(check)["allowed"])

    def test_stale_observation_requires_draft(self):
        check = load_example()
        check["baseline"]["fetched_at"] = "2026-07-12T00:00:00Z"
        check["observation"]["fetched_at"] = "2026-07-13T00:00:00Z"
        check["technical_freshness_status"] = "STALE_DRAFT_ONLY"
        lock(check)

        report = validate_legal_freshness_check(check)

        self.assertTrue(report["allowed"], report["findings"])
        self.assertEqual(report["required_output_state"], "DRAFT")

    def test_status_cannot_disagree_with_bound_hashes(self):
        check = load_example()
        check["observation"]["content_sha256"] = "a" * 64
        lock(check)

        self.assertIn("LEGAL_FRESHNESS_DERIVATION_MISMATCH", finding_codes(check))

    def test_success_requires_observation(self):
        check = load_example()
        check["observation"] = None
        check["response_change"] = "UNKNOWN"
        check["technical_freshness_status"] = "UNAVAILABLE_DRAFT_ONLY"
        lock(check)

        self.assertIn("LEGAL_FRESHNESS_OBSERVATION_MISMATCH", finding_codes(check))

    def test_success_cannot_reuse_baseline_as_observation(self):
        check = load_example()
        check["observation"] = copy.deepcopy(check["baseline"])
        lock(check)

        self.assertIn("LEGAL_FRESHNESS_OBSERVATION_NOT_LATER", finding_codes(check))

    def test_future_observation_is_blocked(self):
        check = load_example()
        check["observation"]["fetched_at"] = "2026-07-15T04:00:00Z"
        lock(check)

        self.assertIn("LEGAL_FRESHNESS_TIME_ORDER_INVALID", finding_codes(check))

    def test_off_allowlist_binding_is_blocked(self):
        check = load_example()
        check["baseline"]["final_url"] = "https://example.com/rule"
        lock(check)

        self.assertIn("LEGAL_FRESHNESS_SOURCE_NOT_ALLOWLISTED", finding_codes(check))

    def test_mutation_without_new_snapshot_is_blocked(self):
        check = load_example()
        check["document_id"] = "SYNTHETIC_OTHER_RULE"

        self.assertIn("LEGAL_FRESHNESS_SNAPSHOT_MISMATCH", finding_codes(check))

    def test_cli_accepts_published_example(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(EXAMPLE_PATH)],
            cwd=SKILL_ROOT,
            capture_output=True,
            encoding="utf-8",
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(json.loads(result.stdout)["submission_ready"])

    def test_build_cli_uses_replayable_frozen_records_and_handles_unavailable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            baseline_path, _baseline = freeze_fetched_source(
                root,
                requested_url="https://flk.npc.gov.cn/detail?id=synthetic",
                publisher_code="NATIONAL_LAWS_REGULATIONS_DATABASE",
                purpose="NORMATIVE_LEGAL_SOURCE",
                fetched=fetched(b"same legal source bytes"),
                fetched_at="2026-07-14T03:00:00Z",
            )
            observation_path, _observation = freeze_fetched_source(
                root,
                requested_url="https://flk.npc.gov.cn/detail?id=synthetic",
                publisher_code="NATIONAL_LAWS_REGULATIONS_DATABASE",
                purpose="NORMATIVE_LEGAL_SOURCE",
                fetched=fetched(b"same legal source bytes"),
                fetched_at="2026-07-15T02:59:00Z",
            )
            common = [
                sys.executable,
                str(BUILD_SCRIPT),
                str(baseline_path),
                "--store",
                str(root),
                "--document-id",
                "SYNTHETIC_WAGE_RULE",
                "--publisher-code",
                "NATIONAL_LAWS_REGULATIONS_DATABASE",
                "--checked-at",
                "2026-07-15T03:00:00Z",
                "--max-age-hours",
                "24",
            ]
            unchanged = subprocess.run(
                [*common, "--observation-record", str(observation_path)],
                cwd=SKILL_ROOT,
                capture_output=True,
                encoding="utf-8",
                check=False,
            )
            unavailable = subprocess.run(
                [*common, "--unavailable"],
                cwd=SKILL_ROOT,
                capture_output=True,
                encoding="utf-8",
                check=False,
            )

        self.assertEqual(unchanged.returncode, 0, unchanged.stdout + unchanged.stderr)
        self.assertEqual(json.loads(unchanged.stdout)["technical_freshness_status"], "UNCHANGED_RESPONSE_BODY_CANDIDATE")
        self.assertEqual(unavailable.returncode, 0, unavailable.stdout + unavailable.stderr)
        self.assertEqual(json.loads(unavailable.stdout)["technical_freshness_status"], "UNAVAILABLE_DRAFT_ONLY")

    def test_cli_rejects_duplicate_keys(self):
        result = self.run_cli('{"schema_version":"1.0","schema_version":"1.0"}')

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            json.loads(result.stdout)["error"]["code"],
            "LEGAL_FRESHNESS_INPUT_DUPLICATE_KEY",
        )

    def test_cli_rejects_non_standard_number_and_non_object(self):
        invalid_number = self.run_cli('{"value":NaN}')
        invalid_root = self.run_cli([])

        self.assertEqual(invalid_number.returncode, 1)
        self.assertEqual(
            json.loads(invalid_number.stdout)["error"]["code"],
            "LEGAL_FRESHNESS_INPUT_INVALID_CONSTANT",
        )
        self.assertEqual(invalid_root.returncode, 1)
        self.assertEqual(
            json.loads(invalid_root.stdout)["error"]["code"],
            "LEGAL_FRESHNESS_INPUT_ROOT_NOT_OBJECT",
        )


if __name__ == "__main__":
    unittest.main()
