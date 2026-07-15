"""Human-gated evidence review, proof-purpose, gap, and suggestion policy."""

from __future__ import annotations

import rfc8785

from fact_analysis_policy import validate_fact_analysis_record
from fact_candidate_policy import validate_fact_candidate_record
from finding_model import finding
from integrity_primitives import calculate_json_snapshot, is_rfc3339_datetime
from parser_extraction_policy import validate_parser_extraction_record
from schema_validation import (
    validate_published_evidence_review_input,
    validate_published_evidence_review_record,
)


LIMITATIONS = [
    "ASSESSMENT_IS_USER_SUPPLIED_UNAUTHENTICATED",
    "AUTHENTICITY_ADMISSIBILITY_AND_WEIGHT_NOT_DETERMINED",
    "PROOF_PURPOSE_DOES_NOT_ESTABLISH_RELEVANCE_OR_SUPPORT",
    "CORROBORATION_BINDINGS_ARE_NOT_EXTERNALLY_VERIFIED",
    "SUGGESTIONS_ARE_GENERIC_GAP_ACTIONS_NOT_LEGAL_ADVICE",
    "NO_SUBMISSION_READINESS",
]
EVIDENCE_TYPE_BY_ADAPTER = {
    "UTF8_TEXT": "TEXT",
    "CSV": "TABLE",
    "DOCX": "DOCUMENT",
    "XLSX": "TABLE",
    "EML": "EMAIL",
    "ZIP_INSPECTION": "ARCHIVE_ENTRY_LIST",
}
SUGGESTION_ACTIONS = {
    "PRESERVE_AUTHENTICATION_MATERIAL": "Preserve the original carrier, complete bytes, metadata, acquisition context, and any available issuer or transmission records for independent authentication review.",
    "OBTAIN_INDEPENDENT_LEGALITY_REVIEW": "Obtain independent legal review of collection, privacy, consent, confidentiality, access, alteration, and proposed-use risks before relying on or sharing the material.",
    "DOCUMENT_SOURCE_PROVENANCE": "Record when, how, from whom, and in what form the material was obtained while preserving the original source separately.",
    "PRESERVE_COMPLETE_CONTEXT": "Preserve the complete document, conversation, attachment set, surrounding entries, and relevant headers instead of relying only on an excerpt.",
    "LINK_SUBJECT_IDENTIFIERS": "Collect independent records that link the people or entities in the material to the asserted case subjects without overwriting any mismatch.",
    "PRESERVE_TIME_METADATA": "Preserve original timestamps, headers, system exports, contemporaneous records, and timezone context for independent time verification.",
    "PRESERVE_ORIGINAL_AND_TRANSFORMATION_CHAIN": "Preserve original bytes and document every conversion, crop, edit, export, redaction, or transcription as a separate transformation step.",
    "SEEK_INDEPENDENT_CORROBORATION": "Seek an independently sourced record or witness account addressing the same proposition and bind it as a separate evidence review.",
}
GAP_TO_SUGGESTION = {
    "AUTHENTICITY_UNVERIFIED": "PRESERVE_AUTHENTICATION_MATERIAL",
    "LEGALITY_REVIEW_REQUIRED": "OBTAIN_INDEPENDENT_LEGALITY_REVIEW",
    "SOURCE_PROVENANCE_UNKNOWN": "DOCUMENT_SOURCE_PROVENANCE",
    "COMPLETENESS_NOT_ASSERTED": "PRESERVE_COMPLETE_CONTEXT",
    "SUBJECT_LINK_NOT_ASSERTED": "LINK_SUBJECT_IDENTIFIERS",
    "SUBJECT_LINK_CONFLICT": "LINK_SUBJECT_IDENTIFIERS",
    "TIME_LINK_NOT_ASSERTED": "PRESERVE_TIME_METADATA",
    "TIME_LINK_CONFLICT": "PRESERVE_TIME_METADATA",
    "ORIGINAL_BYTES_PRESERVATION_NOT_ASSERTED": "PRESERVE_ORIGINAL_AND_TRANSFORMATION_CHAIN",
    "INTEGRITY_CONCERN_FLAGGED": "PRESERVE_ORIGINAL_AND_TRANSFORMATION_CHAIN",
    "NO_CORROBORATING_REVIEW_BOUND": "SEEK_INDEPENDENT_CORROBORATION",
    "LEGALITY_RISK_UNKNOWN": "OBTAIN_INDEPENDENT_LEGALITY_REVIEW",
    "LEGALITY_RISK_FLAGGED": "OBTAIN_INDEPENDENT_LEGALITY_REVIEW",
}


