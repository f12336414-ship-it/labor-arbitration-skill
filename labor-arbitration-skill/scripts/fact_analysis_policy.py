"""Deterministic user-structured fact conflicts and upstream invalidation."""

from __future__ import annotations

import re
from datetime import date, datetime

import rfc8785

from fact_candidate_policy import validate_fact_candidate_record
from finding_model import finding
from integrity_primitives import calculate_json_snapshot, is_rfc3339_datetime
from schema_validation import (
    validate_published_fact_analysis_input,
    validate_published_fact_analysis_record,
)


LIMITATIONS = [
    "STRUCTURED_VALUES_ARE_USER_SUPPLIED_UNAUTHENTICATED",
    "CONFLICT_DETECTION_DOES_NOT_RESOLVE_FACT_TRUTH",
    "NO_EVIDENCE_OR_IDENTITY_AUTHENTICATION",
    "DOWNSTREAM_REVALIDATION_COVERS_THIS_LEDGER_ONLY",
    "NO_LEGAL_OR_SUBMISSION_READINESS",
]
AMOUNT_PATTERN = re.compile(r"^(0|[1-9][0-9]{0,14})\.[0-9]{2}$")
SUBJECT_PATTERN = re.compile(r"^[A-Z][A-Z0-9_-]{2,127}$")
DATE_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
VALUE_CONFLICT_TYPES = {
    "DATE": "DATE_VALUE_CONFLICT",
    "AMOUNT_CNY": "AMOUNT_VALUE_CONFLICT",
    "SUBJECT_KEY": "SUBJECT_VALUE_CONFLICT",
}
ENGINE = {
    "name": "STRUCTURED_FACT_CONFLICTS",
    "version": "1.0.0",
    "comparison_policy": "EXACT_CANONICAL_STRING_ALL_UNEQUAL_PAIRS",
}
MAX_CONFLICTS = 10000


class FactAnalysisError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def calculate_view_snapshot(view: dict) -> str:
    return calculate_json_snapshot(
        {key: value for key, value in view.items() if key != "view_snapshot_sha256"}
    )


def calculate_view_id(view: dict) -> str:
    identity = calculate_json_snapshot(
        {
            "actor_assertion": view["actor_assertion"],
            "actor_label": view["actor_label"],
            "dimension_key": view["dimension_key"],
            "fact_candidate_binding": view["fact_candidate_binding"],
            "semantic_kind": view["semantic_kind"],
            "timeline_role": view["timeline_role"],
            "value": view["value"],
            "view_key": view["view_key"],
        }
    )
    return f"VIEW-{identity[:24].upper()}"


def calculate_upstream_snapshot(views: list[dict]) -> str:
    return calculate_json_snapshot(
        {
            "engine": ENGINE,
            "views": [
                {
                    "fact_candidate_binding": view["fact_candidate_binding"],
                    "view_key": view["view_key"],
                    "view_snapshot_sha256": view["view_snapshot_sha256"],
                }
                for view in views
            ],
        }
    )


def calculate_analysis_id(record: dict) -> str:
    identity = calculate_json_snapshot(
        {
            "artifact_id": record["artifact_id"],
            "conflicts": record["conflicts"],
            "engine": record["engine"],
            "invalidation": record["invalidation"],
            "previous_binding": record["previous_binding"],
            "upstream_snapshot_sha256": record["upstream_snapshot_sha256"],
            "views": record["views"],
        }
    )
    return f"FANALYSIS-{identity[:24].upper()}"


def calculate_analysis_snapshot(record: dict) -> str:
    return calculate_json_snapshot(
        {key: value for key, value in record.items() if key != "record_snapshot_sha256"}
    )


