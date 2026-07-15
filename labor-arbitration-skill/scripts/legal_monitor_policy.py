"""Deterministic legal-source due scheduling, alerts, and error budgets."""

from __future__ import annotations

import copy
from datetime import timedelta

import rfc8785

from finding_model import finding
from integrity_primitives import (
    calculate_json_snapshot,
    is_rfc3339_datetime,
    parse_rfc3339_datetime,
)
from legal_freshness_policy import validate_legal_freshness_check
from schema_validation import (
    validate_published_legal_monitor_definition,
    validate_published_legal_monitor_definition_input,
    validate_published_legal_monitor_run,
    validate_published_legal_monitor_run_input,
)
from source_fetch_policy import FetchRefusal, validate_fetch_target


DEFINITION_LIMITATIONS = [
    "SCHEDULER_INVOCATION_IS_EXTERNAL",
    "UNCHANGED_BYTES_DO_NOT_PROVE_LEGAL_CURRENTNESS",
    "MONITORING_DOES_NOT_AUTHENTICATE_PUBLISHER_OR_LEGAL_EFFECT",
    "ALERTS_REQUIRE_HUMAN_AND_LEGAL_REVIEW",
]
RUN_LIMITATIONS = [
    "UNCHANGED_BYTES_DO_NOT_PROVE_LEGAL_CURRENTNESS",
    "MONITOR_CLOCK_AND_SCHEDULER_ARE_NOT_ATTESTED",
    "PUBLISHER_AUTHORSHIP_LEGAL_EFFECT_AND_APPLICABILITY_NOT_VERIFIED",
    "NO_AUTOMATIC_BASELINE_PROMOTION_AFTER_CHANGE",
    "NO_SUBMISSION_READINESS",
]


class LegalMonitorError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def calculate_definition_id(definition: dict) -> str:
    identity = calculate_json_snapshot(
        {
            "monitor_id": definition["monitor_id"],
            "owner_role": definition["owner_role"],
            "sources": definition["sources"],
        }
    )
    return f"LMDEF-{identity[:24].upper()}"


def calculate_definition_snapshot(definition: dict) -> str:
    return calculate_json_snapshot(
        {key: value for key, value in definition.items() if key != "definition_snapshot_sha256"}
    )


def calculate_run_id(record: dict) -> str:
    identity = calculate_json_snapshot(
        {key: value for key, value in record.items() if key not in {"run_id", "run_snapshot_sha256"}}
    )
    return f"LMRUN-{identity[:24].upper()}"


def calculate_run_snapshot(record: dict) -> str:
    return calculate_json_snapshot(
        {key: value for key, value in record.items() if key != "run_snapshot_sha256"}
    )


def build_legal_monitor_definition(specification: dict) -> dict:
    findings = validate_published_legal_monitor_definition_input(specification)
    if findings:
        raise LegalMonitorError("LEGAL_MONITOR_DEFINITION_INPUT_INVALID", findings[0]["message"])
    if not is_rfc3339_datetime(specification["created_at"]):
        raise LegalMonitorError("LEGAL_MONITOR_DATE_INVALID", "Definition time must be UTC RFC 3339 ending in Z.")
    sources = copy.deepcopy(specification["sources"])
    sources.sort(key=lambda item: item["source_monitor_id"])
    definition = {
        "schema_version": "1.0",
        "definition_id": "LMDEF-" + "0" * 24,
        "monitor_id": specification["monitor_id"],
        "created_at": specification["created_at"],
        "owner_role": specification["owner_role"],
        "sources": sources,
        "limitations": list(DEFINITION_LIMITATIONS),
        "definition_snapshot_sha256": "0" * 64,
    }
    _require_definition_semantics(definition)
    try:
        definition["definition_id"] = calculate_definition_id(definition)
        definition["definition_snapshot_sha256"] = calculate_definition_snapshot(definition)
    except (rfc8785.CanonicalizationError, TypeError, ValueError) as error:
        raise LegalMonitorError("LEGAL_MONITOR_DEFINITION_IJSON_INVALID", "Definition cannot be canonicalized as RFC 8785 I-JSON.") from error
    report = validate_legal_monitor_definition(definition)
    if not report["allowed"]:
        raise LegalMonitorError("LEGAL_MONITOR_DEFINITION_BUILD_FAILED", report["findings"][0]["message"])
    return definition


