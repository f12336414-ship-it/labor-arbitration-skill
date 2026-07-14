"""Published Draft 2020-12 schema validation boundaries."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from finding_model import finding, format_schema_path


REFERENCE_DIRECTORY = Path(__file__).resolve().parents[1] / "references"
CASE_PACKAGE_SCHEMA_PATH = REFERENCE_DIRECTORY / "case-package.schema.json"
INTAKE_MANIFEST_SCHEMA_PATH = REFERENCE_DIRECTORY / "intake-manifest.schema.json"
REVIEW_PACKET_SCHEMA_PATH = REFERENCE_DIRECTORY / "review-packet.schema.json"


def _load_validator(path: Path):
    schema = json.loads(path.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.FormatChecker()
    )


def validate_published_schema(package: dict) -> list[dict]:
    try:
        validator = _load_validator(CASE_PACKAGE_SCHEMA_PATH)
    except (OSError, UnicodeError, json.JSONDecodeError, jsonschema.SchemaError):
        return [
            finding(
                "VALIDATOR_SCHEMA_UNAVAILABLE",
                "$",
                "The bundled v1.3 JSON Schema is unavailable or invalid.",
                "P0",
            )
        ]
    return _collect_errors(
        validator,
        package,
        code="SCHEMA_VALIDATION_ERROR",
        prefix="",
        message="Package content does not conform to the published v1.3 JSON Schema.",
    )


def validate_published_intake_schema(manifest: dict) -> list[dict]:
    try:
        validator = _load_validator(INTAKE_MANIFEST_SCHEMA_PATH)
    except (OSError, UnicodeError, json.JSONDecodeError, jsonschema.SchemaError):
        return [
            finding(
                "INTAKE_SCHEMA_UNAVAILABLE",
                "intake_manifest",
                "The bundled intake-manifest v1.3 JSON Schema is unavailable or invalid.",
                "P0",
            )
        ]
    return _collect_errors(
        validator,
        manifest,
        code="INTAKE_SCHEMA_VALIDATION_ERROR",
        prefix="intake_manifest",
        message="Intake manifest does not conform to the published v1.3 JSON Schema.",
    )


def validate_published_review_packet(packet: dict) -> list[dict]:
    try:
        validator = _load_validator(REVIEW_PACKET_SCHEMA_PATH)
    except (OSError, UnicodeError, json.JSONDecodeError, jsonschema.SchemaError):
        return [
            finding(
                "REVIEW_PACKET_SCHEMA_UNAVAILABLE",
                "$",
                "The bundled review-packet v1.0 JSON Schema is unavailable or invalid.",
                "P0",
            )
        ]
    return _collect_errors(
        validator,
        packet,
        code="REVIEW_PACKET_SCHEMA_VALIDATION_ERROR",
        prefix="",
        message="Review packet does not conform to the published v1.0 JSON Schema.",
    )


def _collect_errors(validator, value, *, code: str, prefix: str, message: str):
    findings = []
    seen_paths = set()
    for error in sorted(
        validator.iter_errors(value),
        key=lambda item: (
            tuple(str(part) for part in item.absolute_path),
            item.message,
        ),
    ):
        schema_path = format_schema_path(error.absolute_path)
        path = schema_path if not prefix else prefix + schema_path[1:]
        if path not in seen_paths:
            seen_paths.add(path)
            findings.append(finding(code, path, message, "P0"))
    return findings
