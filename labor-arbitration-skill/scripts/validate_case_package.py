#!/usr/bin/env python3
"""Validate deterministic promotion gates for a labor-arbitration case package."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path, PurePosixPath


MACHINE_GATED_STATES = {
    "MACHINE_VALIDATED_CANDIDATE",
    "HUMAN_APPROVED_FOR_SUBMISSION",
}
ALLOWED_STATES = {
    "INTERNAL_ANALYSIS",
    "DRAFT",
    "REVIEW_REQUIRED",
    "MACHINE_VALIDATED_CANDIDATE",
    "HUMAN_APPROVED_FOR_SUBMISSION",
    "REVALIDATION_REQUIRED",
}
SUPPORTED_SCHEMA_VERSIONS = {"1.1"}
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
    "EXTRACTED",
    "USER_ASSERTED",
    "REVIEWED_ASSERTION",
    "EVIDENCE_LINKED",
    "CORROBORATED",
    "DISPUTED",
    "UNKNOWN",
    "TRIBUNAL_FOUND",
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
INTEGRITY_SEMANTICS = "Hashes verify bytes observed at ingestion, not authenticity."
ALLOWED_ASSERTION_STATUSES = {"ASSERTED", "CONDITIONALLY_ASSERTED"}
ALLOWED_PROOF_STATUSES = {
    "SUPPORTED",
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


class DuplicateKeyError(ValueError):
    """Raised when a JSON object repeats a key."""


class InvalidJsonConstantError(ValueError):
    """Raised for NaN and Infinity, which are outside standard JSON."""


def finding(code: str, path: str, message: str, severity: str = "P1") -> dict:
    return {
        "code": code,
        "message": message,
        "path": path,
        "severity": severity,
    }


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


def make_report(package: dict, findings: list[dict]) -> dict:
    findings.sort(key=lambda item: (item["code"], item["path"], item["message"]))
    allowed = not findings
    return {
        "allowed": allowed,
        "findings": findings,
        "highest_allowed_state": (
            package.get("requested_state", "INTERNAL_ANALYSIS")
            if allowed
            else "REVIEW_REQUIRED"
        ),
        "requested_state": package.get("requested_state"),
        "schema_version": package.get("schema_version"),
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
                    f"Machine validation requires package field: {field}",
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
                "Machine validation requires the independently generated intake manifest.",
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
        intake_manifest.get("schema_version") != "1.1"
        or intake_manifest.get("integrity_semantics") != INTEGRITY_SEMANTICS
        or not isinstance(manifest_files, list)
        or any(not isinstance(item, dict) for item in manifest_files)
    ):
        return [
            finding(
                "INTAKE_MANIFEST_INVALID",
                "intake_manifest",
                "The intake manifest has an unsupported schema or malformed records.",
            )
        ]
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
    if package.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS:
        findings.append(
            finding(
                "SCHEMA_VERSION_UNSUPPORTED",
                "schema_version",
                "Case-package schema version is not supported by this validator.",
            )
        )

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

    referenced_rule_ids = set()
    source_by_id = {
        source.get("source_id"): source
        for source in package.get("source_artifacts", [])
        if source.get("source_id")
    }
    known_source_ids = set(source_by_id)
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
                        "A machine-validated package requires formal claims and statements.",
                    )
                )

        for raw_index, raw_file in enumerate(package.get("raw_files", [])):
            size_bytes = raw_file.get("size_bytes")
            if (
                not is_safe_relative_path(raw_file.get("relative_path"))
                or not isinstance(raw_file.get("extension"), str)
                or not isinstance(size_bytes, int)
                or isinstance(size_bytes, bool)
                or size_bytes < 0
                or not is_sha256(raw_file.get("sha256"))
                or raw_file.get("integrity_status") != "INGESTION_INTEGRITY_VERIFIED"
            ):
                findings.append(
                    finding(
                        "RAW_FILE_METADATA_INVALID",
                        f"raw_files[{raw_index}]",
                        "Raw-file records require a relative path and SHA-256 checksum.",
                    )
                )

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
                "JURISDICTION_UNSUPPORTED",
                "jurisdiction",
                "Machine validation currently supports Beijing labor-arbitration packages only.",
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
                        "A machine-validated claim requires a structured limitation analysis.",
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
                elif limitation.get("review_status") != "REVIEWED" or limitation.get(
                    "deadline_status"
                ) not in {"WITHIN_LIMITATION", "OUTSIDE_LIMITATION"}:
                    findings.append(
                        finding(
                            "LIMITATION_REVIEW_REQUIRED",
                            f"claims[{claim_index}].limitation_analysis.review_status",
                            "Disputed limitation classification requires human legal review.",
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
            if requires_machine_gates and (
                element.get("assertion_status") not in ALLOWED_ASSERTION_STATUSES
                or element.get("proof_status") not in ALLOWED_PROOF_STATUSES
                or element.get("burden_stage") not in ALLOWED_BURDEN_STAGES
                or element.get("evidence_controller")
                not in ALLOWED_EVIDENCE_CONTROLLERS
                or not isinstance(element.get("initial_burden_satisfied"), bool)
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
                        "Missing or disputed claim elements cannot enter a machine-validated candidate.",
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
                and element.get("proof_status") == "SUPPORTED"
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
                    and element.get("initial_burden_satisfied") is True
                    and isinstance(production_request, dict)
                    and bool(production_request.get("requested_items"))
                )
                if not exception_justified:
                    findings.append(
                        finding(
                            "EMPLOYER_CONTROLLED_EVIDENCE_UNJUSTIFIED",
                            f"claims[{claim_index}].elements[{element_index}]",
                            "Employer-controlled missing evidence requires an initial-burden record and a production request.",
                        )
                    )
            for rule_index, rule_id in enumerate(element.get("rule_ids", [])):
                referenced_rule_ids.add(rule_id)
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
            or privacy_review.get("status") != "COMPLETED"
            or not privacy_review.get("reviewed_by")
            or not privacy_review.get("reviewed_at")
        ):
            findings.append(
                finding(
                    "PRIVACY_REVIEW_MISSING",
                    "privacy_review",
                    "Machine validation requires an attributable completed privacy review.",
                )
            )
        elif privacy_review.get("reviewer_actor_type") != "HUMAN":
            findings.append(
                finding(
                    "PRIVACY_REVIEW_NOT_HUMAN",
                    "privacy_review.reviewer_actor_type",
                    "A model cannot approve its own privacy review.",
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
                        "Open P0/P1 adversarial findings block machine validation.",
                    )
                )
            elif (
                adversarial.get("severity") in {"P0", "P1"}
                and adversarial.get("status") in {"REFUTED", "MITIGATED"}
                and (
                    adversarial.get("resolution_actor_type") != "HUMAN"
                    or not adversarial.get("resolved_by")
                    or not adversarial.get("resolved_at")
                )
            ):
                findings.append(
                    finding(
                        "ADVERSARIAL_RESOLUTION_NOT_HUMAN",
                        f"adversarial_findings[{adversarial_index}]",
                        "Closing a P0/P1 adversarial finding requires attributable human resolution.",
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
                referenced_rule_ids.add(rule_id)
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
            if conflict.get("status") != "RESOLVED":
                findings.append(
                    finding(
                        "CLAIM_CONFLICT_UNRESOLVED",
                        f"conflicts[{conflict_index}]",
                        "Unresolved duplication or remedy conflicts block machine validation.",
                    )
                )
        for fact_index, fact in enumerate(package.get("facts", [])):
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
            if rule.get("rule_id") not in referenced_rule_ids:
                continue
            if rule.get("source_id") not in known_source_ids:
                findings.append(
                    finding(
                        "RULE_SOURCE_UNKNOWN",
                        f"legal_rules[{rule_index}].source_id",
                        "A referenced legal rule must resolve to a source artifact.",
                    )
                )
            else:
                source = source_by_id[rule["source_id"]]
                missing_source_fields = sorted(
                    field for field in REQUIRED_SOURCE_FIELDS if not source.get(field)
                )
                if missing_source_fields:
                    findings.append(
                        finding(
                            "SOURCE_METADATA_INCOMPLETE",
                            f"source_artifacts[{rule.get('source_id')}]",
                            "Missing source metadata: "
                            + ", ".join(missing_source_fields),
                        )
                    )
                if not is_sha256(source.get("content_sha256")):
                    findings.append(
                        finding(
                            "SOURCE_CONTENT_HASH_INVALID",
                            f"source_artifacts[{rule.get('source_id')}].content_sha256",
                            "Formal source artifacts require a SHA-256 content hash.",
                        )
                    )
                canonical_url = source.get("canonical_url")
                if not isinstance(
                    canonical_url, str
                ) or not canonical_url.lower().startswith("https://"):
                    findings.append(
                        finding(
                            "SOURCE_URL_UNSAFE",
                            f"source_artifacts[{rule.get('source_id')}].canonical_url",
                            "Formal source artifacts require a canonical HTTPS URL.",
                        )
                    )
                if (
                    source.get("document_type") not in NORMATIVE_DOCUMENT_TYPES
                    or source.get("binding_status") not in FORMAL_BINDING_STATUSES
                ):
                    findings.append(
                        finding(
                            "SOURCE_NOT_NORMATIVE",
                            f"source_artifacts[{rule.get('source_id')}].document_type",
                            "Publisher authority alone does not make this source a binding legal instrument.",
                        )
                    )
                if source.get("jurisdiction") != package.get("jurisdiction"):
                    findings.append(
                        finding(
                            "SOURCE_JURISDICTION_MISMATCH",
                            f"source_artifacts[{rule.get('source_id')}].jurisdiction",
                            "A formal rule's source jurisdiction must match the case package.",
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
                        "A superseded legal rule cannot support machine validation.",
                    )
                )
            rule_status_allowed = rule.get("status") == "VERIFIED_CURRENT" or (
                rule.get("status") == "VERIFIED_HISTORICAL"
                and rule.get("applicability_status") == "TIME_MATCHED"
            )
            if not rule_status_allowed:
                findings.append(
                    finding(
                        "RULE_STATUS_NOT_ALLOWED",
                        f"legal_rules[{rule_index}].status",
                        "A referenced rule is not verified for the requested snapshot.",
                    )
                )
            if (
                rule.get("verification_actor_type") != "HUMAN"
                or not rule.get("verified_by")
                or not rule.get("verified_at")
            ):
                findings.append(
                    finding(
                        "RULE_VERIFICATION_NOT_HUMAN",
                        f"legal_rules[{rule_index}].verification_actor_type",
                        "A model cannot self-verify a legal rule for formal use.",
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
            if evidence.get("integrity_status") != "INGESTION_INTEGRITY_VERIFIED":
                findings.append(
                    finding(
                        "EVIDENCE_INTEGRITY_UNVERIFIED",
                        f"evidence[{evidence_index}].integrity_status",
                        "Formal evidence must be linked to an ingestion-integrity-verified record.",
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
            if calculation.get("status") not in {
                "EXACT_GIVEN_ASSUMPTIONS",
                "SCENARIO",
            }:
                findings.append(
                    finding(
                        "CALCULATION_STATUS_NOT_ALLOWED",
                        f"calculations[{calculation_index}].status",
                        "Calculations must disclose assumptions and may not claim a pseudo-final status.",
                    )
                )

    if package.get("requested_state") == "HUMAN_APPROVED_FOR_SUBMISSION":
        approvals = package.get("approvals")
        if not approvals:
            findings.append(
                finding(
                    "HUMAN_APPROVAL_MISSING",
                    "approvals",
                    "Human-approved state requires a separately supplied approval artifact.",
                )
            )
        else:
            matching_approvals = [
                approval
                for approval in approvals
                if approval.get("approved_snapshot_sha256")
                == package.get("package_snapshot_sha256")
            ]
            if not matching_approvals:
                findings.append(
                    finding(
                        "APPROVAL_SNAPSHOT_MISMATCH",
                        "approvals",
                        "No human approval matches the requested package snapshot.",
                    )
                )
            else:
                required_approval_fields = {
                    "approval_id",
                    "reviewer_identity",
                    "reviewer_role",
                    "reviewer_actor_type",
                    "approved_scope",
                    "approved_at_utc",
                    "evidence_uri",
                }
                if not any(
                    approval.get("reviewer_actor_type") == "HUMAN"
                    and all(approval.get(field) for field in required_approval_fields)
                    for approval in matching_approvals
                ):
                    findings.append(
                        finding(
                            "HUMAN_APPROVAL_INVALID",
                            "approvals",
                            "A matching approval is missing attributable human-review fields.",
                        )
                    )

    return make_report(package, findings)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_package", type=Path)
    parser.add_argument("--intake-manifest", type=Path)
    args = parser.parse_args()

    try:
        input_size = args.case_package.stat().st_size
    except (OSError, UnicodeError) as error:
        emit_input_error("INPUT_FILE_UNREADABLE", str(error))
        return 1
    if input_size > MAX_CASE_PACKAGE_BYTES:
        emit_input_error(
            "INPUT_FILE_TOO_LARGE",
            f"Case package exceeds the {MAX_CASE_PACKAGE_BYTES}-byte limit.",
        )
        return 1
    try:
        raw_input = args.case_package.read_text(encoding="utf-8")
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
            manifest_size = args.intake_manifest.stat().st_size
            if manifest_size > MAX_CASE_PACKAGE_BYTES:
                emit_input_error(
                    "INTAKE_MANIFEST_TOO_LARGE",
                    f"Intake manifest exceeds the {MAX_CASE_PACKAGE_BYTES}-byte limit.",
                )
                return 1
            manifest_input = args.intake_manifest.read_text(encoding="utf-8")
            intake_manifest = json.loads(
                manifest_input,
                object_pairs_hook=reject_duplicate_keys,
                parse_constant=reject_json_constant,
            )
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
