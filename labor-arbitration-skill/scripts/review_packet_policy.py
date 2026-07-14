"""Deterministic policy for structured cross-validation review packets."""

from __future__ import annotations

import re

from finding_model import finding
from integrity_primitives import (
    calculate_json_snapshot,
    is_rfc3339_datetime,
    parse_calendar_date,
)
from schema_validation import validate_published_review_packet
from source_policy import validate_source_artifact


VERIFIED_CAPABILITIES = [
    "CROSS_VALIDATION_RECORD_SHAPE",
    "OFFICIAL_SOURCE_CANDIDATE_POLICY",
    "REFERENCE_INTEGRITY",
    "REVIEW_PACKET_STRUCTURE",
    "RFC8785_SNAPSHOT_BINDING",
]
UNVERIFIED_CAPABILITIES = [
    "CLAIM_LEGAL_SUFFICIENCY",
    "EXTERNAL_RULE_PACKET_EXISTENCE",
    "FORMULA_LEGAL_CORRECTNESS",
    "LEGAL_CORRECTNESS",
    "PROFESSIONAL_LEGAL_APPROVAL",
    "REVIEWER_IDENTITY_AUTHENTICATION",
    "SOURCE_CONTENT_AUTHENTICITY",
    "SOURCE_CURRENTNESS",
    "SUBMISSION_READINESS",
]
PACKET_PREFIXES = {
    "RULE_REVIEW": "REVIEW-RULE-",
    "CLAIM_REVIEW": "REVIEW-CLAIM-",
    "CALCULATOR_REVIEW": "REVIEW-CALC-",
}
SUBJECT_PATH_TOKEN = re.compile(r"\.([A-Za-z_][A-Za-z0-9_]*)|\[([0-9]+)\]")


def calculate_review_subject_snapshot(packet: dict) -> str:
    return calculate_json_snapshot(
        {
            "schema_version": packet.get("schema_version"),
            "packet_id": packet.get("packet_id"),
            "packet_type": packet.get("packet_type"),
            "jurisdiction": packet.get("jurisdiction"),
            "source_artifacts": packet.get("source_artifacts"),
            "subject": packet.get("subject"),
            "review_questions": packet.get("review_questions"),
            "limitations": packet.get("limitations"),
        }
    )


def calculate_review_packet_snapshot(packet: dict) -> str:
    return calculate_json_snapshot(
        {
            key: value
            for key, value in packet.items()
            if key != "packet_snapshot_sha256"
        }
    )


def _unique_ids(items: list, field: str, path: str, findings: list[dict]) -> set:
    identifiers = []
    for index, item in enumerate(items):
        identifier = item.get(field)
        identifiers.append(identifier)
        if identifiers.count(identifier) > 1:
            findings.append(
                finding(
                    "REVIEW_PACKET_DUPLICATE_ID",
                    f"{path}[{index}].{field}",
                    f"Duplicate review-packet identifier: {identifier}",
                    "P0",
                )
            )
    return set(identifiers)


def _validate_reference_set(
    references: list,
    known: set,
    path: str,
    findings: list[dict],
) -> None:
    for index, reference in enumerate(references):
        if reference not in known:
            findings.append(
                finding(
                    "REVIEW_PACKET_REFERENCE_UNKNOWN",
                    f"{path}[{index}]",
                    f"Unknown review-packet reference: {reference}",
                    "P0",
                )
            )


def _validate_rule_subject(packet: dict, source_ids: set, findings: list[dict]) -> None:
    subject = packet["subject"]
    _validate_reference_set(
        subject["source_ids"], source_ids, "$.subject.source_ids", findings
    )
    for index, provision in enumerate(subject["provision_references"]):
        if provision["source_id"] not in source_ids:
            findings.append(
                finding(
                    "REVIEW_PACKET_REFERENCE_UNKNOWN",
                    f"$.subject.provision_references[{index}].source_id",
                    f"Unknown source reference: {provision['source_id']}",
                    "P0",
                )
            )

    effective_from = parse_calendar_date(subject["effective_from"])
    effective_to = parse_calendar_date(subject["effective_to"])
    if effective_to is not None and (
        effective_from is None or effective_from > effective_to
    ):
        findings.append(
            finding(
                "REVIEW_PACKET_DATE_INTERVAL_INVALID",
                "$.subject.effective_to",
                "A rule candidate's effective_to must not precede effective_from.",
                "P0",
            )
        )


