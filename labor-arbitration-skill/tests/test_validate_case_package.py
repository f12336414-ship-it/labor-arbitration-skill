import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.case_package_factory import (
    calculate_dependency_snapshot,
    calculate_state_request,
    calculate_statement_snapshot,
    calculate_snapshot,
    make_intake_manifest,
    make_valid_machine_candidate,
    make_valid_reference_integrity_package,
)


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_ROOT / "scripts" / "validate_case_package.py"


def load_validator():
    spec = importlib.util.spec_from_file_location("validator_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VALIDATOR = load_validator()


def run_validator(package, include_intake_manifest=True, intake_manifest=None):
    with tempfile.TemporaryDirectory() as temp_dir:
        package_path = Path(temp_dir) / "case-package.json"
        package_path.write_text(
            json.dumps(package, ensure_ascii=False),
            encoding="utf-8",
        )
        command = [sys.executable, str(SCRIPT), str(package_path)]
        if include_intake_manifest and "raw_files" in package:
            manifest_path = Path(temp_dir) / "intake-manifest.json"
            manifest = intake_manifest or make_intake_manifest(package)
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False),
                encoding="utf-8",
            )
            command.extend(["--intake-manifest", str(manifest_path)])
        return subprocess.run(
            command,
            cwd=SKILL_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )


def run_validator_text(text):
    with tempfile.TemporaryDirectory() as temp_dir:
        package_path = Path(temp_dir) / "case-package.json"
        package_path.write_text(text, encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(package_path)],
            cwd=SKILL_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )


