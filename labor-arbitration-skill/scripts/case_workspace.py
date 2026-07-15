"""Create and replay-validate a local content-addressed case workspace."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from finding_model import finding
from integrity_primitives import (
    calculate_json_snapshot,
    expected_raw_id,
    is_rfc3339_datetime,
)
from schema_validation import (
    validate_published_case_workspace,
    validate_published_intake_schema,
)


WORKSPACE_FILENAME = "workspace.json"
MAX_WORKSPACE_MANIFEST_BYTES = 10 * 1024 * 1024


class CaseWorkspaceError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError("non-standard JSON number")


def _is_reparse(metadata: os.stat_result) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(metadata, "st_file_attributes", 0) & reparse_flag)


def _plain_directory(path: Path, *, create: bool = False) -> None:
    try:
        if create:
            path.mkdir(parents=True, exist_ok=True)
        metadata = os.lstat(path)
    except OSError as error:
        raise CaseWorkspaceError(
            "CASE_WORKSPACE_PATH_UNSAFE", "Workspace directory is unavailable."
        ) from error
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or _is_reparse(metadata)
    ):
        raise CaseWorkspaceError(
            "CASE_WORKSPACE_PATH_UNSAFE",
            "Case workspaces require plain local directories.",
        )
    if create and os.name != "nt":
        try:
            os.chmod(path, stat.S_IRWXU)
        except OSError as error:
            raise CaseWorkspaceError(
                "CASE_WORKSPACE_PATH_UNSAFE",
                "Workspace directory permissions could not be restricted.",
            ) from error


def _safe_relative_path(value: str) -> PurePosixPath:
    if not isinstance(value, str) or "\\" in value or "\x00" in value:
        raise CaseWorkspaceError(
            "CASE_WORKSPACE_SOURCE_PATH_UNSAFE", "Manifest path is not portable."
        )
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise CaseWorkspaceError(
            "CASE_WORKSPACE_SOURCE_PATH_UNSAFE", "Manifest path escapes the source root."
        )
    if os.name == "nt" and any(":" in part for part in path.parts):
        raise CaseWorkspaceError(
            "CASE_WORKSPACE_SOURCE_PATH_UNSAFE", "Manifest path is invalid on Windows."
        )
    return path


def _paths_overlap(first: Path, second: Path) -> bool:
    first_text = os.path.normcase(str(first.resolve(strict=False)))
    second_text = os.path.normcase(str(second.resolve(strict=False)))
    try:
        common = os.path.commonpath([first_text, second_text])
    except ValueError:
        return False
    return common in {first_text, second_text}


def _read_plain_stable(path: Path, expected_size: int) -> bytes:
    try:
        supplied = os.lstat(path)
        if (
            not stat.S_ISREG(supplied.st_mode)
            or stat.S_ISLNK(supplied.st_mode)
            or _is_reparse(supplied)
        ):
            raise CaseWorkspaceError(
                "CASE_WORKSPACE_SOURCE_FILE_UNSAFE",
                "Every source must remain a plain regular file.",
            )
        with path.open("rb") as source:
            before = os.fstat(source.fileno())
            payload = source.read(expected_size + 1)
            after = os.fstat(source.fileno())
        final = os.lstat(path)
    except CaseWorkspaceError:
        raise
    except OSError as error:
        raise CaseWorkspaceError(
            "CASE_WORKSPACE_SOURCE_FILE_UNREADABLE",
            "Source file cannot be read safely.",
        ) from error
    signature = lambda item: (
        item.st_dev,
        item.st_ino,
        item.st_mode,
        item.st_size,
        item.st_mtime_ns,
    )
    if (
        len(payload) != expected_size
        or signature(supplied) != signature(before)
        or signature(before) != signature(after)
        or signature(after) != signature(final)
    ):
        raise CaseWorkspaceError(
            "CASE_WORKSPACE_SOURCE_CHANGED",
            "Source bytes or identity changed after intake observation.",
        )
    return payload


def _write_new(path: Path, payload: bytes) -> None:
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise CaseWorkspaceError(
            "CASE_WORKSPACE_WRITE_CONFLICT", "Immutable workspace path already exists."
        ) from error
    except OSError as error:
        raise CaseWorkspaceError(
            "CASE_WORKSPACE_WRITE_FAILED", "Workspace file cannot be created."
        ) from error
    try:
        with os.fdopen(descriptor, "wb") as target:
            target.write(payload)
            target.flush()
            os.fsync(target.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _make_read_only(path: Path) -> str:
    try:
        if os.name == "nt":
            os.chmod(path, stat.S_IREAD)
            return "WINDOWS_READONLY_ATTRIBUTE_ACL_UNVERIFIED"
        os.chmod(path, stat.S_IRUSR)
        return "POSIX_MODE_0400"
    except OSError as error:
        raise CaseWorkspaceError(
            "CASE_WORKSPACE_READONLY_FAILED",
            "Workspace object could not be marked read-only.",
        ) from error


def calculate_case_workspace_snapshot(workspace: dict) -> str:
    return calculate_json_snapshot(
        {
            key: value
            for key, value in workspace.items()
            if key != "workspace_snapshot_sha256"
        }
    )


def _validate_intake_manifest(manifest: dict) -> None:
    if validate_published_intake_schema(manifest):
        raise CaseWorkspaceError(
            "CASE_WORKSPACE_INTAKE_INVALID",
            "Workspace creation requires a schema-valid v1.3 intake manifest.",
        )
    payload = dict(manifest)
    declared = payload.pop("manifest_payload_sha256")
    if declared != calculate_json_snapshot(payload):
        raise CaseWorkspaceError(
            "CASE_WORKSPACE_INTAKE_SNAPSHOT_MISMATCH",
            "Intake manifest self-snapshot is invalid.",
        )


def create_case_workspace(
    source_root: Path,
    intake_manifest: dict,
    workspace_root: Path,
    *,
    created_at: str | None = None,
) -> tuple[Path, dict]:
    _validate_intake_manifest(intake_manifest)
    source = source_root.absolute()
    workspace = workspace_root.absolute()
    if os.name == "nt" and (str(source).startswith("\\") or str(workspace).startswith("\\")):
        raise CaseWorkspaceError(
            "CASE_WORKSPACE_NETWORK_PATH_REFUSED",
            "Case source and workspace must not use Windows network paths.",
        )
    _plain_directory(source)
    if _paths_overlap(source, workspace):
        raise CaseWorkspaceError(
            "CASE_WORKSPACE_PATH_OVERLAP",
            "Source and workspace trees must not contain one another.",
        )
    _plain_directory(workspace, create=True)
    manifest_path = workspace / WORKSPACE_FILENAME
    if manifest_path.exists():
        try:
            existing = json.loads(
                manifest_path.read_text(encoding="utf-8"),
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_constant,
            )
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
            raise CaseWorkspaceError(
                "CASE_WORKSPACE_EXISTING_INVALID",
                "Existing workspace manifest is unreadable.",
            ) from error
        report = validate_case_workspace(existing, workspace)
        if (
            report["allowed"]
            and existing["source_intake_manifest_sha256"]
            == calculate_json_snapshot(intake_manifest)
        ):
            return manifest_path, existing
        raise CaseWorkspaceError(
            "CASE_WORKSPACE_EXISTING_INVALID",
            "Existing workspace does not match this intake manifest.",
        )
    allowed_top_level = {"objects"}
    unexpected = {item.name for item in workspace.iterdir()} - allowed_top_level
    if unexpected:
        raise CaseWorkspaceError(
            "CASE_WORKSPACE_NOT_EMPTY",
            "Workspace contains unrelated files and will not be overwritten.",
        )

    objects = workspace / "objects"
    _plain_directory(objects, create=True)
    records = []
    unique_sizes = {}
    seen_raw_ids = set()
    seen_paths = set()
    for source_record in intake_manifest["files"]:
        raw_id = source_record["raw_id"]
        relative = _safe_relative_path(source_record["relative_path"])
        if raw_id in seen_raw_ids or relative.as_posix() in seen_paths:
            raise CaseWorkspaceError(
                "CASE_WORKSPACE_INTAKE_DUPLICATE",
                "Intake raw IDs and source paths must be unique.",
            )
        seen_raw_ids.add(raw_id)
        seen_paths.add(relative.as_posix())
        payload = _read_plain_stable(
            source.joinpath(*relative.parts), source_record["size_bytes"]
        )
        digest = hashlib.sha256(payload).hexdigest()
        if digest != source_record["sha256"]:
            raise CaseWorkspaceError(
                "CASE_WORKSPACE_SOURCE_HASH_MISMATCH",
                "Source bytes no longer match the intake manifest.",
            )
        object_directory = objects / digest[:2]
        _plain_directory(object_directory, create=True)
        object_path = object_directory / f"{digest}.bin"
        if object_path.exists():
            existing = _read_plain_stable(object_path, len(payload))
            if existing != payload:
                raise CaseWorkspaceError(
                    "CASE_WORKSPACE_OBJECT_CONFLICT",
                    "Existing content-addressed object does not match its hash.",
                )
            access = (
                "WINDOWS_READONLY_ATTRIBUTE_ACL_UNVERIFIED"
                if os.name == "nt"
                else "POSIX_MODE_0400"
            )
        else:
            _write_new(object_path, payload)
            access = _make_read_only(object_path)
        relative_object = PurePosixPath(
            "objects", digest[:2], f"{digest}.bin"
        ).as_posix()
        unique_sizes[digest] = len(payload)
        records.append(
            {
                "raw_id": raw_id,
                "source_relative_path": relative.as_posix(),
                "content_sha256": digest,
                "size_bytes": len(payload),
                "object_relative_path": relative_object,
                "object_access_status": access,
                "ingestion_status": "COPIED_AND_HASH_VERIFIED",
            }
        )
    timestamp = created_at or _utc_now()
    if not is_rfc3339_datetime(timestamp):
        raise CaseWorkspaceError(
            "CASE_WORKSPACE_TIME_INVALID",
            "Workspace creation time must be UTC RFC 3339 ending in Z.",
        )
    intake_snapshot = calculate_json_snapshot(intake_manifest)
    workspace_record = {
        "schema_version": "1.0",
        "workspace_id": f"WORKSPACE-{intake_snapshot[:24].upper()}",
        "created_at": timestamp,
        "clock_status": "SYSTEM_CLOCK_UNATTESTED",
        "source_intake_manifest_sha256": intake_snapshot,
        "storage_layout": "CONTENT_ADDRESSED_SHA256_V1",
        "files": records,
        "summary": {
            "file_count": len(records),
            "logical_bytes": sum(item["size_bytes"] for item in records),
            "unique_object_count": len(unique_sizes),
            "stored_bytes": sum(unique_sizes.values()),
        },
        "limitations": [
            "SOURCE_AUTHENTICITY_NOT_VERIFIED",
            "WINDOWS_ACL_OR_POSIX_OWNER_TRUST_NOT_ATTESTED",
            "AT_REST_ENCRYPTION_NOT_IMPLEMENTED",
            "RELATIVE_FILENAMES_MAY_CONTAIN_SENSITIVE_DATA",
        ],
    }
    workspace_record["workspace_snapshot_sha256"] = calculate_case_workspace_snapshot(
        workspace_record
    )
    if validate_published_case_workspace(workspace_record):
        raise CaseWorkspaceError(
            "CASE_WORKSPACE_GENERATION_INVALID",
            "Generated workspace manifest does not satisfy its published schema.",
        )
    manifest_payload = (
        json.dumps(
            workspace_record,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    _write_new(manifest_path, manifest_payload)
    _make_read_only(manifest_path)
    return manifest_path, workspace_record


def _read_workspace_object(path: Path, maximum: int) -> bytes:
    try:
        return _read_plain_stable(path, maximum)
    except CaseWorkspaceError as error:
        raise CaseWorkspaceError(
            "CASE_WORKSPACE_OBJECT_CHANGED_OR_SIZE_MISMATCH",
            "Workspace object is unsafe, missing, unstable, or has an unexpected size.",
        ) from error


def _enumerate_object_paths(objects_root: Path, limit: int) -> set[str]:
    found = set()
    try:
        with os.scandir(objects_root) as prefixes:
            for prefix in prefixes:
                metadata = prefix.stat(follow_symlinks=False)
                if (
                    not prefix.is_dir(follow_symlinks=False)
                    or stat.S_ISLNK(metadata.st_mode)
                    or _is_reparse(metadata)
                    or len(prefix.name) != 2
                ):
                    raise CaseWorkspaceError(
                        "CASE_WORKSPACE_OBJECT_TREE_UNSAFE",
                        "Object store contains an unsafe prefix entry.",
                    )
                with os.scandir(prefix.path) as objects:
                    for item in objects:
                        item_metadata = item.stat(follow_symlinks=False)
                        if (
                            not item.is_file(follow_symlinks=False)
                            or stat.S_ISLNK(item_metadata.st_mode)
                            or _is_reparse(item_metadata)
                        ):
                            raise CaseWorkspaceError(
                                "CASE_WORKSPACE_OBJECT_TREE_UNSAFE",
                                "Object store contains an unsafe object entry.",
                            )
                        found.add(
                            PurePosixPath(
                                "objects", prefix.name, item.name
                            ).as_posix()
                        )
                        if len(found) > limit:
                            raise CaseWorkspaceError(
                                "CASE_WORKSPACE_UNEXPECTED_OBJECT",
                                "Object store contains more files than the workspace manifest.",
                            )
    except CaseWorkspaceError:
        raise
    except OSError as error:
        raise CaseWorkspaceError(
            "CASE_WORKSPACE_OBJECT_TREE_UNSAFE",
            "Object store cannot be enumerated safely.",
        ) from error
    return found


def validate_case_workspace(workspace_record: dict, workspace_root: Path) -> dict:
    findings = validate_published_case_workspace(workspace_record)
    if findings:
        return _report(workspace_record, findings)
    if not is_rfc3339_datetime(workspace_record["created_at"]):
        findings.append(
            finding(
                "DATE_FORMAT_INVALID",
                "$.created_at",
                "Workspace time must be UTC RFC 3339 ending in Z.",
                "P0",
            )
        )
    files = workspace_record["files"]
    raw_ids = [item["raw_id"] for item in files]
    source_paths = [item["source_relative_path"] for item in files]
    if len(raw_ids) != len(set(raw_ids)) or len(source_paths) != len(set(source_paths)):
        findings.append(
            finding(
                "CASE_WORKSPACE_FILE_IDENTITY_DUPLICATE",
                "$.files",
                "Workspace raw IDs and source paths must be unique.",
                "P0",
            )
        )
    expected_workspace_id = (
        f"WORKSPACE-{workspace_record['source_intake_manifest_sha256'][:24].upper()}"
    )
    if workspace_record["workspace_id"] != expected_workspace_id:
        findings.append(
            finding(
                "CASE_WORKSPACE_ID_MISMATCH",
                "$.workspace_id",
                "Workspace ID must be derived from the bound intake-manifest snapshot.",
                "P0",
            )
        )
    for index, item in enumerate(files):
        try:
            relative = _safe_relative_path(item["source_relative_path"])
        except CaseWorkspaceError:
            findings.append(
                finding(
                    "CASE_WORKSPACE_SOURCE_PATH_UNSAFE",
                    f"$.files[{index}].source_relative_path",
                    "Workspace source paths must remain portable relative paths.",
                    "P0",
                )
            )
        else:
            if expected_raw_id(relative.as_posix(), item["content_sha256"]) != item[
                "raw_id"
            ]:
                findings.append(
                    finding(
                        "CASE_WORKSPACE_RAW_ID_MISMATCH",
                        f"$.files[{index}].raw_id",
                        "Raw ID must bind the exact source-relative path and content hash.",
                        "P0",
                    )
                )
    expected_objects = set()
    unique_sizes = {}
    root = workspace_root.absolute()
    try:
        _plain_directory(root)
        _plain_directory(root / "objects")
    except CaseWorkspaceError as error:
        findings.append(finding(error.code, "$", str(error), "P0"))
    if not findings:
        for index, item in enumerate(files):
            digest = item["content_sha256"]
            expected_relative = PurePosixPath(
                "objects", digest[:2], f"{digest}.bin"
            ).as_posix()
            if item["object_relative_path"] != expected_relative:
                findings.append(
                    finding(
                        "CASE_WORKSPACE_OBJECT_PATH_MISMATCH",
                        f"$.files[{index}].object_relative_path",
                        "Object path must be derived from the content hash.",
                        "P0",
                    )
                )
                continue
            expected_objects.add(expected_relative)
            unique_sizes[digest] = item["size_bytes"]
            object_path = root.joinpath(*PurePosixPath(expected_relative).parts)
            try:
                payload = _read_workspace_object(object_path, item["size_bytes"])
            except CaseWorkspaceError as error:
                findings.append(
                    finding(error.code, f"$.files[{index}].object_relative_path", str(error), "P0")
                )
                continue
            if hashlib.sha256(payload).hexdigest() != digest:
                findings.append(
                    finding(
                        "CASE_WORKSPACE_OBJECT_HASH_MISMATCH",
                        f"$.files[{index}].content_sha256",
                        "Workspace object bytes do not match the manifest hash.",
                        "P0",
                    )
                )
            mode = os.lstat(object_path).st_mode
            if os.name != "nt" and stat.S_IMODE(mode) != stat.S_IRUSR:
                findings.append(
                    finding(
                        "CASE_WORKSPACE_OBJECT_WRITABLE",
                        f"$.files[{index}].object_access_status",
                        "POSIX workspace objects must remain mode 0400.",
                        "P0",
                    )
                )
        try:
            actual_objects = _enumerate_object_paths(root / "objects", len(expected_objects))
        except CaseWorkspaceError as error:
            findings.append(finding(error.code, "$.files", str(error), "P0"))
        else:
            if actual_objects != expected_objects:
                findings.append(
                    finding(
                        "CASE_WORKSPACE_UNEXPECTED_OBJECT",
                        "$.files",
                        "Object store contents must exactly match the workspace manifest.",
                        "P0",
                    )
                )
    expected_summary = {
        "file_count": len(files),
        "logical_bytes": sum(item["size_bytes"] for item in files),
        "unique_object_count": len(unique_sizes),
        "stored_bytes": sum(unique_sizes.values()),
    }
    if workspace_record["summary"] != expected_summary:
        findings.append(
            finding(
                "CASE_WORKSPACE_SUMMARY_MISMATCH",
                "$.summary",
                "Workspace summary must match its file and unique-object records.",
                "P0",
            )
        )
    try:
        expected_snapshot = calculate_case_workspace_snapshot(workspace_record)
    except (TypeError, ValueError):
        findings.append(
            finding(
                "CASE_WORKSPACE_CANONICALIZATION_FAILED",
                "$",
                "Workspace manifest cannot be canonicalized as RFC 8785 I-JSON.",
                "P0",
            )
        )
    else:
        if workspace_record["workspace_snapshot_sha256"] != expected_snapshot:
            findings.append(
                finding(
                    "CASE_WORKSPACE_SNAPSHOT_MISMATCH",
                    "$.workspace_snapshot_sha256",
                    "Workspace manifest changed without a new RFC 8785 snapshot.",
                    "P0",
                )
            )
    return _report(workspace_record, findings)


def _report(workspace_record: dict, findings: list[dict]) -> dict:
    findings.sort(key=lambda item: (item["code"], item["path"], item["message"]))
    allowed = not findings
    return {
        "allowed": allowed,
        "allowed_scope": "LOCAL_CASE_WORKSPACE_BYTE_INTEGRITY_ONLY",
        "findings": findings,
        "legal_review_required": True,
        "submission_ready": False,
        "workspace_id": workspace_record.get("workspace_id"),
        "validation_scope": {
            "verified": (
                [
                    "CONTENT_ADDRESSED_OBJECTS",
                    "OBJECT_HASH_REPLAY",
                    "RFC8785_WORKSPACE_SNAPSHOT",
                    "WORKSPACE_OBJECT_SET",
                ]
                if allowed
                else []
            ),
            "not_verified": [
                "AT_REST_ENCRYPTION",
                "EVIDENCE_AUTHENTICITY",
                "FILESYSTEM_OWNER_OR_ACL_TRUST",
                "SOURCE_PROVENANCE",
            ],
        },
    }
