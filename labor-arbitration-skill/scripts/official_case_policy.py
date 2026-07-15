"""Build and validate privacy-gated official public case classification records."""

from __future__ import annotations

from datetime import datetime, timezone

from finding_model import finding
from integrity_primitives import calculate_json_snapshot, is_rfc3339_datetime
from schema_validation import (
    validate_published_frozen_source_record,
    validate_published_official_case_record,
)
from source_fetch_policy import FetchRefusal, validate_fetch_target


COLLECTOR_VERSION = "1.0.0"


class OfficialCaseRecordError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def calculate_official_case_record_snapshot(record: dict) -> str:
    return calculate_json_snapshot(
        {
            key: value
            for key, value in record.items()
            if key != "case_record_snapshot_sha256"
        }
    )


def calculate_official_case_artifact_id(
    source_binding: dict, classification: dict
) -> str:
    identity = calculate_json_snapshot(
        {
            "classification": classification,
            "source_binding": source_binding,
        }
    )
    return f"OFFICIAL-CASE-{identity[:24].upper()}"


def build_official_case_record(
    frozen_record: dict,
    *,
    dispute_categories: list[str],
    document_type: str,
    procedural_stage: str,
    jurisdiction_scope: str,
    classified_at: str | None = None,
) -> dict:
    if validate_published_frozen_source_record(frozen_record) or frozen_record.get(
        "purpose"
    ) != "OFFICIAL_CASE":
        raise OfficialCaseRecordError(
            "OFFICIAL_CASE_FROZEN_SOURCE_INVALID",
            "Case classification requires a schema-valid OFFICIAL_CASE frozen record.",
        )
    timestamp = classified_at or _utc_now()
    source_binding = {
        "fetch_id": frozen_record["fetch_id"],
        "record_snapshot_sha256": frozen_record["record_snapshot_sha256"],
        "content_sha256": frozen_record["content_sha256"],
        "publisher_code": frozen_record["publisher_code"],
        "final_url": frozen_record["final_url"],
    }
    classification = {
        "dispute_categories": sorted(dispute_categories),
        "document_type": document_type,
        "procedural_stage": procedural_stage,
        "jurisdiction_scope": jurisdiction_scope,
    }
    record = {
        "schema_version": "1.0",
        "case_artifact_id": calculate_official_case_artifact_id(
            source_binding, classification
        ),
        "collector_version": COLLECTOR_VERSION,
        "classified_at": timestamp,
        "source_binding": source_binding,
        "classification": classification,
        "classification_status": "UNVERIFIED_MANUAL_CLASSIFICATION",
        "privacy_review_status": "REQUIRED_BEFORE_ANY_REDISSEMINATION",
        "redistribution_status": "BLOCKED",
        "limitations": [
            "PUBLIC_ACCESS_DOES_NOT_REMOVE_PRIVACY_OR_REUSE_RISK",
            "CLASSIFICATION_NOT_LEGALLY_VERIFIED",
            "NO_CASE_OUTCOME_OR_HOLDING_EXTRACTED",
        ],
    }
    record["case_record_snapshot_sha256"] = calculate_official_case_record_snapshot(
        record
    )
    if validate_published_official_case_record(record):
        raise OfficialCaseRecordError(
            "OFFICIAL_CASE_RECORD_GENERATION_INVALID",
            "Generated case record does not satisfy the published schema.",
        )
    return record


def validate_official_case_record(record: dict) -> dict:
    findings = validate_published_official_case_record(record)
    if findings:
        return _report(record, findings)
    if not is_rfc3339_datetime(record["classified_at"]):
        findings.append(
            finding(
                "DATE_FORMAT_INVALID",
                "$.classified_at",
                "Classification time must be a UTC RFC 3339 timestamp ending in Z.",
                "P0",
            )
        )
    source = record["source_binding"]
    try:
        validate_fetch_target(
            source["final_url"], source["publisher_code"], "OFFICIAL_CASE"
        )
    except FetchRefusal:
        findings.append(
            finding(
                "OFFICIAL_CASE_SOURCE_NOT_ALLOWLISTED",
                "$.source_binding.final_url",
                "Case source must match a publisher registered for OFFICIAL_CASE.",
                "P0",
            )
        )
    categories = record["classification"]["dispute_categories"]
    if categories != sorted(categories):
        findings.append(
            finding(
                "OFFICIAL_CASE_CLASSIFICATION_ORDER_INVALID",
                "$.classification.dispute_categories",
                "Dispute categories must use deterministic sorted order.",
                "P0",
            )
        )
    if record["case_artifact_id"] != calculate_official_case_artifact_id(
        source, record["classification"]
    ):
        findings.append(
            finding(
                "OFFICIAL_CASE_ARTIFACT_ID_MISMATCH",
                "$.case_artifact_id",
                "Case artifact ID must be derived from the exact source and classification binding.",
                "P0",
            )
        )
    try:
        expected_snapshot = calculate_official_case_record_snapshot(record)
    except (TypeError, ValueError):
        findings.append(
            finding(
                "OFFICIAL_CASE_CANONICALIZATION_FAILED",
                "$",
                "Official case record cannot be canonicalized as RFC 8785 I-JSON.",
                "P0",
            )
        )
    else:
        if record["case_record_snapshot_sha256"] != expected_snapshot:
            findings.append(
                finding(
                    "OFFICIAL_CASE_SNAPSHOT_MISMATCH",
                    "$.case_record_snapshot_sha256",
                    "Official case record changed without a new RFC 8785 snapshot.",
                    "P0",
                )
            )
    return _report(record, findings)


def _report(record: dict, findings: list[dict]) -> dict:
    findings.sort(key=lambda item: (item["code"], item["path"], item["message"]))
    allowed = not findings
    return {
        "allowed": allowed,
        "allowed_scope": "PRIVACY_GATED_OFFICIAL_CASE_METADATA_ONLY",
        "case_artifact_id": record.get("case_artifact_id"),
        "findings": findings,
        "legal_review_required": True,
        "redistribution_allowed": False,
        "submission_ready": False,
        "validation_scope": {
            "verified": (
                [
                    "CLASSIFICATION_VOCABULARY",
                    "OFFICIAL_CASE_SOURCE_ALLOWLIST",
                    "RFC8785_CASE_RECORD_SNAPSHOT",
                ]
                if allowed
                else []
            ),
            "not_verified": [
                "CASE_HOLDING_OR_OUTCOME",
                "CLASSIFICATION_LEGAL_CORRECTNESS",
                "FROZEN_SOURCE_EXISTENCE",
                "PRIVACY_OR_REUSE_PERMISSION",
            ],
        },
    }
