import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.case_package_factory import (
    calculate_dependency_snapshot,
    calculate_document_snapshot,
    calculate_snapshot,
    make_intake_manifest,
    make_valid_machine_candidate,
)


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_ROOT / "scripts" / "validate_case_package.py"


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

    def test_blocks_a_fabricated_document_snapshot(self):
        package = make_valid_machine_candidate()
        package["document_snapshot_sha256"] = "a" * 64
        self.assertNotEqual(
            package["document_snapshot_sha256"],
            calculate_document_snapshot(package),
        )

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "DOCUMENT_SNAPSHOT_MISMATCH",
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
        result = run_validator({"schema_version": "1.1", "requested_state": "DRAFT"})

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
            "PRIVACY_REVIEW_NOT_HUMAN",
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
            "ADVERSARIAL_RESOLUTION_NOT_HUMAN",
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
        package.pop("document_snapshot_sha256")

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
        element["initial_burden_satisfied"] = False
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
        element["initial_burden_satisfied"] = True
        element["production_request"] = {
            "requested_items": ["synthetic attendance record"],
            "request_stage": "ARBITRATION",
        }
        package["package_snapshot_sha256"] = calculate_snapshot(package)

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
            "RULE_STATUS_NOT_ALLOWED",
            [finding["code"] for finding in report["findings"]],
        )

    def test_blocks_human_approved_state_without_a_human_approval_artifact(self):
        package = make_valid_machine_candidate()
        package["requested_state"] = "HUMAN_APPROVED_FOR_SUBMISSION"

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "HUMAN_APPROVAL_MISSING",
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
            "APPROVAL_SNAPSHOT_MISMATCH",
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
            "HUMAN_APPROVAL_INVALID",
            [finding["code"] for finding in report["findings"]],
        )

    def test_allows_an_attributable_human_approval_for_the_locked_snapshot(self):
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

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["allowed"])
        self.assertEqual(
            report["highest_allowed_state"],
            "HUMAN_APPROVED_FOR_SUBMISSION",
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
            "HUMAN_APPROVAL_INVALID",
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
            "JURISDICTION_UNSUPPORTED",
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
            "RULE_VERIFICATION_NOT_HUMAN",
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
            "LIMITATION_REVIEW_REQUIRED",
            [finding["code"] for finding in report["findings"]],
        )

    def test_rejects_a_pseudo_final_calculation_status(self):
        package = make_valid_machine_candidate()
        package["calculations"][0]["status"] = "FINAL"

        result = run_validator(package)

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            "CALCULATION_STATUS_NOT_ALLOWED",
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
            "PRIVACY_REVIEW_MISSING",
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
            "CLAIM_CONFLICT_UNRESOLVED",
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


if __name__ == "__main__":
    unittest.main()