def validate_legal_monitor_definition(definition: dict) -> dict:
    findings = validate_published_legal_monitor_definition(definition)
    if findings:
        return _definition_report(definition, findings)
    if not is_rfc3339_datetime(definition["created_at"]):
        findings.append(finding("DATE_FORMAT_INVALID", "$.created_at", "Definition time must be UTC RFC 3339 ending in Z.", "P0"))
    try:
        _require_definition_semantics(definition)
    except LegalMonitorError as error:
        findings.append(finding(error.code, "$.sources", str(error), "P0"))
    try:
        expected_id = calculate_definition_id(definition)
        expected_snapshot = calculate_definition_snapshot(definition)
    except (rfc8785.CanonicalizationError, TypeError, ValueError):
        findings.append(finding("LEGAL_MONITOR_DEFINITION_CANONICALIZATION_FAILED", "$", "Definition cannot be canonicalized as RFC 8785 I-JSON.", "P0"))
    else:
        if definition["definition_id"] != expected_id:
            findings.append(finding("LEGAL_MONITOR_DEFINITION_ID_MISMATCH", "$.definition_id", "Definition ID must bind monitor, owner role, and sorted sources.", "P0"))
        if definition["definition_snapshot_sha256"] != expected_snapshot:
            findings.append(finding("LEGAL_MONITOR_DEFINITION_SNAPSHOT_MISMATCH", "$.definition_snapshot_sha256", "Definition changed without a new RFC 8785 snapshot.", "P0"))
    return _definition_report(definition, findings)


def build_legal_monitor_run(specification: dict) -> dict:
    findings = validate_published_legal_monitor_run_input(specification)
    if findings:
        raise LegalMonitorError("LEGAL_MONITOR_RUN_INPUT_INVALID", findings[0]["message"])
    definition = specification["definition"]
    definition_report = validate_legal_monitor_definition(definition)
    if not definition_report["allowed"]:
        raise LegalMonitorError("LEGAL_MONITOR_DEFINITION_INVALID", "Monitor definition failed validation.")
    if not is_rfc3339_datetime(specification["evaluated_at"]):
        raise LegalMonitorError("LEGAL_MONITOR_DATE_INVALID", "Run time must be UTC RFC 3339 ending in Z.")
    previous = specification["previous_run"]
    _require_previous(previous, definition, specification["evaluated_at"])
    try:
        record = _construct_run(
            definition,
            previous,
            specification["evaluated_at"],
            specification["freshness_checks"],
        )
    except LegalMonitorError:
        raise
    except (rfc8785.CanonicalizationError, TypeError, ValueError) as error:
        raise LegalMonitorError("LEGAL_MONITOR_RUN_IJSON_INVALID", "Monitor run cannot be canonicalized as RFC 8785 I-JSON.") from error
    report = validate_legal_monitor_run(record, definition, previous)
    if not report["allowed"]:
        raise LegalMonitorError("LEGAL_MONITOR_RUN_BUILD_FAILED", report["findings"][0]["message"])
    return record


