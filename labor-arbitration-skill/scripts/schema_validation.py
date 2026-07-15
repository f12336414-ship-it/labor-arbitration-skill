"""Published Draft 2020-12 schema validation boundaries."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import jsonschema

from finding_model import finding, format_schema_path


REFERENCE_DIRECTORY = Path(__file__).resolve().parents[1] / "references"
CASE_PACKAGE_SCHEMA_PATH = REFERENCE_DIRECTORY / "case-package.schema.json"
INTAKE_MANIFEST_SCHEMA_PATH = REFERENCE_DIRECTORY / "intake-manifest.schema.json"
REVIEW_PACKET_SCHEMA_PATH = REFERENCE_DIRECTORY / "review-packet.schema.json"
FORMAL_OUTPUT_STATE_SCHEMA_PATH = (
    REFERENCE_DIRECTORY / "formal-output-state.schema.json"
)
FROZEN_SOURCE_RECORD_SCHEMA_PATH = (
    REFERENCE_DIRECTORY / "frozen-source-record.schema.json"
)
LEGAL_VERSION_GRAPH_SCHEMA_PATH = (
    REFERENCE_DIRECTORY / "legal-version-graph.schema.json"
)
LEGAL_FRESHNESS_CHECK_SCHEMA_PATH = (
    REFERENCE_DIRECTORY / "legal-freshness-check.schema.json"
)
LEGAL_TEXT_DIFF_SCHEMA_PATH = REFERENCE_DIRECTORY / "legal-text-diff.schema.json"
HISTORICAL_VERSION_CANDIDATE_SCHEMA_PATH = (
    REFERENCE_DIRECTORY / "historical-version-candidate.schema.json"
)
OFFICIAL_CASE_RECORD_SCHEMA_PATH = (
    REFERENCE_DIRECTORY / "official-case-record.schema.json"
)
CASE_WORKSPACE_SCHEMA_PATH = REFERENCE_DIRECTORY / "case-workspace.schema.json"
PARSER_EXTRACTION_RECORD_SCHEMA_PATH = (
    REFERENCE_DIRECTORY / "parser-extraction-record.schema.json"
)
FACT_CANDIDATE_RECORD_SCHEMA_PATH = (
    REFERENCE_DIRECTORY / "fact-candidate-record.schema.json"
)
FACT_ANALYSIS_INPUT_SCHEMA_PATH = REFERENCE_DIRECTORY / "fact-analysis-input.schema.json"
FACT_ANALYSIS_RECORD_SCHEMA_PATH = REFERENCE_DIRECTORY / "fact-analysis-record.schema.json"
EVIDENCE_REVIEW_INPUT_SCHEMA_PATH = REFERENCE_DIRECTORY / "evidence-review-input.schema.json"
EVIDENCE_REVIEW_RECORD_SCHEMA_PATH = REFERENCE_DIRECTORY / "evidence-review-record.schema.json"
LEGAL_MONITOR_DEFINITION_INPUT_SCHEMA_PATH = REFERENCE_DIRECTORY / "legal-monitor-definition-input.schema.json"
LEGAL_MONITOR_DEFINITION_SCHEMA_PATH = REFERENCE_DIRECTORY / "legal-monitor-definition.schema.json"
LEGAL_MONITOR_RUN_INPUT_SCHEMA_PATH = REFERENCE_DIRECTORY / "legal-monitor-run-input.schema.json"
LEGAL_MONITOR_RUN_SCHEMA_PATH = REFERENCE_DIRECTORY / "legal-monitor-run.schema.json"


@lru_cache(maxsize=None)
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


def validate_published_formal_output_state(request: dict) -> list[dict]:
    try:
        validator = _load_validator(FORMAL_OUTPUT_STATE_SCHEMA_PATH)
    except (OSError, UnicodeError, json.JSONDecodeError, jsonschema.SchemaError):
        return [
            finding(
                "OUTPUT_STATE_SCHEMA_UNAVAILABLE",
                "$",
                "The bundled formal-output-state v1.0 JSON Schema is unavailable or invalid.",
                "P0",
            )
        ]
    return _collect_errors(
        validator,
        request,
        code="OUTPUT_STATE_SCHEMA_VALIDATION_ERROR",
        prefix="",
        message="State request does not conform to the published v1.0 JSON Schema.",
    )


def validate_published_frozen_source_record(record: dict) -> list[dict]:
    try:
        validator = _load_validator(FROZEN_SOURCE_RECORD_SCHEMA_PATH)
    except (OSError, UnicodeError, json.JSONDecodeError, jsonschema.SchemaError):
        return [
            finding(
                "FROZEN_SOURCE_SCHEMA_UNAVAILABLE",
                "$",
                "The bundled frozen-source-record v1.0 JSON Schema is unavailable or invalid.",
                "P0",
            )
        ]
    return _collect_errors(
        validator,
        record,
        code="FROZEN_SOURCE_SCHEMA_VALIDATION_ERROR",
        prefix="",
        message="Frozen-source record does not conform to the published v1.0 JSON Schema.",
    )


def validate_published_legal_version_graph(graph: dict) -> list[dict]:
    try:
        validator = _load_validator(LEGAL_VERSION_GRAPH_SCHEMA_PATH)
    except (OSError, UnicodeError, json.JSONDecodeError, jsonschema.SchemaError):
        return [
            finding(
                "LEGAL_VERSION_GRAPH_SCHEMA_UNAVAILABLE",
                "$",
                "The bundled legal-version-graph v1.0 JSON Schema is unavailable or invalid.",
                "P0",
            )
        ]
    return _collect_errors(
        validator,
        graph,
        code="LEGAL_VERSION_GRAPH_SCHEMA_VALIDATION_ERROR",
        prefix="",
        message="Version graph does not conform to the published v1.0 JSON Schema.",
    )


def validate_published_legal_freshness_check(check: dict) -> list[dict]:
    try:
        validator = _load_validator(LEGAL_FRESHNESS_CHECK_SCHEMA_PATH)
    except (OSError, UnicodeError, json.JSONDecodeError, jsonschema.SchemaError):
        return [
            finding(
                "LEGAL_FRESHNESS_SCHEMA_UNAVAILABLE",
                "$",
                "The bundled legal-freshness-check v1.0 JSON Schema is unavailable or invalid.",
                "P0",
            )
        ]
    return _collect_errors(
        validator,
        check,
        code="LEGAL_FRESHNESS_SCHEMA_VALIDATION_ERROR",
        prefix="",
        message="Freshness check does not conform to the published v1.0 JSON Schema.",
    )


def validate_published_legal_text_diff(diff: dict) -> list[dict]:
    try:
        validator = _load_validator(LEGAL_TEXT_DIFF_SCHEMA_PATH)
    except (OSError, UnicodeError, json.JSONDecodeError, jsonschema.SchemaError):
        return [
            finding(
                "LEGAL_TEXT_DIFF_SCHEMA_UNAVAILABLE",
                "$",
                "The bundled legal-text-diff v1.0 JSON Schema is unavailable or invalid.",
                "P0",
            )
        ]
    return _collect_errors(
        validator,
        diff,
        code="LEGAL_TEXT_DIFF_SCHEMA_VALIDATION_ERROR",
        prefix="",
        message="Legal text diff does not conform to the published v1.0 JSON Schema.",
    )


def validate_published_historical_version_candidate(selection: dict) -> list[dict]:
    try:
        validator = _load_validator(HISTORICAL_VERSION_CANDIDATE_SCHEMA_PATH)
    except (OSError, UnicodeError, json.JSONDecodeError, jsonschema.SchemaError):
        return [
            finding(
                "HISTORICAL_VERSION_SCHEMA_UNAVAILABLE",
                "$",
                "The bundled historical-version-candidate v1.0 JSON Schema is unavailable or invalid.",
                "P0",
            )
        ]
    return _collect_errors(
        validator,
        selection,
        code="HISTORICAL_VERSION_SCHEMA_VALIDATION_ERROR",
        prefix="",
        message="Historical selection does not conform to the published v1.0 JSON Schema.",
    )


def validate_published_official_case_record(record: dict) -> list[dict]:
    try:
        validator = _load_validator(OFFICIAL_CASE_RECORD_SCHEMA_PATH)
    except (OSError, UnicodeError, json.JSONDecodeError, jsonschema.SchemaError):
        return [
            finding(
                "OFFICIAL_CASE_SCHEMA_UNAVAILABLE",
                "$",
                "The bundled official-case-record v1.0 JSON Schema is unavailable or invalid.",
                "P0",
            )
        ]
    return _collect_errors(
        validator,
        record,
        code="OFFICIAL_CASE_SCHEMA_VALIDATION_ERROR",
        prefix="",
        message="Official case record does not conform to the published v1.0 JSON Schema.",
    )


def validate_published_case_workspace(workspace: dict) -> list[dict]:
    try:
        validator = _load_validator(CASE_WORKSPACE_SCHEMA_PATH)
    except (OSError, UnicodeError, json.JSONDecodeError, jsonschema.SchemaError):
        return [
            finding(
                "CASE_WORKSPACE_SCHEMA_UNAVAILABLE",
                "$",
                "The bundled case-workspace v1.0 JSON Schema is unavailable or invalid.",
                "P0",
            )
        ]
    return _collect_errors(
        validator,
        workspace,
        code="CASE_WORKSPACE_SCHEMA_VALIDATION_ERROR",
        prefix="",
        message="Case workspace does not conform to the published v1.0 JSON Schema.",
    )


def validate_published_parser_extraction_record(record: dict) -> list[dict]:
    try:
        validator = _load_validator(PARSER_EXTRACTION_RECORD_SCHEMA_PATH)
    except (OSError, UnicodeError, json.JSONDecodeError, jsonschema.SchemaError):
        return [
            finding(
                "PARSER_EXTRACTION_SCHEMA_UNAVAILABLE",
                "$",
                "The bundled parser-extraction-record v1.0 JSON Schema is unavailable or invalid.",
                "P0",
            )
        ]
    return _collect_errors(
        validator,
        record,
        code="PARSER_EXTRACTION_SCHEMA_VALIDATION_ERROR",
        prefix="",
        message="Parser extraction record does not conform to the published v1.0 JSON Schema.",
    )


def validate_published_fact_candidate_record(record: dict) -> list[dict]:
    try:
        validator = _load_validator(FACT_CANDIDATE_RECORD_SCHEMA_PATH)
    except (OSError, UnicodeError, json.JSONDecodeError, jsonschema.SchemaError):
        return [
            finding(
                "FACT_CANDIDATE_SCHEMA_UNAVAILABLE",
                "$",
                "The bundled fact-candidate-record v1.0 JSON Schema is unavailable or invalid.",
                "P0",
            )
        ]
    return _collect_errors(
        validator,
        record,
        code="FACT_CANDIDATE_SCHEMA_VALIDATION_ERROR",
        prefix="",
        message="Fact candidate record does not conform to the published v1.0 JSON Schema.",
    )


def validate_published_fact_analysis_input(specification: dict) -> list[dict]:
    try:
        validator = _load_validator(FACT_ANALYSIS_INPUT_SCHEMA_PATH)
    except (OSError, UnicodeError, json.JSONDecodeError, jsonschema.SchemaError):
        return [finding("FACT_ANALYSIS_INPUT_SCHEMA_UNAVAILABLE", "$", "The bundled fact-analysis-input v1.0 JSON Schema is unavailable or invalid.", "P0")]
    return _collect_errors(
        validator,
        specification,
        code="FACT_ANALYSIS_INPUT_SCHEMA_VALIDATION_ERROR",
        prefix="",
        message="Fact analysis input does not conform to the published v1.0 JSON Schema.",
    )


def validate_published_fact_analysis_record(record: dict) -> list[dict]:
    try:
        validator = _load_validator(FACT_ANALYSIS_RECORD_SCHEMA_PATH)
    except (OSError, UnicodeError, json.JSONDecodeError, jsonschema.SchemaError):
        return [finding("FACT_ANALYSIS_SCHEMA_UNAVAILABLE", "$", "The bundled fact-analysis-record v1.0 JSON Schema is unavailable or invalid.", "P0")]
    return _collect_errors(
        validator,
        record,
        code="FACT_ANALYSIS_SCHEMA_VALIDATION_ERROR",
        prefix="",
        message="Fact analysis record does not conform to the published v1.0 JSON Schema.",
    )


def validate_published_evidence_review_input(specification: dict) -> list[dict]:
    try:
        validator = _load_validator(EVIDENCE_REVIEW_INPUT_SCHEMA_PATH)
    except (OSError, UnicodeError, json.JSONDecodeError, jsonschema.SchemaError):
        return [finding("EVIDENCE_REVIEW_INPUT_SCHEMA_UNAVAILABLE", "$", "The bundled evidence-review-input v1.0 JSON Schema is unavailable or invalid.", "P0")]
    return _collect_errors(validator, specification, code="EVIDENCE_REVIEW_INPUT_SCHEMA_VALIDATION_ERROR", prefix="", message="Evidence review input does not conform to the published v1.0 JSON Schema.")


def validate_published_evidence_review_record(record: dict) -> list[dict]:
    try:
        validator = _load_validator(EVIDENCE_REVIEW_RECORD_SCHEMA_PATH)
    except (OSError, UnicodeError, json.JSONDecodeError, jsonschema.SchemaError):
        return [finding("EVIDENCE_REVIEW_SCHEMA_UNAVAILABLE", "$", "The bundled evidence-review-record v1.0 JSON Schema is unavailable or invalid.", "P0")]
    return _collect_errors(validator, record, code="EVIDENCE_REVIEW_SCHEMA_VALIDATION_ERROR", prefix="", message="Evidence review record does not conform to the published v1.0 JSON Schema.")


def _validate_monitor_schema(value, path, unavailable_code, validation_code, message):
    try:
        validator = _load_validator(path)
    except (OSError, UnicodeError, json.JSONDecodeError, jsonschema.SchemaError):
        return [finding(unavailable_code, "$", "The bundled legal-monitor v1.0 JSON Schema is unavailable or invalid.", "P0")]
    return _collect_errors(validator, value, code=validation_code, prefix="", message=message)


def validate_published_legal_monitor_definition_input(specification: dict) -> list[dict]:
    return _validate_monitor_schema(specification, LEGAL_MONITOR_DEFINITION_INPUT_SCHEMA_PATH, "LEGAL_MONITOR_DEFINITION_INPUT_SCHEMA_UNAVAILABLE", "LEGAL_MONITOR_DEFINITION_INPUT_SCHEMA_VALIDATION_ERROR", "Legal monitor definition input does not conform to the published v1.0 JSON Schema.")


def validate_published_legal_monitor_definition(definition: dict) -> list[dict]:
    return _validate_monitor_schema(definition, LEGAL_MONITOR_DEFINITION_SCHEMA_PATH, "LEGAL_MONITOR_DEFINITION_SCHEMA_UNAVAILABLE", "LEGAL_MONITOR_DEFINITION_SCHEMA_VALIDATION_ERROR", "Legal monitor definition does not conform to the published v1.0 JSON Schema.")


def validate_published_legal_monitor_run_input(specification: dict) -> list[dict]:
    return _validate_monitor_schema(specification, LEGAL_MONITOR_RUN_INPUT_SCHEMA_PATH, "LEGAL_MONITOR_RUN_INPUT_SCHEMA_UNAVAILABLE", "LEGAL_MONITOR_RUN_INPUT_SCHEMA_VALIDATION_ERROR", "Legal monitor run input does not conform to the published v1.0 JSON Schema.")


def validate_published_legal_monitor_run(record: dict) -> list[dict]:
    return _validate_monitor_schema(record, LEGAL_MONITOR_RUN_SCHEMA_PATH, "LEGAL_MONITOR_RUN_SCHEMA_UNAVAILABLE", "LEGAL_MONITOR_RUN_SCHEMA_VALIDATION_ERROR", "Legal monitor run does not conform to the published v1.0 JSON Schema.")


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
