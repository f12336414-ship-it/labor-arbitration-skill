"""Cross-process, fail-closed minimum-interval ledger for official case fetches."""

from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path

from integrity_primitives import calculate_json_snapshot, parse_rfc3339_datetime
from source_registry import registry_entry


LEDGER_FILENAME = "official-case-rate-limit.json"
LOCK_FILENAME = ".official-case-rate-limit.lock"
MAX_LEDGER_BYTES = 64 * 1024


class CaseCollectionRefusal(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError("non-standard JSON number")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _is_reparse(metadata: os.stat_result) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(metadata, "st_file_attributes", 0) & reparse_flag)


def _ensure_plain_directory(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
        metadata = os.lstat(path)
    except OSError as error:
        raise CaseCollectionRefusal(
            "CASE_RATE_LIMIT_PATH_UNSAFE", "Rate-limit directory is unavailable."
        ) from error
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or _is_reparse(metadata)
    ):
        raise CaseCollectionRefusal(
            "CASE_RATE_LIMIT_PATH_UNSAFE",
            "Rate-limit state must use a plain local directory.",
        )


def calculate_case_collection_ledger_snapshot(ledger: dict) -> str:
    return calculate_json_snapshot(
        {key: value for key, value in ledger.items() if key != "ledger_snapshot_sha256"}
    )


def _load_ledger(path: Path) -> dict:
    if not path.exists():
        ledger = {
            "schema_version": "1.0",
            "clock_status": "SYSTEM_CLOCK_UNATTESTED",
            "entries": {},
            "limitations": [
                "ONLY_THIS_LEDGER_CLIENT_IS_RATE_LIMITED",
                "SYSTEM_CLOCK_NOT_ATTESTED",
                "AUTOMATED_ACCESS_AUTHORIZATION_NOT_ASSERTED",
            ],
        }
        ledger["ledger_snapshot_sha256"] = calculate_case_collection_ledger_snapshot(
            ledger
        )
        return ledger
    try:
        metadata = os.lstat(path)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or _is_reparse(metadata)
            or metadata.st_size > MAX_LEDGER_BYTES
        ):
            raise CaseCollectionRefusal(
                "CASE_RATE_LIMIT_LEDGER_INVALID", "Rate-limit ledger path is unsafe."
            )
        payload = path.read_bytes()
        ledger = json.loads(
            payload,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except CaseCollectionRefusal:
        raise
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        raise CaseCollectionRefusal(
            "CASE_RATE_LIMIT_LEDGER_INVALID", "Rate-limit ledger is unreadable."
        ) from error
    try:
        valid_snapshot = ledger.get(
            "ledger_snapshot_sha256"
        ) == calculate_case_collection_ledger_snapshot(ledger)
    except (AttributeError, TypeError, ValueError):
        valid_snapshot = False
    if (
        not isinstance(ledger, dict)
        or ledger.get("schema_version") != "1.0"
        or ledger.get("clock_status") != "SYSTEM_CLOCK_UNATTESTED"
        or not isinstance(ledger.get("entries"), dict)
        or ledger.get("limitations")
        != [
            "ONLY_THIS_LEDGER_CLIENT_IS_RATE_LIMITED",
            "SYSTEM_CLOCK_NOT_ATTESTED",
            "AUTOMATED_ACCESS_AUTHORIZATION_NOT_ASSERTED",
        ]
        or not valid_snapshot
    ):
        raise CaseCollectionRefusal(
            "CASE_RATE_LIMIT_LEDGER_INVALID",
            "Rate-limit ledger structure or snapshot is invalid.",
        )
    for code, entry in ledger["entries"].items():
        if (
            registry_entry(code) is None
            or not isinstance(entry, dict)
            or set(entry) != {"last_reserved_at", "reservation_id"}
            or parse_rfc3339_datetime(entry["last_reserved_at"]) is None
            or not isinstance(entry["reservation_id"], str)
            or not entry["reservation_id"].startswith("CASE-RESERVE-")
        ):
            raise CaseCollectionRefusal(
                "CASE_RATE_LIMIT_LEDGER_INVALID",
                "Rate-limit ledger contains an invalid publisher reservation.",
            )
    return ledger


def _write_ledger(path: Path, ledger: dict) -> None:
    payload = (
        json.dumps(ledger, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n"
    ).encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = None
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as target:
            descriptor = None
            target.write(payload)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
    except OSError as error:
        raise CaseCollectionRefusal(
            "CASE_RATE_LIMIT_LEDGER_WRITE_FAILED",
            "Rate-limit reservation could not be persisted.",
        ) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def reserve_official_case_fetch(
    ledger_root: Path,
    publisher_code: str,
    *,
    reserved_at: str | None = None,
) -> dict:
    entry = registry_entry(publisher_code)
    if entry is None or "OFFICIAL_CASE" not in entry["permitted_purposes"]:
        raise CaseCollectionRefusal(
            "CASE_COLLECTION_PUBLISHER_NOT_ALLOWED",
            "Publisher is not registered for official-case collection.",
        )
    timestamp = reserved_at or _utc_now()
    parsed_now = parse_rfc3339_datetime(timestamp)
    if parsed_now is None:
        raise CaseCollectionRefusal(
            "CASE_RATE_LIMIT_TIME_INVALID",
            "Reservation time must be a UTC RFC 3339 timestamp ending in Z.",
        )
    root = ledger_root.absolute()
    _ensure_plain_directory(root)
    lock_path = root / LOCK_FILENAME
    try:
        lock_descriptor = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise CaseCollectionRefusal(
            "CASE_RATE_LIMIT_BUSY",
            "Another official-case reservation is in progress; retry later.",
        ) from error
    except OSError as error:
        raise CaseCollectionRefusal(
            "CASE_RATE_LIMIT_PATH_UNSAFE", "Rate-limit lock cannot be created."
        ) from error
    try:
        os.close(lock_descriptor)
        ledger_path = root / LEDGER_FILENAME
        ledger = _load_ledger(ledger_path)
        previous = ledger["entries"].get(publisher_code)
        if previous is not None:
            parsed_previous = parse_rfc3339_datetime(previous["last_reserved_at"])
            elapsed = (parsed_now - parsed_previous).total_seconds()
            if elapsed < 0:
                raise CaseCollectionRefusal(
                    "CASE_RATE_LIMIT_CLOCK_ROLLBACK",
                    "System clock moved backwards relative to the last reservation.",
                )
            if elapsed < entry["minimum_interval_seconds"]:
                raise CaseCollectionRefusal(
                    "CASE_RATE_LIMIT_EXCEEDED",
                    "Minimum publisher interval has not elapsed.",
                )
        identity = calculate_json_snapshot(
            {"publisher_code": publisher_code, "reserved_at": timestamp}
        )
        reservation = {
            "last_reserved_at": timestamp,
            "reservation_id": f"CASE-RESERVE-{identity[:24].upper()}",
        }
        ledger["entries"][publisher_code] = reservation
        ledger["ledger_snapshot_sha256"] = calculate_case_collection_ledger_snapshot(
            ledger
        )
        _write_ledger(ledger_path, ledger)
        return {
            **reservation,
            "minimum_interval_seconds": entry["minimum_interval_seconds"],
            "ledger_snapshot_sha256": ledger["ledger_snapshot_sha256"],
        }
    finally:
        lock_path.unlink(missing_ok=True)
