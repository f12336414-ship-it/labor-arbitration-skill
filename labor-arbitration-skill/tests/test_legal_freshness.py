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
    calculate_legal_freshness_snapshot,
    validate_legal_freshness_check,
)


EXAMPLE_PATH = (
    REPOSITORY_ROOT
    / "examples"
    / "legal-sources"
    / "synthetic-freshness-unchanged.json"
)
SCRIPT = SCRIPT_DIRECTORY / "validate_legal_freshness.py"


def load_example():
    return json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))


def lock(check):
    check["check_snapshot_sha256"] = calculate_legal_freshness_snapshot(check)
    return check


def finding_codes(check):
    return {item["code"] for item in validate_legal_freshness_check(check)["findings"]}


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
