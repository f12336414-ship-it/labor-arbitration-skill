"""Select and validate historical legal-version interval candidates."""

from __future__ import annotations

import hashlib

from finding_model import finding
from integrity_primitives import calculate_json_snapshot, parse_calendar_date
from legal_version_graph_policy import validate_legal_version_graph
from schema_validation import validate_published_historical_version_candidate


class HistoricalVersionError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def calculate_historical_selection_snapshot(selection: dict) -> str:
    return calculate_json_snapshot(
        {
            key: value
            for key, value in selection.items()
            if key != "selection_snapshot_sha256"
        }
    )


def _expected_status(candidate_count: int) -> str:
    if candidate_count == 0:
        return "NO_CANDIDATE"
    if candidate_count == 1:
        return "UNIQUE_CANDIDATE"
    return "MULTIPLE_CANDIDATES"


def select_historical_version_candidate(
    graph: dict,
    event_date: str,
    *,
    country: str = "CN",
    province: str = "Beijing",
) -> dict:
    graph_report = validate_legal_version_graph(graph)
    if not graph_report["allowed"]:
        raise HistoricalVersionError(
            "HISTORICAL_VERSION_GRAPH_INVALID",
            "Historical selection requires a structurally valid locked version graph.",
        )
    parsed_event = parse_calendar_date(event_date)
    if parsed_event is None:
        raise HistoricalVersionError(
            "HISTORICAL_VERSION_EVENT_DATE_INVALID",
            "Event date must be a real ISO calendar date.",
        )
    jurisdiction = graph["jurisdiction"]
    if country != jurisdiction["country"] or province != jurisdiction["province"]:
        raise HistoricalVersionError(
            "HISTORICAL_VERSION_JURISDICTION_MISMATCH",
            "Requested jurisdiction must exactly match the version graph.",
        )
    candidates = []
    for version in graph["versions"]:
        effective_from = parse_calendar_date(version["effective_from_candidate"])
        effective_to = parse_calendar_date(version["effective_to_candidate"])
        if effective_from is None:
            continue
        if effective_from <= parsed_event and (
            effective_to is None or parsed_event <= effective_to
        ):
            candidates.append(
                {
                    "version_id": version["version_id"],
                    "content_sha256": version["content_sha256"],
                    "effective_from_candidate": version["effective_from_candidate"],
                    "effective_to_candidate": version["effective_to_candidate"],
                    "match_basis": "EVENT_DATE_INSIDE_DECLARED_CANDIDATE_INTERVAL",
                }
            )
    candidates.sort(key=lambda item: item["version_id"])
    identity = hashlib.sha256(
        (
            graph["graph_snapshot_sha256"]
            + "\x00"
            + event_date
            + "\x00"
            + country
            + "\x00"
            + province
        ).encode("utf-8")
    ).hexdigest()
    selection = {
        "schema_version": "1.0",
        "selection_id": f"HIST-{identity[:24].upper()}",
        "graph_id": graph["graph_id"],
        "graph_snapshot_sha256": graph["graph_snapshot_sha256"],
        "document_id": graph["document_id"],
        "event_date": event_date,
        "jurisdiction": {"country": country, "province": province},
        "selection_status": _expected_status(len(candidates)),
        "candidates": candidates,
        "manual_review_status": "PENDING_INDEPENDENT_LEGAL_REVIEW",
        "limitations": [
            "INTERVAL_MATCH_DOES_NOT_PROVE_LEGAL_APPLICABILITY",
            "VERSION_AND_RELATIONSHIP_CANDIDATES_UNVERIFIED",
            "SPECIAL_TRANSITIONAL_RULES_NOT_EVALUATED",
        ],
    }
    selection["selection_snapshot_sha256"] = calculate_historical_selection_snapshot(
        selection
    )
    if validate_published_historical_version_candidate(selection):
        raise HistoricalVersionError(
            "HISTORICAL_VERSION_GENERATION_INVALID",
            "Generated historical candidate does not satisfy its published schema.",
        )
    return selection


def validate_historical_version_candidate(selection: dict) -> dict:
    findings = validate_published_historical_version_candidate(selection)
    if findings:
        return _report(selection, findings)
    event_date = parse_calendar_date(selection["event_date"])
    if event_date is None:
        findings.append(
            finding(
                "HISTORICAL_VERSION_EVENT_DATE_INVALID",
                "$.event_date",
                "Event date must be a real ISO calendar date.",
                "P0",
            )
        )
    version_ids = [item["version_id"] for item in selection["candidates"]]
    if version_ids != sorted(set(version_ids)):
        findings.append(
            finding(
                "HISTORICAL_VERSION_CANDIDATES_INVALID",
                "$.candidates",
                "Historical candidates must be unique and sorted by version ID.",
                "P0",
            )
        )
    if selection["selection_status"] != _expected_status(len(version_ids)):
        findings.append(
            finding(
                "HISTORICAL_VERSION_STATUS_MISMATCH",
                "$.selection_status",
                "Selection status must match the number of interval candidates.",
                "P0",
            )
        )
    if event_date is not None:
        for index, candidate in enumerate(selection["candidates"]):
            effective_from = parse_calendar_date(candidate["effective_from_candidate"])
            effective_to = parse_calendar_date(candidate["effective_to_candidate"])
            if (
                effective_from is None
                or event_date < effective_from
                or (effective_to is not None and event_date > effective_to)
            ):
                findings.append(
                    finding(
                        "HISTORICAL_VERSION_INTERVAL_MISMATCH",
                        f"$.candidates[{index}]",
                        "Each candidate interval must contain the event date.",
                        "P0",
                    )
                )
    try:
        expected_snapshot = calculate_historical_selection_snapshot(selection)
    except (TypeError, ValueError):
        findings.append(
            finding(
                "HISTORICAL_VERSION_CANONICALIZATION_FAILED",
                "$",
                "Historical selection cannot be canonicalized as RFC 8785 I-JSON.",
                "P0",
            )
        )
    else:
        if selection["selection_snapshot_sha256"] != expected_snapshot:
            findings.append(
                finding(
                    "HISTORICAL_VERSION_SNAPSHOT_MISMATCH",
                    "$.selection_snapshot_sha256",
                    "Historical selection changed without a new RFC 8785 snapshot.",
                    "P0",
                )
            )
    return _report(selection, findings)


def _report(selection: dict, findings: list[dict]) -> dict:
    findings.sort(key=lambda item: (item["code"], item["path"], item["message"]))
    allowed = not findings
    return {
        "allowed": allowed,
        "allowed_scope": "HISTORICAL_INTERVAL_CANDIDATE_ONLY",
        "findings": findings,
        "legal_review_required": True,
        "selection_id": selection.get("selection_id"),
        "selection_status": selection.get("selection_status"),
        "submission_ready": False,
        "validation_scope": {
            "verified": (
                ["EVENT_DATE_INTERVAL_MATCH", "RFC8785_SELECTION_SNAPSHOT"]
                if allowed
                else []
            ),
            "not_verified": [
                "LEGAL_APPLICABILITY",
                "SPECIAL_TRANSITIONAL_RULES",
                "VERSION_LEGAL_STATUS",
            ],
        },
    }
