"""Fail-closed policy for formal-output technical state requests."""

from __future__ import annotations

from integrity_primitives import calculate_json_snapshot, is_rfc3339_datetime
from finding_model import finding
from schema_validation import validate_published_formal_output_state


DEPENDENCY_FIELDS = {
    "CASE": "case_sha256",
    "LEGAL_SOURCES": "legal_sources_sha256",
    "ANALYSIS": "analysis_sha256",
    "CALCULATIONS": "calculations_sha256",
    "DOCUMENT": "document_sha256",
}
ALLOWED_TRANSITIONS = {
    "INTERNAL_ANALYSIS": {"INTERNAL_ANALYSIS", "DRAFT"},
    "DRAFT": {"INTERNAL_ANALYSIS", "DRAFT", "REVIEW_REQUIRED"},
    "REVIEW_REQUIRED": {"INTERNAL_ANALYSIS", "DRAFT", "REVIEW_REQUIRED"},
}
VERIFIED_CAPABILITIES = [
    "DEPENDENCY_CHANGE_DETECTION",
    "OUTPUT_STATE_TRANSITION_SHAPE",
    "RFC8785_STATE_REQUEST_BINDING",
]
UNVERIFIED_CAPABILITIES = [
    "APPROVAL_AUTHENTICITY",
    "LEGAL_CORRECTNESS",
    "LEGAL_FRESHNESS",
    "DEPENDENCY_SNAPSHOT_AUTHENTICITY",
    "PREVIOUS_STATE_REQUEST_EXISTENCE",
    "REVIEWER_IDENTITY",
    "SUBMISSION_READINESS",
]


def calculate_state_request_snapshot(request: dict) -> str:
    return calculate_json_snapshot(
        {
            key: value
            for key, value in request.items()
            if key != "state_request_sha256"
        }
    )


def _changed_dependencies(request: dict) -> list[str]:
    previous = request.get("previous_binding")
    if previous is None:
        return []
    old_snapshots = previous["dependency_snapshots"]
    current_snapshots = request["dependency_snapshots"]
    changes = {
        kind
        for kind, field in DEPENDENCY_FIELDS.items()
        if old_snapshots[field] != current_snapshots[field]
    }
    if previous["legal_freshness"] != request["legal_freshness"]:
        changes.add("LEGAL_SOURCES")
    return sorted(changes)


def _validate_transition(request: dict, findings: list[dict]) -> None:
    previous = request["previous_binding"]
    requested_state = request["requested_state"]
    if requested_state == "SUBMISSION_CANDIDATE":
        findings.append(
            finding(
                "SUBMISSION_STATE_UNSUPPORTED",
                "$.requested_state",
                "This release cannot authenticate the freshness, identity, approval, signature, and audit evidence required for submission.",
                "P0",
            )
        )
    if requested_state == "REVIEW_REQUIRED":
        findings.append(
            finding(
                "OUTPUT_REVIEW_REQUIRED_UNSUPPORTED",
                "$.requested_state",
                "This release cannot verify the legal-source, analysis, and professional-calculation prerequisites for REVIEW_REQUIRED.",
                "P0",
            )
        )
    freshness_status = request["legal_freshness"]["status"]
    if requested_state in {"REVIEW_REQUIRED", "SUBMISSION_CANDIDATE"} and (
        freshness_status != "UNCHANGED_RESPONSE_BODY_CANDIDATE"
    ):
        findings.append(
            finding(
                "OUTPUT_LEGAL_FRESHNESS_DRAFT_ONLY",
                "$.legal_freshness.status",
                "Missing, unavailable, stale, or changed legal-source freshness permits DRAFT only.",
                "P0",
            )
        )

    if previous is None:
        if requested_state != "INTERNAL_ANALYSIS":
            findings.append(
                finding(
                    "OUTPUT_STATE_TRANSITION_INVALID",
                    "$.requested_state",
                    "A new output artifact must begin in INTERNAL_ANALYSIS.",
                    "P0",
                )
            )
        return

    previous_state = previous["state"]
    if (
        previous["artifact_id"] != request["artifact_id"]
        or previous["artifact_type"] != request["artifact_type"]
    ):
        findings.append(
            finding(
                "OUTPUT_PREVIOUS_BINDING_MISMATCH",
                "$.previous_binding",
                "A previous binding must identify the same output artifact and artifact type.",
                "P0",
            )
        )
    if requested_state not in ALLOWED_TRANSITIONS[previous_state]:
        findings.append(
            finding(
                "OUTPUT_STATE_TRANSITION_INVALID",
                "$.requested_state",
                f"Transition from {previous_state} to {requested_state} is not supported.",
                "P0",
            )
        )


