"""Immutable content-addressed storage and offline validation for fetched sources."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from finding_model import finding
from integrity_primitives import calculate_json_snapshot, is_rfc3339_datetime
from schema_validation import validate_published_frozen_source_record
from source_fetch_policy import (
    FETCHER_NAME,
    FETCHER_VERSION,
    FetchedSource,
    FetchRefusal,
    validate_fetch_target,
)
from source_registry import registry_entry


LIMITATIONS = [
    "RESPONSE_BODY_ONLY_HTTP_FRAMING_NOT_RETAINED",
    "SYSTEM_CLOCK_NOT_ATTESTED",
    "SOURCE_AUTHORSHIP_AND_LEGAL_STATUS_NOT_VERIFIED",
    "AUTOMATED_ACCESS_AUTHORIZATION_NOT_ASSERTED",
]


class FrozenSourceStoreError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _source_file_sha256() -> str | None:
    try:
        fetcher_source = Path(__file__).with_name("official_source_fetch.py")
        return hashlib.sha256(fetcher_source.read_bytes()).hexdigest()
    except OSError:
        return None


def _is_reparse(metadata: os.stat_result) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(metadata, "st_file_attributes", 0) & reparse_flag)


def _ensure_safe_directory(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
        metadata = os.lstat(path)
    except OSError as error:
        raise FrozenSourceStoreError(
            "FROZEN_STORE_PATH_UNSAFE",
            f"Frozen-source store directory cannot be created safely: {path.name}",
        ) from error
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode) or _is_reparse(metadata):
        raise FrozenSourceStoreError(
            "FROZEN_STORE_PATH_UNSAFE",
            f"Frozen-source store path is not a plain local directory: {path.name}",
        )


def _write_new_file(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as error:
        raise FrozenSourceStoreError(
            "FROZEN_STORE_WRITE_CONFLICT",
            "Immutable frozen-source path appeared during publication.",
        ) from error
    try:
        with os.fdopen(descriptor, "wb") as target:
            target.write(payload)
            target.flush()
            os.fsync(target.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def calculate_frozen_record_snapshot(record: dict) -> str:
    return calculate_json_snapshot(
        {
            key: value
            for key, value in record.items()
            if key != "record_snapshot_sha256"
        }
    )


def freeze_fetched_source(
    store_root: Path,
    *,
    requested_url: str,
    publisher_code: str,
    purpose: str,
    fetched: FetchedSource,
    fetched_at: str | None = None,
) -> tuple[Path, dict]:
    root = store_root.absolute()
    if os.name == "nt" and str(root).startswith("\\\\"):
        raise FrozenSourceStoreError(
            "FROZEN_STORE_NETWORK_PATH_REFUSED",
            "Frozen-source stores must not use a Windows network path.",
        )
    objects = root / "objects"
    records = root / "records"
    for directory in (root, objects, records):
        _ensure_safe_directory(directory)

    content_sha256 = hashlib.sha256(fetched.body).hexdigest()
    object_directory = objects / content_sha256[:2]
    _ensure_safe_directory(object_directory)
    object_path = object_directory / f"{content_sha256}.bin"
    if object_path.exists():
        metadata = os.lstat(object_path)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or _is_reparse(metadata)
            or metadata.st_size != len(fetched.body)
            or object_path.read_bytes() != fetched.body
        ):
            raise FrozenSourceStoreError(
                "FROZEN_OBJECT_CONFLICT",
                "Existing content-addressed object does not match the fetched bytes.",
            )
    else:
        _write_new_file(object_path, fetched.body)

    timestamp = fetched_at or _utc_now()
    if not is_rfc3339_datetime(timestamp):
        raise FrozenSourceStoreError(
            "FROZEN_FETCH_TIME_INVALID", "Fetch time must be a UTC RFC 3339 timestamp."
        )
    compact_timestamp = timestamp[:19].replace("-", "").replace(":", "") + "Z"
    fetch_identity = calculate_json_snapshot(
        {
            "fetched_at": timestamp,
            "publisher_code": publisher_code,
            "purpose": purpose,
            "requested_url": requested_url,
            "final_url": fetched.final_url,
            "content_sha256": content_sha256,
        }
    )
    fetch_id = f"FETCH-{compact_timestamp}-{fetch_identity[:16]}"
    object_relative_path = PurePosixPath(
        "objects", content_sha256[:2], f"{content_sha256}.bin"
    ).as_posix()
    record = {
        "schema_version": "1.0",
        "fetch_id": fetch_id,
        "fetcher": {
            "name": FETCHER_NAME,
            "version": FETCHER_VERSION,
            "runtime_source_sha256": _source_file_sha256(),
        },
        "publisher_code": publisher_code,
        "purpose": purpose,
        "requested_url": requested_url,
        "final_url": fetched.final_url,
        "fetched_at": timestamp,
        "clock_status": "SYSTEM_CLOCK_UNATTESTED",
        "http_status": fetched.status,
        "media_type": fetched.media_type,
        "content_length": len(fetched.body),
        "content_sha256": content_sha256,
        "object_relative_path": object_relative_path,
        "object_permissions": (
            "WINDOWS_DIRECTORY_ACL_INHERITED_NOT_VERIFIED"
            if os.name == "nt"
            else "POSIX_MODE_0600"
        ),
        "response_headers": fetched.response_headers,
        "network_hops": fetched.network_hops,
        "redirect_count": len(fetched.network_hops) - 1,
        "limitations": LIMITATIONS,
    }
    record["record_snapshot_sha256"] = calculate_frozen_record_snapshot(record)
    schema_findings = validate_published_frozen_source_record(record)
    if schema_findings:
        raise FrozenSourceStoreError(
            "FROZEN_RECORD_GENERATION_INVALID",
            "Generated frozen-source record does not satisfy its published schema.",
        )
    record_path = records / f"{fetch_id}.json"
    payload = (
        json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n"
    ).encode("utf-8")
    if record_path.exists():
        metadata = os.lstat(record_path)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or _is_reparse(metadata)
            or metadata.st_size != len(payload)
            or record_path.read_bytes() != payload
        ):
            raise FrozenSourceStoreError(
                "FROZEN_RECORD_CONFLICT",
                "Existing fetch record does not match this idempotent freeze operation.",
            )
    else:
        _write_new_file(record_path, payload)
    return record_path, record


def _read_stable_object(path: Path, maximum: int) -> bytes:
    try:
        supplied = os.lstat(path)
        if not stat.S_ISREG(supplied.st_mode) or stat.S_ISLNK(supplied.st_mode) or _is_reparse(supplied):
            raise FrozenSourceStoreError(
                "FROZEN_OBJECT_PATH_UNSAFE", "Frozen object must be a plain regular file."
            )
        with path.open("rb") as source:
            opened_before = os.fstat(source.fileno())
            payload = source.read(maximum + 1)
            opened_after = os.fstat(source.fileno())
    except OSError as error:
        raise FrozenSourceStoreError(
            "FROZEN_OBJECT_UNREADABLE", "Frozen object cannot be read safely."
        ) from error
    if len(payload) > maximum:
        raise FrozenSourceStoreError(
            "FROZEN_OBJECT_TOO_LARGE", "Frozen object exceeds its registry limit."
        )
    signature = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns)
    if signature(supplied) != signature(opened_before) or signature(opened_before) != signature(opened_after):
        raise FrozenSourceStoreError(
            "FROZEN_OBJECT_CHANGED_DURING_READ", "Frozen object changed while being read."
        )
    return payload


def validate_frozen_source_record(record: dict, store_root: Path) -> dict:
    findings = validate_published_frozen_source_record(record)
    if findings:
        return _frozen_report(record, findings)

    entry = registry_entry(record["publisher_code"])
    if entry is None or record["purpose"] not in entry["permitted_purposes"]:
        findings.append(
            finding(
                "FROZEN_SOURCE_REGISTRY_MISMATCH",
                "$.publisher_code",
                "Frozen source publisher or purpose is not in the reviewed registry.",
                "P0",
            )
        )
        return _frozen_report(record, findings)

    expected_relative = PurePosixPath(
        "objects",
        record["content_sha256"][:2],
        f"{record['content_sha256']}.bin",
    ).as_posix()
    if record["object_relative_path"] != expected_relative:
        findings.append(
            finding(
                "FROZEN_OBJECT_PATH_MISMATCH",
                "$.object_relative_path",
                "Object path must be derived from the declared content SHA-256.",
                "P0",
            )
        )
    if record["redirect_count"] != len(record["network_hops"]) - 1:
        findings.append(
            finding(
                "FROZEN_REDIRECT_COUNT_MISMATCH",
                "$.redirect_count",
                "Redirect count must match the captured network hops.",
                "P0",
            )
        )
    for index, hop in enumerate(record["network_hops"]):
        try:
            validate_fetch_target(
                hop["url"], record["publisher_code"], record["purpose"]
            )
            if hop["redirect_location"] is not None:
                validate_fetch_target(
                    hop["redirect_location"],
                    record["publisher_code"],
                    record["purpose"],
                )
        except FetchRefusal:
            findings.append(
                finding(
                    "FROZEN_NETWORK_HOP_NOT_ALLOWLISTED",
                    f"$.network_hops[{index}]",
                    "Every stored request and redirect must remain inside the publisher allowlist.",
                    "P0",
                )
            )

    if record["record_snapshot_sha256"] != calculate_frozen_record_snapshot(record):
        findings.append(
            finding(
                "FROZEN_RECORD_SNAPSHOT_MISMATCH",
                "$.record_snapshot_sha256",
                "Frozen-source record changed without a new RFC 8785 snapshot.",
                "P0",
            )
        )

    if not findings:
        absolute_root = store_root.absolute()
        object_path = absolute_root.joinpath(*PurePosixPath(expected_relative).parts)
        for directory in (absolute_root, absolute_root / "objects", object_path.parent):
            try:
                metadata = os.lstat(directory)
            except OSError:
                findings.append(
                    finding(
                        "FROZEN_STORE_PATH_UNSAFE",
                        "$.object_relative_path",
                        "Frozen-source store directory is missing or unreadable.",
                        "P0",
                    )
                )
                break
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or stat.S_ISLNK(metadata.st_mode)
                or _is_reparse(metadata)
            ):
                findings.append(
                    finding(
                        "FROZEN_STORE_PATH_UNSAFE",
                        "$.object_relative_path",
                        "Frozen-source store directories must not be links or reparse points.",
                        "P0",
                    )
                )
                break
    if not findings:
        try:
            payload = _read_stable_object(object_path, entry["max_response_bytes"])
        except FrozenSourceStoreError as error:
            findings.append(finding(error.code, "$.object_relative_path", str(error), "P0"))
        else:
            if len(payload) != record["content_length"]:
                findings.append(
                    finding(
                        "FROZEN_OBJECT_SIZE_MISMATCH",
                        "$.content_length",
                        "Frozen response-body size does not match the record.",
                        "P0",
                    )
                )
            if hashlib.sha256(payload).hexdigest() != record["content_sha256"]:
                findings.append(
                    finding(
                        "FROZEN_OBJECT_HASH_MISMATCH",
                        "$.content_sha256",
                        "Frozen response-body bytes do not match the record hash.",
                        "P0",
                    )
                )
    return _frozen_report(record, findings)


def _frozen_report(record: dict, findings: list[dict]) -> dict:
    findings.sort(key=lambda item: (item["code"], item["path"], item["message"]))
    allowed = not findings
    return {
        "allowed": allowed,
        "allowed_scope": "OFFLINE_FROZEN_RESPONSE_BODY_INTEGRITY_ONLY",
        "content_sha256": record.get("content_sha256"),
        "fetch_id": record.get("fetch_id"),
        "findings": findings,
        "legal_review_required": True,
        "submission_ready": False,
        "validation_scope": {
            "verified": [
                "CONTENT_ADDRESSED_OBJECT_PATH",
                "FROZEN_RESPONSE_BODY_HASH",
                "RECORD_RFC8785_SNAPSHOT",
                "STORED_NETWORK_HOP_ALLOWLIST",
            ] if allowed else [],
            "not_verified": [
                "AUTOMATED_ACCESS_AUTHORIZATION",
                "CLOCK_ATTESTATION",
                "LEGAL_APPLICABILITY",
                "LEGAL_CURRENTNESS",
                "PUBLISHER_AUTHORSHIP",
                "RAW_HTTP_FRAMING",
            ],
        },
    }
