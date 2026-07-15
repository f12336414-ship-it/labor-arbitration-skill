"""Fail-closed policy for unverified official-source candidates."""

from __future__ import annotations

from urllib.parse import urlsplit

from finding_model import finding
from integrity_primitives import is_rfc3339_datetime, is_sha256
from source_registry import OFFICIAL_SOURCE_REGISTRY


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
OFFICIAL_SOURCE_CANDIDATE_HOSTS = {
    publisher_code: set(entry["hosts"])
    for publisher_code, entry in OFFICIAL_SOURCE_REGISTRY.items()
}


def source_candidate_host_is_allowlisted(source: dict) -> bool:
    allowed_hosts = OFFICIAL_SOURCE_CANDIDATE_HOSTS.get(
        source.get("publisher_code"), set()
    )
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


def validate_source_artifact(source: dict, source_index: int, package: dict):
    findings = []
    path = f"source_artifacts[{source_index}]"
    missing = sorted(field for field in REQUIRED_SOURCE_FIELDS if not source.get(field))
    if missing:
        findings.append(
            finding(
                "SOURCE_METADATA_INCOMPLETE",
                path,
                "Missing source metadata: " + ", ".join(missing),
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
    if not source_candidate_host_is_allowlisted(source):
        findings.append(
            finding(
                "SOURCE_HOST_NOT_ALLOWLISTED",
                f"{path}.canonical_url",
                "The URL must match the declared publisher's official-source candidate allowlist; this check does not verify page content or legal authority.",
                "P0",
            )
        )
    if source.get("content_hash_status") != "DECLARED_UNVERIFIED":
        findings.append(
            finding(
                "SOURCE_HASH_STATUS_INVALID",
                f"{path}.content_hash_status",
                "No authenticated fetch pipeline is implemented, so source hashes must remain DECLARED_UNVERIFIED.",
                "P0",
            )
        )
    if not is_rfc3339_datetime(source.get("retrieved_at")):
        findings.append(
            finding(
                "DATE_FORMAT_INVALID",
                f"{path}.retrieved_at",
                "Source retrieval time must be an RFC 3339 UTC timestamp ending in Z.",
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
