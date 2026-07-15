import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIRECTORY = SKILL_ROOT / "scripts"
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from formal_output_state_policy import (  # noqa: E402
    calculate_state_request_snapshot,
    validate_formal_output_state,
)


REPOSITORY_ROOT = SKILL_ROOT.parent
EXAMPLE_PATH = (
    REPOSITORY_ROOT
    / "examples"
    / "output-states"
    / "synthetic-internal-analysis.json"
)
SCRIPT = SCRIPT_DIRECTORY / "validate_formal_output_state.py"


def load_example():
    return json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))


def lock(request):
    request["state_request_sha256"] = calculate_state_request_snapshot(request)
    return request


def transition(request, state):
    next_request = copy.deepcopy(request)
    next_request["request_id"] = f"STATE-SYNTHETIC-{state}"
    next_request["previous_binding"] = {
        "artifact_id": request["artifact_id"],
        "artifact_type": request["artifact_type"],
        "state": request["requested_state"],
        "state_request_sha256": request["state_request_sha256"],
        "dependency_snapshots": copy.deepcopy(request["dependency_snapshots"]),
        "legal_freshness": copy.deepcopy(request["legal_freshness"]),
    }
    next_request["requested_state"] = state
    next_request["invalidation"] = {
        "status": "CURRENT",
        "changed_dependency_kinds": [],
        "reason": "Synthetic transition with unchanged dependencies.",
    }
    return lock(next_request)


