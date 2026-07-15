"""Integrity policy for content-bound parser extraction records."""

from __future__ import annotations

import hashlib
import rfc8785

from finding_model import finding
from integrity_primitives import calculate_json_snapshot, is_rfc3339_datetime
from schema_validation import validate_published_parser_extraction_record


def calculate_parser_record_snapshot(record: dict) -> str:
    return calculate_json_snapshot(
        {key: value for key, value in record.items() if key != "record_snapshot_sha256"}
    )


def calculate_anchor_id(binding: dict, kind: str, coordinate: str, text_sha256: str) -> str:
    identity = calculate_json_snapshot(
        {
            "content_sha256": binding["content_sha256"],
            "coordinate": coordinate,
            "kind": kind,
            "raw_id": binding["raw_id"],
            "text_sha256": text_sha256,
            "workspace_id": binding["workspace_id"],
        }
    )
    return f"ANCHOR-{identity[:24].upper()}"


def calculate_parse_id(record: dict) -> str:
    identity = calculate_json_snapshot(
        {
            "anchors": record["anchors"],
            "detected_format": record["detected_format"],
            "parser": record["parser"],
            "security": record["security"],
            "status": record["status"],
            "warnings": record["warnings"],
            "workspace_binding": record["workspace_binding"],
        }
    )
    return f"PARSE-{identity[:24].upper()}"


def validate_parser_extraction_record(record: dict) -> dict:
    findings = validate_published_parser_extraction_record(record)
    if findings:
        return _report(record, findings)
    if not is_rfc3339_datetime(record["created_at"]):
        findings.append(
            finding(
                "DATE_FORMAT_INVALID",
                "$.created_at",
                "Parser record time must be a UTC RFC 3339 timestamp ending in Z.",
                "P0",
            )
        )
    anchor_ids = []
    coordinates = []
    for index, anchor in enumerate(record["anchors"]):
        text_sha256 = hashlib.sha256(anchor["text"].encode("utf-8")).hexdigest()
        if anchor["text_sha256"] != text_sha256:
            findings.append(
                finding(
                    "PARSER_ANCHOR_TEXT_HASH_MISMATCH",
                    f"$.anchors[{index}].text_sha256",
                    "Anchor text hash must bind the exact extracted UTF-8 text.",
                    "P0",
                )
            )
        expected_id = calculate_anchor_id(
            record["workspace_binding"],
            anchor["kind"],
            anchor["coordinate"],
            text_sha256,
        )
        if anchor["anchor_id"] != expected_id:
            findings.append(
                finding(
                    "PARSER_ANCHOR_ID_MISMATCH",
                    f"$.anchors[{index}].anchor_id",
                    "Anchor ID must bind workspace, object, coordinate, kind, and exact text.",
                    "P0",
                )
            )
        anchor_ids.append(anchor["anchor_id"])
        coordinates.append((anchor["kind"], anchor["coordinate"]))
    if len(anchor_ids) != len(set(anchor_ids)) or len(coordinates) != len(set(coordinates)):
        findings.append(
            finding(
                "PARSER_ANCHOR_IDENTITY_DUPLICATE",
                "$.anchors",
                "Anchor IDs and kind/coordinate pairs must be unique.",
                "P0",
            )
        )
    expected_counts = {
        "anchor_count": len(record["anchors"]),
        "extracted_characters": sum(len(item["text"]) for item in record["anchors"]),
    }
    for field, expected in expected_counts.items():
        if record["limits"][field] != expected:
            findings.append(
                finding(
                    "PARSER_LIMIT_SUMMARY_MISMATCH",
                    f"$.limits.{field}",
                    "Parser output counts must match the exact anchor collection.",
                    "P0",
                )
            )
    refused = record["status"] == "REFUSED"
    if refused != (record["security"]["refusal_code"] is not None):
        findings.append(
            finding(
                "PARSER_REFUSAL_STATUS_MISMATCH",
                "$.status",
                "Refused status and refusal code must agree.",
                "P0",
            )
        )
    if refused and record["anchors"]:
        findings.append(
            finding(
                "PARSER_REFUSAL_HAS_ANCHORS",
                "$.anchors",
                "Refused parser results must not publish partial anchors.",
                "P0",
            )
        )
    if not refused and record["parser"]["adapter"] == "UNSUPPORTED":
        findings.append(
            finding(
                "PARSER_ADAPTER_STATUS_MISMATCH",
                "$.parser.adapter",
                "A successful result must name a supported adapter.",
                "P0",
            )
        )
    try:
        expected_parse_id = calculate_parse_id(record)
        expected_snapshot = calculate_parser_record_snapshot(record)
    except (rfc8785.CanonicalizationError, TypeError, ValueError):
        findings.append(
            finding(
                "PARSER_RECORD_CANONICALIZATION_FAILED",
                "$",
                "Parser record cannot be canonicalized as RFC 8785 I-JSON.",
                "P0",
            )
        )
    else:
        if record["parse_id"] != expected_parse_id:
            findings.append(
                finding(
                    "PARSER_PARSE_ID_MISMATCH",
                    "$.parse_id",
                    "Parse ID must bind the exact extraction result and source binding.",
                    "P0",
                )
            )
        if record["record_snapshot_sha256"] != expected_snapshot:
            findings.append(
                finding(
                    "PARSER_RECORD_SNAPSHOT_MISMATCH",
                    "$.record_snapshot_sha256",
                    "Parser record changed without a new RFC 8785 snapshot.",
                    "P0",
                )
            )
    return _report(record, findings)


def _report(record: dict, findings: list[dict]) -> dict:
    findings.sort(key=lambda item: (item["code"], item["path"], item["message"]))
    allowed = not findings
    return {
        "allowed": allowed,
        "allowed_scope": "LOCAL_EXTRACTION_CANDIDATE_INTEGRITY",
        "findings": findings,
        "human_anchor_confirmation_required": True,
        "legal_review_required": True,
        "parse_id": record.get("parse_id"),
        "submission_ready": False,
        "validation_scope": {
            "verified": (
                [
                    "ANCHOR_CONTENT_BINDING",
                    "PARSER_RECORD_RFC8785_SNAPSHOT",
                    "WORKSPACE_OBJECT_BINDING",
                ]
                if allowed
                else []
            ),
            "not_verified": [
                "EVIDENCE_AUTHENTICITY",
                "LEGAL_RELEVANCE_OR_SUPPORT",
                "OCR_CORRECTNESS",
                "OS_LEVEL_SANDBOX",
                "VISUAL_PAGE_OR_CELL_RENDERING",
            ],
        },
    }
