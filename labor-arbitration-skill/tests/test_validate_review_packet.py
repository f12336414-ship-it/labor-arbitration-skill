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

from review_packet_policy import (  # noqa: E402
    calculate_review_packet_snapshot,
    calculate_review_subject_snapshot,
    validate_review_packet,
)


REPOSITORY_ROOT = SKILL_ROOT.parent
EXAMPLE_ROOT = REPOSITORY_ROOT / "examples" / "review-packets"
SCRIPT = SKILL_ROOT / "scripts" / "validate_review_packet.py"


def load_example(name):
    return json.loads((EXAMPLE_ROOT / name).read_text(encoding="utf-8"))


def lock_packet(packet):
    packet["review_subject_sha256"] = calculate_review_subject_snapshot(packet)
    for review in packet["cross_validation"]:
        review["review_subject_sha256"] = packet["review_subject_sha256"]
    packet["packet_snapshot_sha256"] = calculate_review_packet_snapshot(packet)
    return packet


def add_review(packet, *, decision="AGREE", response_decision="AGREE"):
    source_id = packet["source_artifacts"][0]["source_id"]
    packet["cross_validation"] = [
        {
            "review_id": "REVIEW-RECORD-001",
            "review_subject_sha256": packet["review_subject_sha256"],
            "reviewer_reference": "REVIEWER-PROJECT-001",
            "reviewer_role": "PROJECT_CROSS_VALIDATOR",
            "authentication_status": "UNAUTHENTICATED_SELF_DECLARATION",
            "recorded_at": "2026-07-15T01:00:00Z",
            "decision": decision,
            "question_responses": [
                {
                    "question_id": question["question_id"],
                    "decision": response_decision,
                    "basis_source_ids": (
                        [source_id]
                        if response_decision in {"AGREE", "DISAGREE"}
                        else []
                    ),
                    "comment": "Synthetic cross-validation fixture response.",
                }
                for question in packet["review_questions"]
            ],
            "basis_notes": "Synthetic record only; this is not authenticated legal approval.",
            "legal_approval_effect": "NONE",
        }
    ]
    packet["packet_status"] = "CROSS_VALIDATION_RECORDED"
    return lock_packet(packet)