class FormalOutputStateValidationTests(unittest.TestCase):
    def run_cli(self, payload):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "state-request.json"
            if isinstance(payload, str):
                path.write_text(payload, encoding="utf-8")
            else:
                path.write_text(
                    json.dumps(payload, ensure_ascii=False),
                    encoding="utf-8",
                )
            return subprocess.run(
                [sys.executable, str(SCRIPT), str(path)],
                cwd=SKILL_ROOT,
                capture_output=True,
                encoding="utf-8",
                check=False,
            )

    def test_published_initial_example_passes_truthful_scope(self):
        report = validate_formal_output_state(load_example())

        self.assertTrue(report["allowed"], report["findings"])
        self.assertEqual(report["allowed_scope"], "TECHNICAL_OUTPUT_STATE_ONLY")
        self.assertFalse(report["submission_ready"])
        self.assertIn("APPROVAL_AUTHENTICITY", report["validation_scope"]["not_verified"])

    def test_new_artifact_cannot_skip_internal_analysis(self):
        request = load_example()
        request["requested_state"] = "DRAFT"
        lock(request)

        report = validate_formal_output_state(request)

        self.assertIn(
            "OUTPUT_STATE_TRANSITION_INVALID",
            {item["code"] for item in report["findings"]},
        )

    def test_review_required_remains_blocked_until_dependencies_are_verified(self):
        draft = transition(load_example(), "DRAFT")
        review = transition(draft, "REVIEW_REQUIRED")

        report = validate_formal_output_state(review)

        self.assertIn(
            "OUTPUT_REVIEW_REQUIRED_UNSUPPORTED",
            {item["code"] for item in report["findings"]},
        )
        self.assertEqual(
            report["next_required_state"], "COMPLETE_TECHNICAL_PREREQUISITES"
        )
        self.assertFalse(report["submission_ready"])

    def test_previous_binding_cannot_borrow_another_artifact(self):
        draft = transition(load_example(), "DRAFT")
        draft["previous_binding"]["artifact_id"] = "OUTPUT-OTHER-ARTIFACT"
        lock(draft)

        report = validate_formal_output_state(draft)

        self.assertIn(
            "OUTPUT_PREVIOUS_BINDING_MISMATCH",
            {item["code"] for item in report["findings"]},
        )

    def test_dependency_change_is_allowed_only_with_exact_invalidation(self):
        draft = transition(load_example(), "DRAFT")
        changed = transition(draft, "DRAFT")
        changed["dependency_snapshots"]["case_sha256"] = "a" * 64
        changed["invalidation"] = {
            "status": "INVALIDATED_BY_DEPENDENCY_CHANGE",
            "changed_dependency_kinds": ["CASE"],
            "reason": "Synthetic case snapshot changed.",
        }
        lock(changed)

        report = validate_formal_output_state(changed)

        self.assertTrue(report["allowed"], report["findings"])
        self.assertEqual(report["changed_dependency_kinds"], ["CASE"])
        self.assertEqual(report["next_required_state"], "REVALIDATE_CHANGED_DEPENDENCIES")

    def test_declared_change_list_must_exactly_match_snapshots(self):
        draft = transition(load_example(), "DRAFT")
        changed = transition(draft, "DRAFT")
        changed["dependency_snapshots"]["case_sha256"] = "a" * 64
        changed["invalidation"] = {
            "status": "INVALIDATED_BY_DEPENDENCY_CHANGE",
            "changed_dependency_kinds": ["DOCUMENT"],
            "reason": "Deliberately incorrect synthetic declaration.",
        }
        lock(changed)

        report = validate_formal_output_state(changed)

        self.assertIn(
            "OUTPUT_INVALIDATION_DECLARATION_MISMATCH",
            {item["code"] for item in report["findings"]},
        )

    def test_changed_dependency_cannot_retain_review_required(self):
        draft = transition(load_example(), "DRAFT")
        review = transition(draft, "REVIEW_REQUIRED")
        review["dependency_snapshots"]["legal_sources_sha256"] = "a" * 64
        review["invalidation"] = {
            "status": "INVALIDATED_BY_DEPENDENCY_CHANGE",
            "changed_dependency_kinds": ["LEGAL_SOURCES"],
            "reason": "Synthetic legal source changed.",
        }
        lock(review)

        report = validate_formal_output_state(review)

        self.assertIn(
            "OUTPUT_STATE_REVALIDATION_REQUIRED",
            {item["code"] for item in report["findings"]},
        )

    def test_unchanged_dependencies_require_current_declaration(self):
        draft = transition(load_example(), "DRAFT")
        draft["invalidation"]["status"] = "INVALIDATED_BY_DEPENDENCY_CHANGE"
        lock(draft)

        report = validate_formal_output_state(draft)

        self.assertIn(
            "OUTPUT_INVALIDATION_DECLARATION_MISMATCH",
            {item["code"] for item in report["findings"]},
        )

    def test_submission_candidate_is_always_blocked(self):
        draft = transition(load_example(), "DRAFT")
        submission = transition(draft, "SUBMISSION_CANDIDATE")

        report = validate_formal_output_state(submission)

        self.assertIn(
            "SUBMISSION_STATE_UNSUPPORTED",
            {item["code"] for item in report["findings"]},
        )
        self.assertFalse(report["submission_ready"])

    def test_failed_freshness_allows_draft_but_not_review_required(self):
        draft = transition(load_example(), "DRAFT")
        draft["legal_freshness"] = {
            "status": "UNAVAILABLE_DRAFT_ONLY",
            "check_id": "FRESH-SYNTHETIC-UNAVAILABLE",
            "check_snapshot_sha256": "a" * 64,
        }
        draft["invalidation"] = {
            "status": "INVALIDATED_BY_DEPENDENCY_CHANGE",
            "changed_dependency_kinds": ["LEGAL_SOURCES"],
            "reason": "Synthetic freshness check was unavailable.",
        }
        lock(draft)
        draft_report = validate_formal_output_state(draft)
        review = transition(draft, "REVIEW_REQUIRED")
        review_report = validate_formal_output_state(review)

        self.assertTrue(draft_report["allowed"], draft_report["findings"])
        self.assertIn(
            "OUTPUT_LEGAL_FRESHNESS_DRAFT_ONLY",
            {item["code"] for item in review_report["findings"]},
        )

    def test_successful_freshness_is_bound_but_grants_no_promotion(self):
        draft = transition(load_example(), "DRAFT")
        draft["legal_freshness"] = {
            "status": "UNCHANGED_RESPONSE_BODY_CANDIDATE",
            "check_id": "FRESH-SYNTHETIC-WAGE-RULE",
            "check_snapshot_sha256": "b" * 64,
        }
        draft["invalidation"] = {
            "status": "INVALIDATED_BY_DEPENDENCY_CHANGE",
            "changed_dependency_kinds": ["LEGAL_SOURCES"],
            "reason": "Synthetic freshness observation is now bound.",
        }
        lock(draft)

        report = validate_formal_output_state(draft)

        self.assertTrue(report["allowed"], report["findings"])
        self.assertFalse(report["submission_ready"])

    def test_json_approval_cannot_be_added(self):
        request = load_example()
        request["approvals"] = [{"reviewer": "SELF"}]
        lock(request)

        report = validate_formal_output_state(request)

        self.assertIn(
            "OUTPUT_STATE_SCHEMA_VALIDATION_ERROR",
            {item["code"] for item in report["findings"]},
        )

    def test_request_mutation_invalidates_rfc8785_snapshot(self):
        request = load_example()
        request["artifact_type"] = "EVIDENCE_REPORT"

        report = validate_formal_output_state(request)

        self.assertIn(
            "OUTPUT_STATE_REQUEST_SNAPSHOT_MISMATCH",
            {item["code"] for item in report["findings"]},
        )

    def test_non_utc_generation_time_is_blocked(self):
        request = load_example()
        request["generated_at"] = "2026-07-15T10:00:00+08:00"
        lock(request)

        report = validate_formal_output_state(request)

        self.assertIn(
            "DATE_FORMAT_INVALID",
            {item["code"] for item in report["findings"]},
        )

    def test_cli_accepts_published_example(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(EXAMPLE_PATH)],
            cwd=SKILL_ROOT,
            capture_output=True,
            encoding="utf-8",
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)["submission_ready"])

    def test_cli_rejects_duplicate_keys(self):
        result = self.run_cli('{"schema_version":"1.0","schema_version":"1.0"}')

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            json.loads(result.stdout)["error"]["code"],
            "OUTPUT_STATE_INPUT_DUPLICATE_KEY",
        )

    def test_cli_rejects_non_standard_numbers(self):
        result = self.run_cli('{"value":NaN}')

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            json.loads(result.stdout)["error"]["code"],
            "OUTPUT_STATE_INPUT_INVALID_CONSTANT",
        )

    def test_cli_rejects_non_object_root(self):
        result = self.run_cli([])

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            json.loads(result.stdout)["error"]["code"],
            "OUTPUT_STATE_INPUT_ROOT_NOT_OBJECT",
        )


if __name__ == "__main__":
    unittest.main()