def validate_legal_monitor_run(record: dict, definition: dict, previous_run: dict | None = None) -> dict:
    findings = validate_published_legal_monitor_run(record)
    definition_report = validate_legal_monitor_definition(definition)
    if not definition_report["allowed"]:
        findings.append(finding("LEGAL_MONITOR_DEFINITION_INVALID", "$.definition_binding", "Bound monitor definition is invalid.", "P0"))
        return _run_report(record, findings)
    if findings:
        return _run_report(record, findings)
    if not is_rfc3339_datetime(record["evaluated_at"]):
        findings.append(finding("DATE_FORMAT_INVALID", "$.evaluated_at", "Run time must be UTC RFC 3339 ending in Z.", "P0"))
    try:
        _require_previous(previous_run, definition, record["evaluated_at"])
    except LegalMonitorError as error:
        findings.append(finding(error.code, "$.previous_binding", str(error), "P0"))
    try:
        expected_run_id = calculate_run_id(record)
        expected_run_snapshot = calculate_run_snapshot(record)
    except (rfc8785.CanonicalizationError, TypeError, ValueError):
        findings.append(finding("LEGAL_MONITOR_RUN_CANONICALIZATION_FAILED", "$", "Monitor run cannot be canonicalized as RFC 8785 I-JSON.", "P0"))
    else:
        if record["run_id"] != expected_run_id:
            findings.append(finding("LEGAL_MONITOR_RUN_ID_MISMATCH", "$.run_id", "Run ID must bind all deterministic run inputs and derived states.", "P0"))
        if record["run_snapshot_sha256"] != expected_run_snapshot:
            findings.append(finding("LEGAL_MONITOR_RUN_SNAPSHOT_MISMATCH", "$.run_snapshot_sha256", "Run changed without a new RFC 8785 snapshot.", "P0"))
    expected_binding = _definition_binding(definition)
    if record["definition_binding"] != expected_binding or record["monitor_id"] != definition["monitor_id"]:
        findings.append(finding("LEGAL_MONITOR_DEFINITION_BINDING_MISMATCH", "$.definition_binding", "Run must bind the exact monitor definition.", "P0"))
    if record["previous_binding"] is not None and previous_run is None:
        findings.append(finding("LEGAL_MONITOR_PREVIOUS_RUN_REQUIRED", "$.previous_binding", "A derived monitor run requires its exact predecessor.", "P0"))
        return _run_report(record, findings)
    if previous_run is not None and record["previous_binding"] != _previous_binding(previous_run):
        findings.append(finding("LEGAL_MONITOR_PREVIOUS_RUN_MISMATCH", "$.previous_binding", "Run must bind the exact immediate predecessor.", "P0"))
        return _run_report(record, findings)
    try:
        expected = _construct_run(definition, previous_run, record["evaluated_at"], record["freshness_checks"])
    except LegalMonitorError as error:
        findings.append(finding(error.code, "$.freshness_checks", str(error), "P0"))
    except (rfc8785.CanonicalizationError, TypeError, ValueError):
        findings.append(finding("LEGAL_MONITOR_RUN_CANONICALIZATION_FAILED", "$", "Monitor run cannot be canonicalized as RFC 8785 I-JSON.", "P0"))
    else:
        if record != expected:
            findings.append(finding("LEGAL_MONITOR_RUN_DERIVATION_MISMATCH", "$", "Run states, alerts, budgets, bindings, ID, and snapshot must equal the deterministic derivation.", "P0"))
    return _run_report(record, findings)


def _require_definition_semantics(definition):
    source_ids = [item["source_monitor_id"] for item in definition["sources"]]
    document_ids = [item["document_id"] for item in definition["sources"]]
    if source_ids != sorted(source_ids) or len(source_ids) != len(set(source_ids)) or len(document_ids) != len(set(document_ids)):
        raise LegalMonitorError("LEGAL_MONITOR_SOURCE_ORDER_OR_IDENTITY_INVALID", "Sources must be sorted with unique source and document IDs.")
    created = parse_rfc3339_datetime(definition["created_at"])
    for source in definition["sources"]:
        if source["retry_interval_hours"] > source["interval_hours"]:
            raise LegalMonitorError("LEGAL_MONITOR_RETRY_INTERVAL_INVALID", "Retry interval cannot exceed the regular interval.")
        if source["max_failures_in_window"] >= source["failure_window_runs"]:
            raise LegalMonitorError("LEGAL_MONITOR_FAILURE_BUDGET_INVALID", "Maximum failures must be less than the rolling window size.")
        baseline = source["baseline"]
        if source["canonical_url"] != baseline["final_url"]:
            raise LegalMonitorError("LEGAL_MONITOR_BASELINE_URL_MISMATCH", "Canonical URL must equal the approved baseline final URL.")
        if not is_rfc3339_datetime(baseline["fetched_at"]) or created is None or parse_rfc3339_datetime(baseline["fetched_at"]) > created:
            raise LegalMonitorError("LEGAL_MONITOR_BASELINE_TIME_INVALID", "Baseline time must be valid and not later than definition creation.")
        try:
            validate_fetch_target(source["canonical_url"], source["publisher_code"], "NORMATIVE_LEGAL_SOURCE")
        except FetchRefusal as error:
            raise LegalMonitorError("LEGAL_MONITOR_SOURCE_NOT_ALLOWLISTED", "Monitor URL must match the declared official publisher.") from error