def build_fact_analysis(specification: dict) -> dict:
    input_findings = validate_published_fact_analysis_input(specification)
    if input_findings:
        raise FactAnalysisError("FACT_ANALYSIS_INPUT_INVALID", input_findings[0]["message"])
    if not is_rfc3339_datetime(specification["created_at"]):
        raise FactAnalysisError("FACT_ANALYSIS_DATE_INVALID", "created_at must be UTC RFC 3339 ending in Z.")
    try:
        views = [_build_view(item) for item in specification["inputs"]]
    except FactAnalysisError:
        raise
    except (rfc8785.CanonicalizationError, TypeError, ValueError) as error:
        raise FactAnalysisError("FACT_ANALYSIS_IJSON_INVALID", "Structured analysis input cannot be canonicalized as RFC 8785 I-JSON.") from error
    views.sort(key=lambda item: item["view_key"])
    view_keys = [item["view_key"] for item in views]
    if len(view_keys) != len(set(view_keys)):
        raise FactAnalysisError("FACT_ANALYSIS_VIEW_KEY_DUPLICATE", "Each structured view key must be unique.")
    previous = specification["previous_analysis_record"]
    previous_binding, invalidation = _derive_invalidation(previous, specification["artifact_id"], views, specification["created_at"])
    record = {
        "schema_version": "1.0",
        "analysis_id": "FANALYSIS-" + "0" * 24,
        "artifact_id": specification["artifact_id"],
        "created_at": specification["created_at"],
        "clock_status": "SYSTEM_CLOCK_UNATTESTED",
        "engine": dict(ENGINE),
        "views": views,
        "conflicts": detect_conflicts(views),
        "upstream_snapshot_sha256": calculate_upstream_snapshot(views),
        "previous_binding": previous_binding,
        "invalidation": invalidation,
        "output_permission": "INTERNAL_ANALYSIS_ONLY",
        "limitations": list(LIMITATIONS),
        "record_snapshot_sha256": "0" * 64,
    }
    record["analysis_id"] = calculate_analysis_id(record)
    record["record_snapshot_sha256"] = calculate_analysis_snapshot(record)
    report = validate_fact_analysis_record(record, previous)
    if not report["allowed"]:
        raise FactAnalysisError("FACT_ANALYSIS_BUILD_FAILED", report["findings"][0]["message"])
    return record


def validate_fact_analysis_record(record: dict, previous_record: dict | None = None) -> dict:
    findings = validate_published_fact_analysis_record(record)
    if findings:
        return _report(record, findings)
    if not is_rfc3339_datetime(record["created_at"]):
        findings.append(finding("DATE_FORMAT_INVALID", "$.created_at", "Analysis time must be UTC RFC 3339 ending in Z.", "P0"))
    view_keys = []
    for index, view in enumerate(record["views"]):
        view_keys.append(view["view_key"])
        _validate_view(view, index, findings)
    if view_keys != sorted(view_keys) or len(view_keys) != len(set(view_keys)):
        findings.append(finding("FACT_ANALYSIS_VIEW_ORDER_OR_IDENTITY_INVALID", "$.views", "Views must be unique and sorted by view_key.", "P0"))
    try:
        expected_conflicts = detect_conflicts(record["views"])
    except FactAnalysisError as error:
        findings.append(finding(error.code, "$.views", str(error), "P0"))
    else:
        if record["conflicts"] != expected_conflicts:
            findings.append(finding("FACT_ANALYSIS_CONFLICT_SET_MISMATCH", "$.conflicts", "Conflicts must equal the deterministic unresolved conflict set.", "P0"))
    expected_upstream = calculate_upstream_snapshot(record["views"])
    if record["upstream_snapshot_sha256"] != expected_upstream:
        findings.append(finding("FACT_ANALYSIS_UPSTREAM_SNAPSHOT_MISMATCH", "$.upstream_snapshot_sha256", "Upstream snapshot must bind every sorted view and fact candidate snapshot.", "P0"))
    _validate_invalidation(record, previous_record, findings)
    try:
        expected_id = calculate_analysis_id(record)
        expected_snapshot = calculate_analysis_snapshot(record)
    except (rfc8785.CanonicalizationError, TypeError, ValueError):
        findings.append(finding("FACT_ANALYSIS_CANONICALIZATION_FAILED", "$", "Analysis record cannot be canonicalized as RFC 8785 I-JSON.", "P0"))
    else:
        if record["analysis_id"] != expected_id:
            findings.append(finding("FACT_ANALYSIS_ID_MISMATCH", "$.analysis_id", "Analysis ID must bind views, conflicts, predecessor, and invalidation.", "P0"))
        if record["record_snapshot_sha256"] != expected_snapshot:
            findings.append(finding("FACT_ANALYSIS_RECORD_SNAPSHOT_MISMATCH", "$.record_snapshot_sha256", "Analysis changed without a new RFC 8785 snapshot.", "P0"))
    return _report(record, findings)


