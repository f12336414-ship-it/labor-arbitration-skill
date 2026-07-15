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

from evidence_review_policy import (  # noqa: E402
    EvidenceReviewError,
    build_evidence_review,
    calculate_evidence_review_id,
    calculate_evidence_review_snapshot,
    validate_evidence_review_record,
)
from fact_analysis_policy import build_fact_analysis  # noqa: E402
from fact_candidate_policy import build_fact_candidate, invalidate_fact_candidate  # noqa: E402
from tests.test_fact_candidate_model import make_parse_record  # noqa: E402


def evidence_fixture():
    parse_record = make_parse_record(("January wage was 5000", "Payment happened in February"))
    candidates = []
    analysis_inputs = []
    definitions = [
        ("AMOUNT.WAGE", "WAGE.2025-01", "AMOUNT_CNY", "5000.00", "WAGE_AMOUNT"),
        ("DATE.PAYMENT", "PAYMENT.DATE", "DATE", "2025-02-05", "PAYMENT_DATE"),
    ]
    for anchor, definition in zip(parse_record["anchors"], definitions):
        view_key, dimension, kind, value, claim_type = definition
        candidate = build_fact_candidate(
            parse_record,
            anchor_ids=[anchor["anchor_id"]],
            provenance_state="EXTRACTED",
            claim_type=claim_type,
            assertion_text=anchor["text"],
            created_at="2026-07-15T06:00:00Z",
        )
        candidates.append(candidate)
        analysis_inputs.append(
            {
                "view_key": view_key,
                "dimension_key": dimension,
                "semantic_kind": kind,
                "value": value,
                "timeline_role": "NONE",
                "actor_label": "local-structurer",
                "fact_candidate_record": candidate,
                "parse_record": parse_record,
                "previous_fact_candidate_record": None,
            }
        )
    analysis = build_fact_analysis(
        {
            "schema_version": "1.0",
            "artifact_id": "ANALYSIS-EVIDENCE_REVIEW",
            "created_at": "2026-07-15T06:30:00Z",
            "inputs": analysis_inputs,
            "previous_analysis_record": None,
        }
    )
    return parse_record, candidates, analysis


def review_specification(*, assessment=None, corroboration=None):
    parse_record, candidates, analysis = evidence_fixture()
    return {
        "schema_version": "1.0",
        "review_artifact_id": "EVIDENCE-SYNTHETIC_WAGE_RECORD",
        "created_at": "2026-07-15T07:00:00Z",
        "actor_label": "local-reviewer",
        "parse_record": parse_record,
        "fact_candidates": [{"record": item, "previous_record": None} for item in candidates],
        "fact_analysis_record": analysis,
        "previous_fact_analysis_record": None,
        "assessment": assessment or {
            "source_status": "UNKNOWN",
            "completeness_status": "UNKNOWN",
            "subject_link_status": "UNKNOWN",
            "time_link_status": "UNKNOWN",
            "integrity_status": "UNKNOWN",
            "legality_risk_flags": ["UNKNOWN"],
            "notes": "Synthetic review only.",
        },
        "proof_purposes": [
            {
                "purpose_key": "PURPOSE.WAGE_AND_PAYMENT",
                "proposition": "User asserts the record relates to wage amount and payment date.",
                "view_ids": [item["view_id"] for item in analysis["views"]],
            }
        ],
        "corroborating_review_bindings": corroboration or [],
    }


