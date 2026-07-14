"""Semantic validation for a bound v1.3 intake manifest."""

from __future__ import annotations

from finding_model import finding
from integrity_primitives import (
    is_rfc3339_datetime,
    parse_rfc3339_datetime,
    snapshot_matches,
)
from schema_validation import validate_published_intake_schema


INTEGRITY_SEMANTICS = (
    "Hashes and sizes describe bytes read from stable opened file descriptors during "
    "ingestion; they do not prove authenticity, semantic meaning, or later immutability."
)


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
    findings.extend(validate_published_intake_schema(intake_manifest))
    manifest_files = intake_manifest.get("files")
    generator = intake_manifest.get("generator")
    provenance_boundary = intake_manifest.get("provenance_boundary")
    scan_observation = intake_manifest.get("scan_observation")
    if (
        intake_manifest.get("schema_version") != "1.3"
        or intake_manifest.get("integrity_semantics") != INTEGRITY_SEMANTICS
        or intake_manifest.get("canonicalization") != "RFC8785"
        or not isinstance(manifest_files, list)
        or any(not isinstance(item, dict) for item in manifest_files)
        or any(
            not isinstance(item.get("size_bytes"), int)
            or isinstance(item.get("size_bytes"), bool)
            or item.get("size_bytes") < 0
            for item in manifest_files
            if isinstance(item, dict)
        )
        or not isinstance(generator, dict)
        or generator.get("name")
        != "labor-arbitration-skill/intake-manifest-builder"
        or generator.get("version") != "0.3.0"
        or generator.get("build_identity_status") != "UNATTESTED"
        or not isinstance(provenance_boundary, dict)
        or provenance_boundary.get("system_observations")
        != "SYSTEM_OBSERVED_UNATTESTED"
        or provenance_boundary.get("user_declarations") != "NOT_PROVIDED"
        or provenance_boundary.get("generator_authenticity") != "NOT_VERIFIED"
        or not isinstance(scan_observation, dict)
        or not is_rfc3339_datetime(scan_observation.get("started_at"))
        or not is_rfc3339_datetime(scan_observation.get("completed_at"))
        or scan_observation.get("clock_status") != "SYSTEM_CLOCK_UNATTESTED"
        or scan_observation.get("tree_walks_completed") != 2
    ):
        return [
            finding(
                "INTAKE_MANIFEST_INVALID",
                "intake_manifest",
                "The v1.3 intake manifest has an unsupported schema, missing provenance boundary, or malformed records.",
            )
        ]
    _validate_scan_policy(intake_manifest, manifest_files, findings)
    if parse_rfc3339_datetime(
        scan_observation["completed_at"]
    ) < parse_rfc3339_datetime(scan_observation["started_at"]):
        findings.append(
            finding(
                "SCAN_TIME_INTERVAL_INVALID",
                "intake_manifest.scan_observation.completed_at",
                "The scan completion timestamp cannot precede its start timestamp.",
            )
        )
    _validate_hash_bindings(package, intake_manifest, manifest_files, findings)
    _validate_relationships(intake_manifest, manifest_files, findings)
    return findings


def _validate_scan_policy(intake_manifest, manifest_files, findings):
    scan_policy = intake_manifest.get("scan_policy")
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
    if not policy_valid or intake_manifest.get("summary") != expected_summary:
        findings.append(
            finding(
                "INTAKE_SCAN_POLICY_INVALID",
                "intake_manifest.scan_policy",
                "Version 1.3 manifests require bounded scan policy and exact file-count/byte summaries.",
                "P0",
            )
        )


def _validate_hash_bindings(package, intake_manifest, manifest_files, findings):
    manifest_payload = dict(intake_manifest)
    declared_manifest_hash = manifest_payload.pop("manifest_payload_sha256", None)
    if not snapshot_matches(declared_manifest_hash, manifest_payload):
        findings.append(
            finding(
                "INTAKE_MANIFEST_SELF_HASH_MISMATCH",
                "intake_manifest.manifest_payload_sha256",
                "The manifest's RFC 8785 self-hash does not match its payload; this still does not authenticate the generator.",
                "P0",
            )
        )
    if not snapshot_matches(package.get("intake_manifest_sha256"), intake_manifest):
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


def _validate_relationships(intake_manifest, manifest_files, findings):
    expected_relationships = []
    for relationship_type, key in (
        ("DUPLICATE_CONTENT", "sha256"),
        ("HARDLINK_CANDIDATE", "filesystem_identity_sha256"),
    ):
        groups = {}
        for item in manifest_files:
            value = item.get(key)
            raw_id = item.get("raw_id")
            if isinstance(value, str) and isinstance(raw_id, str):
                groups.setdefault(value, []).append(raw_id)
        for value, raw_ids in sorted(groups.items()):
            if len(raw_ids) > 1:
                expected_relationships.append(
                    {
                        "relationship_type": relationship_type,
                        "identity_sha256": value,
                        "raw_ids": sorted(raw_ids),
                        "observation_status": "SYSTEM_OBSERVED_UNATTESTED",
                    }
                )
    if intake_manifest.get("relationships") != expected_relationships:
        findings.append(
            finding(
                "INTAKE_RELATIONSHIPS_INVALID",
                "intake_manifest.relationships",
                "Duplicate-content and hardlink-candidate relationships must be derived exactly from observed file records.",
            )
        )