def detect_conflicts(views: list[dict]) -> list[dict]:
    conflicts = []
    def add(conflict):
        if len(conflicts) >= MAX_CONFLICTS:
            raise FactAnalysisError("FACT_ANALYSIS_CONFLICT_LIMIT_EXCEEDED", "Conflict count exceeds the 10000-record safety limit; split the analysis scope without dropping sources.")
        conflicts.append(conflict)
    grouped = {}
    by_dimension = {}
    for view in views:
        grouped.setdefault((view["semantic_kind"], view["dimension_key"]), []).append(view)
        by_dimension.setdefault(view["dimension_key"], []).append(view)
    for dimension, members in sorted(by_dimension.items()):
        for left_index, left in enumerate(members):
            for right in members[left_index + 1 :]:
                if left["semantic_kind"] != right["semantic_kind"]:
                    add(_conflict("SEMANTIC_KIND_CONFLICT", dimension, [left, right]))
    for (kind, dimension), members in sorted(grouped.items()):
        values = {item["value"] for item in members}
        if len(values) > 1:
            for left_index, left in enumerate(members):
                for right in members[left_index + 1 :]:
                    if left["value"] != right["value"]:
                        add(_conflict(VALUE_CONFLICT_TYPES[kind], dimension, [left, right]))
    starts = [view for view in views if view["timeline_role"] == "EMPLOYMENT_START"]
    ends = [view for view in views if view["timeline_role"] == "EMPLOYMENT_END"]
    terminations = [view for view in views if view["timeline_role"] == "TERMINATION"]
    for start in starts:
        for end in ends:
            if start["value"] > end["value"]:
                add(_conflict("TIMELINE_ORDER_CONFLICT", "EMPLOYMENT_PERIOD", [start, end]))
    for termination in terminations:
        for boundary in starts:
            if termination["value"] < boundary["value"]:
                add(_conflict("TERMINATION_OUTSIDE_EMPLOYMENT_CONFLICT", "EMPLOYMENT_TERMINATION", [boundary, termination]))
        for boundary in ends:
            if termination["value"] > boundary["value"]:
                add(_conflict("TERMINATION_OUTSIDE_EMPLOYMENT_CONFLICT", "EMPLOYMENT_TERMINATION", [termination, boundary]))
    conflicts.sort(key=lambda item: item["conflict_id"])
    return conflicts


def _build_view(item: dict) -> dict:
    candidate = item["fact_candidate_record"]
    candidate_report = validate_fact_candidate_record(candidate, item["parse_record"], item["previous_fact_candidate_record"])
    if not candidate_report["allowed"] or candidate.get("candidate_status") != "ACTIVE":
        raise FactAnalysisError("FACT_ANALYSIS_CANDIDATE_INVALID", "Every structured view requires an active, replay-valid fact candidate.")
    _require_value(item["semantic_kind"], item["value"], item["timeline_role"])
    view = {
        "view_id": "VIEW-" + "0" * 24,
        "view_key": item["view_key"],
        "dimension_key": item["dimension_key"],
        "semantic_kind": item["semantic_kind"],
        "value": item["value"],
        "timeline_role": item["timeline_role"],
        "actor_assertion": "USER_STRUCTURED_UNAUTHENTICATED",
        "actor_label": item["actor_label"],
        "fact_candidate_binding": {
            "fact_candidate_id": candidate["fact_candidate_id"],
            "record_snapshot_sha256": candidate["record_snapshot_sha256"],
            "parse_id": candidate["parse_binding"]["parse_id"],
            "parse_record_snapshot_sha256": candidate["parse_binding"]["parse_record_snapshot_sha256"],
            "provenance_state": candidate["provenance_state"],
        },
        "value_status": "USER_STRUCTURED_UNAUTHENTICATED",
        "truth_status": "UNVERIFIED",
        "view_snapshot_sha256": "0" * 64,
    }
    view["view_id"] = calculate_view_id(view)
    view["view_snapshot_sha256"] = calculate_view_snapshot(view)
    return view