def _validate_claim_subject(packet: dict, findings: list[dict]) -> None:
    subject = packet["subject"]
    _unique_ids(subject["elements"], "element_id", "$.subject.elements", findings)
    dependency_ids = _validate_rule_dependencies(subject, findings)
    for index, element in enumerate(subject["elements"]):
        _validate_reference_set(
            element["rule_ids"],
            dependency_ids,
            f"$.subject.elements[{index}].rule_ids",
            findings,
        )
    _validate_reference_set(
        subject["limitation_candidate"]["rule_ids"],
        dependency_ids,
        "$.subject.limitation_candidate.rule_ids",
        findings,
    )
    claim_id = subject["claim_id"]
    compatible = set(subject["compatible_claim_ids"])
    mutually_exclusive = set(subject["mutually_exclusive_claim_ids"])
    if claim_id in compatible or claim_id in mutually_exclusive:
        findings.append(
            finding(
                "REVIEW_PACKET_CLAIM_SELF_CONFLICT",
                "$.subject",
                "A claim cannot declare itself compatible or mutually exclusive.",
                "P0",
            )
        )
    overlap = compatible & mutually_exclusive
    if overlap:
        findings.append(
            finding(
                "REVIEW_PACKET_CLAIM_RELATION_CONFLICT",
                "$.subject.mutually_exclusive_claim_ids",
                "Claims cannot be both compatible and mutually exclusive: "
                + ", ".join(sorted(overlap)),
                "P0",
            )
        )


def _validate_calculator_subject(packet: dict, findings: list[dict]) -> None:
    subject = packet["subject"]
    dependency_ids = _validate_rule_dependencies(subject, findings)
    input_ids = _unique_ids(subject["inputs"], "input_id", "$.subject.inputs", findings)
    for index, calculator_input in enumerate(subject["inputs"]):
        _validate_reference_set(
            calculator_input["rule_ids"],
            dependency_ids,
            f"$.subject.inputs[{index}].rule_ids",
            findings,
        )
    _unique_ids(
        subject["dynamic_parameters"],
        "parameter_id",
        "$.subject.dynamic_parameters",
        findings,
    )
    for index, parameter in enumerate(subject["dynamic_parameters"]):
        _validate_reference_set(
            parameter["rule_ids"],
            dependency_ids,
            f"$.subject.dynamic_parameters[{index}].rule_ids",
            findings,
        )
    _unique_ids(
        subject["test_vectors"],
        "vector_id",
        "$.subject.test_vectors",
        findings,
    )
    for index, vector in enumerate(subject["test_vectors"]):
        provided_inputs = set(vector["inputs"])
        if provided_inputs != input_ids:
            findings.append(
                finding(
                    "REVIEW_PACKET_TEST_VECTOR_INPUT_MISMATCH",
                    f"$.subject.test_vectors[{index}].inputs",
                    "Each calculator test vector must provide exactly the declared input IDs.",
                    "P0",
                )
            )


def _validate_rule_dependencies(subject: dict, findings: list[dict]) -> set:
    dependency_ids = _unique_ids(
        subject["rule_dependencies"],
        "rule_id",
        "$.subject.rule_dependencies",
        findings,
    )
    declared_rule_ids = set(subject["rule_ids"])
    if dependency_ids != declared_rule_ids:
        findings.append(
            finding(
                "REVIEW_PACKET_RULE_DEPENDENCY_MISMATCH",
                "$.subject.rule_dependencies",
                "Each declared rule ID must have exactly one version-bound rule dependency.",
                "P0",
            )
        )
    return dependency_ids


def _subject_path_exists(packet: dict, path: str) -> bool:
    current = packet
    for name, index_text in SUBJECT_PATH_TOKEN.findall(path[1:]):
        if name:
            if not isinstance(current, dict) or name not in current:
                return False
            current = current[name]
        else:
            index = int(index_text)
            if not isinstance(current, list) or index >= len(current):
                return False
            current = current[index]
    return True


def _has_unresolved_review(packet: dict) -> bool:
    return any(
        review["decision"] != "AGREE"
        or any(
            response["decision"] != "AGREE"
            for response in review["question_responses"]
        )
        for review in packet.get("cross_validation", [])
    )


