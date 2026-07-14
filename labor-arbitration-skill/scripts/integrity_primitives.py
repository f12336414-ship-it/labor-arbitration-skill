"""Portable integrity primitives shared by local validation entry points."""

from __future__ import annotations

import hashlib
from datetime import date, datetime

import rfc8785


def canonicalize_json(value) -> bytes:
    """Return RFC 8785 bytes or raise when the value is outside I-JSON."""
    return rfc8785.dumps(value)


def calculate_json_snapshot(value) -> str:
    return hashlib.sha256(canonicalize_json(value)).hexdigest()


def snapshot_matches(expected, value) -> bool:
    try:
        return expected == calculate_json_snapshot(value)
    except (rfc8785.CanonicalizationError, TypeError, ValueError):
        return False


def calculation_matches(expected, calculator, *args) -> bool:
    try:
        return expected == calculator(*args)
    except (rfc8785.CanonicalizationError, TypeError, ValueError):
        return False


def is_sha256(value) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value.lower())
    )


def expected_raw_id(relative_path, content_sha256) -> str | None:
    if not isinstance(relative_path, str) or not is_sha256(content_sha256):
        return None
    digest = hashlib.sha256()
    try:
        digest.update(relative_path.encode("utf-8"))
    except UnicodeEncodeError:
        return None
    digest.update(b"\x00")
    digest.update(bytes.fromhex(content_sha256))
    return f"RAW-{digest.hexdigest()}"


def parse_calendar_date(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def is_rfc3339_datetime(value) -> bool:
    return parse_rfc3339_datetime(value) is not None


def parse_rfc3339_datetime(value):
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None
