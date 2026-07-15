"""Human-gated fact candidates bound to replayable parser anchors."""

from __future__ import annotations

import copy
import hashlib
from datetime import datetime

import rfc8785

from finding_model import finding
from integrity_primitives import calculate_json_snapshot, is_rfc3339_datetime
from parser_extraction_policy import validate_parser_extraction_record
from schema_validation import validate_published_fact_candidate_record


LIMITATIONS = [
    "CANDIDATE_IS_NOT_ESTABLISHED_FACT",
    "ACTOR_IDENTITY_IS_NOT_AUTHENTICATED",
    "ADJUDICATED_MEANS_PASSAGE_CLASSIFICATION_NOT_TRIBUNAL_AUTHENTICATION",
    "ANCHOR_BINDING_DOES_NOT_PROVE_EVIDENCE_AUTHENTICITY",
    "LEGAL_RELEVANCE_AND_EFFECT_REQUIRE_INDEPENDENT_REVIEW",
]
CLAIM_TYPES = {
    "EMPLOYMENT_DATE", "WAGE_AMOUNT", "PAYMENT_DATE", "WORK_TIME",
    "WORK_LOCATION", "PARTY_IDENTITY", "TERMINATION_EVENT",
    "OTHER_OR_UNDETERMINED",
}


class FactCandidateError(ValueError):
    """A stable-code failure to create a fact candidate."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def calculate_fact_candidate_snapshot(record: dict) -> str:
    return calculate_json_snapshot(
        {key: value for key, value in record.items() if key != "record_snapshot_sha256"}
    )


def calculate_fact_candidate_id(record: dict) -> str:
    identity = calculate_json_snapshot(
        {
            "adjudicative_context": record["adjudicative_context"],
            "anchor_bindings": record["anchor_bindings"],
            "assertion": record["assertion"],
            "candidate_status": record["candidate_status"],
            "invalidation": record["invalidation"],
            "parse_binding": record["parse_binding"],
            "provenance_state": record["provenance_state"],
            "revision": record["revision"],
            "review": record["review"],
            "truth_status": record["truth_status"],
        }
    )
    return f"FACT-{identity[:24].upper()}"


def build_fact_candidate(
    parse_record: dict,
    *,
    anchor_ids: list[str],
    provenance_state: str,
    claim_type: str,
    assertion_text: str,
    created_at: str,
    actor_label: str | None = None,
    adjudicative_document_kind: str | None = None,
    adjudicative_document_reference: str | None = None,
    previous_record: dict | None = None,
) -> dict:
    _require_valid_parse(parse_record)
    if not is_rfc3339_datetime(created_at):
        raise FactCandidateError("FACT_DATE_INVALID", "created_at must be UTC RFC 3339 ending in Z.")
    if provenance_state not in {"EXTRACTED", "USER_ANNOTATED", "ADJUDICATED"}:
        raise FactCandidateError("FACT_PROVENANCE_STATE_INVALID", "Unsupported provenance state.")
    if claim_type not in CLAIM_TYPES:
        raise FactCandidateError("FACT_CLAIM_TYPE_INVALID", "Unsupported claim type.")
    if not isinstance(assertion_text, str) or not assertion_text or len(assertion_text) > 10000:
        raise FactCandidateError("FACT_ASSERTION_INVALID", "Assertion text must contain 1 to 10000 characters.")
    try:
        assertion_sha256 = hashlib.sha256(assertion_text.encode("utf-8")).hexdigest()
    except UnicodeEncodeError as error:
        raise FactCandidateError("FACT_ASSERTION_UTF8_INVALID", "Assertion text must be valid UTF-8 scalar text.") from error
    anchors = _select_anchors(parse_record, anchor_ids)
    review, adjudicative_context, transition = _state_fields(
        provenance_state,
        anchors,
        assertion_text,
        actor_label,
        created_at,
        adjudicative_document_kind,
        adjudicative_document_reference,
        previous_record,
    )
    revision = _revision(previous_record, transition)
    record = {
        "schema_version": "1.0",
        "fact_candidate_id": "FACT-" + "0" * 24,
        "created_at": created_at,
        "clock_status": "SYSTEM_CLOCK_UNATTESTED",
        "parse_binding": _parse_binding(parse_record),
        "provenance_state": provenance_state,
        "assertion": {
            "claim_type": claim_type,
            "text": assertion_text,
            "text_sha256": assertion_sha256,
        },
        "anchor_bindings": [_anchor_binding(item) for item in anchors],
        "review": review,
        "adjudicative_context": adjudicative_context,
        "truth_status": "UNVERIFIED",
        "candidate_status": "ACTIVE",
        "invalidation": None,
        "revision": revision,
        "limitations": list(LIMITATIONS),
        "record_snapshot_sha256": "0" * 64,
    }
    record["fact_candidate_id"] = calculate_fact_candidate_id(record)
    record["record_snapshot_sha256"] = calculate_fact_candidate_snapshot(record)
    report = validate_fact_candidate_record(record, parse_record, previous_record)
    if not report["allowed"]:
        raise FactCandidateError("FACT_CANDIDATE_BUILD_FAILED", report["findings"][0]["message"])
    return record


def invalidate_fact_candidate(
    previous_record: dict,
    parse_record: dict,
    *,
    reason_code: str,
    reason: str,
    actor_label: str,
    created_at: str,
) -> dict:
    previous_report = validate_fact_candidate_record(previous_record, parse_record)
    blocking_previous_findings = [
        item
        for item in previous_report["findings"]
        if item["code"] != "FACT_PREVIOUS_RECORD_REQUIRED"
    ]
    if blocking_previous_findings:
        raise FactCandidateError("FACT_PREVIOUS_RECORD_INVALID", "Previous fact candidate is invalid.")
    if previous_record["candidate_status"] != "ACTIVE":
        raise FactCandidateError("FACT_ALREADY_INVALIDATED", "Only an active candidate can be invalidated.")
    if reason_code not in {"SOURCE_CHANGED", "ANCHOR_MISSING", "USER_RETRACTED", "SUPERSEDED", "OTHER"}:
        raise FactCandidateError("FACT_INVALIDATION_REASON_CODE_INVALID", "Unsupported invalidation reason code.")
    if not reason or len(reason) > 1000 or not actor_label or len(actor_label) > 128:
        raise FactCandidateError("FACT_INVALIDATION_DETAILS_INVALID", "Invalidation requires bounded reason and actor label.")
    if not is_rfc3339_datetime(created_at):
        raise FactCandidateError("FACT_DATE_INVALID", "created_at must be UTC RFC 3339 ending in Z.")
    record = copy.deepcopy(previous_record)
    record["created_at"] = created_at
    record["candidate_status"] = "INVALIDATED"
    record["invalidation"] = {
        "reason_code": reason_code,
        "reason": reason,
        "invalidated_at": created_at,
        "actor_label": actor_label,
    }
    record["revision"] = _revision(previous_record, "INVALIDATED")
    record["fact_candidate_id"] = calculate_fact_candidate_id(record)
    record["record_snapshot_sha256"] = calculate_fact_candidate_snapshot(record)
    report = validate_fact_candidate_record(record, parse_record, previous_record)
    if not report["allowed"]:
        raise FactCandidateError("FACT_CANDIDATE_BUILD_FAILED", report["findings"][0]["message"])
    return record


def validate_fact_candidate_record(
    record: dict, parse_record: dict, previous_record: dict | None = None
) -> dict:
    findings = validate_published_fact_candidate_record(record)
    parse_report = validate_parser_extraction_record(parse_record)
    if not parse_report["allowed"]:
        findings.append(finding("FACT_PARSE_RECORD_INVALID", "$.parse_binding", "The bound parser extraction record is invalid.", "P0"))
        return _report(record, findings)
    if findings:
        return _report(record, findings)

    if not is_rfc3339_datetime(record["created_at"]):
        findings.append(finding("DATE_FORMAT_INVALID", "$.created_at", "Fact candidate time must be UTC RFC 3339 ending in Z.", "P0"))
    reviewed_at = record["review"]["reviewed_at"]
    if reviewed_at is not None and not is_rfc3339_datetime(reviewed_at):
        findings.append(finding("DATE_FORMAT_INVALID", "$.review.reviewed_at", "Review time must be UTC RFC 3339 ending in Z.", "P0"))
    expected_binding = _parse_binding(parse_record)
    if record["parse_binding"] != expected_binding:
        findings.append(finding("FACT_PARSE_BINDING_MISMATCH", "$.parse_binding", "Candidate must bind the exact parser record, workspace, and raw content.", "P0"))
    parse_anchors = {item["anchor_id"]: item for item in parse_record["anchors"]}
    for index, binding in enumerate(record["anchor_bindings"]):
        source = parse_anchors.get(binding["anchor_id"])
        if source is None or binding != _anchor_binding(source):
            findings.append(finding("FACT_ANCHOR_REPLAY_FAILED", f"$.anchor_bindings[{index}]", "Anchor must replay exactly against the bound parser record.", "P0"))
    if len({item["anchor_id"] for item in record["anchor_bindings"]}) != len(record["anchor_bindings"]):
        findings.append(finding("FACT_ANCHOR_DUPLICATE", "$.anchor_bindings", "Anchor bindings must be unique.", "P0"))
    try:
        assertion_hash = hashlib.sha256(record["assertion"]["text"].encode("utf-8")).hexdigest()
    except UnicodeEncodeError:
        assertion_hash = None
        findings.append(finding("FACT_ASSERTION_UTF8_INVALID", "$.assertion.text", "Assertion text must be valid UTF-8 scalar text.", "P0"))
    if assertion_hash is not None and record["assertion"]["text_sha256"] != assertion_hash:
        findings.append(finding("FACT_ASSERTION_HASH_MISMATCH", "$.assertion.text_sha256", "Assertion hash must bind exact UTF-8 text.", "P0"))
    _validate_state_semantics(record, parse_anchors, findings)
    _validate_status_semantics(record, findings)
    _validate_revision(record, previous_record, parse_record, findings)
    try:
        expected_id = calculate_fact_candidate_id(record)
        expected_snapshot = calculate_fact_candidate_snapshot(record)
    except (rfc8785.CanonicalizationError, TypeError, ValueError):
        findings.append(finding("FACT_CANONICALIZATION_FAILED", "$", "Fact candidate cannot be canonicalized as RFC 8785 I-JSON.", "P0"))
    else:
        if record["fact_candidate_id"] != expected_id:
            findings.append(finding("FACT_ID_MISMATCH", "$.fact_candidate_id", "Fact candidate ID must bind its semantic identity.", "P0"))
        if record["record_snapshot_sha256"] != expected_snapshot:
            findings.append(finding("FACT_SNAPSHOT_MISMATCH", "$.record_snapshot_sha256", "Fact candidate changed without a new RFC 8785 snapshot.", "P0"))
    return _report(record, findings)


def _require_valid_parse(parse_record: dict) -> None:
    report = validate_parser_extraction_record(parse_record)
    if not report["allowed"] or parse_record.get("status") != "SUCCEEDED":
        raise FactCandidateError("FACT_PARSE_RECORD_INVALID", "A successful valid parser record is required.")


def _select_anchors(parse_record: dict, anchor_ids: list[str]) -> list[dict]:
    if not anchor_ids or len(anchor_ids) > 100 or len(anchor_ids) != len(set(anchor_ids)):
        raise FactCandidateError("FACT_ANCHOR_SELECTION_INVALID", "Select 1 to 100 unique parser anchors.")
    available = {item["anchor_id"]: item for item in parse_record["anchors"]}
    try:
        return [available[anchor_id] for anchor_id in anchor_ids]
    except KeyError as error:
        raise FactCandidateError("FACT_ANCHOR_NOT_FOUND", "Selected anchor is absent from the parser record.") from error


def _state_fields(state, anchors, text, actor_label, created_at, document_kind, document_reference, previous):
    if state == "EXTRACTED":
        if previous is not None:
            raise FactCandidateError("FACT_TRANSITION_INVALID", "EXTRACTED can only create an initial candidate.")
        if len(anchors) != 1 or text != anchors[0]["text"]:
            raise FactCandidateError("FACT_EXTRACTED_TEXT_NOT_EXACT", "EXTRACTED text must equal one exact parser anchor.")
        if actor_label is not None or document_kind is not None or document_reference is not None:
            raise FactCandidateError("FACT_EXTRACTED_REVIEW_INVALID", "EXTRACTED cannot claim a human or adjudicative review.")
        return ({"actor_assertion": "MACHINE_EXTRACTION", "actor_label": None, "confirmation_status": "NOT_HUMAN_CONFIRMED", "reviewed_at": None}, None, "CREATED")
    if previous is None or previous.get("provenance_state") != "EXTRACTED" or previous.get("candidate_status") != "ACTIVE":
        raise FactCandidateError("FACT_TRANSITION_INVALID", "Human-labelled states require an active EXTRACTED predecessor.")
    previous_anchor_ids = {
        item["anchor_id"] for item in previous.get("anchor_bindings", [])
    }
    selected_anchor_ids = {item["anchor_id"] for item in anchors}
    if not previous_anchor_ids or not previous_anchor_ids.issubset(selected_anchor_ids):
        raise FactCandidateError("FACT_TRANSITION_ANCHOR_MISMATCH", "A derived label must retain every predecessor anchor.")
    if not actor_label or len(actor_label) > 128:
        raise FactCandidateError("FACT_ACTOR_LABEL_REQUIRED", "A bounded self-declared actor label is required.")
    if state == "USER_ANNOTATED":
        if document_kind is not None or document_reference is not None:
            raise FactCandidateError("FACT_ADJUDICATIVE_CONTEXT_INVALID", "User annotations cannot claim adjudicative context.")
        return ({"actor_assertion": "USER_SELF_DECLARED_UNAUTHENTICATED", "actor_label": actor_label, "confirmation_status": "USER_CONFIRMED_UNAUTHENTICATED", "reviewed_at": created_at}, None, "USER_ANNOTATED")
    if len(anchors) != 1 or text != anchors[0]["text"]:
        raise FactCandidateError("FACT_ADJUDICATED_TEXT_NOT_EXACT", "ADJUDICATED text must equal one exact parser anchor.")
    if document_kind not in {"ARBITRATION_AWARD", "COURT_JUDGMENT", "COURT_RULING", "OTHER_ADJUDICATIVE_DOCUMENT"} or not document_reference:
        raise FactCandidateError("FACT_ADJUDICATIVE_CONTEXT_REQUIRED", "Document kind and self-declared reference are required.")
    return ({"actor_assertion": "ADJUDICATIVE_DOCUMENT_TRANSCRIPTION_UNVERIFIED", "actor_label": actor_label, "confirmation_status": "DOCUMENT_PASSAGE_CLASSIFIED_UNAUTHENTICATED", "reviewed_at": created_at}, {"document_kind": document_kind, "document_reference": document_reference, "passage_role": "CANDIDATE_ADJUDICATIVE_STATEMENT", "document_authenticity_status": "UNVERIFIED", "legal_effect_status": "UNVERIFIED"}, "ADJUDICATIVE_DOCUMENT_TRANSCRIBED")


def _revision(previous, transition):
    if previous is None:
        return {"revision_number": 1, "transition": "CREATED", "previous_fact_candidate_id": None, "previous_record_snapshot_sha256": None}
    return {"revision_number": previous["revision"]["revision_number"] + 1, "transition": transition, "previous_fact_candidate_id": previous["fact_candidate_id"], "previous_record_snapshot_sha256": previous["record_snapshot_sha256"]}


def _parse_binding(parse_record):
    workspace = parse_record["workspace_binding"]
    return {"parse_id": parse_record["parse_id"], "parse_record_snapshot_sha256": parse_record["record_snapshot_sha256"], "workspace_id": workspace["workspace_id"], "raw_id": workspace["raw_id"], "content_sha256": workspace["content_sha256"]}


def _anchor_binding(anchor):
    return {key: anchor[key] for key in ("anchor_id", "kind", "coordinate", "text_sha256")}


def _validate_state_semantics(record, parse_anchors, findings):
    state = record["provenance_state"]
    review = record["review"]
    anchors = record["anchor_bindings"]
    exact = len(anchors) == 1 and anchors[0]["anchor_id"] in parse_anchors and record["assertion"]["text"] == parse_anchors[anchors[0]["anchor_id"]]["text"]
    expectations = {
        "EXTRACTED": ("MACHINE_EXTRACTION", None, "NOT_HUMAN_CONFIRMED", None),
        "USER_ANNOTATED": ("USER_SELF_DECLARED_UNAUTHENTICATED", "NON_NULL", "USER_CONFIRMED_UNAUTHENTICATED", None),
        "ADJUDICATED": ("ADJUDICATIVE_DOCUMENT_TRANSCRIPTION_UNVERIFIED", "NON_NULL", "DOCUMENT_PASSAGE_CLASSIFIED_UNAUTHENTICATED", "NON_NULL"),
    }
    actor, label, confirmation, context = expectations[state]
    valid = review["actor_assertion"] == actor and review["confirmation_status"] == confirmation
    valid = valid and ((review["actor_label"] is not None) == (label == "NON_NULL"))
    valid = valid and ((record["adjudicative_context"] is not None) == (context == "NON_NULL"))
    valid = valid and ((review["reviewed_at"] is not None) == (state != "EXTRACTED"))
    valid = valid and (
        state == "EXTRACTED"
        or record["candidate_status"] == "INVALIDATED"
        or review["reviewed_at"] == record["created_at"]
    )
    if not valid:
        findings.append(finding("FACT_STATE_SEMANTICS_MISMATCH", "$.provenance_state", "Provenance state, actor assertion, confirmation, time, and context must agree.", "P0"))
    if state in {"EXTRACTED", "ADJUDICATED"} and not exact:
        findings.append(finding("FACT_EXACT_ANCHOR_TEXT_REQUIRED", "$.assertion.text", "Extracted or adjudicative transcription text must equal one exact anchor.", "P0"))


def _validate_status_semantics(record, findings):
    invalidated = record["candidate_status"] == "INVALIDATED"
    if invalidated != (record["invalidation"] is not None):
        findings.append(finding("FACT_INVALIDATION_STATUS_MISMATCH", "$.candidate_status", "Invalidated status and invalidation details must agree.", "P0"))
    if invalidated:
        value = record["invalidation"]
        if not is_rfc3339_datetime(value["invalidated_at"]) or value["invalidated_at"] != record["created_at"]:
            findings.append(finding("FACT_INVALIDATION_TIME_MISMATCH", "$.invalidation.invalidated_at", "Invalidation time must be the revision creation time.", "P0"))


def _validate_revision(record, previous, parse_record, findings):
    revision = record["revision"]
    initial = revision["revision_number"] == 1
    if initial:
        if revision != {"revision_number": 1, "transition": "CREATED", "previous_fact_candidate_id": None, "previous_record_snapshot_sha256": None} or record["provenance_state"] != "EXTRACTED" or record["candidate_status"] != "ACTIVE":
            findings.append(finding("FACT_INITIAL_REVISION_INVALID", "$.revision", "Initial revision must be an active EXTRACTED creation without a predecessor.", "P0"))
        if previous is not None:
            findings.append(finding("FACT_UNEXPECTED_PREVIOUS_RECORD", "$.revision", "Initial candidate must not receive a previous record.", "P0"))
        return
    if previous is None:
        findings.append(finding("FACT_PREVIOUS_RECORD_REQUIRED", "$.revision", "A derived revision requires its exact predecessor for validation.", "P0"))
        return
    previous_report = validate_fact_candidate_record(previous, parse_record)
    if any(
        item["code"] != "FACT_PREVIOUS_RECORD_REQUIRED"
        for item in previous_report["findings"]
    ):
        findings.append(finding("FACT_PREVIOUS_RECORD_INVALID", "$.revision", "The supplied predecessor fails its own integrity checks.", "P0"))
    if previous.get("fact_candidate_id") != revision["previous_fact_candidate_id"] or previous.get("record_snapshot_sha256") != revision["previous_record_snapshot_sha256"] or revision["revision_number"] != previous.get("revision", {}).get("revision_number", 0) + 1:
        findings.append(finding("FACT_PREVIOUS_RECORD_MISMATCH", "$.revision", "Revision must bind the exact immediately preceding candidate snapshot.", "P0"))
    if previous.get("candidate_status") != "ACTIVE" or previous.get("parse_binding") != record["parse_binding"] or _parse_time(record["created_at"]) < _parse_time(previous.get("created_at", "")):
        findings.append(finding("FACT_TRANSITION_PRECONDITION_FAILED", "$.revision", "Transition requires an active predecessor on the same parse binding and non-decreasing time.", "P0"))
    transition = revision["transition"]
    previous_anchor_ids = {
        item["anchor_id"] for item in previous.get("anchor_bindings", [])
    }
    current_anchor_ids = {item["anchor_id"] for item in record["anchor_bindings"]}
    retained_predecessor_anchors = bool(previous_anchor_ids) and previous_anchor_ids.issubset(current_anchor_ids)
    unchanged_invalidation_fields = all(
        record.get(field) == previous.get(field)
        for field in (
            "schema_version", "clock_status", "parse_binding", "provenance_state",
            "assertion", "anchor_bindings", "review", "adjudicative_context",
            "truth_status", "limitations",
        )
    )
    allowed = (
        transition == "INVALIDATED" and record["candidate_status"] == "INVALIDATED" and unchanged_invalidation_fields
    ) or (
        transition == "USER_ANNOTATED" and previous.get("provenance_state") == "EXTRACTED" and record["provenance_state"] == "USER_ANNOTATED" and record["candidate_status"] == "ACTIVE" and retained_predecessor_anchors
    ) or (
        transition == "ADJUDICATIVE_DOCUMENT_TRANSCRIBED" and previous.get("provenance_state") == "EXTRACTED" and record["provenance_state"] == "ADJUDICATED" and record["candidate_status"] == "ACTIVE" and record["anchor_bindings"] == previous.get("anchor_bindings")
    )
    if not allowed:
        findings.append(finding("FACT_TRANSITION_INVALID", "$.revision.transition", "Candidate provenance/status transition is not permitted.", "P0"))


def _parse_time(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return datetime.min.replace(tzinfo=datetime.now().astimezone().tzinfo)


def _report(record, findings):
    findings.sort(key=lambda item: (item["code"], item["path"], item["message"]))
    allowed = not findings
    return {
        "allowed": allowed,
        "allowed_scope": "LOCAL_FACT_CANDIDATE_INTEGRITY",
        "fact_candidate_id": record.get("fact_candidate_id"),
        "findings": findings,
        "human_identity_authenticated": False,
        "legal_review_required": True,
        "submission_ready": False,
        "truth_established": False,
        "validation_scope": {
            "verified": ["ANCHOR_REPLAY_AGAINST_PARSE_RECORD", "FACT_REVISION_BINDING", "RFC8785_RECORD_SNAPSHOT"] if allowed else [],
            "not_verified": ["ACTOR_IDENTITY", "ADJUDICATIVE_DOCUMENT_AUTHENTICITY_OR_EFFECT", "EVIDENCE_AUTHENTICITY", "FACT_TRUTH", "LEGAL_RELEVANCE"],
        },
    }