def _require_value(kind: str, value: str, role: str) -> None:
    valid = False
    if kind == "DATE":
        try:
            date.fromisoformat(value)
            valid = DATE_PATTERN.fullmatch(value) is not None
        except (TypeError, ValueError):
            pass
        if role == "NONE" or role in {"EMPLOYMENT_START", "EMPLOYMENT_END", "TERMINATION"}:
            pass
        else:
            valid = False
    elif kind == "AMOUNT_CNY":
        valid = AMOUNT_PATTERN.fullmatch(value) is not None and role == "NONE"
    elif kind == "SUBJECT_KEY":
        valid = SUBJECT_PATTERN.fullmatch(value) is not None and role == "NONE"
    if not valid:
        raise FactAnalysisError("FACT_ANALYSIS_STRUCTURED_VALUE_INVALID", "Structured value or timeline role is not canonical for its semantic kind.")


def _validate_view(view: dict, index: int, findings: list[dict]) -> None:
    try:
        _require_value(view["semantic_kind"], view["value"], view["timeline_role"])
    except FactAnalysisError:
        findings.append(finding("FACT_ANALYSIS_STRUCTURED_VALUE_INVALID", f"$.views[{index}].value", "Structured value or timeline role is not canonical.", "P0"))
    try:
        expected_id = calculate_view_id(view)
        expected_snapshot = calculate_view_snapshot(view)
    except (rfc8785.CanonicalizationError, TypeError, ValueError):
        findings.append(finding("FACT_ANALYSIS_VIEW_CANONICALIZATION_FAILED", f"$.views[{index}]", "View cannot be canonicalized as RFC 8785 I-JSON.", "P0"))
        return
    if view["view_id"] != expected_id:
        findings.append(finding("FACT_ANALYSIS_VIEW_ID_MISMATCH", f"$.views[{index}].view_id", "View ID must bind the user-structured value and candidate snapshot.", "P0"))
    if view["view_snapshot_sha256"] != expected_snapshot:
        findings.append(finding("FACT_ANALYSIS_VIEW_SNAPSHOT_MISMATCH", f"$.views[{index}].view_snapshot_sha256", "View changed without a new RFC 8785 snapshot.", "P0"))


def _conflict(conflict_type: str, dimension: str, views: list[dict]) -> dict:
    ordered = sorted(views, key=lambda item: item["view_id"])
    identity = calculate_json_snapshot(
        {"conflict_type": conflict_type, "dimension_key": dimension, "view_ids": [item["view_id"] for item in ordered], "values": [item["value"] for item in ordered]}
    )
    return {
        "conflict_id": f"CONFLICT-{identity[:24].upper()}",
        "conflict_type": conflict_type,
        "dimension_key": dimension,
        "view_ids": [item["view_id"] for item in ordered],
        "values": [item["value"] for item in ordered],
        "status": "PENDING_HUMAN_REVIEW",
        "auto_selected_view_id": None,
        "resolution": None,
    }


def _derive_invalidation(previous, artifact_id, views, created_at):
    if previous is None:
        return None, {"status": "BASELINE_CURRENT", "changed_view_keys": [], "reason": "Initial structured fact dependency baseline."}
    prior_report = validate_fact_analysis_record(previous)
    blocking = [item for item in prior_report["findings"] if item["code"] != "FACT_ANALYSIS_PREVIOUS_RECORD_REQUIRED"]
    if blocking or previous["artifact_id"] != artifact_id or _parse_time(created_at) < _parse_time(previous["created_at"]):
        raise FactAnalysisError("FACT_ANALYSIS_PREVIOUS_RECORD_INVALID", "Previous analysis must be intact, for the same artifact, and not from the future.")
    binding = {"analysis_id": previous["analysis_id"], "artifact_id": previous["artifact_id"], "upstream_snapshot_sha256": previous["upstream_snapshot_sha256"], "record_snapshot_sha256": previous["record_snapshot_sha256"]}
    changed = _changed_view_keys(previous["views"], views)
    if changed:
        return binding, {"status": "INVALIDATED_BY_FACT_CHANGE", "changed_view_keys": changed, "reason": "One or more structured fact dependencies were added, removed, or changed; downstream work requires revalidation."}
    return binding, {"status": "CURRENT", "changed_view_keys": [], "reason": "Structured fact dependencies are unchanged from the bound predecessor."}