def _validate_cross_validation(
    packet: dict,
    source_ids: set,
    question_ids: set,
    findings: list[dict],
) -> None:
    reviews = packet["cross_validation"]
    _unique_ids(reviews, "review_id", "$.cross_validation", findings)
    expected_subject_hash = packet["review_subject_sha256"]

    for review_index, review in enumerate(reviews):
        review_path = f"$.cross_validation[{review_index}]"
        if review["review_subject_sha256"] != expected_subject_hash:
            findings.append(
                finding(
                    "REVIEW_SUBJECT_BINDING_MISMATCH",
                    f"{review_path}.review_subject_sha256",
                    "Cross-validation must bind the current review subject snapshot.",
                    "P0",
                )
            )
        if not is_rfc3339_datetime(review["recorded_at"]):
            findings.append(
                finding(
                    "DATE_FORMAT_INVALID",
                    f"{review_path}.recorded_at",
                    "Cross-validation time must be an RFC 3339 UTC timestamp ending in Z.",
                    "P0",
                )
            )

        response_ids = _unique_ids(
            review["question_responses"],
            "question_id",
            f"{review_path}.question_responses",
            findings,
        )
        if response_ids != question_ids:
            findings.append(
                finding(
                    "REVIEW_QUESTION_COVERAGE_INCOMPLETE",
                    f"{review_path}.question_responses",
                    "Each cross-validation record must answer every review question exactly once.",
                    "P0",
                )
            )

        response_decisions = []
        for response_index, response in enumerate(review["question_responses"]):
            response_decisions.append(response["decision"])
            _validate_reference_set(
                response["basis_source_ids"],
                source_ids,
                f"{review_path}.question_responses[{response_index}].basis_source_ids",
                findings,
            )
            if response["decision"] in {"AGREE", "DISAGREE"} and not response[
                "basis_source_ids"
            ]:
                findings.append(
                    finding(
                        "REVIEW_BASIS_REQUIRED",
                        f"{review_path}.question_responses[{response_index}].basis_source_ids",
                        "Agree or disagree responses require at least one declared source basis.",
                        "P0",
                    )
                )

        if "DISAGREE" in response_decisions:
            expected_decision = "DISAGREE"
        elif "NEEDS_MORE_EVIDENCE" in response_decisions:
            expected_decision = "NEEDS_MORE_EVIDENCE"
        else:
            expected_decision = "AGREE"
        if review["decision"] != expected_decision:
            findings.append(
                finding(
                    "REVIEW_DECISION_INCONSISTENT",
                    f"{review_path}.decision",
                    "Overall review decision must equal the strict aggregate of its question responses.",
                    "P0",
                )
            )

    status = packet["packet_status"]
    any_non_agree = _has_unresolved_review(packet)
    if status == "DRAFT_FOR_CROSS_VALIDATION" and reviews:
        findings.append(
            finding(
                "REVIEW_PACKET_STATUS_INVALID",
                "$.packet_status",
                "Draft review packets cannot already contain cross-validation records.",
                "P0",
            )
        )
    elif status != "DRAFT_FOR_CROSS_VALIDATION" and not reviews:
        findings.append(
            finding(
                "REVIEW_PACKET_STATUS_INVALID",
                "$.packet_status",
                "A non-draft review-packet status requires a cross-validation record.",
                "P0",
            )
        )
    elif status == "REVISION_REQUIRED" and not any_non_agree:
        findings.append(
            finding(
                "REVIEW_PACKET_STATUS_INVALID",
                "$.packet_status",
                "REVISION_REQUIRED needs at least one disagreement or request for evidence.",
                "P0",
            )
        )
    elif status == "PENDING_INDEPENDENT_LEGAL_REVIEW" and any_non_agree:
        findings.append(
            finding(
                "REVIEW_PACKET_STATUS_INVALID",
                "$.packet_status",
                "Pending independent legal review requires all recorded cross-validation responses to agree.",
                "P0",
            )
        )


