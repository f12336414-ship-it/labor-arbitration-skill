#!/usr/bin/env python3
"""Validate deterministic promotion gates for a labor-arbitration case package."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

import jsonschema


MACHINE_GATED_STATES = {
    "REFERENCE_INTEGRITY_VALIDATED",
}
ALLOWED_STATES = {
    "INTERNAL_ANALYSIS",
    "DRAFT",
    "REVIEW_REQUIRED",
    "MACHINE_VALIDATED_CANDIDATE",
    "HUMAN_APPROVED_FOR_SUBMISSION",
    "REFERENCE_INTEGRITY_VALIDATED",
    "REVALIDATION_REQUIRED",
}
SUPPORTED_SCHEMA_VERSIONS = {"1.2"}
NORMATIVE_DOCUMENT_TYPES = {
    "CONSTITUTION",
    "LAW",
    "ADMINISTRATIVE_REGULATION",
    "JUDICIAL_INTERPRETATION",
    "LOCAL_REGULATION",
    "DEPARTMENT_RULE",
    "LOCAL_GOVERNMENT_RULE",
    "OFFICIAL_NORMATIVE_DOCUMENT",
}
FORMAL_BINDING_STATUSES = {"BINDING", "GENERALLY_APPLICABLE"}
ALLOWED_FACT_STATUSES = {
    "USER_ASSERTED",
    "EVIDENCE_LINKED",
    "DISPUTED",
    "UNKNOWN",
}
IDENTIFIER_FIELDS = {
    "adversarial_findings": "finding_id",
    "approvals": "approval_id",
    "raw_files": "raw_id",
    "source_artifacts": "source_id",
    "legal_rules": "rule_id",
    "evidence": "evidence_id",
    "facts": "fact_id",
    "claims": "claim_id",
    "calculations": "calculation_id",
    "conflicts": "conflict_id",
    "statements": "statement_id",
}
REQUIRED_SOURCE_FIELDS = {
    "source_id",
    "canonical_url",
    "publisher",
    "document_title",
    "document_type",
    "legal_hierarchy",
    "binding_status",
    "jurisdiction",
    "retrieved_at",
    "content_sha256",
    "content_hash_status",
    "publisher_code",
}
REQUIRED_CALCULATION_FIELDS = {
    "calculation_id",
    "calculator_version",
    "formula_id",
    "status",
    "inputs",
    "result",
    "rounding_policy",
    "intermediate_steps",
    "assumptions",
}
FORMAL_COLLECTIONS = tuple(
    sorted(set(IDENTIFIER_FIELDS) | {"adversarial_findings", "approvals", "conflicts"})
)
MACHINE_REQUIRED_FIELDS = {
    "schema_version",
    "requested_state",
    "jurisdiction",
    "dependency_snapshot_sha256",
    "document_snapshot_sha256",
    "intake_manifest_sha256",
    "package_snapshot_sha256",
    "privacy_review",
    *FORMAL_COLLECTIONS,
}
NESTED_ARRAY_FIELDS = {
    "facts": ("evidence_ids",),
    "legal_rules": ("supersedes",),
    "calculations": ("inputs", "intermediate_steps", "assumptions"),
    "statements": ("fact_ids", "rule_ids", "calculation_ids"),
}
MAX_CASE_PACKAGE_BYTES = 10 * 1024 * 1024
DECIMAL_TEXT_PATTERN = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
INTEGRITY_SEMANTICS = (
    "Hashes and sizes describe bytes read from stable opened file descriptors during "
    "ingestion; they do not prove authenticity, semantic meaning, or later immutability."
)
ALLOWED_ASSERTION_STATUSES = {"ASSERTED", "CONDITIONALLY_ASSERTED"}
ALLOWED_PROOF_STATUSES = {
    "EVIDENCE_LINKED_UNVERIFIED",
    "EMPLOYER_CONTROLLED_MISSING",
    "MISSING",
    "DISPUTED",
}
ALLOWED_BURDEN_STAGES = {
    "APPLICANT_INITIAL",
    "EMPLOYER_PRODUCTION",
    "BURDEN_SHIFTED",
    "TRIBUNAL_ASSESSMENT",
}
ALLOWED_EVIDENCE_CONTROLLERS = {
    "APPLICANT",
    "EMPLOYER",
    "THIRD_PARTY",
    "SHARED",
    "UNKNOWN",
}
CASE_PACKAGE_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "references" / "case-package.schema.json"
)
VERIFIED_REFERENCE_CAPABILITIES = [
    "ARITHMETIC_RECOMPUTATION",
    "PACKAGE_STRUCTURE",
    "REFERENCE_INTEGRITY",
]
UNVERIFIED_LEGAL_CAPABILITIES = [
    "BEIJING_RULE_PACK_COMPLETENESS",
    "CLAIM_ELEMENT_LEGAL_SUFFICIENCY",
    "DOCUMENT_SUBMISSION_READINESS",
    "EMPLOYER_IDENTITY_VERIFICATION",
    "EVIDENCE_AUTHENTICITY",
    "EVIDENCE_SEMANTIC_SUPPORT",
    "HUMAN_IDENTITY_AUTHENTICATION",
    "JURISDICTION_DETERMINATION",
    "LEGAL_APPLICABILITY",
    "LEGAL_SOURCE_CURRENTNESS",
    "LIMITATION_COMPUTATION",
    "PROFESSIONAL_CLAIM_CALCULATION",
]
DEPRECATED_OUTPUT_STATES = {
    "HUMAN_APPROVED_FOR_SUBMISSION",
    "MACHINE_VALIDATED_CANDIDATE",
}
OFFICIAL_SOURCE_CANDIDATE_HOSTS = {
    "BEIJING_GOVERNMENT": {"www.beijing.gov.cn"},
    "BEIJING_HRSS": {"rsj.beijing.gov.cn", "fuwu.rsj.beijing.gov.cn"},
    "MOHRSS": {"www.mohrss.gov.cn"},
    "NATIONAL_LAWS_REGULATIONS_DATABASE": {"flk.npc.gov.cn"},
    "STATE_COUNCIL": {"www.gov.cn"},
    "SUPREME_PEOPLES_COURT": {"www.court.gov.cn"},
}


class DuplicateKeyError(ValueError):
    """Raised when a JSON object repeats a key."""


class InvalidJsonConstantError(ValueError):
    """Raised for NaN and Infinity, which are outside standard JSON."""


class InputTooLargeError(ValueError):
    """Raised when a bounded input exceeds its byte limit."""


class InputChangedError(OSError):
    """Raised when an input changes while it is being read."""


def finding(code: str, path: str, message: str, severity: str = "P1") -> dict:
    return {
        "code": code,
        "message": message,
        "path": path,
        "severity": severity,
    }


def format_schema_path(path_parts) -> str:
    path = "$"
    for part in path_parts:
        path += f"[{part}]" if isinstance(part, int) else f".{part}"
    return path


def validate_published_schema(package: dict) -> list[dict]:
    try:
        schema = json.loads(CASE_PACKAGE_SCHEMA_PATH.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
        validator = jsonschema.Draft202012Validator(schema)
    except (OSError, UnicodeError, json.JSONDecodeError, jsonschema.SchemaError):
        return [
            finding(
                "VALIDATOR_SCHEMA_UNAVAILABLE",
                "$",
                "The bundled v1.2 JSON Schema is unavailable or invalid.",
                "P0",
            )
        ]

    findings = []
    seen_paths = set()
    errors = sorted(
        validator.iter_errors(package),
        key=lambda error: (tuple(str(part) for part in error.absolute_path), error.message),
    )
    for error in errors:
        path = format_schema_path(error.absolute_path)
        if path in seen_paths:
            continue
        seen_paths.add(path)
        findings.append(
            finding(
                "SCHEMA_VALIDATION_ERROR",
                path,
                "Package content does not conform to the published v1.2 JSON Schema.",
                "P0",
            )
        )
    return findings


def calculate_snapshot(package: dict) -> str:
    snapshot_content = {
        key: value
        for key, value in package.items()
        if key not in {"requested_state", "package_snapshot_sha256", "approvals"}
    }
    encoded = json.dumps(
        snapshot_content,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def calculate_json_snapshot(value) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def calculate_dependency_snapshot(package: dict) -> str:
    return calculate_json_snapshot(
        {
            "source_artifacts": package.get("source_artifacts", []),
            "legal_rules": package.get("legal_rules", []),
            "calculators": [
                {
                    "calculator_version": calculation.get("calculator_version"),
                    "formula_id": calculation.get("formula_id"),
                    "rounding_policy": calculation.get("rounding_policy"),
                }
                for calculation in package.get("calculations", [])
            ],
        }
    )


def calculate_document_snapshot(package: dict) -> str:
    return calculate_json_snapshot({"statements": package.get("statements", [])})


def is_sha256(value) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value.lower())
    )


def is_decimal_text(value) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= 100
        and DECIMAL_TEXT_PATTERN.fullmatch(value) is not None
    )


def recompute_sum_decimal_inputs(calculation: dict):
    if (
        calculation.get("formula_id") != "SUM_DECIMAL_INPUTS_V1"
        or calculation.get("calculator_version") != "1.0.0"
        or calculation.get("rounding_policy") != "ROUND_HALF_UP_2"
    ):
        return None
    running_total = Decimal("0")
    intermediate_steps = []
    try:
        for calculation_input in calculation.get("inputs", []):
            value = calculation_input.get("value")
            if not is_decimal_text(value):
                return None
            running_total += Decimal(value)
            intermediate_steps.append(
                format(
                    running_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                    ".2f",
                )
            )
        result = format(
            running_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            ".2f",
        )
    except InvalidOperation:
        return None
    return result, intermediate_steps


def is_safe_relative_path(value) -> bool:
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts and value != "."


def source_candidate_host_is_allowlisted(source: dict) -> bool:
    publisher_code = source.get("publisher_code")
    allowed_hosts = OFFICIAL_SOURCE_CANDIDATE_HOSTS.get(publisher_code, set())
    canonical_url = source.get("canonical_url")
    if not isinstance(canonical_url, str):
        return False
    try:
        parsed = urlsplit(canonical_url)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme.lower() == "https"
        and parsed.hostname is not None
        and parsed.hostname.lower() in allowed_hosts
        and parsed.username is None
        and parsed.password is None
        and port in {None, 443}
        and not parsed.fragment
    )


def validate_source_artifact(source: dict, source_index: int, package: dict) -> list[dict]:
    findings = []
    path = f"source_artifacts[{source_index}]"
    missing_source_fields = sorted(
        field for field in REQUIRED_SOURCE_FIELDS if not source.get(field)
    )
    if missing_source_fields:
        findings.append(
            finding(
                "SOURCE_METADATA_INCOMPLETE",
                path,
                "Missing source metadata: " + ", ".join(missing_source_fields),
            )
        )
    if not is_sha256(source.get("content_sha256")):
        findings.append(
            finding(
                "SOURCE_CONTENT_HASH_INVALID",
                f"{path}.content_sha256",
                "Source candidates require a declared SHA-256-shaped content hash.",
            )
        )
    canonical_url = source.get("canonical_url")
    if not isinstance(canonical_url, str) or not canonical_url.lower().startswith(
        "https://"
    ):
        findings.append(
            finding(
                "SOURCE_URL_UNSAFE",
                f"{path}.canonical_url",
                "Source candidates require a canonical HTTPS URL.",
            )
        )
    if (
        not source_candidate_host_is_allowlisted(source)
        or source.get("content_hash_status") != "DECLARED_UNVERIFIED"
    ):
        findings.append(
            finding(
                "SOURCE_HOST_NOT_ALLOWLISTED",
                f"{path}.canonical_url",
                "The URL must match the declared publisher's official-source candidate allowlist and the hash must remain DECLARED_UNVERIFIED; this check does not verify page content or legal authority.",
                "P0",
            )
        )
    if (
        source.get("document_type") not in NORMATIVE_DOCUMENT_TYPES
        or source.get("binding_status") not in FORMAL_BINDING_STATUSES
    ):
        findings.append(
            finding(
                "SOURCE_NOT_NORMATIVE",
                f"{path}.document_type",
                "The declared source classification is outside the narrow normative candidate set; this check does not verify legal authority.",
            )
        )
    if source.get("jurisdiction") != package.get("jurisdiction"):
        findings.append(
            finding(
                "SOURCE_JURISDICTION_MISMATCH",
                f"{path}.jurisdiction",
                "A source candidate's declared jurisdiction must match the package declaration.",
            )
        )
    return findings


def reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(key)
        result[key] = value
    return result


def reject_json_constant(value):
    raise InvalidJsonConstantError(value)


def emit_input_error(code: str, message: str) -> None:
    print(
        json.dumps(
            {"error": {"code": code, "message": message}},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


def input_metadata_signature(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def read_stable_utf8(path: Path, max_bytes: int) -> str:
    with path.open("rb") as source:
        before = os.fstat(source.fileno())
        if before.st_size > max_bytes:
            raise InputTooLargeError
        payload = source.read(max_bytes + 1)
        after = os.fstat(source.fileno())
    if len(payload) > max_bytes:
        raise InputTooLargeError
    if len(payload) != before.st_size or input_metadata_signature(
        before
    ) != input_metadata_signature(after):
        raise InputChangedError("Input changed while it was being read.")
    try:
        path_after = os.stat(path)
    except OSError as error:
        raise InputChangedError("Input path changed while it was being read.") from error
    if input_metadata_signature(path_after) != input_metadata_signature(after):
        raise InputChangedError("Input path changed while it was being read.")
    return payload.decode("utf-8")


def make_report(package: dict, findings: list[dict]) -> dict:
    findings.sort(key=lambda item: (item["code"], item["path"], item["message"]))
    allowed = not findings
    reference_scope_passed = (
        allowed and package.get("requested_state") == "REFERENCE_INTEGRITY_VALIDATED"
    )
    return {
        "allowed": allowed,
        "allowed_scope": "REQUESTED_TECHNICAL_STATE_ONLY",
        "findings": findings,
        "highest_allowed_state": (
            package.get("requested_state", "INTERNAL_ANALYSIS")
            if allowed
            else "REVIEW_REQUIRED"
        ),
        "requested_state": package.get("requested_state"),
        "schema_version": package.get("schema_version"),
        "legal_review_required": True,
        "next_required_state": "PENDING_LEGAL_REVIEW",
        "replacement_state": (
            "REFERENCE_INTEGRITY_VALIDATED"
            if package.get("requested_state") in DEPRECATED_OUTPUT_STATES
            else None
        ),
        "validation_scope": {
            "verified": VERIFIED_REFERENCE_CAPABILITIES if reference_scope_passed else [],
            "not_verified": UNVERIFIED_LEGAL_CAPABILITIES,
        },
    }


def validate_machine_structure(package: dict) -> tuple[list[dict], bool]:
    """Return structural findings and whether semantic validation is safe."""
    findings = []
    safe = True
    for field in sorted(MACHINE_REQUIRED_FIELDS):
        if field not in package:
            findings.append(
                finding(
                    "PACKAGE_FIELD_MISSING",
                    field,
                    f"Reference-integrity validation requires package field: {field}",
                )
            )

    for collection_name in FORMAL_COLLECTIONS:
        if collection_name not in package:
            continue
        collection = package[collection_name]
        if not isinstance(collection, list):
            findings.append(
                finding(
                    "COLLECTION_NOT_ARRAY",
                    collection_name,
                    "A formal package collection must be a JSON array.",
                )
            )
            safe = False
            continue
        for item_index, item in enumerate(collection):
            if not isinstance(item, dict):
                findings.append(
                    finding(
                        "RECORD_NOT_OBJECT",
                        f"{collection_name}[{item_index}]",
                        "A formal package record must be a JSON object.",
                    )
                )
                safe = False

    if not isinstance(package.get("jurisdiction"), dict):
        findings.append(
            finding(
                "FIELD_NOT_OBJECT",
                "jurisdiction",
                "Jurisdiction must be a JSON object.",
            )
        )
        safe = False
    if not isinstance(package.get("privacy_review"), dict):
        findings.append(
            finding(
                "FIELD_NOT_OBJECT",
                "privacy_review",
                "Privacy review must be a JSON object.",
            )
        )
        safe = False

    if not safe:
        return findings, False

    for collection_name, field_names in NESTED_ARRAY_FIELDS.items():
        for item_index, item in enumerate(package.get(collection_name, [])):
            for field_name in field_names:
                if field_name in item and not isinstance(item.get(field_name), list):
                    findings.append(
                        finding(
                            "FIELD_NOT_ARRAY",
                            f"{collection_name}[{item_index}].{field_name}",
                            "A formal reference or calculation field must be a JSON array.",
                        )
                    )
                    safe = False

    for claim_index, claim in enumerate(package.get("claims", [])):
        if "calculation_ids" in claim and not isinstance(
            claim.get("calculation_ids"), list
        ):
            findings.append(
                finding(
                    "FIELD_NOT_ARRAY",
                    f"claims[{claim_index}].calculation_ids",
                    "Claim calculation references must be a JSON array.",
                )
            )
            safe = False
        elements = claim.get("elements")
        if not isinstance(elements, list):
            findings.append(
                finding(
                    "FIELD_NOT_ARRAY",
                    f"claims[{claim_index}].elements",
                    "Claim elements must be a JSON array.",
                )
            )
            safe = False
            continue
        for element_index, element in enumerate(elements):
            if not isinstance(element, dict):
                findings.append(
                    finding(
                        "RECORD_NOT_OBJECT",
                        f"claims[{claim_index}].elements[{element_index}]",
                        "A claim element must be a JSON object.",
                    )
                )
                safe = False
                continue
            for field_name in ("fact_ids", "evidence_ids", "rule_ids"):
                if field_name in element and not isinstance(
                    element.get(field_name), list
                ):
                    findings.append(
                        finding(
                            "FIELD_NOT_ARRAY",
                            f"claims[{claim_index}].elements[{element_index}].{field_name}",
                            "Claim-element references must be a JSON array.",
                        )
                    )
                    safe = False
        limitation = claim.get("limitation_analysis")
        if isinstance(limitation, dict):
            for field_name in (
                "interruption_events",
                "suspension_intervals",
                "evidence_ids",
            ):
                if field_name in limitation and not isinstance(
                    limitation.get(field_name), list
                ):
                    findings.append(
                        finding(
                            "FIELD_NOT_ARRAY",
                            f"claims[{claim_index}].limitation_analysis.{field_name}",
                            "Limitation event and evidence fields must be JSON arrays.",
                        )
                    )
                    safe = False
    for calculation_index, calculation in enumerate(package.get("calculations", [])):
        inputs = calculation.get("inputs")
        if not isinstance(inputs, list):
            continue
        for input_index, calculation_input in enumerate(inputs):
            if not isinstance(calculation_input, dict):
                findings.append(
                    finding(
                        "RECORD_NOT_OBJECT",
                        f"calculations[{calculation_index}].inputs[{input_index}]",
                        "A calculation input must be a JSON object.",
                    )
                )
                safe = False
    return findings, safe


def validate_intake_manifest(package: dict, intake_manifest) -> list[dict]:
    findings = []
    if intake_manifest is None:
        return [
            finding(
                "INTAKE_MANIFEST_REQUIRED",
                "intake_manifest",
                "Reference-integrity validation requires the independently generated intake manifest.",
            )
        ]
    if not isinstance(intake_manifest, dict):
        return [
            finding(
                "INTAKE_MANIFEST_INVALID",
                "intake_manifest",
                "The intake-manifest JSON root must be an object.",
            )
        ]
    manifest_files = intake_manifest.get("files")
    if (
        intake_manifest.get("schema_version") != "1.2"
        or intake_manifest.get("integrity_semantics") != INTEGRITY_SEMANTICS
        or not isinstance(manifest_files, list)
        or any(not isinstance(item, dict) for item in manifest_files)
        or any(
            not isinstance(item.get("size_bytes"), int)
            or isinstance(item.get("size_bytes"), bool)
            or item.get("size_bytes") < 0
            for item in manifest_files
            if isinstance(item, dict)
        )
    ):
        return [
            finding(
                "INTAKE_MANIFEST_INVALID",
                "intake_manifest",
                "The intake manifest has an unsupported schema or malformed records.",
            )
        ]
    scan_policy = intake_manifest.get("scan_policy")
    summary = intake_manifest.get("summary")
    integer_limits = ("max_depth", "max_file_bytes", "max_files", "max_total_bytes")
    policy_valid = (
        isinstance(scan_policy, dict)
        and all(
            isinstance(scan_policy.get(field), int)
            and not isinstance(scan_policy.get(field), bool)
            and scan_policy.get(field) >= (0 if field == "max_depth" else 1)
            for field in integer_limits
        )
        and isinstance(scan_policy.get("timeout_seconds"), (int, float))
        and not isinstance(scan_policy.get("timeout_seconds"), bool)
        and scan_policy.get("timeout_seconds") > 0
    )
    expected_summary = {
        "file_count": len(manifest_files),
        "total_bytes": sum(item.get("size_bytes", 0) for item in manifest_files),
    }
    if not policy_valid or summary != expected_summary:
        findings.append(
            finding(
                "INTAKE_SCAN_POLICY_INVALID",
                "intake_manifest.scan_policy",
                "Version 1.2 manifests require bounded scan policy and exact file-count/byte summaries.",
                "P0",
            )
        )
    if package.get("intake_manifest_sha256") != calculate_json_snapshot(
        intake_manifest
    ):
        findings.append(
            finding(
                "INTAKE_MANIFEST_SNAPSHOT_MISMATCH",
                "intake_manifest_sha256",
                "The supplied intake manifest does not match the locked manifest snapshot.",
            )
        )
    if package.get("raw_files") != manifest_files:
        findings.append(
            finding(
                "RAW_FILES_MANIFEST_MISMATCH",
                "raw_files",
                "Case-package raw-file records must exactly match the intake manifest.",
            )
        )
    return findings


def validate_case_package(package: dict, intake_manifest=None) -> dict:
    findings = []
    requires_machine_gates = package.get("requested_state") in MACHINE_GATED_STATES

    if package.get("requested_state") not in ALLOWED_STATES:
        findings.append(
            finding(
                "OUTPUT_STATE_UNKNOWN",
                "requested_state",
                "Requested output state is not part of the reliability state machine.",
            )
        )
    if package.get("requested_state") in DEPRECATED_OUTPUT_STATES:
        findings.append(
            finding(
                "OUTPUT_STATE_DEPRECATED",
                "requested_state",
                "This state overstates what deterministic validation can prove; use REFERENCE_INTEGRITY_VALIDATED and obtain external legal review.",
                "P0",
            )
        )
    if package.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS:
        findings.append(
            finding(
                "SCHEMA_VERSION_UNSUPPORTED",
                "schema_version",
                "Case-package schema version is not supported by this validator.",
            )
        )
    findings.extend(validate_published_schema(package))

    if requires_machine_gates:
        structure_findings, structurally_safe = validate_machine_structure(package)
        findings.extend(structure_findings)
        if not structurally_safe:
            if package.get("package_snapshot_sha256") != calculate_snapshot(package):
                findings.append(
                    finding(
                        "PACKAGE_SNAPSHOT_MISMATCH",
                        "package_snapshot_sha256",
                        "The locked package snapshot does not match the package content.",
                    )
                )
            return make_report(package, findings)
        findings.extend(validate_intake_manifest(package, intake_manifest))

    known_source_ids = {
        source.get("source_id")
        for source in package.get("source_artifacts", [])
        if source.get("source_id")
    }
    known_rule_ids = {
        rule.get("rule_id")
        for rule in package.get("legal_rules", [])
        if rule.get("rule_id")
    }
    known_calculation_ids = {
        calculation.get("calculation_id")
        for calculation in package.get("calculations", [])
        if calculation.get("calculation_id")
    }
    known_fact_ids = {
        fact.get("fact_id") for fact in package.get("facts", []) if fact.get("fact_id")
    }
    known_evidence_ids = {
        evidence.get("evidence_id")
        for evidence in package.get("evidence", [])
        if evidence.get("evidence_id")
    }
    known_raw_ids = {
        raw_file.get("raw_id")
        for raw_file in package.get("raw_files", [])
        if raw_file.get("raw_id")
    }

    if requires_machine_gates:
        for collection_name, id_field in IDENTIFIER_FIELDS.items():
            seen_ids = set()
            for item_index, item in enumerate(package.get(collection_name, [])):
                item_id = item.get(id_field)
                if not item_id:
                    findings.append(
                        finding(
                            "IDENTIFIER_MISSING",
                            f"{collection_name}[{item_index}].{id_field}",
                            f"Formal record requires identifier field: {id_field}",
                        )
                    )
                if item_id and item_id in seen_ids:
                    findings.append(
                        finding(
                            "IDENTIFIER_DUPLICATE",
                            f"{collection_name}[{item_index}].{id_field}",
                            f"Duplicate {id_field}: {item_id}",
                        )
                    )
                if item_id:
                    seen_ids.add(item_id)

        for hash_field in (
            "dependency_snapshot_sha256",
            "document_snapshot_sha256",
            "package_snapshot_sha256",
        ):
            if hash_field in package and not is_sha256(package.get(hash_field)):
                findings.append(
                    finding(
                        "SNAPSHOT_HASH_INVALID",
                        hash_field,
                        "Snapshot hashes must be 64-character SHA-256 hex strings.",
                    )
                )

        for collection_name in ("claims", "statements"):
            if not package.get(collection_name):
                findings.append(
                    finding(
                        "FORMAL_CONTENT_EMPTY",
                        collection_name,
                        "A reference-integrity package requires formal claims and statements.",
                    )
                )

        for raw_index, raw_file in enumerate(package.get("raw_files", [])):
            size_bytes = raw_file.get("size_bytes")
            expected_integrity_status = "INGESTION_BYTES_OBSERVED"
            if (
                not is_safe_relative_path(raw_file.get("relative_path"))
                or not isinstance(raw_file.get("extension"), str)
                or not isinstance(size_bytes, int)
                or isinstance(size_bytes, bool)
                or size_bytes < 0
                or not is_sha256(raw_file.get("sha256"))
                or raw_file.get("integrity_status") != expected_integrity_status
            ):
                findings.append(
                    finding(
                        "RAW_FILE_METADATA_INVALID",
                        f"raw_files[{raw_index}]",
                        "Raw-file records require a relative path and SHA-256 checksum.",
                    )
                )
        for source_index, source in enumerate(package.get("source_artifacts", [])):
            findings.extend(validate_source_artifact(source, source_index, package))

    if requires_machine_gates and package.get(
        "package_snapshot_sha256"
    ) != calculate_snapshot(package):
        findings.append(
            finding(
                "PACKAGE_SNAPSHOT_MISMATCH",
                "package_snapshot_sha256",
                "The locked package snapshot does not match the package content.",
            )
        )
    if requires_machine_gates and package.get(
        "dependency_snapshot_sha256"
    ) != calculate_dependency_snapshot(package):
        findings.append(
            finding(
                "DEPENDENCY_SNAPSHOT_MISMATCH",
                "dependency_snapshot_sha256",
                "The dependency snapshot does not match legal sources, rules, and calculator metadata.",
            )
        )
    if requires_machine_gates and package.get(
        "document_snapshot_sha256"
    ) != calculate_document_snapshot(package):
        findings.append(
            finding(
                "DOCUMENT_SNAPSHOT_MISMATCH",
                "document_snapshot_sha256",
                "The document snapshot does not match the formal statements.",
            )
        )
    if requires_machine_gates and package.get("jurisdiction") != {
        "country": "CN",
        "province": "Beijing",
    }:
        findings.append(
            finding(
                "DECLARED_SCOPE_UNSUPPORTED",
                "jurisdiction",
                "This release only checks reference integrity for packages declared as Beijing; it does not determine jurisdiction or provide a Beijing rule pack.",
            )
        )

    for claim_index, claim in enumerate(package.get("claims", [])):
        if requires_machine_gates:
            for calculation_index, calculation_id in enumerate(
                claim.get("calculation_ids", [])
            ):
                if calculation_id not in known_calculation_ids:
                    findings.append(
                        finding(
                            "CALCULATION_REFERENCE_UNKNOWN",
                            f"claims[{claim_index}].calculation_ids[{calculation_index}]",
                            f"Referenced calculation does not exist: {calculation_id}",
                        )
                    )
        if requires_machine_gates:
            limitation = claim.get("limitation_analysis")
            if not isinstance(limitation, dict):
                findings.append(
                    finding(
                        "LIMITATION_ANALYSIS_UNSTRUCTURED",
                        f"claims[{claim_index}].limitation_analysis",
                        "A reference-integrity claim requires structured limitation fields.",
                    )
                )
            else:
                required_limitation_fields = {
                    "accrual_basis",
                    "knowledge_date",
                    "relationship_end_date",
                    "interruption_events",
                    "suspension_intervals",
                    "special_rule",
                    "calculated_deadline",
                    "deadline_status",
                    "evidence_ids",
                    "review_status",
                }
                missing_limitation_fields = sorted(
                    required_limitation_fields - set(limitation)
                )
                if missing_limitation_fields:
                    findings.append(
                        finding(
                            "LIMITATION_ANALYSIS_INCOMPLETE",
                            f"claims[{claim_index}].limitation_analysis",
                            "Missing limitation fields: "
                            + ", ".join(missing_limitation_fields),
                        )
                    )
                elif (
                    limitation.get("review_status") != "PENDING_LEGAL_REVIEW"
                    or limitation.get("deadline_status") != "UNVERIFIED"
                    or limitation.get("calculated_deadline") is not None
                ):
                    findings.append(
                        finding(
                            "LIMITATION_CONCLUSION_UNVERIFIED",
                            f"claims[{claim_index}].limitation_analysis",
                            "No limitation engine is implemented; deadline conclusions must remain UNVERIFIED with no calculated deadline pending external legal review.",
                            "P0",
                        )
                    )
                for evidence_index, evidence_id in enumerate(
                    limitation.get("evidence_ids", [])
                ):
                    if evidence_id not in known_evidence_ids:
                        findings.append(
                            finding(
                                "EVIDENCE_REFERENCE_UNKNOWN",
                                f"claims[{claim_index}].limitation_analysis.evidence_ids[{evidence_index}]",
                                f"Referenced evidence does not exist: {evidence_id}",
                            )
                        )
        for element_index, element in enumerate(claim.get("elements", [])):
            if package.get("schema_version") == "1.2" and (
                "initial_burden_satisfied" in element
                or element.get("initial_burden_status") != "UNVERIFIED"
            ):
                findings.append(
                    finding(
                        "CLAIM_LEGAL_SUFFICIENCY_UNVERIFIED",
                        f"claims[{claim_index}].elements[{element_index}].initial_burden_status",
                        "No claim-element catalog or legal sufficiency engine is implemented; initial burden must remain UNVERIFIED.",
                        "P0",
                    )
                )
            if (
                package.get("schema_version") == "1.2"
                and element.get("proof_status") == "SUPPORTED"
            ):
                findings.append(
                    finding(
                        "EVIDENCE_SUPPORT_CLAIM_UNVERIFIED",
                        f"claims[{claim_index}].elements[{element_index}].proof_status",
                        "Reference existence does not establish authenticity, semantic support, contradiction resolution, or legal sufficiency; use EVIDENCE_LINKED_UNVERIFIED.",
                        "P0",
                    )
                )
            if requires_machine_gates and (
                element.get("assertion_status") not in ALLOWED_ASSERTION_STATUSES
                or element.get("proof_status") not in ALLOWED_PROOF_STATUSES
                or element.get("burden_stage") not in ALLOWED_BURDEN_STAGES
                or element.get("evidence_controller")
                not in ALLOWED_EVIDENCE_CONTROLLERS
                or element.get("initial_burden_status") != "UNVERIFIED"
                or not isinstance(element.get("adverse_consequence_candidate"), bool)
            ):
                findings.append(
                    finding(
                        "CLAIM_ELEMENT_STATUS_INVALID",
                        f"claims[{claim_index}].elements[{element_index}]",
                        "Claim-element assertion, proof, burden, controller, and Boolean fields must use allowed values.",
                    )
                )
            if requires_machine_gates and element.get("proof_status") in {
                "MISSING",
                "DISPUTED",
            }:
                findings.append(
                    finding(
                        "CLAIM_ELEMENT_UNRESOLVED",
                        f"claims[{claim_index}].elements[{element_index}].proof_status",
                        "Missing or disputed claim elements cannot enter the reference-integrity state.",
                    )
                )
            if requires_machine_gates and (
                not element.get("fact_ids") or not element.get("rule_ids")
            ):
                findings.append(
                    finding(
                        "CLAIM_ELEMENT_TRACE_INCOMPLETE",
                        f"claims[{claim_index}].elements[{element_index}]",
                        "Every formal claim element requires fact and legal-rule links.",
                    )
                )
            if requires_machine_gates:
                for fact_index, fact_id in enumerate(element.get("fact_ids", [])):
                    if fact_id not in known_fact_ids:
                        findings.append(
                            finding(
                                "FACT_REFERENCE_UNKNOWN",
                                f"claims[{claim_index}].elements[{element_index}].fact_ids[{fact_index}]",
                                f"Referenced fact does not exist: {fact_id}",
                            )
                        )
                for evidence_index, evidence_id in enumerate(
                    element.get("evidence_ids", [])
                ):
                    if evidence_id not in known_evidence_ids:
                        findings.append(
                            finding(
                                "EVIDENCE_REFERENCE_UNKNOWN",
                                f"claims[{claim_index}].elements[{element_index}].evidence_ids[{evidence_index}]",
                                f"Referenced evidence does not exist: {evidence_id}",
                            )
                        )
            if (
                requires_machine_gates
                and element.get("proof_status")
                in {"SUPPORTED", "EVIDENCE_LINKED_UNVERIFIED"}
                and not element.get("evidence_ids")
            ):
                findings.append(
                    finding(
                        "CLAIM_EVIDENCE_MISSING",
                        f"claims[{claim_index}].elements[{element_index}].evidence_ids",
                        "A supported claim element requires at least one evidence link.",
                    )
                )
            if (
                requires_machine_gates
                and element.get("proof_status") == "EMPLOYER_CONTROLLED_MISSING"
            ):
                production_request = element.get("production_request")
                exception_justified = (
                    element.get("evidence_controller") == "EMPLOYER"
                    and isinstance(production_request, dict)
                    and bool(production_request.get("requested_items"))
                )
                if not exception_justified:
                    findings.append(
                        finding(
                            "EMPLOYER_CONTROLLED_EVIDENCE_UNJUSTIFIED",
                            f"claims[{claim_index}].elements[{element_index}]",
                            "Employer-controlled missing evidence requires an employer-controller declaration and a production request; legal sufficiency remains unverified.",
                        )
                    )
            for rule_index, rule_id in enumerate(element.get("rule_ids", [])):
                if requires_machine_gates and rule_id not in known_rule_ids:
                    findings.append(
                        finding(
                            "RULE_REFERENCE_UNKNOWN",
                            f"claims[{claim_index}].elements[{element_index}].rule_ids[{rule_index}]",
                            f"Referenced legal rule does not exist: {rule_id}",
                        )
                    )

    if requires_machine_gates:
        privacy_review = package.get("privacy_review")
        if (
            not isinstance(privacy_review, dict)
            or privacy_review.get("status") != "EXTERNAL_REVIEW_REQUIRED"
            or any(
                privacy_review.get(field) is not None
                for field in ("reviewed_by", "reviewed_at", "reviewer_actor_type")
            )
        ):
            findings.append(
                finding(
                    "UNAUTHENTICATED_PRIVACY_REVIEW_UNSUPPORTED",
                    "privacy_review",
                    "This local validator cannot authenticate privacy review; the status must remain EXTERNAL_REVIEW_REQUIRED.",
                    "P0",
                )
            )
        for adversarial_index, adversarial in enumerate(
            package.get("adversarial_findings", [])
        ):
            if adversarial.get("severity") in {"P0", "P1"} and adversarial.get(
                "status"
            ) not in {"REFUTED", "MITIGATED"}:
                findings.append(
                    finding(
                        "ADVERSARIAL_BLOCKER_OPEN",
                        f"adversarial_findings[{adversarial_index}]",
                        "Open P0/P1 adversarial findings block reference-integrity validation.",
                    )
                )
            elif adversarial.get("severity") in {"P0", "P1"}:
                findings.append(
                    finding(
                        "UNAUTHENTICATED_RISK_RESOLUTION_UNSUPPORTED",
                        f"adversarial_findings[{adversarial_index}]",
                        "This local validator cannot authenticate risk ownership or resolution; P0/P1 findings cannot be closed through JSON fields.",
                        "P0",
                    )
                )
        for statement_index, statement in enumerate(package.get("statements", [])):
            statement_fact_ids = statement.get("fact_ids", [])
            statement_rule_ids = statement.get("rule_ids", [])
            if (
                not statement.get("text")
                or not statement_fact_ids
                or not statement_rule_ids
            ):
                findings.append(
                    finding(
                        "STATEMENT_TRACE_INCOMPLETE",
                        f"statements[{statement_index}]",
                        "Every formal statement requires text, fact links, and legal-rule links.",
                    )
                )
            for fact_index, fact_id in enumerate(statement_fact_ids):
                if fact_id not in known_fact_ids:
                    findings.append(
                        finding(
                            "FACT_REFERENCE_UNKNOWN",
                            f"statements[{statement_index}].fact_ids[{fact_index}]",
                            f"Referenced fact does not exist: {fact_id}",
                        )
                    )
            for rule_index, rule_id in enumerate(statement_rule_ids):
                if rule_id not in known_rule_ids:
                    findings.append(
                        finding(
                            "RULE_REFERENCE_UNKNOWN",
                            f"statements[{statement_index}].rule_ids[{rule_index}]",
                            f"Referenced legal rule does not exist: {rule_id}",
                        )
                    )
            for calculation_index, calculation_id in enumerate(
                statement.get("calculation_ids", [])
            ):
                if calculation_id not in known_calculation_ids:
                    findings.append(
                        finding(
                            "CALCULATION_REFERENCE_UNKNOWN",
                            f"statements[{statement_index}].calculation_ids[{calculation_index}]",
                            f"Referenced calculation does not exist: {calculation_id}",
                        )
                    )
        for conflict_index, conflict in enumerate(package.get("conflicts", [])):
            if conflict.get("status") != "PENDING_LEGAL_REVIEW":
                findings.append(
                    finding(
                        "CLAIM_CONFLICT_RESOLUTION_UNVERIFIED",
                        f"conflicts[{conflict_index}]",
                        "No claim-relationship matrix or authenticated legal review is implemented; conflicts must remain PENDING_LEGAL_REVIEW.",
                        "P0",
                    )
                )
        for fact_index, fact in enumerate(package.get("facts", [])):
            if fact.get("status") in {
                "CORROBORATED",
                "EXTRACTED",
                "REVIEWED_ASSERTION",
            }:
                findings.append(
                    finding(
                        "FACT_STATUS_SEMANTIC_VERIFICATION_UNSUPPORTED",
                        f"facts[{fact_index}].status",
                        "This validator cannot authenticate review or determine semantic corroboration; use EVIDENCE_LINKED, USER_ASSERTED, DISPUTED, or UNKNOWN.",
                        "P0",
                    )
                )
            if (
                package.get("schema_version") == "1.2"
                and fact.get("status") == "TRIBUNAL_FOUND"
            ):
                findings.append(
                    finding(
                        "FACT_STATUS_EXTERNAL_AUTHORITY_REQUIRED",
                        f"facts[{fact_index}].status",
                        "The validator cannot authenticate an award, judgment, effective status, or cited passage; TRIBUNAL_FOUND is unavailable.",
                        "P0",
                    )
                )
            if fact.get("status") not in ALLOWED_FACT_STATUSES:
                findings.append(
                    finding(
                        "FACT_STATUS_NOT_ALLOWED",
                        f"facts[{fact_index}].status",
                        "Fact status must distinguish assertions, evidence links, disputes, and tribunal findings.",
                    )
                )
            if fact.get("status") in {
                "EVIDENCE_LINKED",
                "CORROBORATED",
                "TRIBUNAL_FOUND",
            } and not fact.get("evidence_ids"):
                findings.append(
                    finding(
                        "FACT_EVIDENCE_MISSING",
                        f"facts[{fact_index}].evidence_ids",
                        "An evidence-linked, corroborated, or tribunal-found fact requires evidence links.",
                    )
                )
            for evidence_index, evidence_id in enumerate(fact.get("evidence_ids", [])):
                if evidence_id not in known_evidence_ids:
                    findings.append(
                        finding(
                            "EVIDENCE_REFERENCE_UNKNOWN",
                            f"facts[{fact_index}].evidence_ids[{evidence_index}]",
                            f"Referenced evidence does not exist: {evidence_id}",
                        )
                    )
        for rule_index, rule in enumerate(package.get("legal_rules", [])):
            if rule.get("source_id") not in known_source_ids:
                findings.append(
                    finding(
                        "RULE_SOURCE_UNKNOWN",
                        f"legal_rules[{rule_index}].source_id",
                        "A referenced legal rule must resolve to a source artifact.",
                    )
                )
            if rule.get("jurisdiction") != package.get("jurisdiction"):
                findings.append(
                    finding(
                        "RULE_JURISDICTION_MISMATCH",
                        f"legal_rules[{rule_index}].jurisdiction",
                        "A formal rule jurisdiction must match the case package.",
                    )
                )
            if rule.get("superseded_by"):
                findings.append(
                    finding(
                        "RULE_SUPERSEDED",
                        f"legal_rules[{rule_index}].superseded_by",
                        "A rule declared superseded cannot support reference-integrity validation.",
                    )
                )
            if (
                rule.get("status") != "UNVERIFIED_CANDIDATE"
                or rule.get("verified_by") is not None
                or rule.get("verified_at") is not None
                or rule.get("verification_actor_type") is not None
            ):
                findings.append(
                    finding(
                        "RULE_VERIFICATION_CLAIM_UNSUPPORTED",
                        f"legal_rules[{rule_index}].status",
                        "This validator does not fetch, freeze, compare, version, or authenticate legal review; rules must remain UNVERIFIED_CANDIDATE.",
                        "P0",
                    )
                )
        for evidence_index, evidence in enumerate(package.get("evidence", [])):
            if evidence.get("raw_id") not in known_raw_ids:
                findings.append(
                    finding(
                        "EVIDENCE_RAW_FILE_UNKNOWN",
                        f"evidence[{evidence_index}].raw_id",
                        "Evidence must resolve to a registered raw file.",
                    )
                )
            expected_integrity_status = "INGESTION_BYTES_OBSERVED"
            if evidence.get("integrity_status") != expected_integrity_status:
                findings.append(
                    finding(
                        "EVIDENCE_INTEGRITY_UNVERIFIED",
                        f"evidence[{evidence_index}].integrity_status",
                        "Evidence must link to bytes observed in the bound intake manifest; this does not authenticate the evidence.",
                    )
                )
            location = evidence.get("location")
            if (
                not isinstance(location, dict)
                or not location.get("type")
                or not location.get("value")
            ):
                findings.append(
                    finding(
                        "EVIDENCE_LOCATION_MISSING",
                        f"evidence[{evidence_index}].location",
                        "Formal evidence requires a typed source location.",
                    )
                )
        for calculation_index, calculation in enumerate(
            package.get("calculations", [])
        ):
            missing_calculation_fields = sorted(
                field
                for field in REQUIRED_CALCULATION_FIELDS
                if field not in calculation or calculation.get(field) is None
            )
            if missing_calculation_fields:
                findings.append(
                    finding(
                        "CALCULATION_REPRODUCIBILITY_INCOMPLETE",
                        f"calculations[{calculation_index}]",
                        "Missing calculation fields: "
                        + ", ".join(missing_calculation_fields),
                    )
                )
            if not is_decimal_text(calculation.get("result")):
                findings.append(
                    finding(
                        "CALCULATION_DECIMAL_FORMAT_INVALID",
                        f"calculations[{calculation_index}].result",
                        "Calculation results must use deterministic decimal text, not JSON numbers.",
                    )
                )
            for input_index, calculation_input in enumerate(
                calculation.get("inputs", [])
            ):
                if not is_decimal_text(calculation_input.get("value")):
                    findings.append(
                        finding(
                            "CALCULATION_DECIMAL_FORMAT_INVALID",
                            f"calculations[{calculation_index}].inputs[{input_index}].value",
                            "Calculation inputs must use deterministic decimal text.",
                        )
                    )
                evidence_id = calculation_input.get("evidence_id")
                if evidence_id not in known_evidence_ids:
                    findings.append(
                        finding(
                            "EVIDENCE_REFERENCE_UNKNOWN",
                            f"calculations[{calculation_index}].inputs[{input_index}].evidence_id",
                            f"Referenced evidence does not exist: {evidence_id}",
                        )
                    )
            recomputed = recompute_sum_decimal_inputs(calculation)
            if recomputed is None:
                findings.append(
                    finding(
                        "CALCULATOR_UNSUPPORTED",
                        f"calculations[{calculation_index}]",
                        "The calculator formula, version, rounding policy, or decimal inputs are unsupported.",
                    )
                )
            else:
                expected_result, expected_steps = recomputed
                if calculation.get("result") != expected_result:
                    findings.append(
                        finding(
                            "CALCULATION_RESULT_MISMATCH",
                            f"calculations[{calculation_index}].result",
                            "The declared result does not match deterministic recomputation.",
                        )
                    )
                if calculation.get("intermediate_steps") != expected_steps:
                    findings.append(
                        finding(
                            "CALCULATION_STEPS_MISMATCH",
                            f"calculations[{calculation_index}].intermediate_steps",
                            "Intermediate steps do not match deterministic recomputation.",
                        )
                    )
            if calculation.get("status") != "ARITHMETIC_RECOMPUTED":
                findings.append(
                    finding(
                        "LEGAL_AMOUNT_STATUS_UNSUPPORTED",
                        f"calculations[{calculation_index}].status",
                        "The generic sum verifies arithmetic only and cannot claim an exact or professionally calculated labor-law amount.",
                        "P0",
                    )
                )

    if package.get("approvals"):
        findings.append(
            finding(
                "UNAUTHENTICATED_APPROVAL_UNSUPPORTED",
                "approvals",
                "Approval artifacts require an external authenticated, authorized, signed, and auditable channel; JSON fields are rejected.",
                "P0",
            )
        )
    if package.get("requested_state") == "HUMAN_APPROVED_FOR_SUBMISSION":
        findings.append(
            finding(
                "UNAUTHENTICATED_APPROVAL_UNSUPPORTED",
                "requested_state",
                "This local validator cannot authenticate identity, authorization, signatures, or separation of duties; JSON approval fields never grant a submission state.",
                "P0",
            )
        )

    return make_report(package, findings)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_package", type=Path)
    parser.add_argument("--intake-manifest", type=Path)
    args = parser.parse_args()

    try:
        raw_input = read_stable_utf8(args.case_package, MAX_CASE_PACKAGE_BYTES)
    except InputTooLargeError:
        emit_input_error(
            "INPUT_FILE_TOO_LARGE",
            f"Case package exceeds the {MAX_CASE_PACKAGE_BYTES}-byte limit.",
        )
        return 1
    except (OSError, UnicodeError) as error:
        emit_input_error("INPUT_FILE_UNREADABLE", str(error))
        return 1
    try:
        package = json.loads(
            raw_input,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_json_constant,
        )
    except DuplicateKeyError as error:
        emit_input_error(
            "INPUT_JSON_DUPLICATE_KEY",
            f"Duplicate JSON object key: {error}",
        )
        return 1
    except InvalidJsonConstantError as error:
        emit_input_error(
            "INPUT_JSON_INVALID_CONSTANT",
            f"Non-standard JSON numeric constant: {error}",
        )
        return 1
    except json.JSONDecodeError as error:
        emit_input_error(
            "INPUT_JSON_INVALID",
            f"Invalid JSON at line {error.lineno}, column {error.colno}.",
        )
        return 1
    except RecursionError:
        emit_input_error(
            "INPUT_JSON_TOO_DEEPLY_NESTED",
            "Case-package JSON nesting exceeds the parser safety limit.",
        )
        return 1
    if not isinstance(package, dict):
        emit_input_error(
            "INPUT_ROOT_NOT_OBJECT",
            "The case-package JSON root must be an object.",
        )
        return 1

    intake_manifest = None
    if args.intake_manifest is not None:
        try:
            manifest_input = read_stable_utf8(
                args.intake_manifest, MAX_CASE_PACKAGE_BYTES
            )
            intake_manifest = json.loads(
                manifest_input,
                object_pairs_hook=reject_duplicate_keys,
                parse_constant=reject_json_constant,
            )
        except InputTooLargeError:
            emit_input_error(
                "INTAKE_MANIFEST_TOO_LARGE",
                f"Intake manifest exceeds the {MAX_CASE_PACKAGE_BYTES}-byte limit.",
            )
            return 1
        except (OSError, UnicodeError) as error:
            emit_input_error("INTAKE_MANIFEST_UNREADABLE", str(error))
            return 1
        except DuplicateKeyError as error:
            emit_input_error(
                "INTAKE_MANIFEST_DUPLICATE_KEY",
                f"Duplicate JSON object key: {error}",
            )
            return 1
        except InvalidJsonConstantError as error:
            emit_input_error(
                "INTAKE_MANIFEST_INVALID_CONSTANT",
                f"Non-standard JSON numeric constant: {error}",
            )
            return 1
        except json.JSONDecodeError as error:
            emit_input_error(
                "INTAKE_MANIFEST_JSON_INVALID",
                f"Invalid JSON at line {error.lineno}, column {error.colno}.",
            )
            return 1
        except RecursionError:
            emit_input_error(
                "INTAKE_MANIFEST_TOO_DEEPLY_NESTED",
                "Intake-manifest JSON nesting exceeds the parser safety limit.",
            )
            return 1
        if not isinstance(intake_manifest, dict):
            emit_input_error(
                "INTAKE_MANIFEST_ROOT_NOT_OBJECT",
                "The intake-manifest JSON root must be an object.",
            )
            return 1

    report = validate_case_package(package, intake_manifest)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["allowed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