def _validate_invalidation(record, previous, findings):
    if previous is None:
        if record["previous_binding"] is None:
            expected = {"status": "BASELINE_CURRENT", "changed_view_keys": [], "reason": "Initial structured fact dependency baseline."}
            if record["invalidation"] != expected:
                findings.append(finding("FACT_ANALYSIS_INVALIDATION_MISMATCH", "$.invalidation", "Initial analysis must declare the exact baseline state.", "P0"))
        else:
            findings.append(finding("FACT_ANALYSIS_PREVIOUS_RECORD_REQUIRED", "$.previous_binding", "A derived analysis requires its exact predecessor.", "P0"))
        return
    prior_report = validate_fact_analysis_record(previous)
    blocking = [item for item in prior_report["findings"] if item["code"] != "FACT_ANALYSIS_PREVIOUS_RECORD_REQUIRED"]
    expected_binding = {"analysis_id": previous.get("analysis_id"), "artifact_id": previous.get("artifact_id"), "upstream_snapshot_sha256": previous.get("upstream_snapshot_sha256"), "record_snapshot_sha256": previous.get("record_snapshot_sha256")}
    if blocking or record["previous_binding"] != expected_binding or record["artifact_id"] != previous.get("artifact_id") or _parse_time(record["created_at"]) < _parse_time(previous.get("created_at", "")):
        findings.append(finding("FACT_ANALYSIS_PREVIOUS_RECORD_MISMATCH", "$.previous_binding", "Analysis must bind an intact immediate predecessor for the same artifact with non-decreasing time.", "P0"))
        return
    changed = _changed_view_keys(previous["views"], record["views"])
    expected = {"status": "INVALIDATED_BY_FACT_CHANGE", "changed_view_keys": changed, "reason": "One or more structured fact dependencies were added, removed, or changed; downstream work requires revalidation."} if changed else {"status": "CURRENT", "changed_view_keys": [], "reason": "Structured fact dependencies are unchanged from the bound predecessor."}
    if record["invalidation"] != expected:
        findings.append(finding("FACT_ANALYSIS_INVALIDATION_MISMATCH", "$.invalidation", "Invalidation must exactly match added, removed, or changed view dependencies.", "P0"))


def _changed_view_keys(old_views, new_views):
    old = {item["view_key"]: item["view_snapshot_sha256"] for item in old_views}
    new = {item["view_key"]: item["view_snapshot_sha256"] for item in new_views}
    return sorted(key for key in set(old) | set(new) if old.get(key) != new.get(key))


def _parse_time(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return datetime.min.astimezone()


def _report(record, findings):
    findings.sort(key=lambda item: (item["code"], item["path"], item["message"]))
    allowed = not findings
    invalidated = record.get("invalidation", {}).get("status") == "INVALIDATED_BY_FACT_CHANGE"
    return {
        "allowed": allowed,
        "allowed_scope": "LOCAL_STRUCTURED_FACT_CONFLICT_AND_DEPENDENCY_INTEGRITY",
        "analysis_id": record.get("analysis_id"),
        "downstream_revalidation_required": invalidated,
        "fact_truth_established": False,
        "findings": findings,
        "human_identity_authenticated": False,
        "legal_review_required": True,
        "next_required_state": "REVALIDATE_DOWNSTREAM_DEPENDENCIES" if invalidated else "CONTINUE_INTERNAL_ANALYSIS",
        "submission_ready": False,
        "validation_scope": {
            "verified": ["DETERMINISTIC_STRUCTURED_CONFLICTS", "DIRECT_PREDECESSOR_INVALIDATION", "RFC8785_ANALYSIS_BINDING"] if allowed else [],
            "not_verified": ["EVIDENCE_AUTHENTICITY", "FACT_TRUTH", "HUMAN_IDENTITY", "LEGAL_RELEVANCE", "SEMANTIC_EXTRACTION_CORRECTNESS", "UNREGISTERED_DOWNSTREAM_ARTIFACTS"],
        },
    }