def _require_previous(previous, definition, evaluated_at):
    if previous is None:
        return
    previous_report = validate_legal_monitor_run(previous, definition)
    blocking = [item for item in previous_report["findings"] if item["code"] != "LEGAL_MONITOR_PREVIOUS_RUN_REQUIRED"]
    if blocking:
        raise LegalMonitorError("LEGAL_MONITOR_PREVIOUS_RUN_INVALID", "Previous monitor run fails its own integrity checks.")
    if previous["definition_binding"] != _definition_binding(definition) or previous["monitor_id"] != definition["monitor_id"]:
        raise LegalMonitorError("LEGAL_MONITOR_PREVIOUS_DEFINITION_MISMATCH", "Previous run belongs to another monitor definition.")
    state_ids = [item["source_monitor_id"] for item in previous["source_states"]]
    check_ids = [item["source_monitor_id"] for item in previous["freshness_checks"]]
    if state_ids != sorted(state_ids) or len(state_ids) != len(set(state_ids)):
        raise LegalMonitorError(
            "LEGAL_MONITOR_PREVIOUS_STATE_ORDER_OR_IDENTITY_INVALID",
            "Previous source states must be sorted and unique.",
        )
    if check_ids != sorted(check_ids) or len(check_ids) != len(set(check_ids)):
        raise LegalMonitorError(
            "LEGAL_MONITOR_PREVIOUS_CHECK_ORDER_OR_IDENTITY_INVALID",
            "Previous freshness checks must be sorted and unique.",
        )
    if parse_rfc3339_datetime(evaluated_at) < parse_rfc3339_datetime(previous["evaluated_at"]):
        raise LegalMonitorError("LEGAL_MONITOR_TIME_ROLLBACK", "Monitor run time cannot move backward.")


def _construct_run(definition, previous, evaluated_at, checks):
    check_map = {}
    normalized_checks = []
    source_definitions = {item["source_monitor_id"]: item for item in definition["sources"]}
    for item in checks:
        source_id = item["source_monitor_id"]
        if source_id not in source_definitions:
            raise LegalMonitorError("LEGAL_MONITOR_CHECK_SOURCE_UNKNOWN", "Freshness check names an unknown monitored source.")
        if source_id in check_map:
            raise LegalMonitorError("LEGAL_MONITOR_CHECK_DUPLICATE", "Only one freshness check per source is permitted in a run.")
        check_map[source_id] = item["check"]
        normalized_checks.append(copy.deepcopy(item))
    normalized_checks.sort(key=lambda item: item["source_monitor_id"])
    previous_states = {item["source_monitor_id"]: item for item in previous["source_states"]} if previous else {}
    if previous and set(previous_states) != set(source_definitions):
        raise LegalMonitorError("LEGAL_MONITOR_PREVIOUS_SOURCE_SET_MISMATCH", "Previous run source set must exactly match the definition.")
    states = []
    for source in definition["sources"]:
        source_id = source["source_monitor_id"]
        prior = previous_states.get(source_id)
        check = check_map.get(source_id)
        due = prior is None or parse_rfc3339_datetime(evaluated_at) >= parse_rfc3339_datetime(prior["next_due_at"])
        if check is not None:
            state = _state_from_check(source, prior, check, evaluated_at)
        elif due:
            state = _missed_state(source, prior, evaluated_at)
        else:
            state = copy.deepcopy(prior)
            state["check_execution_status"] = "CARRIED_FORWARD_NOT_DUE"
        states.append(state)
    alerts = []
    for source, state in zip(definition["sources"], states):
        alerts.extend(_alerts_for_state(source, state, evaluated_at))
    alerts.sort(key=lambda item: item["alert_id"])
    critical = any(item["code"] in {"LEGAL_SOURCE_CHANGE_DETECTED", "LEGAL_SOURCE_ERROR_BUDGET_EXHAUSTED"} for item in alerts)
    overall = "CRITICAL_DRAFT_ONLY" if critical else "WARNING_DRAFT_ONLY" if alerts else "HEALTHY_TECHNICALLY_UNCHANGED"
    record = {
        "schema_version": "1.0",
        "run_id": "LMRUN-" + "0" * 24,
        "monitor_id": definition["monitor_id"],
        "definition_binding": _definition_binding(definition),
        "evaluated_at": evaluated_at,
        "clock_status": "SYSTEM_CLOCK_UNATTESTED",
        "previous_binding": _previous_binding(previous) if previous else None,
        "freshness_checks": normalized_checks,
        "source_states": states,
        "alerts": alerts,
        "overall_status": overall,
        "required_output_state": "DRAFT" if alerts else "NO_PROMOTION_GRANTED",
        "legal_review_required": True,
        "limitations": list(RUN_LIMITATIONS),
        "run_snapshot_sha256": "0" * 64,
    }
    record["run_id"] = calculate_run_id(record)
    record["run_snapshot_sha256"] = calculate_run_snapshot(record)
    return record


