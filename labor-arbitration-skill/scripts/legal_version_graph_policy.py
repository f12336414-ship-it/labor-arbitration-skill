"""Structural policy for unverified legal-source version candidate graphs."""

from __future__ import annotations

from finding_model import finding
from integrity_primitives import (
    calculate_json_snapshot,
    is_rfc3339_datetime,
    parse_calendar_date,
)
from schema_validation import validate_published_legal_version_graph
from source_fetch_policy import FetchRefusal, validate_fetch_target


ACYCLIC_RELATIONSHIP_TYPES = {"AMENDS", "REPEALS", "SUPERSEDES", "CORRECTS"}
UNVERIFIED_CAPABILITIES = [
    "FROZEN_RECORD_EXISTENCE",
    "LEGAL_APPLICABILITY",
    "LEGAL_CURRENTNESS",
    "RELATIONSHIP_LEGAL_CORRECTNESS",
]


def calculate_legal_version_graph_snapshot(graph: dict) -> str:
    return calculate_json_snapshot(
        {
            key: value
            for key, value in graph.items()
            if key != "graph_snapshot_sha256"
        }
    )


def _duplicates(items: list[dict], field: str) -> set[str]:
    seen = set()
    duplicates = set()
    for item in items:
        value = item[field]
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


def _directed_cycle_exists(relationships: list[dict]) -> bool:
    adjacency = {}
    for relationship in relationships:
        if relationship["relationship_type"] not in ACYCLIC_RELATIONSHIP_TYPES:
            continue
        adjacency.setdefault(relationship["from_version_id"], set()).add(
            relationship["to_version_id"]
        )
    visiting = set()
    visited = set()

    def visit(node):
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        if any(visit(neighbor) for neighbor in adjacency.get(node, set())):
            return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in adjacency)


def validate_legal_version_graph(graph: dict) -> dict:
    findings = validate_published_legal_version_graph(graph)
    if findings:
        return _report(graph, findings)

    if not is_rfc3339_datetime(graph["generated_at"]):
        findings.append(
            finding(
                "DATE_FORMAT_INVALID",
                "$.generated_at",
                "Version graph generation time must be a UTC RFC 3339 timestamp ending in Z.",
                "P0",
            )
        )

    for duplicate in sorted(_duplicates(graph["versions"], "version_id")):
        findings.append(
            finding(
                "LEGAL_VERSION_DUPLICATE_ID",
                "$.versions",
                f"Duplicate version ID: {duplicate}",
                "P0",
            )
        )
    for duplicate in sorted(_duplicates(graph["relationships"], "relationship_id")):
        findings.append(
            finding(
                "LEGAL_RELATIONSHIP_DUPLICATE_ID",
                "$.relationships",
                f"Duplicate relationship ID: {duplicate}",
                "P0",
            )
        )

    version_ids = {version["version_id"] for version in graph["versions"]}
    for index, version in enumerate(graph["versions"]):
        try:
            validate_fetch_target(
                version["source_url"],
                graph["publisher_code"],
                "NORMATIVE_LEGAL_SOURCE",
            )
        except FetchRefusal:
            findings.append(
                finding(
                    "LEGAL_VERSION_SOURCE_NOT_ALLOWLISTED",
                    f"$.versions[{index}].source_url",
                    "Each legal version source URL must match the graph publisher registry.",
                    "P0",
                )
            )
        effective_from = parse_calendar_date(version["effective_from_candidate"])
        effective_to = parse_calendar_date(version["effective_to_candidate"])
        if effective_to is not None and (
            effective_from is None or effective_from > effective_to
        ):
            findings.append(
                finding(
                    "LEGAL_VERSION_DATE_INTERVAL_INVALID",
                    f"$.versions[{index}].effective_to_candidate",
                    "Candidate effective_to must not precede effective_from.",
                    "P0",
                )
            )

    relationship_keys = set()
    for index, relationship in enumerate(graph["relationships"]):
        relationship_path = f"$.relationships[{index}]"
        source_id = relationship["from_version_id"]
        target_id = relationship["to_version_id"]
        if source_id not in version_ids or target_id not in version_ids:
            findings.append(
                finding(
                    "LEGAL_RELATIONSHIP_VERSION_UNKNOWN",
                    relationship_path,
                    "Version relationships must reference versions in the same graph.",
                    "P0",
                )
            )
        if source_id == target_id:
            findings.append(
                finding(
                    "LEGAL_RELATIONSHIP_SELF_REFERENCE",
                    relationship_path,
                    "A legal version cannot relate to itself.",
                    "P0",
                )
            )
        key = (source_id, target_id, relationship["relationship_type"])
        if key in relationship_keys:
            findings.append(
                finding(
                    "LEGAL_RELATIONSHIP_DUPLICATE_EDGE",
                    relationship_path,
                    "Duplicate relationship edge is not allowed.",
                    "P0",
                )
            )
        relationship_keys.add(key)

    if _directed_cycle_exists(graph["relationships"]):
        findings.append(
            finding(
                "LEGAL_VERSION_GRAPH_CYCLE",
                "$.relationships",
                "Directed amendment, repeal, supersession, and correction relationships must be acyclic.",
                "P0",
            )
        )

    try:
        expected_snapshot = calculate_legal_version_graph_snapshot(graph)
    except (TypeError, ValueError):
        findings.append(
            finding(
                "LEGAL_VERSION_GRAPH_CANONICALIZATION_FAILED",
                "$",
                "Version graph cannot be canonicalized as RFC 8785 I-JSON.",
                "P0",
            )
        )
    else:
        if graph["graph_snapshot_sha256"] != expected_snapshot:
            findings.append(
                finding(
                    "LEGAL_VERSION_GRAPH_SNAPSHOT_MISMATCH",
                    "$.graph_snapshot_sha256",
                    "Version graph changed without a new RFC 8785 snapshot.",
                    "P0",
                )
            )
    return _report(graph, findings)


def _report(graph: dict, findings: list[dict]) -> dict:
    findings.sort(key=lambda item: (item["code"], item["path"], item["message"]))
    allowed = not findings
    return {
        "allowed": allowed,
        "allowed_scope": "UNVERIFIED_LEGAL_VERSION_GRAPH_STRUCTURE_ONLY",
        "findings": findings,
        "graph_id": graph.get("graph_id"),
        "legal_review_required": True,
        "submission_ready": False,
        "validation_scope": {
            "verified": [
                "GRAPH_REFERENCE_INTEGRITY",
                "RELATIONSHIP_ACYCLICITY",
                "RFC8785_GRAPH_SNAPSHOT",
                "SOURCE_CANDIDATE_ALLOWLIST",
            ] if allowed else [],
            "not_verified": UNVERIFIED_CAPABILITIES,
        },
    }
