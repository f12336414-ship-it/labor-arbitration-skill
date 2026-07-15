import copy
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = SKILL_ROOT.parent
SCRIPT_DIRECTORY = SKILL_ROOT / "scripts"
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from legal_freshness_policy import (  # noqa: E402
    build_legal_freshness_check,
    calculate_legal_freshness_snapshot,
)
from legal_monitor_policy import (  # noqa: E402
    LegalMonitorError,
    build_legal_monitor_definition,
    build_legal_monitor_run,
    calculate_definition_snapshot,
    calculate_run_id,
    calculate_run_snapshot,
    validate_legal_monitor_definition,
    validate_legal_monitor_run,
)


FRESHNESS_EXAMPLE = REPOSITORY_ROOT / "examples" / "legal-sources" / "synthetic-freshness-unchanged.json"
BUILD_DEFINITION = SCRIPT_DIRECTORY / "build_legal_monitor_definition.py"
VALIDATE_DEFINITION = SCRIPT_DIRECTORY / "validate_legal_monitor_definition.py"
BUILD_RUN = SCRIPT_DIRECTORY / "build_legal_monitor_run.py"
VALIDATE_RUN = SCRIPT_DIRECTORY / "validate_legal_monitor_run.py"


def example_check():
    return json.loads(FRESHNESS_EXAMPLE.read_text(encoding="utf-8"))


def definition_spec(source_overrides=None):
    check = example_check()
    source = {
        "source_monitor_id": "LSOURCE-SYNTHETIC-WAGE",
        "document_id": check["document_id"],
        "publisher_code": check["publisher_code"],
        "canonical_url": check["baseline"]["final_url"],
        "baseline": copy.deepcopy(check["baseline"]),
        "interval_hours": 24,
        "retry_interval_hours": 1,
        "max_age_hours": 24,
        "failure_window_runs": 3,
        "max_failures_in_window": 1,
        "urgency": "CRITICAL",
    }
    source.update(source_overrides or {})
    return {
        "schema_version": "1.0",
        "monitor_id": "LEGALMON-SYNTHETIC",
        "created_at": "2026-07-15T03:00:00Z",
        "owner_role": "LEGAL_SOURCE_ADMIN",
        "sources": [source],
    }