def _state_from_check(source, prior, check, evaluated_at):
    report = validate_legal_freshness_check(check)
    if not report["allowed"]:
        raise LegalMonitorError("LEGAL_MONITOR_FRESHNESS_CHECK_INVALID", "Freshness check failed validation.")
    if (
        check["document_id"] != source["document_id"]
        or check["publisher_code"] != source["publisher_code"]
        or check["baseline"] != source["baseline"]
        or check["checked_at"] != evaluated_at
        or check["max_age_hours"] != source["max_age_hours"]
    ):
        raise LegalMonitorError("LEGAL_MONITOR_FRESHNESS_BINDING_MISMATCH", "Freshness check must bind the monitored document, publisher, baseline, max age, and run time.")
    outcome = "SUCCESS" if check["network_status"] == "SUCCESS" else "UNAVAILABLE"
    outcomes = _append_outcome(prior, outcome, source["failure_window_runs"])
    hours = source["interval_hours"] if outcome == "SUCCESS" else source["retry_interval_hours"]
    return _source_state(
        source,
        "CHECKED",
        check["technical_freshness_status"],
        check["check_id"],
        check["check_snapshot_sha256"],
        check["checked_at"],
        _add_hours(evaluated_at, hours),
        outcomes,
    )


def _missed_state(source, prior, evaluated_at):
    outcomes = _append_outcome(prior, "MISSED", source["failure_window_runs"])
    return _source_state(
        source,
        "MISSED_DUE_CHECK",
        "NOT_CHECKED_MISSED_DRAFT_ONLY",
        prior["latest_check_id"] if prior else None,
        prior["latest_check_snapshot_sha256"] if prior else None,
        prior["last_checked_at"] if prior else None,
        _add_hours(evaluated_at, source["retry_interval_hours"]),
        outcomes,
    )


def _source_state(source, execution, technical_status, check_id, check_snapshot, last_checked, next_due, outcomes):
    failures = sum(item in {"UNAVAILABLE", "MISSED"} for item in outcomes)
    budget_status = "EXHAUSTED" if failures > source["max_failures_in_window"] else "WITHIN_BUDGET"
    draft = technical_status != "UNCHANGED_RESPONSE_BODY_CANDIDATE" or budget_status == "EXHAUSTED"
    return {
        "source_monitor_id": source["source_monitor_id"],
        "document_id": source["document_id"],
        "check_execution_status": execution,
        "technical_freshness_status": technical_status,
        "latest_check_id": check_id,
        "latest_check_snapshot_sha256": check_snapshot,
        "last_checked_at": last_checked,
        "next_due_at": next_due,
        "recent_outcomes": outcomes,
        "error_budget": {
            "window_runs": source["failure_window_runs"],
            "max_failures": source["max_failures_in_window"],
            "observed_failures": failures,
            "status": budget_status,
        },
        "required_output_state": "DRAFT" if draft else "NO_PROMOTION_GRANTED",
    }


def _append_outcome(prior, outcome, window):
    values = list(prior["recent_outcomes"] if prior else [])
    values.append(outcome)
    return values[-window:]


