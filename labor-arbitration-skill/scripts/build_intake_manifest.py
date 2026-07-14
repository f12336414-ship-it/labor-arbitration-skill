#!/usr/bin/env python3
"""Build a bounded, race-aware ingestion-integrity manifest for a local directory."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import stat
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import rfc8785


DEFAULT_MAX_FILES = 10_000
DEFAULT_MAX_FILE_BYTES = 100 * 1024 * 1024
DEFAULT_MAX_TOTAL_BYTES = 1024 * 1024 * 1024
DEFAULT_MAX_DEPTH = 20
DEFAULT_TIMEOUT_SECONDS = 60.0
FILE_ATTRIBUTE_REPARSE_POINT = getattr(
    stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x0400
)
INTEGRITY_SEMANTICS = (
    "Hashes and sizes describe bytes read from stable opened file descriptors during "
    "ingestion; they do not prove authenticity, semantic meaning, or later immutability."
)
GENERATOR_NAME = "labor-arbitration-skill/intake-manifest-builder"
GENERATOR_VERSION = "0.3.0"
CANONICALIZATION_ALGORITHM = "RFC8785"
MEDIA_TYPE_BY_EXTENSION = {
    ".gif": "image/gif",
    ".gz": "application/gzip",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".txt": "text/plain",
    ".zip": "application/zip",
}


class ScanSafetyError(RuntimeError):
    """Raised when ingestion cannot safely produce a complete manifest."""


def configure_utf8_stdio() -> None:
    """Make CLI diagnostics independent of the host console code page."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="strict")


def ensure_before_deadline(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise ScanSafetyError("SCAN_TIMEOUT: scan deadline expired.")


def is_reparse_point(metadata: os.stat_result) -> bool:
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0)
        & FILE_ATTRIBUTE_REPARSE_POINT
    )


def metadata_signature(metadata: os.stat_result) -> tuple[int, ...]:
    # Windows deprecated st_ctime_ns and may change its meaning between Python
    # versions. File identity, type, size, mtime, and observed bytes provide the
    # portable content-stability boundary used by this scanner.
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_size,
        metadata.st_mtime_ns,
    )


def entry_observation_signature(metadata: os.stat_result) -> tuple[int, ...]:
    """Fields consistently populated by both Windows DirEntry.stat and fstat."""
    return (
        stat.S_IFMT(metadata.st_mode),
        metadata.st_size,
        metadata.st_mtime_ns,
    )


def tree_entry_signature(metadata: os.stat_result) -> tuple[int, ...]:
    """Identity and content metadata compared across two DirEntry tree walks."""
    return (
        metadata.st_dev,
        metadata.st_ino,
        stat.S_IFMT(metadata.st_mode),
        metadata.st_size,
        metadata.st_mtime_ns,
    )


def utc_now_rfc3339() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def sha256_file_if_available(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def utf8_path_bytes(relative_path: str) -> bytes:
    try:
        return relative_path.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ScanSafetyError(
            "SCAN_FILENAME_UNICODE_INVALID: a relative path is outside I-JSON Unicode."
        ) from error


def stable_raw_id(relative_path: str, content_sha256: str) -> str:
    identity = hashlib.sha256()
    identity.update(utf8_path_bytes(relative_path))
    identity.update(b"\x00")
    identity.update(bytes.fromhex(content_sha256))
    return f"RAW-{identity.hexdigest()}"


def detect_media_type(prefix: bytes) -> str:
    signatures = (
        (b"%PDF-", "application/pdf"),
        (b"\x89PNG\r\n\x1a\n", "image/png"),
        (b"\xff\xd8\xff", "image/jpeg"),
        (b"GIF87a", "image/gif"),
        (b"GIF89a", "image/gif"),
        (b"PK\x03\x04", "application/zip"),
        (b"PK\x05\x06", "application/zip"),
        (b"PK\x07\x08", "application/zip"),
        (b"\x1f\x8b", "application/gzip"),
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "application/x-ole-storage"),
        (b"MZ", "application/vnd.microsoft.portable-executable"),
    )
    for signature, media_type in signatures:
        if prefix.startswith(signature):
            return media_type
    if b"\x00" not in prefix:
        try:
            prefix.decode("utf-8")
        except UnicodeDecodeError:
            pass
        else:
            return "text/plain"
    return "application/octet-stream"


def filesystem_identity_sha256(signature: tuple[int, ...]) -> str:
    return hashlib.sha256(f"{signature[0]}:{signature[1]}".encode("ascii")).hexdigest()