class EvidenceReviewError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def calculate_purpose_id(purpose: dict) -> str:
    identity = calculate_json_snapshot(
        {
            "purpose_key": purpose["purpose_key"],
            "proposition": purpose["proposition"],
            "relationship_status": purpose["relationship_status"],
            "view_bindings": purpose["view_bindings"],
        }
    )
    return f"PURPOSE-{identity[:24].upper()}"


def calculate_purpose_snapshot(purpose: dict) -> str:
    return calculate_json_snapshot(
        {key: value for key, value in purpose.items() if key != "purpose_snapshot_sha256"}
    )


def calculate_evidence_review_id(record: dict) -> str:
    identity = calculate_json_snapshot(
        {
            "actor_assertion": record["actor_assertion"],
            "actor_label": record["actor_label"],
            "assessment": record["assessment"],
            "corroborating_review_bindings": record["corroborating_review_bindings"],
            "evidence_binding": record["evidence_binding"],
            "evidence_type": record["evidence_type"],
            "identified_gaps": record["identified_gaps"],
            "proof_purposes": record["proof_purposes"],
            "review_artifact_id": record["review_artifact_id"],
            "strengthening_suggestions": record["strengthening_suggestions"],
        }
    )
    return f"EVREVIEW-{identity[:24].upper()}"


def calculate_evidence_review_snapshot(record: dict) -> str:
    return calculate_json_snapshot(
        {key: value for key, value in record.items() if key != "record_snapshot_sha256"}
    )


def build_evidence_review(specification: dict) -> dict:
    input_findings = validate_published_evidence_review_input(specification)
    if input_findings:
        raise EvidenceReviewError("EVIDENCE_REVIEW_INPUT_INVALID", input_findings[0]["message"])
    if not is_rfc3339_datetime(specification["created_at"]):
        raise EvidenceReviewError("EVIDENCE_REVIEW_DATE_INVALID", "created_at must be UTC RFC 3339 ending in Z.")
    try:
        return _build_evidence_review(specification)
    except EvidenceReviewError:
        raise
    except (rfc8785.CanonicalizationError, TypeError, ValueError) as error:
        raise EvidenceReviewError("EVIDENCE_REVIEW_IJSON_INVALID", "Evidence review input cannot be canonicalized as RFC 8785 I-JSON.") from error