class ReviewPacketValidationTests(unittest.TestCase):
    def run_cli(self, payload):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "review-packet.json"
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

    def test_all_three_published_examples_pass(self):
        expected_types = {
            "synthetic-rule-review.json": "RULE_REVIEW",
            "synthetic-claim-review.json": "CLAIM_REVIEW",
            "synthetic-calculator-review.json": "CALCULATOR_REVIEW",
        }
        for filename, packet_type in expected_types.items():
            with self.subTest(filename=filename):
                packet = load_example(filename)
                report = validate_review_packet(packet)
                self.assertTrue(report["allowed"], report["findings"])
                self.assertEqual(report["packet_type"], packet_type)
                self.assertFalse(report["submission_ready"])
                self.assertEqual(
                    report["cross_validation_effect"],
                    "RECORD_ONLY_NO_LEGAL_APPROVAL",
                )

    def test_cli_reports_truthful_scope_for_each_example(self):
        for path in sorted(EXAMPLE_ROOT.glob("*.json")):
            with self.subTest(path=path.name):
                result = subprocess.run(
                    [sys.executable, str(SCRIPT), str(path)],
                    cwd=SKILL_ROOT,
                    capture_output=True,
                    encoding="utf-8",
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                report = json.loads(result.stdout)
                self.assertEqual(
                    report["allowed_scope"], "STRUCTURAL_CROSS_VALIDATION_ONLY"
                )
                self.assertTrue(report["legal_review_required"])
                self.assertIn(
                    "PROFESSIONAL_LEGAL_APPROVAL",
                    report["validation_scope"]["not_verified"],
                )

    def test_subject_mutation_invalidates_subject_and_packet_snapshots(self):
        packet = load_example("synthetic-rule-review.json")
        packet["subject"]["candidate_proposition"] += " changed"

        report = validate_review_packet(packet)

        self.assertFalse(report["allowed"])
        codes = {item["code"] for item in report["findings"]}
        self.assertIn("REVIEW_SUBJECT_SNAPSHOT_MISMATCH", codes)
        self.assertIn("REVIEW_PACKET_SNAPSHOT_MISMATCH", codes)

    def test_complete_agreement_can_be_recorded_without_granting_approval(self):
        packet = add_review(load_example("synthetic-rule-review.json"))

        report = validate_review_packet(packet)

        self.assertTrue(report["allowed"], report["findings"])
        self.assertFalse(report["submission_ready"])
        self.assertEqual(
            report["next_required_state"], "INDEPENDENT_LEGAL_REVIEW"
        )

    def test_cross_validation_must_bind_current_subject(self):
        packet = add_review(load_example("synthetic-rule-review.json"))
        packet["cross_validation"][0]["review_subject_sha256"] = "f" * 64
        packet["packet_snapshot_sha256"] = calculate_review_packet_snapshot(packet)

        report = validate_review_packet(packet)

        self.assertIn(
            "REVIEW_SUBJECT_BINDING_MISMATCH",
            {item["code"] for item in report["findings"]},
        )

    def test_schema_rejects_an_approval_field(self):
        packet = load_example("synthetic-rule-review.json")
        packet["approvals"] = [{"approved": True}]
        lock_packet(packet)

        report = validate_review_packet(packet)

        self.assertIn(
            "REVIEW_PACKET_SCHEMA_VALIDATION_ERROR",
            {item["code"] for item in report["findings"]},
        )

    def test_source_candidate_must_remain_allowlisted_and_unverified(self):
        packet = load_example("synthetic-rule-review.json")
        packet["source_artifacts"][0]["canonical_url"] = "https://example.com/law"
        lock_packet(packet)

        report = validate_review_packet(packet)

        self.assertIn(
            "SOURCE_HOST_NOT_ALLOWLISTED",
            {item["code"] for item in report["findings"]},
        )

    def test_rule_provision_source_reference_must_exist(self):
        packet = load_example("synthetic-rule-review.json")
        packet["subject"]["provision_references"][0]["source_id"] = "SRC-UNKNOWN"
        lock_packet(packet)

        report = validate_review_packet(packet)

        self.assertIn(
            "REVIEW_PACKET_REFERENCE_UNKNOWN",
            {item["code"] for item in report["findings"]},
        )

    def test_review_must_answer_every_question_exactly_once(self):
        packet = add_review(load_example("synthetic-rule-review.json"))
        packet["cross_validation"][0]["question_responses"].pop()
        packet["packet_snapshot_sha256"] = calculate_review_packet_snapshot(packet)

        report = validate_review_packet(packet)

        self.assertIn(
            "REVIEW_QUESTION_COVERAGE_INCOMPLETE",
            {item["code"] for item in report["findings"]},
        )

    def test_agree_or_disagree_response_requires_a_declared_basis(self):
        packet = add_review(load_example("synthetic-rule-review.json"))
        packet["cross_validation"][0]["question_responses"][0][
            "basis_source_ids"
        ] = []
        packet["packet_snapshot_sha256"] = calculate_review_packet_snapshot(packet)

        report = validate_review_packet(packet)

        self.assertIn(
            "REVIEW_BASIS_REQUIRED",
            {item["code"] for item in report["findings"]},
        )

    def test_overall_review_decision_must_match_question_responses(self):
        packet = add_review(
            load_example("synthetic-rule-review.json"),
            decision="AGREE",
            response_decision="DISAGREE",
        )

        report = validate_review_packet(packet)

        self.assertIn(
            "REVIEW_DECISION_INCONSISTENT",
            {item["code"] for item in report["findings"]},
        )

    def test_overall_review_decision_uses_strict_disagreement_precedence(self):
        packet = add_review(
            load_example("synthetic-rule-review.json"),
            decision="NEEDS_MORE_EVIDENCE",
            response_decision="DISAGREE",
        )

        report = validate_review_packet(packet)

        self.assertIn(
            "REVIEW_DECISION_INCONSISTENT",
            {item["code"] for item in report["findings"]},
        )

    def test_unresolved_recorded_review_routes_back_to_packet_revision(self):
        packet = add_review(
            load_example("synthetic-rule-review.json"),
            decision="DISAGREE",
            response_decision="DISAGREE",
        )

        report = validate_review_packet(packet)

        self.assertTrue(report["allowed"], report["findings"])
        self.assertEqual(report["next_required_state"], "PACKET_REVISION")

    def test_revision_required_needs_a_non_agree_result(self):
        packet = add_review(load_example("synthetic-rule-review.json"))
        packet["packet_status"] = "REVISION_REQUIRED"
        lock_packet(packet)

        report = validate_review_packet(packet)

        self.assertIn(
            "REVIEW_PACKET_STATUS_INVALID",
            {item["code"] for item in report["findings"]},
        )

    def test_pending_legal_review_rejects_unresolved_cross_validation(self):
        packet = add_review(
            load_example("synthetic-rule-review.json"),
            decision="DISAGREE",
            response_decision="DISAGREE",
        )
        packet["packet_status"] = "PENDING_INDEPENDENT_LEGAL_REVIEW"
        lock_packet(packet)

        report = validate_review_packet(packet)

        self.assertIn(
            "REVIEW_PACKET_STATUS_INVALID",
            {item["code"] for item in report["findings"]},
        )

    def test_claim_cannot_be_both_compatible_and_mutually_exclusive(self):
        packet = load_example("synthetic-claim-review.json")
        other_claim = "CLAIM-SYNTHETIC-OTHER"
        packet["subject"]["compatible_claim_ids"] = [other_claim]
        packet["subject"]["mutually_exclusive_claim_ids"] = [other_claim]
        lock_packet(packet)

        report = validate_review_packet(packet)

        self.assertIn(
            "REVIEW_PACKET_CLAIM_RELATION_CONFLICT",
            {item["code"] for item in report["findings"]},
        )

    def test_calculator_vector_must_cover_exactly_the_declared_inputs(self):
        packet = load_example("synthetic-calculator-review.json")
        packet["subject"]["test_vectors"][0]["inputs"].pop("INPUT-WAGE-PAID")
        lock_packet(packet)

        report = validate_review_packet(packet)

        self.assertIn(
            "REVIEW_PACKET_TEST_VECTOR_INPUT_MISMATCH",
            {item["code"] for item in report["findings"]},
        )

    def test_claim_rule_ids_require_exact_version_bound_dependencies(self):
        packet = load_example("synthetic-claim-review.json")
        packet["subject"]["rule_dependencies"] = []
        lock_packet(packet)

        report = validate_review_packet(packet)

        self.assertIn(
            "REVIEW_PACKET_SCHEMA_VALIDATION_ERROR",
            {item["code"] for item in report["findings"]},
        )

    def test_extra_rule_dependency_cannot_hide_outside_declared_rule_ids(self):
        packet = load_example("synthetic-claim-review.json")
        extra_dependency = copy.deepcopy(packet["subject"]["rule_dependencies"][0])
        extra_dependency["rule_id"] = "RULE-UNDECLARED"
        packet["subject"]["rule_dependencies"].append(extra_dependency)
        lock_packet(packet)

        report = validate_review_packet(packet)

        self.assertIn(
            "REVIEW_PACKET_RULE_DEPENDENCY_MISMATCH",
            {item["code"] for item in report["findings"]},
        )

    def test_nested_calculator_rule_reference_must_be_declared(self):
        packet = load_example("synthetic-calculator-review.json")
        packet["subject"]["inputs"][0]["rule_ids"] = ["RULE-UNDECLARED"]
        lock_packet(packet)

        report = validate_review_packet(packet)

        self.assertIn(
            "REVIEW_PACKET_REFERENCE_UNKNOWN",
            {item["code"] for item in report["findings"]},
        )

    def test_rule_effective_interval_cannot_run_backwards(self):
        packet = load_example("synthetic-rule-review.json")
        packet["subject"]["effective_to"] = "2025-12-31"
        lock_packet(packet)

        report = validate_review_packet(packet)

        self.assertIn(
            "REVIEW_PACKET_DATE_INTERVAL_INVALID",
            {item["code"] for item in report["findings"]},
        )

    def test_packet_type_and_subject_are_discriminated_by_schema(self):
        packet = load_example("synthetic-claim-review.json")
        packet["packet_type"] = "RULE_REVIEW"
        packet["packet_id"] = "REVIEW-RULE-SYNTHETIC-MISMATCH"
        lock_packet(packet)

        report = validate_review_packet(packet)

        self.assertIn(
            "REVIEW_PACKET_SCHEMA_VALIDATION_ERROR",
            {item["code"] for item in report["findings"]},
        )

    def test_review_question_must_point_to_an_existing_subject_field(self):
        packet = load_example("synthetic-rule-review.json")
        packet["review_questions"][0]["subject_paths"] = [
            "$.subject.nonexistent_field"
        ]
        lock_packet(packet)

        report = validate_review_packet(packet)

        self.assertIn(
            "REVIEW_QUESTION_SUBJECT_PATH_UNKNOWN",
            {item["code"] for item in report["findings"]},
        )

    def test_cli_rejects_duplicate_json_keys(self):
        result = self.run_cli('{"schema_version":"1.0","schema_version":"1.0"}')

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            json.loads(result.stdout)["error"]["code"],
            "REVIEW_PACKET_INPUT_DUPLICATE_KEY",
        )

    def test_cli_rejects_non_standard_json_constants(self):
        result = self.run_cli('{"value":NaN}')

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            json.loads(result.stdout)["error"]["code"],
            "REVIEW_PACKET_INPUT_INVALID_CONSTANT",
        )

    def test_cli_rejects_non_object_root(self):
        result = self.run_cli([])

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            json.loads(result.stdout)["error"]["code"],
            "REVIEW_PACKET_INPUT_ROOT_NOT_OBJECT",
        )

    def test_examples_are_synthetic_and_contain_no_approval_claim(self):
        for path in sorted(EXAMPLE_ROOT.glob("*.json")):
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertIn("Synthetic", text)
                self.assertNotIn("HUMAN_APPROVED", text)
                self.assertNotIn("SUBMISSION_CANDIDATE", text)


if __name__ == "__main__":
    unittest.main()