def iso(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def make_check(checked_at, kind="UNCHANGED"):
    base = example_check()
    checked = datetime.fromisoformat(checked_at[:-1] + "+00:00")
    observation = copy.deepcopy(base["observation"])
    observed_at = checked - timedelta(minutes=1)
    observation["fetch_id"] = "FETCH-" + observed_at.strftime("%Y%m%dT%H%M%SZ") + "-aaaaaaaaaaaaaaaa"
    observation["record_snapshot_sha256"] = checked.strftime("%Y%m%d%H%M").ljust(64, "a")
    observation["fetched_at"] = iso(observed_at)
    if kind == "CHANGED":
        observation["content_sha256"] = "a" * 64
    elif kind == "STALE":
        observation["fetched_at"] = "2026-07-14T04:00:00Z"
    elif kind == "UNAVAILABLE":
        observation = None
    return build_legal_freshness_check(
        document_id=base["document_id"],
        publisher_code=base["publisher_code"],
        baseline=copy.deepcopy(base["baseline"]),
        observation=observation,
        checked_at=checked_at,
        max_age_hours=24,
    )


def run_spec(definition, evaluated_at, checks=None, previous=None):
    return {
        "schema_version": "1.0",
        "evaluated_at": evaluated_at,
        "definition": definition,
        "previous_run": previous,
        "freshness_checks": [
            {"source_monitor_id": "LSOURCE-SYNTHETIC-WAGE", "check": item}
            for item in (checks or [])
        ],
    }


def finding_codes(report):
    return {item["code"] for item in report["findings"]}


def relock_definition(definition):
    definition["definition_snapshot_sha256"] = calculate_definition_snapshot(definition)
    return definition


def relock_run(record):
    record["run_id"] = calculate_run_id(record)
    record["run_snapshot_sha256"] = calculate_run_snapshot(record)
    return record


class LegalMonitorDefinitionTests(unittest.TestCase):
    def test_definition_is_deterministic_and_never_attests_currentness(self):
        first = build_legal_monitor_definition(definition_spec())
        second = build_legal_monitor_definition(definition_spec())

        self.assertEqual(first, second)
        report = validate_legal_monitor_definition(first)
        self.assertTrue(report["allowed"], report["findings"])
        self.assertFalse(report["legal_currentness_verified"])
        self.assertFalse(report["submission_ready"])

    def test_sources_are_sorted_and_input_order_does_not_change_identity(self):
        spec = definition_spec()
        other = copy.deepcopy(spec["sources"][0])
        other["source_monitor_id"] = "LSOURCE-A-SYNTHETIC"
        other["document_id"] = "SYNTHETIC_OTHER_RULE"
        spec["sources"].append(other)
        reversed_spec = copy.deepcopy(spec)
        reversed_spec["sources"].reverse()

        self.assertEqual(
            build_legal_monitor_definition(spec),
            build_legal_monitor_definition(reversed_spec),
        )

    def test_duplicate_source_or_document_is_rejected(self):
        for field in ("source_monitor_id", "document_id"):
            spec = definition_spec()
            other = copy.deepcopy(spec["sources"][0])
            other["source_monitor_id"] = "LSOURCE-OTHER"
            other["document_id"] = "SYNTHETIC_OTHER_RULE"
            other[field] = spec["sources"][0][field]
            spec["sources"].append(other)
            with self.subTest(field=field), self.assertRaises(LegalMonitorError) as caught:
                build_legal_monitor_definition(spec)
            self.assertEqual(caught.exception.code, "LEGAL_MONITOR_SOURCE_ORDER_OR_IDENTITY_INVALID")

    def test_off_allowlist_retry_and_failure_budget_are_rejected(self):
        cases = [
            ({"retry_interval_hours": 25}, "LEGAL_MONITOR_RETRY_INTERVAL_INVALID"),
            ({"max_failures_in_window": 3}, "LEGAL_MONITOR_FAILURE_BUDGET_INVALID"),
        ]
        for overrides, code in cases:
            with self.subTest(code=code), self.assertRaises(LegalMonitorError) as caught:
                build_legal_monitor_definition(definition_spec(overrides))
            self.assertEqual(caught.exception.code, code)

        off_allowlist = definition_spec({"canonical_url": "https://example.com/rule"})
        off_allowlist["sources"][0]["baseline"]["final_url"] = "https://example.com/rule"
        with self.assertRaises(LegalMonitorError) as caught:
            build_legal_monitor_definition(off_allowlist)
        self.assertEqual(caught.exception.code, "LEGAL_MONITOR_SOURCE_NOT_ALLOWLISTED")

    def test_baseline_after_definition_is_rejected(self):
        spec = definition_spec()
        spec["sources"][0]["baseline"]["fetched_at"] = "2026-07-15T04:00:00Z"

        with self.assertRaises(LegalMonitorError) as caught:
            build_legal_monitor_definition(spec)

        self.assertEqual(caught.exception.code, "LEGAL_MONITOR_BASELINE_TIME_INVALID")


class LegalMonitorRunTests(unittest.TestCase):
    def setUp(self):
        self.definition = build_legal_monitor_definition(definition_spec())

    def build(self, evaluated_at, kind="UNCHANGED", previous=None):
        check = make_check(evaluated_at, kind) if kind else None
        return build_legal_monitor_run(
            run_spec(self.definition, evaluated_at, [check] if check else [], previous)
        )

    def test_unchanged_first_run_is_healthy_but_never_promotes(self):
        record = self.build("2026-07-15T03:00:00Z")
        report = validate_legal_monitor_run(record, self.definition)

        self.assertTrue(report["allowed"], report["findings"])
        self.assertEqual(record["overall_status"], "HEALTHY_TECHNICALLY_UNCHANGED")
        self.assertEqual(record["required_output_state"], "NO_PROMOTION_GRANTED")
        self.assertTrue(record["legal_review_required"])
        self.assertFalse(report["legal_currentness_verified"])
        self.assertFalse(report["submission_ready"])

    def test_changed_unavailable_stale_and_missed_checks_force_draft(self):
        cases = [
            ("CHANGED", "LEGAL_SOURCE_CHANGE_DETECTED", "CRITICAL_DRAFT_ONLY"),
            ("UNAVAILABLE", "LEGAL_SOURCE_CHECK_UNAVAILABLE", "WARNING_DRAFT_ONLY"),
            ("STALE", "LEGAL_SOURCE_CHECK_STALE", "WARNING_DRAFT_ONLY"),
            (None, "LEGAL_SOURCE_CHECK_MISSED", "WARNING_DRAFT_ONLY"),
        ]
        for kind, code, overall in cases:
            record = self.build("2026-07-16T03:00:00Z", kind)
            with self.subTest(kind=kind):
                self.assertEqual(record["required_output_state"], "DRAFT")
                self.assertEqual(record["overall_status"], overall)
                self.assertIn(code, {item["code"] for item in record["alerts"]})

    def test_not_due_run_carries_state_without_consuming_budget(self):
        first = self.build("2026-07-15T03:00:00Z")
        carried = self.build("2026-07-15T04:00:00Z", None, first)

        self.assertEqual(carried["source_states"][0]["check_execution_status"], "CARRIED_FORWARD_NOT_DUE")
        self.assertEqual(carried["source_states"][0]["recent_outcomes"], ["SUCCESS"])
        self.assertEqual(carried["source_states"][0]["next_due_at"], "2026-07-16T03:00:00Z")
        self.assertEqual(carried["alerts"], [])

    def test_explicit_early_check_is_recorded(self):
        first = self.build("2026-07-15T03:00:00Z")
        early = self.build("2026-07-15T04:00:00Z", "UNCHANGED", first)

        self.assertEqual(early["source_states"][0]["check_execution_status"], "CHECKED")
        self.assertEqual(early["source_states"][0]["next_due_at"], "2026-07-16T04:00:00Z")

    def test_repeated_failures_exhaust_and_successes_restore_rolling_budget(self):
        first = self.build("2026-07-15T03:00:00Z", "UNAVAILABLE")
        exhausted = self.build("2026-07-15T04:00:00Z", None, first)
        still_exhausted = self.build("2026-07-15T05:00:00Z", "UNCHANGED", exhausted)
        restored = self.build("2026-07-16T05:00:00Z", "UNCHANGED", still_exhausted)

        self.assertEqual(exhausted["source_states"][0]["error_budget"]["status"], "EXHAUSTED")
        self.assertIn("LEGAL_SOURCE_ERROR_BUDGET_EXHAUSTED", {item["code"] for item in exhausted["alerts"]})
        self.assertEqual(still_exhausted["required_output_state"], "DRAFT")
        self.assertEqual(restored["source_states"][0]["recent_outcomes"], ["MISSED", "SUCCESS", "SUCCESS"])
        self.assertEqual(restored["source_states"][0]["error_budget"]["status"], "WITHIN_BUDGET")
        self.assertEqual(restored["required_output_state"], "NO_PROMOTION_GRANTED")

    def test_check_binding_mismatches_are_rejected(self):
        mutations = [
            lambda check: check.update(document_id="OTHER_RULE"),
            lambda check: check.update(publisher_code="SUPREME_PEOPLES_COURT"),
            lambda check: check.update(checked_at="2026-07-15T04:00:00Z"),
            lambda check: check.update(max_age_hours=12),
        ]
        for mutate in mutations:
            check = make_check("2026-07-15T03:00:00Z")
            mutate(check)
            check["check_snapshot_sha256"] = calculate_legal_freshness_snapshot(check)
            with self.subTest(mutate=mutate), self.assertRaises(LegalMonitorError) as caught:
                build_legal_monitor_run(run_spec(self.definition, "2026-07-15T03:00:00Z", [check]))
            self.assertIn(caught.exception.code, {"LEGAL_MONITOR_FRESHNESS_CHECK_INVALID", "LEGAL_MONITOR_FRESHNESS_BINDING_MISMATCH"})

    def test_unknown_and_duplicate_check_sources_are_rejected(self):
        check = make_check("2026-07-15T03:00:00Z")
        spec = run_spec(self.definition, "2026-07-15T03:00:00Z", [check])
        spec["freshness_checks"][0]["source_monitor_id"] = "LSOURCE-UNKNOWN"
        with self.assertRaises(LegalMonitorError) as unknown:
            build_legal_monitor_run(spec)
        self.assertEqual(unknown.exception.code, "LEGAL_MONITOR_CHECK_SOURCE_UNKNOWN")

        duplicate = run_spec(self.definition, "2026-07-15T03:00:00Z", [check, check])
        with self.assertRaises(LegalMonitorError) as repeated:
            build_legal_monitor_run(duplicate)
        self.assertEqual(repeated.exception.code, "LEGAL_MONITOR_CHECK_DUPLICATE")

    def test_previous_run_is_required_and_must_be_exact(self):
        first = self.build("2026-07-15T03:00:00Z")
        second = self.build("2026-07-16T03:00:00Z", "UNCHANGED", first)

        missing = validate_legal_monitor_run(second, self.definition)
        self.assertIn("LEGAL_MONITOR_PREVIOUS_RUN_REQUIRED", finding_codes(missing))

        wrong = copy.deepcopy(first)
        wrong["evaluated_at"] = "2026-07-15T02:00:00Z"
        relock_run(wrong)
        report = validate_legal_monitor_run(second, self.definition, wrong)
        self.assertIn("LEGAL_MONITOR_PREVIOUS_RUN_MISMATCH", finding_codes(report))

    def test_time_rollback_is_rejected(self):
        first = self.build("2026-07-15T03:00:00Z")
        with self.assertRaises(LegalMonitorError) as caught:
            self.build("2026-07-15T02:00:00Z", "UNCHANGED", first)
        self.assertEqual(caught.exception.code, "LEGAL_MONITOR_TIME_ROLLBACK")

    def test_snapshot_and_derivation_tampering_are_detected(self):
        record = self.build("2026-07-15T03:00:00Z")
        record["overall_status"] = "WARNING_DRAFT_ONLY"
        report = validate_legal_monitor_run(record, self.definition)
        self.assertIn("LEGAL_MONITOR_RUN_SNAPSHOT_MISMATCH", finding_codes(report))

        relock_run(record)
        report = validate_legal_monitor_run(record, self.definition)
        self.assertIn("LEGAL_MONITOR_RUN_DERIVATION_MISMATCH", finding_codes(report))

    def test_invalid_previous_state_identity_is_rejected_even_if_relocked(self):
        first = self.build("2026-07-15T03:00:00Z")
        second = self.build("2026-07-16T03:00:00Z", "UNCHANGED", first)
        second["source_states"].append(copy.deepcopy(second["source_states"][0]))
        relock_run(second)

        with self.assertRaises(LegalMonitorError) as caught:
            self.build("2026-07-17T03:00:00Z", "UNCHANGED", second)

        self.assertEqual(caught.exception.code, "LEGAL_MONITOR_PREVIOUS_STATE_ORDER_OR_IDENTITY_INVALID")


class LegalMonitorCliTests(unittest.TestCase):
    def run_cli(self, command):
        return subprocess.run(
            [sys.executable, *map(str, command)],
            cwd=SKILL_ROOT,
            capture_output=True,
            encoding="utf-8",
            check=False,
        )

    def test_build_and_validate_cli_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            spec_path = root / "definition-input.json"
            definition_path = root / "definition.json"
            run_spec_path = root / "run-input.json"
            run_path = root / "run.json"
            spec_path.write_text(json.dumps(definition_spec()), encoding="utf-8")

            built_definition = self.run_cli([BUILD_DEFINITION, spec_path])
            self.assertEqual(built_definition.returncode, 0, built_definition.stdout + built_definition.stderr)
            definition_path.write_text(built_definition.stdout, encoding="utf-8")
            validated_definition = self.run_cli([VALIDATE_DEFINITION, definition_path])
            self.assertEqual(validated_definition.returncode, 0, validated_definition.stdout + validated_definition.stderr)

            definition = json.loads(built_definition.stdout)
            specification = run_spec(definition, "2026-07-15T03:00:00Z", [make_check("2026-07-15T03:00:00Z")])
            run_spec_path.write_text(json.dumps(specification), encoding="utf-8")
            built_run = self.run_cli([BUILD_RUN, run_spec_path])
            self.assertEqual(built_run.returncode, 0, built_run.stdout + built_run.stderr)
            run_path.write_text(built_run.stdout, encoding="utf-8")
            validated_run = self.run_cli([VALIDATE_RUN, run_path, "--definition", definition_path])
            self.assertEqual(validated_run.returncode, 0, validated_run.stdout + validated_run.stderr)
            self.assertFalse(json.loads(validated_run.stdout)["legal_currentness_verified"])

    def test_cli_rejects_duplicate_json_keys(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "duplicate.json"
            path.write_text('{"schema_version":"1.0","schema_version":"1.0"}', encoding="utf-8")
            result = self.run_cli([BUILD_DEFINITION, path])

        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["error"]["code"], "LEGAL_MONITOR_DEFINITION_INPUT_DUPLICATE_KEY")


if __name__ == "__main__":
    unittest.main()