def _validate_invalidation(request: dict, findings: list[dict]) -> list[str]:
    previous = request["previous_binding"]
    invalidation = request["invalidation"]
    declared_changes = sorted(invalidation["changed_dependency_kinds"])
    actual_changes = _changed_dependencies(request)

    if previous is None:
        if invalidation["status"] != "NOT_APPLICABLE" or declared_changes:
            findings.append(
                finding(
                    "OUTPUT_INVALIDATION_DECLARATION_MISMATCH",
                    "$.invalidation",
                    "A first state request must declare NOT_APPLICABLE with no changed dependencies.",
                    "P0",
                )
            )
    elif actual_changes:
        if (
            invalidation["status"] != "INVALIDATED_BY_DEPENDENCY_CHANGE"
            or declared_changes != actual_changes
        ):
            findings.append(
                finding(
                    "OUTPUT_INVALIDATION_DECLARATION_MISMATCH",
                    "$.invalidation",
                    "Invalidation status and changed dependency kinds must exactly match the snapshots.",
                    "P0",
                )
            )
        if request["requested_state"] == "REVIEW_REQUIRED":
            findings.append(
                finding(
                    "OUTPUT_STATE_REVALIDATION_REQUIRED",
                    "$.requested_state",
                    "Changed dependencies require a downgrade before REVIEW_REQUIRED can be requested again.",
                    "P0",
                )
            )
    elif invalidation["status"] != "CURRENT" or declared_changes:
        findings.append(
            finding(
                "OUTPUT_INVALIDATION_DECLARATION_MISMATCH",
                "$.invalidation",
                "Unchanged dependencies must declare CURRENT with an empty change list.",
                "P0",
            )
        )
    return actual_changes


def _make_report(request: dict, findings: list[dict], changes: list[str]) -> dict:
    findings.sort(key=lambda item: (item["code"], item["path"], item["message"]))
    allowed = not findings
    requested_state = request.get("requested_state")
    if changes:
        next_required_state = "REVALIDATE_CHANGED_DEPENDENCIES"
    elif requested_state == "REVIEW_REQUIRED":
        next_required_state = "COMPLETE_TECHNICAL_PREREQUISITES"
    else:
        next_required_state = "CONTINUE_TECHNICAL_WORK"
    return {
        "allowed": allowed,
        "allowed_scope": "TECHNICAL_OUTPUT_STATE_ONLY",
        "artifact_id": request.get("artifact_id"),
        "changed_dependency_kinds": changes,
        "findings": findings,
        "legal_review_required": True,
        "next_required_state": next_required_state,
        "requested_state": requested_state,
        "schema_version": request.get("schema_version"),
        "submission_ready": False,
        "validation_scope": {
            "verified": VERIFIED_CAPABILITIES if allowed else [],
            "not_verified": UNVERIFIED_CAPABILITIES,
        },
    }


def validate_formal_output_state(request: dict) -> dict:
    findings = validate_published_formal_output_state(request)
    if findings:
        return _make_report(request, findings, [])

    if not is_rfc3339_datetime(request["generated_at"]):
        findings.append(
            finding(
                "DATE_FORMAT_INVALID",
                "$.generated_at",
                "State request generation time must be an RFC 3339 UTC timestamp ending in Z.",
                "P0",
            )
        )

    _validate_transition(request, findings)
    changes = _validate_invalidation(request, findings)

    try:
        expected_snapshot = calculate_state_request_snapshot(request)
    except (TypeError, ValueError):
        findings.append(
            finding(
                "OUTPUT_STATE_CANONICALIZATION_FAILED",
                "$",
                "State request cannot be canonicalized as RFC 8785 I-JSON.",
                "P0",
            )
        )
    else:
        if request["state_request_sha256"] != expected_snapshot:
            findings.append(
                finding(
                    "OUTPUT_STATE_REQUEST_SNAPSHOT_MISMATCH",
                    "$.state_request_sha256",
                    "The state request changed without a new RFC 8785 snapshot.",
                    "P0",
                )
            )

    return _make_report(request, findings, changes)