def _make_report(packet: dict, findings: list[dict]) -> dict:
    findings.sort(key=lambda item: (item["code"], item["path"], item["message"]))
    allowed = not findings
    status = packet.get("packet_status")
    if status == "DRAFT_FOR_CROSS_VALIDATION":
        next_required_state = "PROJECT_CROSS_VALIDATION"
    elif status == "REVISION_REQUIRED" or _has_unresolved_review(packet):
        next_required_state = "PACKET_REVISION"
    else:
        next_required_state = "INDEPENDENT_LEGAL_REVIEW"
    return {
        "allowed": allowed,
        "allowed_scope": "STRUCTURAL_CROSS_VALIDATION_ONLY",
        "cross_validation_effect": "RECORD_ONLY_NO_LEGAL_APPROVAL",
        "findings": findings,
        "legal_review_required": True,
        "next_required_state": next_required_state,
        "packet_id": packet.get("packet_id"),
        "packet_status": status,
        "packet_type": packet.get("packet_type"),
        "schema_version": packet.get("schema_version"),
        "submission_ready": False,
        "validation_scope": {
            "verified": VERIFIED_CAPABILITIES if allowed else [],
            "not_verified": UNVERIFIED_CAPABILITIES,
        },
    }


def validate_review_packet(packet: dict) -> dict:
    findings = validate_published_review_packet(packet)
    if findings:
        return _make_report(packet, findings)

    if not is_rfc3339_datetime(packet["generated_at"]):
        findings.append(
            finding(
                "DATE_FORMAT_INVALID",
                "$.generated_at",
                "Review packet generation time must be an RFC 3339 UTC timestamp ending in Z.",
                "P0",
            )
        )

    source_ids = _unique_ids(
        packet["source_artifacts"],
        "source_id",
        "$.source_artifacts",
        findings,
    )
    for index, source in enumerate(packet["source_artifacts"]):
        source_findings = validate_source_artifact(source, index, packet)
        for source_finding in source_findings:
            source_finding["path"] = "$." + source_finding["path"]
        findings.extend(source_findings)

    question_ids = _unique_ids(
        packet["review_questions"],
        "question_id",
        "$.review_questions",
        findings,
    )
    for question_index, question in enumerate(packet["review_questions"]):
        for path_index, subject_path in enumerate(question["subject_paths"]):
            if not _subject_path_exists(packet, subject_path):
                findings.append(
                    finding(
                        "REVIEW_QUESTION_SUBJECT_PATH_UNKNOWN",
                        f"$.review_questions[{question_index}].subject_paths[{path_index}]",
                        "Review questions must point to an existing field in the current subject.",
                        "P0",
                    )
                )

    expected_prefix = PACKET_PREFIXES[packet["packet_type"]]
    if not packet["packet_id"].startswith(expected_prefix):
        findings.append(
            finding(
                "REVIEW_PACKET_TYPE_ID_MISMATCH",
                "$.packet_id",
                f"{packet['packet_type']} packet IDs must start with {expected_prefix}",
                "P0",
            )
        )

    if packet["packet_type"] == "RULE_REVIEW":
        _validate_rule_subject(packet, source_ids, findings)
    elif packet["packet_type"] == "CLAIM_REVIEW":
        _validate_claim_subject(packet, findings)
    else:
        _validate_calculator_subject(packet, findings)

    _validate_cross_validation(packet, source_ids, question_ids, findings)

    try:
        expected_subject_hash = calculate_review_subject_snapshot(packet)
        expected_packet_hash = calculate_review_packet_snapshot(packet)
    except (TypeError, ValueError):
        findings.append(
            finding(
                "REVIEW_PACKET_CANONICALIZATION_FAILED",
                "$",
                "Review packet cannot be canonicalized as RFC 8785 I-JSON.",
                "P0",
            )
        )
    else:
        if packet["review_subject_sha256"] != expected_subject_hash:
            findings.append(
                finding(
                    "REVIEW_SUBJECT_SNAPSHOT_MISMATCH",
                    "$.review_subject_sha256",
                    "The review subject or its declared sources and questions changed.",
                    "P0",
                )
            )
        if packet["packet_snapshot_sha256"] != expected_packet_hash:
            findings.append(
                finding(
                    "REVIEW_PACKET_SNAPSHOT_MISMATCH",
                    "$.packet_snapshot_sha256",
                    "The complete review packet changed without a new RFC 8785 snapshot.",
                    "P0",
                )
            )

    return _make_report(packet, findings)