def _alerts_for_state(source, state, evaluated_at):
    mapping = {
        "CHANGE_DETECTED_REVIEW_REQUIRED": ("LEGAL_SOURCE_CHANGE_DETECTED", "CRITICAL"),
        "UNAVAILABLE_DRAFT_ONLY": ("LEGAL_SOURCE_CHECK_UNAVAILABLE", _failure_severity(source)),
        "STALE_DRAFT_ONLY": ("LEGAL_SOURCE_CHECK_STALE", "HIGH"),
        "NOT_CHECKED_MISSED_DRAFT_ONLY": ("LEGAL_SOURCE_CHECK_MISSED", _failure_severity(source)),
    }
    alerts = []
    if state["technical_freshness_status"] in mapping:
        code, severity = mapping[state["technical_freshness_status"]]
        alerts.append(_alert(source["source_monitor_id"], code, severity, state, evaluated_at))
    if state["error_budget"]["status"] == "EXHAUSTED":
        severity = "CRITICAL" if source["urgency"] == "CRITICAL" else "HIGH"
        alerts.append(_alert(source["source_monitor_id"], "LEGAL_SOURCE_ERROR_BUDGET_EXHAUSTED", severity, state, evaluated_at))
    return alerts


def _alert(source_id, code, severity, state, evaluated_at):
    check_id = state["latest_check_id"] if code != "LEGAL_SOURCE_CHECK_MISSED" else None
    check_snapshot = state["latest_check_snapshot_sha256"] if code != "LEGAL_SOURCE_CHECK_MISSED" else None
    identity = calculate_json_snapshot(
        {"check_id": check_id, "check_snapshot_sha256": check_snapshot, "code": code, "evaluated_at": evaluated_at, "source_monitor_id": source_id}
    )
    return {
        "alert_id": f"LMALERT-{identity[:24].upper()}",
        "source_monitor_id": source_id,
        "code": code,
        "severity": severity,
        "status": "OPEN_REQUIRES_HUMAN_REVIEW",
        "check_id": check_id,
        "check_snapshot_sha256": check_snapshot,
    }


def _failure_severity(source):
    return "HIGH" if source["urgency"] in {"CRITICAL", "HIGH"} else "WARNING"


def _add_hours(timestamp, hours):
    return (parse_rfc3339_datetime(timestamp) + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def _definition_binding(definition):
    return {"definition_id": definition["definition_id"], "definition_snapshot_sha256": definition["definition_snapshot_sha256"]}


def _previous_binding(previous):
    return {
        "run_id": previous["run_id"],
        "run_snapshot_sha256": previous["run_snapshot_sha256"],
        "evaluated_at": previous["evaluated_at"],
        "definition_binding": previous["definition_binding"],
    }


def _definition_report(definition, findings):
    findings.sort(key=lambda item: (item["code"], item["path"], item["message"]))
    return {
        "allowed": not findings,
        "allowed_scope": "LEGAL_MONITOR_DEFINITION_INTEGRITY",
        "definition_id": definition.get("definition_id"),
        "findings": findings,
        "legal_currentness_verified": False,
        "submission_ready": False,
    }


def _run_report(record, findings):
    findings.sort(key=lambda item: (item["code"], item["path"], item["message"]))
    allowed = not findings
    return {
        "allowed": allowed,
        "allowed_scope": "LEGAL_UPDATE_MONITOR_TECHNICAL_STATE_ONLY",
        "alerts": record.get("alerts", []),
        "findings": findings,
        "legal_currentness_verified": False,
        "legal_review_required": True,
        "required_output_state": record.get("required_output_state"),
        "run_id": record.get("run_id"),
        "submission_ready": False,
        "validation_scope": {
            "verified": ["DUE_AND_MISSED_CHECK_DERIVATION", "ERROR_BUDGET_DERIVATION", "FRESHNESS_ALERT_DERIVATION", "RFC8785_MONITOR_BINDINGS"] if allowed else [],
            "not_verified": ["CLOCK_OR_SCHEDULER_ATTESTATION", "LEGAL_CURRENTNESS", "LEGAL_EFFECT", "PUBLISHER_AUTHORSHIP", "SOURCE_APPLICABILITY"],
        },
    }