def _build_evidence_review(specification: dict) -> dict:
    parse_record = specification["parse_record"]
    parse_report = validate_parser_extraction_record(parse_record)
    adapter = parse_record.get("parser", {}).get("adapter")
    if not parse_report["allowed"] or parse_record.get("status") != "SUCCEEDED" or adapter not in EVIDENCE_TYPE_BY_ADAPTER:
        raise EvidenceReviewError("EVIDENCE_REVIEW_PARSE_INVALID", "A successful supported parser record is required.")
    candidate_by_id = {}
    for item in specification["fact_candidates"]:
        candidate = item["record"]
        report = validate_fact_candidate_record(candidate, parse_record, item["previous_record"])
        if not report["allowed"] or candidate.get("candidate_status") != "ACTIVE":
            raise EvidenceReviewError("EVIDENCE_REVIEW_CANDIDATE_INVALID", "Every bound fact candidate must be active and replay-valid against the same parser record.")
        candidate_id = candidate["fact_candidate_id"]
        if candidate_id in candidate_by_id:
            raise EvidenceReviewError("EVIDENCE_REVIEW_CANDIDATE_DUPLICATE", "Fact candidate bindings must be unique.")
        candidate_by_id[candidate_id] = candidate
    analysis = specification["fact_analysis_record"]
    analysis_report = validate_fact_analysis_record(analysis, specification["previous_fact_analysis_record"])
    if not analysis_report["allowed"]:
        raise EvidenceReviewError("EVIDENCE_REVIEW_ANALYSIS_INVALID", "The bound structured fact analysis record is invalid.")
    view_by_id = {view["view_id"]: view for view in analysis["views"]}
    purposes = [_build_purpose(item, view_by_id, candidate_by_id) for item in specification["proof_purposes"]]
    purposes.sort(key=lambda item: item["purpose_key"])
    purpose_keys = [item["purpose_key"] for item in purposes]
    if len(purpose_keys) != len(set(purpose_keys)):
        raise EvidenceReviewError("EVIDENCE_REVIEW_PURPOSE_KEY_DUPLICATE", "Proof-purpose keys must be unique.")
    used_candidate_ids = {
        binding["fact_candidate_id"]
        for purpose in purposes
        for binding in purpose["view_bindings"]
    }
    if used_candidate_ids != set(candidate_by_id):
        raise EvidenceReviewError("EVIDENCE_REVIEW_UNUSED_CANDIDATE", "Every supplied fact candidate must be used by at least one proof purpose.")
    assessment = dict(specification["assessment"])
    risks = sorted(assessment["legality_risk_flags"])
    if "NONE_DECLARED_UNVERIFIED" in risks and len(risks) != 1:
        raise EvidenceReviewError("EVIDENCE_REVIEW_LEGALITY_FLAGS_CONFLICT", "NONE_DECLARED_UNVERIFIED cannot be combined with another legality risk flag.")
    assessment["legality_risk_flags"] = risks
    assessment["assessment_status"] = "USER_ASSESSED_UNAUTHENTICATED"
    corroboration = [
        {
            **item,
            "relationship_status": "USER_DECLARED_CORROBORATION_UNVERIFIED",
        }
        for item in specification["corroborating_review_bindings"]
    ]
    corroboration.sort(key=lambda item: (item["evidence_review_id"], item["record_snapshot_sha256"]))
    corroboration_ids = [item["evidence_review_id"] for item in corroboration]
    if len(corroboration_ids) != len(set(corroboration_ids)):
        raise EvidenceReviewError("EVIDENCE_REVIEW_CORROBORATION_DUPLICATE", "A corroborating review ID may appear only once.")
    gaps = _identified_gaps(assessment, corroboration)
    suggestions = _suggestions(gaps)
    workspace = parse_record["workspace_binding"]
    candidate_bindings = [
        {
            "fact_candidate_id": candidate["fact_candidate_id"],
            "record_snapshot_sha256": candidate["record_snapshot_sha256"],
            "provenance_state": candidate["provenance_state"],
        }
        for candidate in candidate_by_id.values()
    ]
    candidate_bindings.sort(key=lambda item: item["fact_candidate_id"])
    record = {
        "schema_version": "1.0",
        "evidence_review_id": "EVREVIEW-" + "0" * 24,
        "review_artifact_id": specification["review_artifact_id"],
        "created_at": specification["created_at"],
        "clock_status": "SYSTEM_CLOCK_UNATTESTED",
        "actor_assertion": "USER_EVIDENCE_REVIEW_UNAUTHENTICATED",
        "actor_label": specification["actor_label"],
        "evidence_binding": {
            "workspace_id": workspace["workspace_id"],
            "raw_id": workspace["raw_id"],
            "content_sha256": workspace["content_sha256"],
            "parse_id": parse_record["parse_id"],
            "parse_record_snapshot_sha256": parse_record["record_snapshot_sha256"],
            "fact_candidate_bindings": candidate_bindings,
            "fact_analysis_id": analysis["analysis_id"],
            "fact_analysis_snapshot_sha256": analysis["record_snapshot_sha256"],
        },
        "evidence_type": EVIDENCE_TYPE_BY_ADAPTER[adapter],
        "assessment": assessment,
        "proof_purposes": purposes,
        "corroborating_review_bindings": corroboration,
        "identified_gaps": gaps,
        "strengthening_suggestions": suggestions,
        "authenticity_status": "UNVERIFIED",
        "admissibility_status": "NOT_DETERMINED_REQUIRES_LEGAL_REVIEW",
        "evidence_weight_status": "NOT_ASSESSED",
        "legality_review_status": "PENDING_LEGAL_REVIEW",
        "overall_status": "GAPS_RECORDED_PENDING_HUMAN_AND_LEGAL_REVIEW",
        "output_permission": "INTERNAL_ANALYSIS_ONLY",
        "limitations": list(LIMITATIONS),
        "record_snapshot_sha256": "0" * 64,
    }
    record["evidence_review_id"] = calculate_evidence_review_id(record)
    record["record_snapshot_sha256"] = calculate_evidence_review_snapshot(record)
    report = validate_evidence_review_record(record)
    if not report["allowed"]:
        raise EvidenceReviewError("EVIDENCE_REVIEW_BUILD_FAILED", report["findings"][0]["message"])
    return record


