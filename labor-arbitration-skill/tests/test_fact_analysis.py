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

from fact_analysis_policy import (  # noqa: E402
    FactAnalysisError,
    build_fact_analysis,
    calculate_analysis_id,
    calculate_analysis_snapshot,
    calculate_upstream_snapshot,
    calculate_view_id,
    calculate_view_snapshot,
    detect_conflicts,
    validate_fact_analysis_record,
)
from fact_candidate_policy import build_fact_candidate, invalidate_fact_candidate  # noqa: E402
from tests.test_fact_candidate_model import make_parse_record  # noqa: E402


def source_input(view_key, dimension_key, kind, value, role="NONE", text=None):
    text = text or f"synthetic source for {view_key}"
    parse_record = make_parse_record((text,))
    candidate = build_fact_candidate(
        parse_record,
        anchor_ids=[parse_record["anchors"][0]["anchor_id"]],
        provenance_state="EXTRACTED",
        claim_type={"DATE": "EMPLOYMENT_DATE", "AMOUNT_CNY": "WAGE_AMOUNT", "SUBJECT_KEY": "PARTY_IDENTITY"}[kind],
        assertion_text=text,
        created_at="2026-07-15T06:00:00Z",
    )
    return {
        "view_key": view_key,
        "dimension_key": dimension_key,
        "semantic_kind": kind,
        "value": value,
        "timeline_role": role,
        "actor_label": "local-structurer",
        "fact_candidate_record": candidate,
        "parse_record": parse_record,
        "previous_fact_candidate_record": None,
    }


def base_inputs():
    return [
        source_input("DATE.START.A", "EMPLOYMENT.START", "DATE", "2025-02-01", "EMPLOYMENT_START"),
        source_input("DATE.START.B", "EMPLOYMENT.START", "DATE", "2025-01-01", "EMPLOYMENT_START"),
        source_input("DATE.END.A", "EMPLOYMENT.END", "DATE", "2025-01-01", "EMPLOYMENT_END"),
        source_input("DATE.TERMINATION.A", "TERMINATION.DATE", "DATE", "2025-03-01", "TERMINATION"),
        source_input("AMOUNT.WAGE.A", "WAGE.2025-01", "AMOUNT_CNY", "5000.00"),
        source_input("AMOUNT.WAGE.B", "WAGE.2025-01", "AMOUNT_CNY", "6000.00"),
        source_input("SUBJECT.EMPLOYER.A", "EMPLOYER.IDENTITY", "SUBJECT_KEY", "COMPANY_A"),
        source_input("SUBJECT.EMPLOYER.B", "EMPLOYER.IDENTITY", "SUBJECT_KEY", "COMPANY_B"),
    ]


def specification(inputs=None, previous=None, created_at="2026-07-15T07:00:00Z"):
    return {
        "schema_version": "1.0",
        "artifact_id": "ANALYSIS-SYNTHETIC_CASE",
        "created_at": created_at,
        "inputs": inputs if inputs is not None else base_inputs(),
        "previous_analysis_record": previous,
    }


class FactAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.inputs = base_inputs()
        self.baseline = build_fact_analysis(specification(self.inputs))

    def report(self, record, previous=None):
        return validate_fact_analysis_record(record, previous)

    def refresh_view(self, view):
        view["view_id"] = calculate_view_id(view)
        view["view_snapshot_sha256"] = calculate_view_snapshot(view)

    def refresh_record(self, record):
        record["views"].sort(key=lambda item: item["view_key"])
        record["upstream_snapshot_sha256"] = calculate_upstream_snapshot(record["views"])
        record["analysis_id"] = calculate_analysis_id(record)
        record["record_snapshot_sha256"] = calculate_analysis_snapshot(record)

    def test_date_amount_subject_and_timeline_conflicts_are_deterministic(self):
        types = [item["conflict_type"] for item in self.baseline["conflicts"]]
        self.assertCountEqual(
            types,
            [
                "DATE_VALUE_CONFLICT",
                "AMOUNT_VALUE_CONFLICT",
                "SUBJECT_VALUE_CONFLICT",
                "TIMELINE_ORDER_CONFLICT",
                "TERMINATION_OUTSIDE_EMPLOYMENT_CONFLICT",
            ],
        )
        self.assertTrue(all(item["status"] == "PENDING_HUMAN_REVIEW" for item in self.baseline["conflicts"]))
        self.assertTrue(all(item["auto_selected_view_id"] is None and item["resolution"] is None for item in self.baseline["conflicts"]))

    def test_baseline_report_never_establishes_truth_identity_or_submission(self):
        report = self.report(self.baseline)
        self.assertTrue(report["allowed"], report["findings"])
        self.assertFalse(report["fact_truth_established"])
        self.assertFalse(report["human_identity_authenticated"])
        self.assertFalse(report["submission_ready"])
        self.assertEqual(self.baseline["output_permission"], "INTERNAL_ANALYSIS_ONLY")

    def test_input_order_does_not_change_views_conflicts_or_identity(self):
        reordered = build_fact_analysis(specification(list(reversed(self.inputs))))
        self.assertEqual(reordered, self.baseline)

    def test_equal_values_do_not_create_value_conflict(self):
        inputs = [
            source_input("AMOUNT.A", "WAGE.MONTH", "AMOUNT_CNY", "5000.00"),
            source_input("AMOUNT.B", "WAGE.MONTH", "AMOUNT_CNY", "5000.00"),
        ]
        record = build_fact_analysis(specification(inputs))
        self.assertEqual(record["conflicts"], [])

    def test_same_dimension_with_different_semantic_kinds_is_explicit_conflict(self):
        inputs = [
            source_input("VALUE.DATE", "SAME.DIMENSION", "DATE", "2025-01-01"),
            source_input("VALUE.AMOUNT", "SAME.DIMENSION", "AMOUNT_CNY", "5000.00"),
        ]
        record = build_fact_analysis(specification(inputs))
        self.assertEqual([item["conflict_type"] for item in record["conflicts"]], ["SEMANTIC_KIND_CONFLICT"])

    def test_engine_version_is_bound_into_upstream_snapshot(self):
        self.assertEqual(self.baseline["engine"]["version"], "1.0.0")
        record = copy.deepcopy(self.baseline)
        record["engine"]["version"] = "9.9.9"
        report = self.report(record)
        codes = {item["code"] for item in report["findings"]}
        self.assertFalse(report["allowed"])
        self.assertIn("FACT_ANALYSIS_SCHEMA_VALIDATION_ERROR", codes)

    def test_all_structured_values_are_explicitly_user_supplied_unverified(self):
        for view in self.baseline["views"]:
            self.assertEqual(view["actor_assertion"], "USER_STRUCTURED_UNAUTHENTICATED")
            self.assertEqual(view["value_status"], "USER_STRUCTURED_UNAUTHENTICATED")
            self.assertEqual(view["truth_status"], "UNVERIFIED")

    def test_invalid_date_amount_subject_and_role_are_refused(self):
        cases = [
            ("DATE", "2025-02-30", "NONE"),
            ("DATE", "20250201", "NONE"),
            ("AMOUNT_CNY", "5e3", "NONE"),
            ("AMOUNT_CNY", "5000.0", "NONE"),
            ("SUBJECT_KEY", "Company A", "NONE"),
            ("SUBJECT_KEY", "AA", "NONE"),
            ("AMOUNT_CNY", "5000.00", "EMPLOYMENT_START"),
        ]
        for index, (kind, value, role) in enumerate(cases):
            with self.subTest(kind=kind, value=value, role=role), self.assertRaises(FactAnalysisError):
                build_fact_analysis(specification([source_input(f"VALUE.{index}", "VALUE.TEST", kind, value, role)]))

    def test_invalid_unicode_actor_fails_closed_without_crashing(self):
        inputs = copy.deepcopy(self.inputs[:1])
        inputs[0]["actor_label"] = "\ud800"
        with self.assertRaises(FactAnalysisError) as raised:
            build_fact_analysis(specification(inputs))
        self.assertEqual(raised.exception.code, "FACT_ANALYSIS_IJSON_INVALID")

        record = copy.deepcopy(self.baseline)
        record["views"][0]["actor_label"] = "\ud800"
        report = self.report(record)
        self.assertFalse(report["allowed"])
        self.assertIn("FACT_ANALYSIS_VIEW_CANONICALIZATION_FAILED", {item["code"] for item in report["findings"]})

    def test_conflict_explosion_is_bounded_without_truncation(self):
        views = []
        for index in range(143):
            views.append(
                {
                    "view_id": f"VIEW-{index:024X}",
                    "dimension_key": "AMOUNT.SAME",
                    "semantic_kind": "AMOUNT_CNY",
                    "value": f"{index}.00",
                    "timeline_role": "NONE",
                }
            )
        with self.assertRaises(FactAnalysisError) as raised:
            detect_conflicts(views)
        self.assertEqual(raised.exception.code, "FACT_ANALYSIS_CONFLICT_LIMIT_EXCEEDED")

    def test_duplicate_view_key_is_refused(self):
        inputs = [
            source_input("VALUE.SAME", "WAGE.A", "AMOUNT_CNY", "1.00"),
            source_input("VALUE.SAME", "WAGE.B", "AMOUNT_CNY", "2.00"),
        ]
        with self.assertRaises(FactAnalysisError) as raised:
            build_fact_analysis(specification(inputs))
        self.assertEqual(raised.exception.code, "FACT_ANALYSIS_VIEW_KEY_DUPLICATE")

    def test_tampered_or_invalidated_fact_candidate_is_refused(self):
        tampered = copy.deepcopy(self.inputs[0])
        tampered["fact_candidate_record"]["assertion"]["text"] = "tampered"
        with self.assertRaises(FactAnalysisError):
            build_fact_analysis(specification([tampered]))

        invalidated = copy.deepcopy(self.inputs[0])
        invalidated["fact_candidate_record"] = invalidate_fact_candidate(
            invalidated["fact_candidate_record"],
            invalidated["parse_record"],
            reason_code="OTHER",
            reason="synthetic invalidation",
            actor_label="u",
            created_at="2026-07-15T06:30:00Z",
        )
        invalidated["previous_fact_candidate_record"] = self.inputs[0]["fact_candidate_record"]
        with self.assertRaises(FactAnalysisError):
            build_fact_analysis(specification([invalidated]))

    def test_view_value_tamper_breaks_view_conflict_and_record_bindings(self):
        record = copy.deepcopy(self.baseline)
        record["views"][0]["value"] = "2024-01-01"
        report = self.report(record)
        codes = {item["code"] for item in report["findings"]}
        self.assertFalse(report["allowed"])
        self.assertIn("FACT_ANALYSIS_VIEW_ID_MISMATCH", codes)
        self.assertIn("FACT_ANALYSIS_CONFLICT_SET_MISMATCH", codes)
        self.assertIn("FACT_ANALYSIS_RECORD_SNAPSHOT_MISMATCH", codes)

    def test_conflict_cannot_be_resolved_or_auto_selected_in_record(self):
        for field, value in (("resolution", "pick first"), ("auto_selected_view_id", self.baseline["views"][0]["view_id"])):
            record = copy.deepcopy(self.baseline)
            record["conflicts"][0][field] = value
            report = self.report(record)
            self.assertFalse(report["allowed"])
            self.assertIn("FACT_ANALYSIS_SCHEMA_VALIDATION_ERROR", {item["code"] for item in report["findings"]})

    def test_unchanged_revision_is_current(self):
        current = build_fact_analysis(specification(self.inputs, self.baseline, "2026-07-15T08:00:00Z"))
        report = self.report(current, self.baseline)
        self.assertTrue(report["allowed"], report["findings"])
        self.assertEqual(current["invalidation"]["status"], "CURRENT")
        self.assertEqual(current["invalidation"]["changed_view_keys"], [])
        self.assertFalse(report["downstream_revalidation_required"])

    def test_value_change_invalidates_exact_view_key(self):
        changed_inputs = copy.deepcopy(self.inputs)
        changed_inputs[4]["value"] = "5500.00"
        changed = build_fact_analysis(specification(changed_inputs, self.baseline, "2026-07-15T08:00:00Z"))
        report = self.report(changed, self.baseline)
        self.assertTrue(report["allowed"], report["findings"])
        self.assertEqual(changed["invalidation"]["status"], "INVALIDATED_BY_FACT_CHANGE")
        self.assertEqual(changed["invalidation"]["changed_view_keys"], ["AMOUNT.WAGE.A"])
        self.assertTrue(report["downstream_revalidation_required"])
        self.assertEqual(report["next_required_state"], "REVALIDATE_DOWNSTREAM_DEPENDENCIES")

    def test_fact_candidate_snapshot_change_invalidates_even_when_value_is_same(self):
        changed_inputs = copy.deepcopy(self.inputs)
        old = changed_inputs[4]
        candidate = build_fact_candidate(
            old["parse_record"],
            anchor_ids=[old["parse_record"]["anchors"][0]["anchor_id"]],
            provenance_state="EXTRACTED",
            claim_type="WAGE_AMOUNT",
            assertion_text=old["parse_record"]["anchors"][0]["text"],
            created_at="2026-07-15T06:01:00Z",
        )
        self.assertEqual(candidate["fact_candidate_id"], old["fact_candidate_record"]["fact_candidate_id"])
        self.assertNotEqual(candidate["record_snapshot_sha256"], old["fact_candidate_record"]["record_snapshot_sha256"])
        old["fact_candidate_record"] = candidate
        changed = build_fact_analysis(specification(changed_inputs, self.baseline, "2026-07-15T08:00:00Z"))
        self.assertEqual(changed["invalidation"]["changed_view_keys"], ["AMOUNT.WAGE.A"])

    def test_added_and_removed_views_are_both_reported(self):
        changed_inputs = copy.deepcopy(self.inputs[1:])
        changed_inputs.append(source_input("AMOUNT.BONUS.A", "BONUS.2025", "AMOUNT_CNY", "1000.00"))
        changed = build_fact_analysis(specification(changed_inputs, self.baseline, "2026-07-15T08:00:00Z"))
        self.assertEqual(changed["invalidation"]["changed_view_keys"], ["AMOUNT.BONUS.A", "DATE.START.A"])

    def test_derived_record_requires_exact_previous_record(self):
        current = build_fact_analysis(specification(self.inputs, self.baseline, "2026-07-15T08:00:00Z"))
        report = self.report(current)
        self.assertFalse(report["allowed"])
        self.assertIn("FACT_ANALYSIS_PREVIOUS_RECORD_REQUIRED", {item["code"] for item in report["findings"]})
        wrong = copy.deepcopy(self.baseline)
        wrong["record_snapshot_sha256"] = "f" * 64
        report = self.report(current, wrong)
        self.assertFalse(report["allowed"])
        self.assertIn("FACT_ANALYSIS_PREVIOUS_RECORD_MISMATCH", {item["code"] for item in report["findings"]})

    def test_previous_artifact_mismatch_tamper_and_time_rollback_are_refused(self):
        wrong_artifact = copy.deepcopy(self.baseline)
        wrong_artifact["artifact_id"] = "ANALYSIS-OTHER"
        with self.assertRaises(FactAnalysisError):
            build_fact_analysis(specification(self.inputs, wrong_artifact, "2026-07-15T08:00:00Z"))
        tampered = copy.deepcopy(self.baseline)
        tampered["views"][0]["value"] = "2024-01-01"
        with self.assertRaises(FactAnalysisError):
            build_fact_analysis(specification(self.inputs, tampered, "2026-07-15T08:00:00Z"))
        with self.assertRaises(FactAnalysisError):
            build_fact_analysis(specification(self.inputs, self.baseline, "2026-07-15T06:59:59Z"))

    def test_invalidation_declaration_tamper_fails_even_with_new_hashes(self):
        changed_inputs = copy.deepcopy(self.inputs)
        changed_inputs[4]["value"] = "5500.00"
        record = build_fact_analysis(specification(changed_inputs, self.baseline, "2026-07-15T08:00:00Z"))
        record["invalidation"]["changed_view_keys"] = []
        self.refresh_record(record)
        report = self.report(record, self.baseline)
        self.assertFalse(report["allowed"])
        self.assertIn("FACT_ANALYSIS_INVALIDATION_MISMATCH", {item["code"] for item in report["findings"]})

    def test_non_utc_date_and_schema_extras_are_refused(self):
        bad_time = specification(self.inputs, created_at="2026-07-15T15:00:00+08:00")
        with self.assertRaises(FactAnalysisError):
            build_fact_analysis(bad_time)
        extra = specification(self.inputs)
        extra["unexpected"] = True
        with self.assertRaises(FactAnalysisError):
            build_fact_analysis(extra)

    def test_cli_build_and_validate_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec_path = root / "spec.json"
            record_path = root / "analysis.json"
            spec_path.write_text(json.dumps(specification(self.inputs)), encoding="utf-8")
            build = subprocess.run(
                [sys.executable, str(SCRIPT_DIRECTORY / "build_fact_analysis.py"), str(spec_path)],
                capture_output=True, text=True, encoding="utf-8", check=False,
            )
            self.assertEqual(build.returncode, 0, build.stderr + build.stdout)
            record_path.write_text(build.stdout, encoding="utf-8")
            validate = subprocess.run(
                [sys.executable, str(SCRIPT_DIRECTORY / "validate_fact_analysis.py"), str(record_path)],
                capture_output=True, text=True, encoding="utf-8", check=False,
            )
            self.assertEqual(validate.returncode, 0, validate.stderr + validate.stdout)
            self.assertTrue(json.loads(validate.stdout)["allowed"])

    def test_cli_rejects_non_object_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad.json"
            path.write_text("[]", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPT_DIRECTORY / "build_fact_analysis.py"), str(path)],
                capture_output=True, text=True, encoding="utf-8", check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("FACT_ANALYSIS_INPUT_ROOT_NOT_OBJECT", result.stdout)


if __name__ == "__main__":
    unittest.main()