class ValidateCasePackageTests(unittest.TestCase):
    def test_reports_truthful_scope_for_reference_integrity_validation(self):
        package = make_valid_reference_integrity_package()

        result = run_validator(package)

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(
            report["allowed_scope"], "REQUESTED_TECHNICAL_STATE_ONLY"
        )
        self.assertEqual(
            report["highest_allowed_state"], "REFERENCE_INTEGRITY_VALIDATED"
        )
        self.assertEqual(report["next_required_state"], "PENDING_LEGAL_REVIEW")
        self.assertTrue(report["legal_review_required"])
        self.assertEqual(
            report["validation_scope"]["verified"],
            [
                "ARITHMETIC_RECOMPUTATION",
                "PACKAGE_STRUCTURE",
                "REFERENCE_INTEGRITY",
            ],
        )
        self.assertIn(
            "LEGAL_SOURCE_CURRENTNESS",
            report["validation_scope"]["not_verified"],
        )
        self.assertIn(
            "EVIDENCE_SEMANTIC_SUPPORT",
            report["validation_scope"]["not_verified"],
        )
        self.assertIn(
            "LIMITATION_COMPUTATION",
            report["validation_scope"]["not_verified"],
        )
        self.assertIn(
            "HUMAN_IDENTITY_AUTHENTICATION",
            report["validation_scope"]["not_verified"],
        )

    def test_blocks_fields_outside_the_published_schema(self):
        package = make_valid_reference_integrity_package()
        package["legal_conclusion"] = "fabricated"
        package["package_snapshot_sha256"] = calculate_snapshot(package)

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "SCHEMA_VALIDATION_ERROR",
            [finding["code"] for finding in report["findings"]],
        )

    def test_never_authenticates_human_approval_from_json_fields(self):
        package = make_valid_machine_candidate()
        package["schema_version"] = "1.3"
        package["requested_state"] = "HUMAN_APPROVED_FOR_SUBMISSION"
        package["package_snapshot_sha256"] = calculate_snapshot(package)
        package["approvals"] = [
            {
                "approval_id": "APPROVAL-001",
                "reviewer_identity": "HUMAN-REVIEWER-001",
                "reviewer_role": "LEGAL_REVIEWER",
                "reviewer_actor_type": "HUMAN",
                "approved_snapshot_sha256": package["package_snapshot_sha256"],
                "approved_scope": "synthetic test package",
                "approved_at_utc": "2026-07-14T00:00:00Z",
                "evidence_uri": "urn:synthetic:approval:001",
            }
        ]

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["highest_allowed_state"], "REVIEW_REQUIRED")
        self.assertIn(
            "UNAUTHENTICATED_APPROVAL_UNSUPPORTED",
            [finding["code"] for finding in report["findings"]],
        )

    def test_deprecates_the_misleading_machine_candidate_state(self):
        package = make_valid_machine_candidate()
        package["schema_version"] = "1.3"
        package["requested_state"] = "MACHINE_VALIDATED_CANDIDATE"
        package["package_snapshot_sha256"] = calculate_snapshot(package)

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "OUTPUT_STATE_DEPRECATED",
            [finding["code"] for finding in report["findings"]],
        )
        self.assertEqual(report["replacement_state"], "REFERENCE_INTEGRITY_VALIDATED")

    def test_rejects_legacy_schema_instead_of_allowing_a_trust_boundary_downgrade(self):
        package = make_valid_machine_candidate()
        package["schema_version"] = "1.1"
        package["requested_state"] = "MACHINE_VALIDATED_CANDIDATE"
        package["package_snapshot_sha256"] = calculate_snapshot(package)

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        codes = [finding["code"] for finding in report["findings"]]
        self.assertIn("SCHEMA_VERSION_UNSUPPORTED", codes)
        self.assertIn("OUTPUT_STATE_DEPRECATED", codes)

    def test_blocks_uncomputed_limitation_conclusions(self):
        package = make_valid_machine_candidate()
        package["schema_version"] = "1.3"
        package["requested_state"] = "REFERENCE_INTEGRITY_VALIDATED"
        package["claims"][0]["limitation_analysis"].update(
            {
                "calculated_deadline": "2027-01-01",
                "deadline_status": "WITHIN_LIMITATION",
                "review_status": "REVIEWED",
            }
        )
        package["package_snapshot_sha256"] = calculate_snapshot(package)

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "LIMITATION_CONCLUSION_UNVERIFIED",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_generic_arithmetic_claiming_an_exact_legal_amount(self):
        package = make_valid_machine_candidate()
        package["schema_version"] = "1.3"
        package["requested_state"] = "REFERENCE_INTEGRITY_VALIDATED"
        package["claims"][0]["limitation_analysis"].update(
            {
                "calculated_deadline": None,
                "deadline_status": "UNVERIFIED",
                "review_status": "PENDING_LEGAL_REVIEW",
            }
        )
        package["calculations"][0]["status"] = "EXACT_GIVEN_ASSUMPTIONS"
        package["package_snapshot_sha256"] = calculate_snapshot(package)

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "LEGAL_AMOUNT_STATUS_UNSUPPORTED",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_self_declared_current_legal_rules(self):
        package = make_valid_machine_candidate()
        package["schema_version"] = "1.3"
        package["requested_state"] = "REFERENCE_INTEGRITY_VALIDATED"
        package["claims"][0]["limitation_analysis"].update(
            {
                "calculated_deadline": None,
                "deadline_status": "UNVERIFIED",
                "review_status": "PENDING_LEGAL_REVIEW",
            }
        )
        package["calculations"][0]["status"] = "ARITHMETIC_RECOMPUTED"
        package["legal_rules"][0].update(
            {
                "status": "VERIFIED_CURRENT",
                "verified_at": "2026-07-14T00:00:00Z",
                "verified_by": "LEGAL-REVIEWER-001",
                "verification_actor_type": "HUMAN",
            }
        )
        package["dependency_snapshot_sha256"] = calculate_dependency_snapshot(package)
        package["package_snapshot_sha256"] = calculate_snapshot(package)

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "RULE_VERIFICATION_CLAIM_UNSUPPORTED",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_a_source_host_outside_its_official_candidate_allowlist(self):
        package = make_valid_machine_candidate()
        package["schema_version"] = "1.3"
        package["requested_state"] = "REFERENCE_INTEGRITY_VALIDATED"
        package["source_artifacts"][0].update(
            {
                "publisher_code": "NATIONAL_LAWS_REGULATIONS_DATABASE",
                "canonical_url": "https://example.com/fake-law",
                "content_hash_status": "DECLARED_UNVERIFIED",
            }
        )
        package["legal_rules"][0].update(
            {
                "status": "UNVERIFIED_CANDIDATE",
                "verified_at": None,
                "verified_by": None,
                "verification_actor_type": None,
            }
        )
        package["claims"][0]["limitation_analysis"].update(
            {
                "calculated_deadline": None,
                "deadline_status": "UNVERIFIED",
                "review_status": "PENDING_LEGAL_REVIEW",
            }
        )
        package["calculations"][0]["status"] = "ARITHMETIC_RECOMPUTED"
        package["dependency_snapshot_sha256"] = calculate_dependency_snapshot(package)
        package["package_snapshot_sha256"] = calculate_snapshot(package)

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "SOURCE_HOST_NOT_ALLOWLISTED",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_an_unreferenced_source_outside_the_candidate_allowlist(self):
        package = make_valid_reference_integrity_package()
        extra_source = dict(package["source_artifacts"][0])
        extra_source.update(
            {
                "source_id": "SRC-UNREFERENCED",
                "canonical_url": "https://example.com/fake-law",
            }
        )
        package["source_artifacts"].append(extra_source)
        package["dependency_snapshot_sha256"] = calculate_dependency_snapshot(package)
        package["package_snapshot_sha256"] = calculate_snapshot(package)

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "SOURCE_HOST_NOT_ALLOWLISTED",
            [finding["code"] for finding in report["findings"]],
        )

    def test_checks_source_links_for_unreferenced_rule_records(self):
        package = make_valid_reference_integrity_package()
        extra_rule = dict(package["legal_rules"][0])
        extra_rule.update(
            {"rule_id": "RULE-UNREFERENCED", "source_id": "SRC-UNKNOWN"}
        )
        package["legal_rules"].append(extra_rule)
        package["dependency_snapshot_sha256"] = calculate_dependency_snapshot(package)
        package["package_snapshot_sha256"] = calculate_snapshot(package)

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "RULE_SOURCE_UNKNOWN",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_tribunal_findings_without_external_authority_verification(self):
        package = make_valid_reference_integrity_package()
        package["facts"][0]["status"] = "TRIBUNAL_FOUND"
        package["package_snapshot_sha256"] = calculate_snapshot(package)

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "FACT_STATUS_EXTERNAL_AUTHORITY_REQUIRED",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_semantically_verified_fact_statuses(self):
        package = make_valid_reference_integrity_package()
        package["facts"][0]["status"] = "CORROBORATED"
        package["package_snapshot_sha256"] = calculate_snapshot(package)

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "FACT_STATUS_SEMANTIC_VERIFICATION_UNSUPPORTED",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_evidence_links_claiming_semantic_support(self):
        package = make_valid_reference_integrity_package()
        package["claims"][0]["elements"][0]["proof_status"] = "SUPPORTED"
        package["package_snapshot_sha256"] = calculate_snapshot(package)

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "EVIDENCE_SUPPORT_CLAIM_UNVERIFIED",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_self_declared_initial_burden_satisfaction(self):
        package = make_valid_reference_integrity_package()
        element = package["claims"][0]["elements"][0]
        element.pop("initial_burden_status")
        element["initial_burden_satisfied"] = True
        package["package_snapshot_sha256"] = calculate_snapshot(package)

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "CLAIM_LEGAL_SUFFICIENCY_UNVERIFIED",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_self_declared_claim_conflict_resolution(self):
        package = make_valid_reference_integrity_package()
        package["conflicts"] = [
            {
                "conflict_id": "CONFLICT-001",
                "type": "POSSIBLE_DUPLICATION",
                "status": "RESOLVED",
            }
        ]
        package["package_snapshot_sha256"] = calculate_snapshot(package)

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "CLAIM_CONFLICT_RESOLUTION_UNVERIFIED",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_json_only_privacy_approval(self):
        package = make_valid_reference_integrity_package()
        package["privacy_review"] = {
            "status": "COMPLETED",
            "reviewed_by": "PRIVACY-REVIEWER-001",
            "reviewed_at": "2026-07-14T00:00:00Z",
            "reviewer_actor_type": "HUMAN",
        }
        package["package_snapshot_sha256"] = calculate_snapshot(package)
        package["state_request_sha256"] = calculate_state_request(package)

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "UNAUTHENTICATED_PRIVACY_REVIEW_UNSUPPORTED",
            [finding["code"] for finding in report["findings"]],
        )

    def test_rejects_approval_artifacts_without_an_authenticated_channel(self):
        package = make_valid_reference_integrity_package()
        package["approvals"] = [
            {
                "approval_id": "APPROVAL-001",
                "reviewer_actor_type": "HUMAN",
                "reviewer_identity": "ANY-TEXT",
            }
        ]

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "UNAUTHENTICATED_APPROVAL_UNSUPPORTED",
            [finding["code"] for finding in report["findings"]],
        )

    def test_rejects_human_text_fields_as_p0_p1_risk_resolution(self):
        package = make_valid_reference_integrity_package()
        package["adversarial_findings"] = [
            {
                "finding_id": "ATK-001",
                "severity": "P1",
                "status": "MITIGATED",
                "title": "Synthetic blocker",
                "resolution_actor_type": "HUMAN",
                "resolved_by": "RISK-OWNER-001",
                "resolved_at": "2026-07-14T00:00:00Z",
            }
        ]
        package["package_snapshot_sha256"] = calculate_snapshot(package)

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "UNAUTHENTICATED_RISK_RESOLUTION_UNSUPPORTED",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_a_fabricated_claim_element_status(self):
        package = make_valid_machine_candidate()
        package["claims"][0]["elements"][0]["proof_status"] = "GUARANTEED"

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "CLAIM_ELEMENT_STATUS_INVALID",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_an_unresolved_claim_element(self):
        package = make_valid_machine_candidate()
        package["claims"][0]["elements"][0]["proof_status"] = "DISPUTED"

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "CLAIM_ELEMENT_UNRESOLVED",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_a_claim_element_without_fact_and_rule_traceability(self):
        package = make_valid_machine_candidate()
        element = package["claims"][0]["elements"][0]
        element["fact_ids"] = []
        element["rule_ids"] = []

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "CLAIM_ELEMENT_TRACE_INCOMPLETE",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_an_evidence_linked_fact_without_evidence(self):
        package = make_valid_machine_candidate()
        package["facts"][0]["evidence_ids"] = []

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "FACT_EVIDENCE_MISSING",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_a_limitation_analysis_with_unknown_evidence(self):
        package = make_valid_machine_candidate()
        package["claims"][0]["limitation_analysis"]["evidence_ids"] = ["E-UNKNOWN"]

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "EVIDENCE_REFERENCE_UNKNOWN",
            [finding["code"] for finding in report["findings"]],
        )

    def test_recomputes_and_blocks_an_incorrect_calculation_result(self):
        package = make_valid_machine_candidate()
        package["calculations"][0]["result"] = "999.00"

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "CALCULATION_RESULT_MISMATCH",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_an_unsupported_calculator_formula(self):
        package = make_valid_machine_candidate()
        package["calculations"][0]["formula_id"] = "MODEL_DECIDES_AMOUNT"

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "CALCULATOR_UNSUPPORTED",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_a_fabricated_dependency_snapshot(self):
        package = make_valid_machine_candidate()
        package["dependency_snapshot_sha256"] = "a" * 64
        self.assertNotEqual(
            package["dependency_snapshot_sha256"],
            calculate_dependency_snapshot(package),
        )

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "DEPENDENCY_SNAPSHOT_MISMATCH",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_a_fabricated_statement_snapshot(self):
        package = make_valid_machine_candidate()
        package["statement_snapshot_sha256"] = "a" * 64
        self.assertNotEqual(
            package["statement_snapshot_sha256"],
            calculate_statement_snapshot(package),
        )

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "STATEMENT_SNAPSHOT_MISMATCH",
            [finding["code"] for finding in report["findings"]],
        )

    def test_rejects_duplicate_authority_record_identifiers(self):
        package = make_valid_machine_candidate()
        package["adversarial_findings"] = [
            {
                "finding_id": "ATK-001",
                "severity": "P2",
                "status": "OPEN",
            },
            {
                "finding_id": "ATK-001",
                "severity": "P2",
                "status": "OPEN",
            },
        ]

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "IDENTIFIER_DUPLICATE",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_a_machine_candidate_without_an_intake_manifest(self):
        package = make_valid_machine_candidate()

        result = run_validator(package, include_intake_manifest=False)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "INTAKE_MANIFEST_REQUIRED",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_a_machine_candidate_with_a_different_intake_manifest(self):
        package = make_valid_machine_candidate()
        manifest = make_intake_manifest(package)
        manifest["files"] = []

        result = run_validator(package, intake_manifest=manifest)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        codes = [finding["code"] for finding in report["findings"]]
        self.assertIn("INTAKE_MANIFEST_SNAPSHOT_MISMATCH", codes)
        self.assertIn("RAW_FILES_MANIFEST_MISMATCH", codes)

    def test_rejects_non_numeric_manifest_sizes_without_a_traceback(self):
        package = make_valid_machine_candidate()
        manifest = make_intake_manifest(package)
        manifest["files"][0]["size_bytes"] = "not-a-number"

        result = run_validator(package, intake_manifest=manifest)

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "INTAKE_MANIFEST_INVALID",
            [finding["code"] for finding in report["findings"]],
        )

    def test_reports_malformed_json_without_a_traceback(self):
        result = run_validator_text('{"schema_version":')

        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["error"]["code"], "INPUT_JSON_INVALID")

    def test_rejects_duplicate_json_object_keys(self):
        result = run_validator_text(
            '{"schema_version":"1.1","schema_version":"9.9",'
            '"requested_state":"DRAFT"}'
        )

        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["error"]["code"], "INPUT_JSON_DUPLICATE_KEY")

    def test_rejects_nonstandard_json_numbers(self):
        result = run_validator_text(
            '{"schema_version":"1.1","requested_state":"DRAFT","value":NaN}'
        )

        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["error"]["code"], "INPUT_JSON_INVALID_CONSTANT")

    def test_rejects_an_oversized_case_package_before_parsing(self):
        result = run_validator_text(" " * (10 * 1024 * 1024 + 1))

        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["error"]["code"], "INPUT_FILE_TOO_LARGE")

    def test_reports_a_missing_input_file_without_a_traceback(self):
        missing_path = SKILL_ROOT / "tests" / "does-not-exist.json"

        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(missing_path)],
            cwd=SKILL_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["error"]["code"], "INPUT_FILE_UNREADABLE")

    def test_rejects_a_non_object_json_root_without_a_traceback(self):
        result = run_validator_text("[]")

        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["error"]["code"], "INPUT_ROOT_NOT_OBJECT")

    def test_allows_an_incomplete_draft_without_running_formal_gates(self):
        result = run_validator({"schema_version": "1.3", "requested_state": "DRAFT"})

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["allowed"])
        self.assertEqual(report["highest_allowed_state"], "DRAFT")

    def test_rejects_duplicate_identifiers_in_machine_gated_collections(self):
        collection_and_id_field = {
            "raw_files": "raw_id",
            "source_artifacts": "source_id",
            "legal_rules": "rule_id",
            "evidence": "evidence_id",
            "facts": "fact_id",
            "claims": "claim_id",
            "calculations": "calculation_id",
            "statements": "statement_id",
        }
        for collection, id_field in collection_and_id_field.items():
            with self.subTest(collection=collection):
                package = make_valid_machine_candidate()
                duplicate = dict(package[collection][0])
                self.assertIn(id_field, duplicate)
                package[collection].append(duplicate)

                result = run_validator(package)

                self.assertEqual(result.returncode, 2, result.stderr)
                report = json.loads(result.stdout)
                self.assertIn(
                    "IDENTIFIER_DUPLICATE",
                    [finding["code"] for finding in report["findings"]],
                )

    def test_blocks_a_source_artifact_with_missing_required_metadata(self):
        package = make_valid_machine_candidate()
        package["source_artifacts"][0].pop("content_sha256")

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "SOURCE_METADATA_INCOMPLETE",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_a_rule_whose_jurisdiction_differs_from_the_package(self):
        package = make_valid_machine_candidate()
        package["legal_rules"][0]["jurisdiction"] = {
            "country": "CN",
            "province": "Shanghai",
        }

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "RULE_JURISDICTION_MISMATCH",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_a_rule_whose_source_jurisdiction_differs_from_the_package(self):
        package = make_valid_machine_candidate()
        package["source_artifacts"][0]["jurisdiction"] = {
            "country": "CN",
            "province": "Shanghai",
        }

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "SOURCE_JURISDICTION_MISMATCH",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_a_rule_marked_as_superseded(self):
        package = make_valid_machine_candidate()
        package["legal_rules"][0]["superseded_by"] = "RULE-NEWER"

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "RULE_SUPERSEDED",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_a_calculation_missing_reproducibility_fields(self):
        package = make_valid_machine_candidate()
        package["calculations"][0].pop("rounding_policy")

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "CALCULATION_REPRODUCIBILITY_INCOMPLETE",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_a_fact_that_references_unknown_evidence(self):
        package = make_valid_machine_candidate()
        package["facts"][0]["evidence_ids"] = ["E-UNKNOWN"]

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "EVIDENCE_REFERENCE_UNKNOWN",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_evidence_without_ingestion_integrity_verification(self):
        package = make_valid_machine_candidate()
        package["evidence"][0]["integrity_status"] = "UNVERIFIED"

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "EVIDENCE_INTEGRITY_UNVERIFIED",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_model_self_review_of_privacy(self):
        package = make_valid_machine_candidate()
        package["privacy_review"]["reviewer_actor_type"] = "MODEL"

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "UNAUTHENTICATED_PRIVACY_REVIEW_UNSUPPORTED",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_model_self_mitigation_of_an_adversarial_blocker(self):
        package = make_valid_machine_candidate()
        package["adversarial_findings"] = [
            {
                "finding_id": "ATK-001",
                "severity": "P1",
                "status": "MITIGATED",
                "title": "Synthetic mitigated blocker",
                "resolution_actor_type": "MODEL",
                "resolved_by": "MODEL-001",
                "resolved_at": "2026-07-14T00:00:00Z",
            }
        ]

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "UNAUTHENTICATED_RISK_RESOLUTION_UNSUPPORTED",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_a_numeric_calculation_result_instead_of_decimal_text(self):
        package = make_valid_machine_candidate()
        package["calculations"][0]["result"] = 100.0

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "CALCULATION_DECIMAL_FORMAT_INVALID",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_a_calculation_input_with_unknown_evidence(self):
        package = make_valid_machine_candidate()
        package["calculations"][0]["inputs"][0]["evidence_id"] = "E-UNKNOWN"

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "EVIDENCE_REFERENCE_UNKNOWN",
            [finding["code"] for finding in report["findings"]],
        )

    def test_emits_a_deterministic_report_for_the_same_input(self):
        package = make_valid_machine_candidate()
        package["facts"][0]["status"] = "ADJUDICATED"

        first = run_validator(package)
        second = run_validator(package)

        self.assertEqual(first.returncode, 2, first.stderr)
        self.assertEqual(first.stdout, second.stdout)

    def test_blocks_a_machine_candidate_missing_dependency_snapshots(self):
        package = make_valid_machine_candidate()
        package.pop("dependency_snapshot_sha256")
        package.pop("statement_snapshot_sha256")

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "PACKAGE_FIELD_MISSING",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_invalid_snapshot_hash_formats(self):
        package = make_valid_machine_candidate()
        package["dependency_snapshot_sha256"] = "not-a-sha256"

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "SNAPSHOT_HASH_INVALID",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_an_empty_formal_package(self):
        package = make_valid_machine_candidate()
        package["claims"] = []
        package["statements"] = []

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "FORMAL_CONTENT_EMPTY",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_a_record_without_its_identifier(self):
        package = make_valid_machine_candidate()
        package["facts"][0].pop("fact_id")

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "IDENTIFIER_MISSING",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_a_non_array_collection_without_a_traceback(self):
        package = make_valid_machine_candidate()
        package["facts"] = {"fact_id": "FACT-INVALID-SHAPE"}

        result = run_validator(package)

        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "COLLECTION_NOT_ARRAY",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_a_malformed_draft_collection_without_a_traceback(self):
        package = {
            "schema_version": "1.3",
            "requested_state": "DRAFT",
            "source_artifacts": {"source_id": "SOURCE-INVALID-SHAPE"},
            "claims": "invalid-collection",
        }

        result = run_validator(package, include_intake_manifest=False)

        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "SCHEMA_VALIDATION_ERROR",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_a_non_object_collection_record_without_a_traceback(self):
        package = make_valid_machine_candidate()
        package["evidence"] = ["malformed-record"]

        result = run_validator(package)

        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "RECORD_NOT_OBJECT",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_a_non_array_nested_reference_without_a_traceback(self):
        package = make_valid_machine_candidate()
        package["statements"][0]["fact_ids"] = "FACT-001"

        result = run_validator(package)

        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "FIELD_NOT_ARRAY",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_a_raw_file_record_without_a_valid_checksum(self):
        package = make_valid_machine_candidate()
        package["raw_files"][0]["sha256"] = "bad"

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "RAW_FILE_METADATA_INVALID",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_a_raw_file_path_that_escapes_the_intake_root(self):
        package = make_valid_machine_candidate()
        package["raw_files"][0]["relative_path"] = "../outside.txt"

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "RAW_FILE_METADATA_INVALID",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_a_source_with_an_invalid_content_hash(self):
        package = make_valid_machine_candidate()
        package["source_artifacts"][0]["content_sha256"] = "not-a-hash"

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "SOURCE_CONTENT_HASH_INVALID",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_a_formal_source_with_a_non_https_url(self):
        package = make_valid_machine_candidate()
        package["source_artifacts"][0]["canonical_url"] = "file:///local-rule.txt"

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "SOURCE_URL_UNSAFE",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_a_machine_candidate_that_references_an_unknown_rule(self):
        package = make_valid_machine_candidate()
        package["claims"][0]["elements"][0]["rule_ids"] = ["RULE-UNKNOWN"]

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertFalse(report["allowed"])
        self.assertEqual(report["highest_allowed_state"], "REVIEW_REQUIRED")
        self.assertIn(
            "RULE_REFERENCE_UNKNOWN",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_a_machine_candidate_with_unlocated_evidence(self):
        package = make_valid_machine_candidate()
        package["evidence"][0].pop("location")

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "EVIDENCE_LOCATION_MISSING",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_a_supported_claim_element_without_evidence_links(self):
        package = make_valid_machine_candidate()
        package["claims"][0]["elements"][0]["evidence_ids"] = []

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "CLAIM_EVIDENCE_MISSING",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_an_unjustified_employer_controlled_evidence_exception(self):
        package = make_valid_machine_candidate()
        element = package["claims"][0]["elements"][0]
        element["proof_status"] = "EMPLOYER_CONTROLLED_MISSING"
        element["evidence_controller"] = "EMPLOYER"
        element["evidence_ids"] = []
        element["initial_burden_status"] = "UNVERIFIED"
        element["production_request"] = None

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "EMPLOYER_CONTROLLED_EVIDENCE_UNJUSTIFIED",
            [finding["code"] for finding in report["findings"]],
        )

    def test_allows_a_justified_employer_controlled_evidence_exception(self):
        package = make_valid_machine_candidate()
        element = package["claims"][0]["elements"][0]
        element["proof_status"] = "EMPLOYER_CONTROLLED_MISSING"
        element["evidence_controller"] = "EMPLOYER"
        element["evidence_ids"] = []
        element["initial_burden_status"] = "UNVERIFIED"
        element["production_request"] = {
            "requested_items": ["synthetic attendance record"],
            "request_stage": "ARBITRATION",
        }
        package["package_snapshot_sha256"] = calculate_snapshot(package)
        package["state_request_sha256"] = calculate_state_request(package)

        result = run_validator(package)

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["allowed"])
        self.assertEqual(report["findings"], [])

    def test_rejects_a_boolean_only_limitation_check(self):
        package = make_valid_machine_candidate()
        package["claims"][0]["limitation_analysis"] = True

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "LIMITATION_ANALYSIS_UNSTRUCTURED",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_a_stale_legal_rule(self):
        package = make_valid_machine_candidate()
        package["legal_rules"][0]["status"] = "STALE"

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "RULE_VERIFICATION_CLAIM_UNSUPPORTED",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_human_approved_state_without_a_human_approval_artifact(self):
        package = make_valid_machine_candidate()
        package["requested_state"] = "HUMAN_APPROVED_FOR_SUBMISSION"

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "UNAUTHENTICATED_APPROVAL_UNSUPPORTED",
            [finding["code"] for finding in report["findings"]],
        )

    def test_invalidates_a_human_approval_for_a_different_snapshot(self):
        package = make_valid_machine_candidate()
        package["requested_state"] = "HUMAN_APPROVED_FOR_SUBMISSION"
        package["approvals"] = [
            {
                "approval_id": "APPROVAL-001",
                "reviewer_identity": "HUMAN-REVIEWER-001",
                "reviewer_role": "LEGAL_REVIEWER",
                "approved_snapshot_sha256": "0" * 64,
                "approved_scope": "synthetic test package",
                "approved_at_utc": "2026-07-14T00:00:00Z",
                "evidence_uri": "urn:synthetic:approval:001",
            }
        ]

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "UNAUTHENTICATED_APPROVAL_UNSUPPORTED",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_a_case_package_changed_after_its_snapshot_was_locked(self):
        package = make_valid_machine_candidate()
        package["facts"][0]["summary"] = "changed after locking"

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "PACKAGE_SNAPSHOT_MISMATCH",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_an_unattributable_human_approval(self):
        package = make_valid_machine_candidate()
        package["requested_state"] = "HUMAN_APPROVED_FOR_SUBMISSION"
        package["approvals"] = [
            {
                "approval_id": "APPROVAL-001",
                "approved_snapshot_sha256": package["package_snapshot_sha256"],
            }
        ]

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "UNAUTHENTICATED_APPROVAL_UNSUPPORTED",
            [finding["code"] for finding in report["findings"]],
        )

    def test_rejects_an_attributable_json_approval_for_the_locked_snapshot(self):
        package = make_valid_machine_candidate()
        package["requested_state"] = "HUMAN_APPROVED_FOR_SUBMISSION"
        package["approvals"] = [
            {
                "approval_id": "APPROVAL-001",
                "reviewer_identity": "HUMAN-REVIEWER-001",
                "reviewer_role": "LEGAL_REVIEWER",
                "reviewer_actor_type": "HUMAN",
                "approved_snapshot_sha256": package["package_snapshot_sha256"],
                "approved_scope": "synthetic test package",
                "approved_at_utc": "2026-07-14T00:00:00Z",
                "evidence_uri": "urn:synthetic:approval:001",
            }
        ]

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "UNAUTHENTICATED_APPROVAL_UNSUPPORTED",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_model_self_approval_even_with_complete_metadata(self):
        package = make_valid_machine_candidate()
        package["requested_state"] = "HUMAN_APPROVED_FOR_SUBMISSION"
        package["approvals"] = [
            {
                "approval_id": "APPROVAL-001",
                "reviewer_identity": "MODEL-001",
                "reviewer_role": "LEGAL_REVIEWER",
                "reviewer_actor_type": "MODEL",
                "approved_snapshot_sha256": package["package_snapshot_sha256"],
                "approved_scope": "synthetic test package",
                "approved_at_utc": "2026-07-14T00:00:00Z",
                "evidence_uri": "urn:synthetic:approval:001",
            }
        ]

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "UNAUTHENTICATED_APPROVAL_UNSUPPORTED",
            [finding["code"] for finding in report["findings"]],
        )

    def test_rejects_an_unknown_output_state(self):
        package = make_valid_machine_candidate()
        package["requested_state"] = "GUARANTEED_WIN"

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "OUTPUT_STATE_UNKNOWN",
            [finding["code"] for finding in report["findings"]],
        )

    def test_rejects_an_unsupported_case_package_schema(self):
        package = make_valid_machine_candidate()
        package["schema_version"] = "9.9"

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "SCHEMA_VERSION_UNSUPPORTED",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_machine_validation_outside_the_supported_jurisdiction(self):
        package = make_valid_machine_candidate()
        package["jurisdiction"] = {"country": "CN", "province": "Shanghai"}

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "DECLARED_SCOPE_UNSUPPORTED",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_a_rule_without_its_source_artifact(self):
        package = make_valid_machine_candidate()
        package["source_artifacts"] = []

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "RULE_SOURCE_UNKNOWN",
            [finding["code"] for finding in report["findings"]],
        )

    def test_does_not_treat_an_official_faq_as_a_binding_legal_rule(self):
        package = make_valid_machine_candidate()
        package["source_artifacts"][0]["document_type"] = "FAQ"

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "SOURCE_NOT_NORMATIVE",
            [finding["code"] for finding in report["findings"]],
        )

    def test_does_not_accept_model_self_verification_of_a_legal_rule(self):
        package = make_valid_machine_candidate()
        package["legal_rules"][0]["verification_actor_type"] = "MODEL"

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "RULE_VERIFICATION_CLAIM_UNSUPPORTED",
            [finding["code"] for finding in report["findings"]],
        )

    def test_rejects_an_incomplete_limitation_event_model(self):
        package = make_valid_machine_candidate()
        package["claims"][0]["limitation_analysis"].pop("interruption_events")

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "LIMITATION_ANALYSIS_INCOMPLETE",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_an_unresolved_limitation_analysis(self):
        package = make_valid_machine_candidate()
        package["claims"][0]["limitation_analysis"]["review_status"] = "DISPUTED"

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "LIMITATION_CONCLUSION_UNVERIFIED",
            [finding["code"] for finding in report["findings"]],
        )

    def test_rejects_a_pseudo_final_calculation_status(self):
        package = make_valid_machine_candidate()
        package["calculations"][0]["status"] = "FINAL"

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "LEGAL_AMOUNT_STATUS_UNSUPPORTED",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_an_unknown_calculation_reference(self):
        package = make_valid_machine_candidate()
        package["claims"][0]["calculation_ids"] = ["CALC-UNKNOWN"]

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "CALCULATION_REFERENCE_UNKNOWN",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_an_unknown_fact_reference(self):
        package = make_valid_machine_candidate()
        package["claims"][0]["elements"][0]["fact_ids"] = ["FACT-UNKNOWN"]

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "FACT_REFERENCE_UNKNOWN",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_an_unknown_evidence_reference(self):
        package = make_valid_machine_candidate()
        package["claims"][0]["elements"][0]["evidence_ids"] = ["E-UNKNOWN"]

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "EVIDENCE_REFERENCE_UNKNOWN",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_evidence_that_does_not_resolve_to_a_raw_file(self):
        package = make_valid_machine_candidate()
        package["evidence"][0]["raw_id"] = "RAW-UNKNOWN"

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "EVIDENCE_RAW_FILE_UNKNOWN",
            [finding["code"] for finding in report["findings"]],
        )

    def test_rejects_adjudicated_as_a_system_assigned_fact_status(self):
        package = make_valid_machine_candidate()
        package["facts"][0]["status"] = "ADJUDICATED"

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "FACT_STATUS_NOT_ALLOWED",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_machine_validation_without_a_privacy_review(self):
        package = make_valid_machine_candidate()
        package["privacy_review"] = {"status": "NOT_STARTED"}

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "UNAUTHENTICATED_PRIVACY_REVIEW_UNSUPPORTED",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_machine_validation_with_an_open_adversarial_p1(self):
        package = make_valid_machine_candidate()
        package["adversarial_findings"] = [
            {
                "finding_id": "ATK-001",
                "severity": "P1",
                "status": "ACCEPTED",
                "title": "Synthetic unresolved blocker",
            }
        ]

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "ADVERSARIAL_BLOCKER_OPEN",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_an_unresolved_claim_duplication_conflict(self):
        package = make_valid_machine_candidate()
        package["conflicts"] = [
            {
                "conflict_id": "CONFLICT-001",
                "type": "POSSIBLE_DUPLICATION",
                "status": "OPEN",
            }
        ]

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "CLAIM_CONFLICT_RESOLUTION_UNVERIFIED",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_a_formal_statement_without_fact_and_rule_traceability(self):
        package = make_valid_machine_candidate()
        package["statements"][0]["fact_ids"] = []
        package["statements"][0]["rule_ids"] = []

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "STATEMENT_TRACE_INCOMPLETE",
            [finding["code"] for finding in report["findings"]],
        )

    def test_uses_rfc8785_utf16_property_order_for_snapshot_canonicalization(self):
        canonical = VALIDATOR.canonicalize_json({"\ue000": 1, "😀": 2})
        self.assertEqual(canonical, '{"😀":2,"\ue000":1}'.encode("utf-8"))

    def test_binds_requested_state_to_the_locked_package(self):
        package = make_valid_reference_integrity_package()
        package["requested_state"] = "REVALIDATION_REQUIRED"

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        codes = [item["code"] for item in json.loads(result.stdout)["findings"]]
        self.assertIn("PACKAGE_SNAPSHOT_MISMATCH", codes)
        self.assertIn("STATE_REQUEST_MISMATCH", codes)

    def test_splits_source_hash_status_from_host_allowlist_errors(self):
        package = make_valid_reference_integrity_package()
        package["source_artifacts"][0]["content_hash_status"] = "FETCH_VERIFIED"
        package["dependency_snapshot_sha256"] = calculate_dependency_snapshot(package)
        package["package_snapshot_sha256"] = calculate_snapshot(package)
        package["state_request_sha256"] = calculate_state_request(package)

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        codes = [item["code"] for item in json.loads(result.stdout)["findings"]]
        self.assertIn("SOURCE_HASH_STATUS_INVALID", codes)
        self.assertNotIn("SOURCE_HOST_NOT_ALLOWLISTED", codes)
        hash_finding = next(
            item
            for item in json.loads(result.stdout)["findings"]
            if item["code"] == "SOURCE_HASH_STATUS_INVALID"
        )
        self.assertIn("哈希", hash_finding["message_zh"])
        self.assertIn("DECLARED_UNVERIFIED", hash_finding["remediation"])

    def test_rejects_invalid_rfc3339_and_calendar_date_values(self):
        package = make_valid_reference_integrity_package()
        package["source_artifacts"][0]["retrieved_at"] = "14/07/2026"
        package["legal_rules"][0]["effective_from"] = "2026-02-30"
        package["dependency_snapshot_sha256"] = calculate_dependency_snapshot(package)
        package["package_snapshot_sha256"] = calculate_snapshot(package)
        package["state_request_sha256"] = calculate_state_request(package)

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        codes = [item["code"] for item in json.loads(result.stdout)["findings"]]
        self.assertIn("DATE_FORMAT_INVALID", codes)

    def test_rejects_an_inverted_rule_effective_interval(self):
        package = make_valid_reference_integrity_package()
        package["legal_rules"][0]["effective_from"] = "2026-02-01"
        package["legal_rules"][0]["effective_to"] = "2026-01-31"
        package["dependency_snapshot_sha256"] = calculate_dependency_snapshot(package)
        package["package_snapshot_sha256"] = calculate_snapshot(package)
        package["state_request_sha256"] = calculate_state_request(package)

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        codes = [item["code"] for item in json.loads(result.stdout)["findings"]]
        self.assertIn("DATE_INTERVAL_INVALID", codes)

    def test_rejects_a_manifest_with_a_forged_self_hash(self):
        package = make_valid_reference_integrity_package()
        manifest = make_intake_manifest(package)
        manifest["manifest_payload_sha256"] = "0" * 64
        package["intake_manifest_sha256"] = VALIDATOR.calculate_json_snapshot(manifest)
        package["package_snapshot_sha256"] = calculate_snapshot(package)
        package["state_request_sha256"] = calculate_state_request(package)

        result = run_validator(package, intake_manifest=manifest)

        self.assertEqual(result.returncode, 2, result.stderr)
        codes = [item["code"] for item in json.loads(result.stdout)["findings"]]
        self.assertIn("INTAKE_MANIFEST_SELF_HASH_MISMATCH", codes)

    def test_rejects_an_inverted_scan_time_interval(self):
        package = make_valid_reference_integrity_package()
        manifest = make_intake_manifest(package)
        manifest["scan_observation"]["completed_at"] = "2026-07-13T23:59:59Z"
        payload = dict(manifest)
        payload.pop("manifest_payload_sha256")
        manifest["manifest_payload_sha256"] = VALIDATOR.calculate_json_snapshot(payload)
        package["intake_manifest_sha256"] = VALIDATOR.calculate_json_snapshot(manifest)
        package["package_snapshot_sha256"] = calculate_snapshot(package)
        package["state_request_sha256"] = calculate_state_request(package)

        result = run_validator(package, intake_manifest=manifest)

        self.assertEqual(result.returncode, 2, result.stderr)
        codes = [item["code"] for item in json.loads(result.stdout)["findings"]]
        self.assertIn("SCAN_TIME_INTERVAL_INVALID", codes)


if __name__ == "__main__":
    unittest.main()