def validate_evidence_review_record(record: dict) -> dict:
    findings = validate_published_evidence_review_record(record)
    if findings:
        return _report(record, findings)
    if not is_rfc3339_datetime(record["created_at"]):
        findings.append(finding("DATE_FORMAT_INVALID", "$.created_at", "Evidence review time must be UTC RFC 3339 ending in Z.", "P0"))
    candidate_bindings = record["evidence_binding"]["fact_candidate_bindings"]
    candidate_ids = [item["fact_candidate_id"] for item in candidate_bindings]
    if candidate_ids != sorted(candidate_ids) or len(candidate_ids) != len(set(candidate_ids)):
        findings.append(finding("EVIDENCE_REVIEW_CANDIDATE_ORDER_OR_IDENTITY_INVALID", "$.evidence_binding.fact_candidate_bindings", "Candidate bindings must be unique and sorted.", "P0"))
    purpose_keys = []
    for index, purpose in enumerate(record["proof_purposes"]):
        purpose_keys.append(purpose["purpose_key"])
        _validate_purpose(purpose, index, findings)
    if purpose_keys != sorted(purpose_keys) or len(purpose_keys) != len(set(purpose_keys)):
        findings.append(finding("EVIDENCE_REVIEW_PURPOSE_ORDER_OR_IDENTITY_INVALID", "$.proof_purposes", "Proof purposes must be unique and sorted by purpose_key.", "P0"))
    corroboration = record["corroborating_review_bindings"]
    if corroboration != sorted(corroboration, key=lambda item: (item["evidence_review_id"], item["record_snapshot_sha256"])):
        findings.append(finding("EVIDENCE_REVIEW_CORROBORATION_ORDER_INVALID", "$.corroborating_review_bindings", "Corroborating review bindings must be sorted deterministically.", "P0"))
    corroboration_ids = [item["evidence_review_id"] for item in corroboration]
    if len(corroboration_ids) != len(set(corroboration_ids)):
        findings.append(finding("EVIDENCE_REVIEW_CORROBORATION_DUPLICATE", "$.corroborating_review_bindings", "A corroborating review ID may appear only once.", "P0"))
    if record["evidence_review_id"] in corroboration_ids:
        findings.append(finding("EVIDENCE_REVIEW_SELF_CORROBORATION", "$.corroborating_review_bindings", "An evidence review cannot corroborate itself.", "P0"))
    risks = record["assessment"]["legality_risk_flags"]
    if risks != sorted(risks) or ("NONE_DECLARED_UNVERIFIED" in risks and len(risks) != 1):
        findings.append(finding("EVIDENCE_REVIEW_LEGALITY_FLAGS_INVALID", "$.assessment.legality_risk_flags", "Legality flags must be sorted and NONE cannot coexist with another flag.", "P0"))
    expected_gaps = _identified_gaps(record["assessment"], corroboration)
    if record["identified_gaps"] != expected_gaps:
        findings.append(finding("EVIDENCE_REVIEW_GAP_SET_MISMATCH", "$.identified_gaps", "Gap set must exactly match the bounded user assessment.", "P0"))
    expected_suggestions = _suggestions(expected_gaps)
    if record["strengthening_suggestions"] != expected_suggestions:
        findings.append(finding("EVIDENCE_REVIEW_SUGGESTION_SET_MISMATCH", "$.strengthening_suggestions", "Suggestions must exactly match the generic action map for open gaps.", "P0"))
    try:
        expected_id = calculate_evidence_review_id(record)
        expected_snapshot = calculate_evidence_review_snapshot(record)
    except (rfc8785.CanonicalizationError, TypeError, ValueError):
        findings.append(finding("EVIDENCE_REVIEW_CANONICALIZATION_FAILED", "$", "Evidence review cannot be canonicalized as RFC 8785 I-JSON.", "P0"))
    else:
        if record["evidence_review_id"] != expected_id:
            findings.append(finding("EVIDENCE_REVIEW_ID_MISMATCH", "$.evidence_review_id", "Evidence review ID must bind assessment, purposes, gaps, and upstream snapshots.", "P0"))
        if record["record_snapshot_sha256"] != expected_snapshot:
            findings.append(finding("EVIDENCE_REVIEW_SNAPSHOT_MISMATCH", "$.record_snapshot_sha256", "Evidence review changed without a new RFC 8785 snapshot.", "P0"))
    return _report(record, findings)


