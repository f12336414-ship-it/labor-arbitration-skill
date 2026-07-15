"""Fail-closed technical policy for legal-source freshness observations."""

from __future__ import annotations

from datetime import datetime, timezone

from finding_model import finding
from integrity_primitives import calculate_json_snapshot, is_rfc3339_datetime
from schema_validation import validate_published_legal_freshness_check
from source_fetch_policy import FetchRefusal, validate_fetch_target


LIMITATIONS = [
    "HISTORICAL_APPLICABILITY",
    "LEGAL_CURRENTNESS",
    "PUBLISHER_AUTHORSHIP",
    "SOURCE_LEGAL_EFFECT",
]


def calculate_legal_freshness_snapshot(check: dict) -> str:
    return calculate_json_snapshot(
        {
            key: value
            for key, value in check.items()
            if key != "check_snapshot_sha256"
        }
    )


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)


def _expected_state(check: dict) -> tuple[str, str]:
    observation = check["observation"]
    if check["network_status"] == "UNAVAILABLE":
        return "UNKNOWN", "UNAVAILABLE_DRAFT_ONLY"
    if observation["content_sha256"] != check["baseline"]["content_sha256"]:
        return "CHANGED", "CHANGE_DETECTED_REVIEW_REQUIRED"
    age = _parse_utc(check["checked_at"]) - _parse_utc(observation["fetched_at"])
    if age.total_seconds() > check["max_age_hours"] * 3600:
        return "UNCHANGED", "STALE_DRAFT_ONLY"
    return "UNCHANGED", "UNCHANGED_RESPONSE_BODY_CANDIDATE"


def validate_legal_freshness_check(check: dict) -> dict:
    findings = validate_published_legal_freshness_check(check)
    if findings:
        return _report(check, findings)

    timestamp_paths = [("$.checked_at", check["checked_at"])]
    timestamp_paths.extend(
        (f"$.{name}.fetched_at", binding["fetched_at"])
        for name, binding in (
            ("baseline", check["baseline"]),
            ("observation", check["observation"]),
        )
        if binding is not None
    )
    invalid_timestamp = False
    for path, value in timestamp_paths:
        if not is_rfc3339_datetime(value):
            invalid_timestamp = True
            findings.append(
                finding(
                    "DATE_FORMAT_INVALID",
                    path,
                    "Freshness timestamps must be UTC RFC 3339 values ending in Z.",
                    "P0",
                )
            )

    for name in ("baseline", "observation"):
        binding = check[name]
        if binding is None:
            continue
        try:
            validate_fetch_target(
                binding["final_url"],
                check["publisher_code"],
                "NORMATIVE_LEGAL_SOURCE",
            )
        except FetchRefusal:
            findings.append(
                finding(
                    "LEGAL_FRESHNESS_SOURCE_NOT_ALLOWLISTED",
                    f"$.{name}.final_url",
                    "Freshness bindings must match the declared official-source publisher.",
                    "P0",
                )
            )

    observation = check["observation"]
    if check["network_status"] == "UNAVAILABLE" and observation is not None:
        findings.append(
            finding(
                "LEGAL_FRESHNESS_OBSERVATION_MISMATCH",
                "$.observation",
                "An unavailable check cannot contain a successful frozen observation.",
                "P0",
            )
        )
    if check["network_status"] == "SUCCESS" and observation is None:
        findings.append(
            finding(
                "LEGAL_FRESHNESS_OBSERVATION_MISMATCH",
                "$.observation",
                "A successful check must bind the later frozen observation.",
                "P0",
            )
        )

    if (
        not invalid_timestamp
        and check["network_status"] == "SUCCESS"
        and observation is not None
        and (
            _parse_utc(observation["fetched_at"])
            <= _parse_utc(check["baseline"]["fetched_at"])
            or observation["fetch_id"] == check["baseline"]["fetch_id"]
            or observation["record_snapshot_sha256"]
            == check["baseline"]["record_snapshot_sha256"]
        )
    ):
        findings.append(
            finding(
                "LEGAL_FRESHNESS_OBSERVATION_NOT_LATER",
                "$.observation",
                "A successful freshness check must bind a distinct observation later than the baseline.",
                "P0",
            )
        )

    expected_change = None
    expected_status = None
    if not invalid_timestamp and (
        check["network_status"] == "UNAVAILABLE" or observation is not None
    ):
        for name, binding in (("baseline", check["baseline"]), ("observation", observation)):
            if binding is not None and _parse_utc(binding["fetched_at"]) > _parse_utc(check["checked_at"]):
                findings.append(
                    finding(
                        "LEGAL_FRESHNESS_TIME_ORDER_INVALID",
                        f"$.{name}.fetched_at",
                        "A frozen observation cannot be later than checked_at.",
                        "P0",
                    )
                )
        expected_change, expected_status = _expected_state(check)
        if (
            check["response_change"] != expected_change
            or check["technical_freshness_status"] != expected_status
        ):
            findings.append(
                finding(
                    "LEGAL_FRESHNESS_DERIVATION_MISMATCH",
                    "$.technical_freshness_status",
                    "Response-change and technical-freshness status must be derived from the bound observations.",
                    "P0",
                )
            )

    try:
        expected_snapshot = calculate_legal_freshness_snapshot(check)
    except (TypeError, ValueError):
        findings.append(
            finding(
                "LEGAL_FRESHNESS_CANONICALIZATION_FAILED",
                "$",
                "Freshness check cannot be canonicalized as RFC 8785 I-JSON.",
                "P0",
            )
        )
    else:
        if check["check_snapshot_sha256"] != expected_snapshot:
            findings.append(
                finding(
                    "LEGAL_FRESHNESS_SNAPSHOT_MISMATCH",
                    "$.check_snapshot_sha256",
                    "Freshness check changed without a new RFC 8785 snapshot.",
                    "P0",
                )
            )
    return _report(check, findings)


def _report(check: dict, findings: list[dict]) -> dict:
    findings.sort(key=lambda item: (item["code"], item["path"], item["message"]))
    allowed = not findings
    status = check.get("technical_freshness_status")
    return {
        "allowed": allowed,
        "allowed_scope": "TECHNICAL_RESPONSE_FRESHNESS_ONLY",
        "allows_formal_promotion": False,
        "check_id": check.get("check_id"),
        "findings": findings,
        "legal_review_required": True,
        "required_output_state": (
            "DRAFT"
            if status in {
                "CHANGE_DETECTED_REVIEW_REQUIRED",
                "UNAVAILABLE_DRAFT_ONLY",
                "STALE_DRAFT_ONLY",
            }
            else "NO_PROMOTION_GRANTED"
        ),
        "submission_ready": False,
        "technical_freshness_status": status,
        "validation_scope": {
            "verified": (
                [
                    "ALLOWLISTED_OBSERVATION_BINDING",
                    "CONTENT_HASH_COMPARISON",
                    "RFC8785_CHECK_SNAPSHOT",
                    "TECHNICAL_MAX_AGE",
                ]
                if allowed
                else []
            ),
            "not_verified": LIMITATIONS,
        },
    }