def build_relationships(files: list[dict]) -> list[dict]:
    relationships = []
    for relationship_type, key in (
        ("DUPLICATE_CONTENT", "sha256"),
        ("HARDLINK_CANDIDATE", "filesystem_identity_sha256"),
    ):
        groups: dict[str, list[str]] = {}
        for item in files:
            groups.setdefault(item[key], []).append(item["raw_id"])
        for value, raw_ids in sorted(groups.items()):
            if len(raw_ids) > 1:
                relationships.append(
                    {
                        "relationship_type": relationship_type,
                        "identity_sha256": value,
                        "raw_ids": sorted(raw_ids),
                        "observation_status": "SYSTEM_OBSERVED_UNATTESTED",
                    }
                )
    return relationships


def enumerate_regular_files(
    input_directory: Path,
    max_files: int,
    max_depth: int,
    deadline: float,
) -> list[tuple[Path, os.stat_result]]:
    files: list[tuple[Path, os.stat_result]] = []
    pending_directories = [(input_directory, 0)]
    while pending_directories:
        ensure_before_deadline(deadline)
        directory, depth = pending_directories.pop()
        try:
            with os.scandir(directory) as scanner:
                entries = sorted(scanner, key=lambda item: item.name)
        except OSError as error:
            raise ScanSafetyError(
                f"SCAN_DIRECTORY_UNREADABLE: {directory.name}: {error}"
            ) from error
        for entry in entries:
            ensure_before_deadline(deadline)
            path = Path(entry.path)
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError as error:
                raise ScanSafetyError(
                    f"SCAN_ENTRY_UNREADABLE: {entry.name}: {error}"
                ) from error
            if is_reparse_point(metadata):
                raise ScanSafetyError(
                    f"SCAN_REPARSE_POINT_REFUSED: {entry.name}"
                )
            if stat.S_ISDIR(metadata.st_mode):
                child_depth = depth + 1
                if child_depth > max_depth:
                    raise ScanSafetyError(
                        f"SCAN_DEPTH_LIMIT_EXCEEDED: {entry.name} exceeds depth {max_depth}."
                    )
                if os.path.ismount(path):
                    raise ScanSafetyError(
                        f"SCAN_MOUNT_POINT_REFUSED: {entry.name}"
                    )
                pending_directories.append((path, child_depth))
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise ScanSafetyError(
                    f"SCAN_SPECIAL_FILE_REFUSED: {entry.name}"
                )
            files.append((path, metadata))
            if len(files) > max_files:
                raise ScanSafetyError(
                    f"SCAN_FILE_LIMIT_EXCEEDED: found more than {max_files} files."
                )
    return sorted(
        files,
        key=lambda item: item[0].relative_to(input_directory).as_posix(),
    )


def hash_stable_file(
    path: Path,
    expected_metadata: os.stat_result,
    max_file_bytes: int,
    deadline: float,
) -> tuple[str, int, tuple[int, ...], bytes]:
    digest = hashlib.sha256()
    bytes_read = 0
    prefix = bytearray()
    try:
        with path.open("rb") as source:
            opened_metadata = os.fstat(source.fileno())
            if (
                is_reparse_point(opened_metadata)
                or not stat.S_ISREG(opened_metadata.st_mode)
                or entry_observation_signature(opened_metadata)
                != entry_observation_signature(expected_metadata)
            ):
                raise ScanSafetyError(
                    f"SCAN_FILE_CHANGED_DURING_READ: {path.name}"
                )
            if opened_metadata.st_size > max_file_bytes:
                raise ScanSafetyError(
                    f"SCAN_FILE_SIZE_LIMIT_EXCEEDED: {path.name} exceeds {max_file_bytes} bytes."
                )
            while True:
                ensure_before_deadline(deadline)
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                bytes_read += len(chunk)
                if bytes_read > max_file_bytes:
                    raise ScanSafetyError(
                        f"SCAN_FILE_SIZE_LIMIT_EXCEEDED: {path.name} exceeds {max_file_bytes} bytes."
                    )
                digest.update(chunk)
                if len(prefix) < 8192:
                    prefix.extend(chunk[: 8192 - len(prefix)])
            finished_metadata = os.fstat(source.fileno())
    except ScanSafetyError:
        raise
    except OSError as error:
        raise ScanSafetyError(
            f"SCAN_FILE_UNREADABLE: {path.name}: {error}"
        ) from error
    if (
        bytes_read != opened_metadata.st_size
        or metadata_signature(finished_metadata)
        != metadata_signature(opened_metadata)
    ):
        raise ScanSafetyError(f"SCAN_FILE_CHANGED_DURING_READ: {path.name}")
    try:
        path_metadata = os.lstat(path)
    except OSError as error:
        raise ScanSafetyError(
            f"SCAN_FILE_CHANGED_DURING_READ: {path.name}: {error}"
        ) from error
    if (
        is_reparse_point(path_metadata)
        or metadata_signature(path_metadata) != metadata_signature(opened_metadata)
    ):
        raise ScanSafetyError(f"SCAN_FILE_CHANGED_DURING_READ: {path.name}")
    return (
        digest.hexdigest(),
        bytes_read,
        metadata_signature(opened_metadata),
        bytes(prefix),
    )