def _build_purpose(item, view_by_id, candidate_by_id):
    bindings = []
    for view_id in item["view_ids"]:
        view = view_by_id.get(view_id)
        if view is None:
            raise EvidenceReviewError("EVIDENCE_REVIEW_VIEW_NOT_FOUND", "Every proof-purpose view must exist in the bound fact analysis.")
        candidate_id = view["fact_candidate_binding"]["fact_candidate_id"]
        candidate = candidate_by_id.get(candidate_id)
        if candidate is None or candidate["record_snapshot_sha256"] != view["fact_candidate_binding"]["record_snapshot_sha256"]:
            raise EvidenceReviewError("EVIDENCE_REVIEW_VIEW_CANDIDATE_MISMATCH", "Every selected view must bind one supplied candidate with the exact snapshot.")
        bindings.append(
            {
                "view_id": view["view_id"],
                "view_snapshot_sha256": view["view_snapshot_sha256"],
                "fact_candidate_id": candidate_id,
                "fact_candidate_snapshot_sha256": candidate["record_snapshot_sha256"],
            }
        )
    bindings.sort(key=lambda value: value["view_id"])
    purpose = {
        "purpose_id": "PURPOSE-" + "0" * 24,
        "purpose_key": item["purpose_key"],
        "proposition": item["proposition"],
        "view_bindings": bindings,
        "relationship_status": "USER_ASSERTED_PROOF_PURPOSE_UNVERIFIED",
        "purpose_snapshot_sha256": "0" * 64,
    }
    purpose["purpose_id"] = calculate_purpose_id(purpose)
    purpose["purpose_snapshot_sha256"] = calculate_purpose_snapshot(purpose)
    return purpose


def _validate_purpose(purpose, index, findings):
    view_ids = [item["view_id"] for item in purpose["view_bindings"]]
    if view_ids != sorted(view_ids) or len(view_ids) != len(set(view_ids)):
        findings.append(finding("EVIDENCE_REVIEW_PURPOSE_VIEW_BINDING_INVALID", f"$.proof_purposes[{index}].view_bindings", "Purpose view bindings must be unique and sorted.", "P0"))
    try:
        expected_id = calculate_purpose_id(purpose)
        expected_snapshot = calculate_purpose_snapshot(purpose)
    except (rfc8785.CanonicalizationError, TypeError, ValueError):
        findings.append(finding("EVIDENCE_REVIEW_PURPOSE_CANONICALIZATION_FAILED", f"$.proof_purposes[{index}]", "Purpose cannot be canonicalized as RFC 8785 I-JSON.", "P0"))
        return
    if purpose["purpose_id"] != expected_id:
        findings.append(finding("EVIDENCE_REVIEW_PURPOSE_ID_MISMATCH", f"$.proof_purposes[{index}].purpose_id", "Purpose ID must bind proposition and exact views.", "P0"))
    if purpose["purpose_snapshot_sha256"] != expected_snapshot:
        findings.append(finding("EVIDENCE_REVIEW_PURPOSE_SNAPSHOT_MISMATCH", f"$.proof_purposes[{index}].purpose_snapshot_sha256", "Purpose changed without a new RFC 8785 snapshot.", "P0"))