class EvidenceReviewTests(unittest.TestCase):
    def setUp(self):
        self.specification = review_specification()
        self.record = build_evidence_review(self.specification)

    def report(self, record):
        return validate_evidence_review_record(record)

    def refresh(self, record):
        record["evidence_review_id"] = calculate_evidence_review_id(record)
        record["record_snapshot_sha256"] = calculate_evidence_review_snapshot(record)

    def test_unknown_assessment_generates_all_applicable_open_gaps(self):
        codes = {item["code"] for item in self.record["identified_gaps"]}
        self.assertEqual(
            codes,
            {
                "AUTHENTICITY_UNVERIFIED",
                "LEGALITY_REVIEW_REQUIRED",
                "SOURCE_PROVENANCE_UNKNOWN",
                "COMPLETENESS_NOT_ASSERTED",
                "SUBJECT_LINK_NOT_ASSERTED",
                "TIME_LINK_NOT_ASSERTED",
                "ORIGINAL_BYTES_PRESERVATION_NOT_ASSERTED",
                "NO_CORROBORATING_REVIEW_BOUND",
                "LEGALITY_RISK_UNKNOWN",
            },
        )
        self.assertTrue(all(item["status"] == "OPEN" for item in self.record["identified_gaps"]))

    def test_suggestions_are_deterministic_generic_actions_not_legal_advice(self):
        suggestions = self.record["strengthening_suggestions"]
        self.assertEqual([item["code"] for item in suggestions], sorted(item["code"] for item in suggestions))
        self.assertTrue(all(item["status"] == "GENERIC_ACTION_NOT_LEGAL_ADVICE" for item in suggestions))
        self.assertEqual(len({item["code"] for item in suggestions}), len(suggestions))

    def test_even_strong_user_assertions_never_verify_authenticity_or_admissibility(self):
        assessment = {
            "source_status": "EMPLOYER_ISSUED_ASSERTED",
            "completeness_status": "COMPLETE_ASSERTED",
            "subject_link_status": "MATCH_ASSERTED",
            "time_link_status": "MATCH_ASSERTED",
            "integrity_status": "ORIGINAL_BYTES_PRESERVED_ASSERTED",
            "legality_risk_flags": ["NONE_DECLARED_UNVERIFIED"],
            "notes": "All are user assertions.",
        }
        corroboration = [{"evidence_review_id": "EVREVIEW-" + "A" * 24, "record_snapshot_sha256": "b" * 64}]
        record = build_evidence_review(review_specification(assessment=assessment, corroboration=corroboration))
        self.assertEqual([item["code"] for item in record["identified_gaps"]], ["AUTHENTICITY_UNVERIFIED", "LEGALITY_REVIEW_REQUIRED"])
        self.assertEqual(record["authenticity_status"], "UNVERIFIED")
        self.assertEqual(record["admissibility_status"], "NOT_DETERMINED_REQUIRES_LEGAL_REVIEW")
        self.assertEqual(record["evidence_weight_status"], "NOT_ASSESSED")
        report = self.report(record)
        self.assertTrue(report["allowed"], report["findings"])
        self.assertFalse(report["authenticity_verified"])
        self.assertFalse(report["admissibility_determined"])
        self.assertFalse(report["evidence_weight_assessed"])

    def test_mismatch_and_integrity_concern_remain_visible(self):
        assessment = copy.deepcopy(self.specification["assessment"])
        assessment.update(
            {
                "subject_link_status": "MISMATCH_ASSERTED",
                "time_link_status": "MISMATCH_ASSERTED",
                "integrity_status": "ALTERATION_CONCERN",
                "legality_risk_flags": ["ALTERATION_OR_FABRICATION_CONCERN", "PRIVACY_OR_PERSONAL_INFORMATION"],
            }
        )
        record = build_evidence_review({**self.specification, "assessment": assessment})
        codes = {item["code"] for item in record["identified_gaps"]}
        self.assertTrue({"SUBJECT_LINK_CONFLICT", "TIME_LINK_CONFLICT", "INTEGRITY_CONCERN_FLAGGED", "LEGALITY_RISK_FLAGGED"}.issubset(codes))

    def test_none_legality_flag_cannot_hide_another_risk(self):
        specification = copy.deepcopy(self.specification)
        specification["assessment"]["legality_risk_flags"] = ["NONE_DECLARED_UNVERIFIED", "PRIVACY_OR_PERSONAL_INFORMATION"]
        with self.assertRaises(EvidenceReviewError) as raised:
            build_evidence_review(specification)
        self.assertEqual(raised.exception.code, "EVIDENCE_REVIEW_LEGALITY_FLAGS_CONFLICT")

    def test_proof_purpose_binds_exact_views_and_candidate_snapshots(self):
        purpose = self.record["proof_purposes"][0]
        self.assertEqual(purpose["relationship_status"], "USER_ASSERTED_PROOF_PURPOSE_UNVERIFIED")
        expected = {item["record"]["fact_candidate_id"] for item in self.specification["fact_candidates"]}
        self.assertEqual({item["fact_candidate_id"] for item in purpose["view_bindings"]}, expected)

    def test_missing_view_or_candidate_binding_is_refused(self):
        missing_view = copy.deepcopy(self.specification)
        missing_view["proof_purposes"][0]["view_ids"] = ["VIEW-" + "F" * 24]
        with self.assertRaises(EvidenceReviewError) as raised:
            build_evidence_review(missing_view)
        self.assertEqual(raised.exception.code, "EVIDENCE_REVIEW_VIEW_NOT_FOUND")

        missing_candidate = copy.deepcopy(self.specification)
        missing_candidate["fact_candidates"] = missing_candidate["fact_candidates"][:1]
        with self.assertRaises(EvidenceReviewError) as raised:
            build_evidence_review(missing_candidate)
        self.assertEqual(raised.exception.code, "EVIDENCE_REVIEW_VIEW_CANDIDATE_MISMATCH")

    def test_unused_candidate_is_refused(self):
        specification = copy.deepcopy(self.specification)
        first_view = specification["fact_analysis_record"]["views"][0]["view_id"]
        specification["proof_purposes"][0]["view_ids"] = [first_view]
        with self.assertRaises(EvidenceReviewError) as raised:
            build_evidence_review(specification)
        self.assertEqual(raised.exception.code, "EVIDENCE_REVIEW_UNUSED_CANDIDATE")

    def test_candidate_from_another_parse_or_invalidated_candidate_is_refused(self):
        other_parse = make_parse_record(("other evidence",))
        wrong_parse = copy.deepcopy(self.specification)
        wrong_parse["parse_record"] = other_parse
        with self.assertRaises(EvidenceReviewError):
            build_evidence_review(wrong_parse)

        invalidated = copy.deepcopy(self.specification)
        original = invalidated["fact_candidates"][0]["record"]
        invalidated["fact_candidates"][0] = {
            "record": invalidate_fact_candidate(
                original,
                invalidated["parse_record"],
                reason_code="OTHER",
                reason="synthetic invalidation",
                actor_label="u",
                created_at="2026-07-15T06:20:00Z",
            ),
            "previous_record": original,
        }
        with self.assertRaises(EvidenceReviewError):
            build_evidence_review(invalidated)

    def test_tampered_fact_analysis_is_refused(self):
        specification = copy.deepcopy(self.specification)
        specification["fact_analysis_record"]["views"][0]["value"] = "9999.00"
        with self.assertRaises(EvidenceReviewError) as raised:
            build_evidence_review(specification)
        self.assertEqual(raised.exception.code, "EVIDENCE_REVIEW_ANALYSIS_INVALID")

    def test_candidate_snapshot_change_cannot_reuse_old_analysis_view(self):
        specification = copy.deepcopy(self.specification)
        old = specification["fact_candidates"][0]["record"]
        anchor = specification["parse_record"]["anchors"][0]
        replacement = build_fact_candidate(
            specification["parse_record"],
            anchor_ids=[anchor["anchor_id"]],
            provenance_state="EXTRACTED",
            claim_type="WAGE_AMOUNT",
            assertion_text=anchor["text"],
            created_at="2026-07-15T06:01:00Z",
        )
        self.assertEqual(old["fact_candidate_id"], replacement["fact_candidate_id"])
        specification["fact_candidates"][0]["record"] = replacement
        with self.assertRaises(EvidenceReviewError) as raised:
            build_evidence_review(specification)
        self.assertEqual(raised.exception.code, "EVIDENCE_REVIEW_VIEW_CANDIDATE_MISMATCH")

    def test_duplicate_candidate_and_purpose_keys_are_refused(self):
        duplicate_candidate = copy.deepcopy(self.specification)
        duplicate_candidate["fact_candidates"].append(copy.deepcopy(duplicate_candidate["fact_candidates"][0]))
        with self.assertRaises(EvidenceReviewError) as raised:
            build_evidence_review(duplicate_candidate)
        self.assertEqual(raised.exception.code, "EVIDENCE_REVIEW_CANDIDATE_DUPLICATE")

        duplicate_purpose = copy.deepcopy(self.specification)
        duplicate_purpose["proof_purposes"].append(copy.deepcopy(duplicate_purpose["proof_purposes"][0]))
        with self.assertRaises(EvidenceReviewError) as raised:
            build_evidence_review(duplicate_purpose)
        self.assertEqual(raised.exception.code, "EVIDENCE_REVIEW_PURPOSE_KEY_DUPLICATE")

    def test_purpose_tamper_breaks_nested_and_record_snapshots(self):
        record = copy.deepcopy(self.record)
        record["proof_purposes"][0]["proposition"] = "tampered proposition"
        report = self.report(record)
        codes = {item["code"] for item in report["findings"]}
        self.assertFalse(report["allowed"])
        self.assertIn("EVIDENCE_REVIEW_PURPOSE_ID_MISMATCH", codes)
        self.assertIn("EVIDENCE_REVIEW_PURPOSE_SNAPSHOT_MISMATCH", codes)
        self.assertIn("EVIDENCE_REVIEW_SNAPSHOT_MISMATCH", codes)

    def test_gap_or_suggestion_cannot_be_removed_even_with_new_outer_hashes(self):
        for field in ("identified_gaps", "strengthening_suggestions"):
            record = copy.deepcopy(self.record)
            record[field] = record[field][1:]
            self.refresh(record)
            report = self.report(record)
            self.assertFalse(report["allowed"])
            expected = "EVIDENCE_REVIEW_GAP_SET_MISMATCH" if field == "identified_gaps" else "EVIDENCE_REVIEW_SUGGESTION_SET_MISMATCH"
            self.assertIn(expected, {item["code"] for item in report["findings"]})

    def test_schema_blocks_verified_or_admissible_escalation(self):
        cases = [
            ("authenticity_status", "VERIFIED"),
            ("admissibility_status", "ADMISSIBLE"),
            ("evidence_weight_status", "HIGH"),
            ("output_permission", "SUBMISSION_READY"),
        ]
        for field, value in cases:
            record = copy.deepcopy(self.record)
            record[field] = value
            report = self.report(record)
            self.assertFalse(report["allowed"])
            self.assertIn("EVIDENCE_REVIEW_SCHEMA_VALIDATION_ERROR", {item["code"] for item in report["findings"]})

    def test_corroboration_binding_remains_unverified(self):
        specification = copy.deepcopy(self.specification)
        specification["corroborating_review_bindings"] = [
            {"evidence_review_id": "EVREVIEW-" + "C" * 24, "record_snapshot_sha256": "d" * 64}
        ]
        record = build_evidence_review(specification)
        self.assertEqual(record["corroborating_review_bindings"][0]["relationship_status"], "USER_DECLARED_CORROBORATION_UNVERIFIED")
        self.assertIn("CORROBORATION", self.report(record)["validation_scope"]["not_verified"])

    def test_duplicate_and_self_corroboration_are_refused(self):
        duplicate = copy.deepcopy(self.specification)
        duplicate["corroborating_review_bindings"] = [
            {"evidence_review_id": "EVREVIEW-" + "C" * 24, "record_snapshot_sha256": "d" * 64},
            {"evidence_review_id": "EVREVIEW-" + "C" * 24, "record_snapshot_sha256": "e" * 64},
        ]
        with self.assertRaises(EvidenceReviewError) as raised:
            build_evidence_review(duplicate)
        self.assertEqual(raised.exception.code, "EVIDENCE_REVIEW_CORROBORATION_DUPLICATE")

        record = copy.deepcopy(self.record)
        record["corroborating_review_bindings"] = [
            {
                "evidence_review_id": record["evidence_review_id"],
                "record_snapshot_sha256": record["record_snapshot_sha256"],
                "relationship_status": "USER_DECLARED_CORROBORATION_UNVERIFIED",
            }
        ]
        self.refresh(record)
        record["corroborating_review_bindings"][0]["evidence_review_id"] = record["evidence_review_id"]
        report = self.report(record)
        self.assertFalse(report["allowed"])
        self.assertIn("EVIDENCE_REVIEW_SELF_CORROBORATION", {item["code"] for item in report["findings"]})

    def test_invalid_unicode_and_non_utc_time_fail_closed(self):
        invalid_unicode = copy.deepcopy(self.specification)
        invalid_unicode["actor_label"] = "\ud800"
        with self.assertRaises(EvidenceReviewError) as raised:
            build_evidence_review(invalid_unicode)
        self.assertEqual(raised.exception.code, "EVIDENCE_REVIEW_IJSON_INVALID")

        non_utc = copy.deepcopy(self.specification)
        non_utc["created_at"] = "2026-07-15T15:00:00+08:00"
        with self.assertRaises(EvidenceReviewError):
            build_evidence_review(non_utc)

    def test_input_order_is_normalized(self):
        reordered = copy.deepcopy(self.specification)
        reordered["fact_candidates"].reverse()
        reordered["proof_purposes"][0]["view_ids"].reverse()
        self.assertEqual(build_evidence_review(reordered), self.record)

    def test_cli_build_and_validate_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec_path = root / "spec.json"
            record_path = root / "review.json"
            spec_path.write_text(json.dumps(self.specification), encoding="utf-8")
            build = subprocess.run(
                [sys.executable, str(SCRIPT_DIRECTORY / "build_evidence_review.py"), str(spec_path)],
                capture_output=True, text=True, encoding="utf-8", check=False,
            )
            self.assertEqual(build.returncode, 0, build.stderr + build.stdout)
            record_path.write_text(build.stdout, encoding="utf-8")
            validate = subprocess.run(
                [sys.executable, str(SCRIPT_DIRECTORY / "validate_evidence_review.py"), str(record_path)],
                capture_output=True, text=True, encoding="utf-8", check=False,
            )
            self.assertEqual(validate.returncode, 0, validate.stderr + validate.stdout)
            self.assertTrue(json.loads(validate.stdout)["allowed"])


if __name__ == "__main__":
    unittest.main()