def build_manifest(
    input_directory: Path,
    max_files: int = DEFAULT_MAX_FILES,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    max_depth: int = DEFAULT_MAX_DEPTH,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict:
    started_at = utc_now_rfc3339()
    repository_lock = Path(__file__).resolve().parents[2] / "requirements.lock"
    dependency_contract = (
        repository_lock
        if repository_lock.is_file()
        else Path(__file__).resolve().parents[1] / "requirements.txt"
    )
    deadline = time.monotonic() + timeout_seconds
    ensure_before_deadline(deadline)
    files = enumerate_regular_files(
        input_directory, max_files=max_files, max_depth=max_depth, deadline=deadline
    )
    manifest_files = []
    observed_signatures = []
    total_bytes = 0
    initial_tree = {
        path.relative_to(input_directory).as_posix(): tree_entry_signature(metadata)
        for path, metadata in files
    }
    for path, expected_metadata in files:
        checksum, size_bytes, signature, prefix = hash_stable_file(
            path,
            expected_metadata,
            max_file_bytes=max_file_bytes,
            deadline=deadline,
        )
        total_bytes += size_bytes
        if total_bytes > max_total_bytes:
            raise ScanSafetyError(
                f"SCAN_TOTAL_SIZE_LIMIT_EXCEEDED: files exceed {max_total_bytes} bytes."
            )
        relative_path = path.relative_to(input_directory).as_posix()
        relative_path_bytes = utf8_path_bytes(relative_path)
        extension = path.suffix.lower()
        detected_media_type = detect_media_type(prefix)
        expected_media_type = MEDIA_TYPE_BY_EXTENSION.get(extension)
        manifest_files.append(
            {
                "raw_id": stable_raw_id(relative_path, checksum),
                "relative_path": relative_path,
                "path_sha256": hashlib.sha256(relative_path_bytes).hexdigest(),
                "extension": path.suffix.lower(),
                "detected_media_type": detected_media_type,
                "media_type_detection": "MAGIC_PREFIX_V1",
                "extension_media_type_mismatch": (
                    expected_media_type is not None
                    and expected_media_type != detected_media_type
                ),
                "size_bytes": size_bytes,
                "sha256": checksum,
                "modified_at_ns": str(signature[4]),
                "filesystem_identity_sha256": filesystem_identity_sha256(signature),
                "integrity_status": "INGESTION_BYTES_OBSERVED",
                "observation_status": "SYSTEM_OBSERVED_UNATTESTED",
                "user_provenance_status": "NOT_PROVIDED",
            }
        )
        observed_signatures.append((path, signature))
    for path, signature in observed_signatures:
        ensure_before_deadline(deadline)
        try:
            current_metadata = os.lstat(path)
        except OSError as error:
            raise ScanSafetyError(
                f"SCAN_FILE_CHANGED_DURING_READ: {path.name}: {error}"
            ) from error
        if is_reparse_point(current_metadata) or metadata_signature(
            current_metadata
        ) != signature:
            raise ScanSafetyError(f"SCAN_FILE_CHANGED_DURING_READ: {path.name}")
    final_files = enumerate_regular_files(
        input_directory, max_files=max_files, max_depth=max_depth, deadline=deadline
    )
    final_tree = {
        path.relative_to(input_directory).as_posix(): tree_entry_signature(metadata)
        for path, metadata in final_files
    }
    if final_tree != initial_tree:
        raise ScanSafetyError(
            "SCAN_TREE_CHANGED_DURING_READ: the final file tree differs from the initial walk."
        )

    manifest = {
        "schema_version": "1.3",
        "integrity_semantics": INTEGRITY_SEMANTICS,
        "canonicalization": CANONICALIZATION_ALGORITHM,
        "generator": {
            "name": GENERATOR_NAME,
            "version": GENERATOR_VERSION,
            "build_identity_status": "UNATTESTED",
            "runtime_source_sha256": sha256_file_if_available(Path(__file__)),
            "dependency_contract_sha256": sha256_file_if_available(dependency_contract),
            "dependency_contract_kind": (
                "HASH_LOCK" if dependency_contract == repository_lock else "DIRECT_REQUIREMENTS"
            ),
            "python_version": ".".join(str(value) for value in sys.version_info[:3]),
            "platform": sys.platform,
        },
        "provenance_boundary": {
            "system_observations": "SYSTEM_OBSERVED_UNATTESTED",
            "user_declarations": "NOT_PROVIDED",
            "generator_authenticity": "NOT_VERIFIED",
        },
        "scan_observation": {
            "started_at": started_at,
            "completed_at": utc_now_rfc3339(),
            "clock_status": "SYSTEM_CLOCK_UNATTESTED",
            "tree_walks_completed": 2,
        },
        "output_security": {
            "permissions_enforcement": (
                "WINDOWS_DIRECTORY_ACL_INHERITED_NOT_VERIFIED"
                if os.name == "nt"
                else "POSIX_MODE_0600"
            ),
            "absolute_paths_emitted": False,
            "relative_paths_may_contain_sensitive_data": True,
        },
        "scan_policy": {
            "max_depth": max_depth,
            "max_file_bytes": max_file_bytes,
            "max_files": max_files,
            "max_total_bytes": max_total_bytes,
            "timeout_seconds": timeout_seconds,
        },
        "summary": {"file_count": len(manifest_files), "total_bytes": total_bytes},
        "relationships": build_relationships(manifest_files),
        "files": manifest_files,
    }
    manifest["manifest_payload_sha256"] = hashlib.sha256(
        rfc8785.dumps(manifest)
    ).hexdigest()
    return manifest


def write_manifest_atomically(output: Path, manifest: dict) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    )
    descriptor, temporary_name = tempfile.mkstemp(
        dir=output.parent,
        prefix=f".{output.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        if os.name != "nt":
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as target:
            target.write(payload)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, output)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_directory", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES)
    parser.add_argument(
        "--max-file-bytes", type=int, default=DEFAULT_MAX_FILE_BYTES
    )
    parser.add_argument(
        "--max-total-bytes", type=int, default=DEFAULT_MAX_TOTAL_BYTES
    )
    parser.add_argument("--max-depth", type=int, default=DEFAULT_MAX_DEPTH)
    parser.add_argument(
        "--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS
    )
    args = parser.parse_args()

    supplied_input = args.input_directory.absolute()
    if os.name == "nt" and str(supplied_input).startswith("\\\\"):
        print(
            "SCAN_NETWORK_PATH_REFUSED: network input roots are not supported.",
            file=sys.stderr,
        )
        return 2
    try:
        supplied_metadata = os.lstat(supplied_input)
    except OSError:
        print("Input directory does not exist or is not a directory.", file=sys.stderr)
        return 1
    if is_reparse_point(supplied_metadata):
        print(
            "SCAN_REPARSE_POINT_REFUSED: input root is a link or reparse point.",
            file=sys.stderr,
        )
        return 2
    input_directory = supplied_input.resolve()
    output = args.output.resolve()
    if not input_directory.is_dir():
        print("Input directory does not exist or is not a directory.", file=sys.stderr)
        return 1
    if output.is_relative_to(input_directory):
        print(
            "Safety refusal: --output must be outside the scanned input directory.",
            file=sys.stderr,
        )
        return 2

    if (
        args.max_files < 1
        or args.max_file_bytes < 1
        or args.max_total_bytes < 1
        or args.max_depth < 0
        or args.timeout_seconds < 0
        or not math.isfinite(args.timeout_seconds)
    ):
        print("SCAN_LIMIT_INVALID: scan limits must be positive.", file=sys.stderr)
        return 2
    try:
        manifest = build_manifest(
            input_directory,
            max_files=args.max_files,
            max_file_bytes=args.max_file_bytes,
            max_total_bytes=args.max_total_bytes,
            max_depth=args.max_depth,
            timeout_seconds=args.timeout_seconds,
        )
    except ScanSafetyError as error:
        print(str(error), file=sys.stderr)
        return 2
    write_manifest_atomically(output, manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