def _identified_gaps(assessment, corroboration):
    codes = {"AUTHENTICITY_UNVERIFIED", "LEGALITY_REVIEW_REQUIRED"}
    if assessment["source_status"] == "UNKNOWN":
        codes.add("SOURCE_PROVENANCE_UNKNOWN")
    if assessment["completeness_status"] != "COMPLETE_ASSERTED":
        codes.add("COMPLETENESS_NOT_ASSERTED")
    if assessment["subject_link_status"] == "UNKNOWN":
        codes.add("SUBJECT_LINK_NOT_ASSERTED")
    elif assessment["subject_link_status"] == "MISMATCH_ASSERTED":
        codes.add("SUBJECT_LINK_CONFLICT")
    if assessment["time_link_status"] == "UNKNOWN":
        codes.add("TIME_LINK_NOT_ASSERTED")
    elif assessment["time_link_status"] == "MISMATCH_ASSERTED":
        codes.add("TIME_LINK_CONFLICT")
    if assessment["integrity_status"] != "ORIGINAL_BYTES_PRESERVED_ASSERTED":
        codes.add("ORIGINAL_BYTES_PRESERVATION_NOT_ASSERTED")
    if assessment["integrity_status"] == "ALTERATION_CONCERN":
        codes.add("INTEGRITY_CONCERN_FLAGGED")
    if not corroboration:
        codes.add("NO_CORROBORATING_REVIEW_BOUND")
    risks = set(assessment["legality_risk_flags"])
    if "UNKNOWN" in risks:
        codes.add("LEGALITY_RISK_UNKNOWN")
    if risks - {"NONE_DECLARED_UNVERIFIED", "UNKNOWN"}:
        codes.add("LEGALITY_RISK_FLAGGED")
    return [{"code": code, "status": "OPEN"} for code in sorted(codes)]


def _suggestions(gaps):
    codes = sorted({GAP_TO_SUGGESTION[item["code"]] for item in gaps})
    return [
        {
            "code": code,
            "action": SUGGESTION_ACTIONS[code],
            "status": "GENERIC_ACTION_NOT_LEGAL_ADVICE",
        }
        for code in codes
    ]


def _report(record, findings):
    findings.sort(key=lambda item: (item["code"], item["path"], item["message"]))
    allowed = not findings
    return {
        "allowed": allowed,
        "allowed_scope": "LOCAL_EVIDENCE_REVIEW_STRUCTURE_INTEGRITY",
        "admissibility_determined": False,
        "authenticity_verified": False,
        "evidence_review_id": record.get("evidence_review_id"),
        "evidence_weight_assessed": False,
        "findings": findings,
        "human_identity_authenticated": False,
        "legal_review_required": True,
        "submission_ready": False,
        "validation_scope": {
            "verified": ["GAP_TO_SUGGESTION_DETERMINISM", "PROOF_PURPOSE_BINDING", "RFC8785_EVIDENCE_REVIEW_BINDING"] if allowed else [],
            "not_verified": ["ADMISSIBILITY", "AUTHENTICITY", "CORROBORATION", "EVIDENCE_WEIGHT", "HUMAN_IDENTITY", "LEGALITY", "RELEVANCE_OR_SUPPORT", "UPSTREAM_RECORD_EXISTENCE_OR_CURRENTNESS"],
        },
    }
