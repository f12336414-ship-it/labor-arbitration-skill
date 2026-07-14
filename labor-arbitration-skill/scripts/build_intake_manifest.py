#!/usr/bin/env python3
"""Build a deterministic ingestion-integrity manifest for a local directory."""

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
from pathlib import Path


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


class ScanSafetyError(RuntimeError):
    """Raised when ingestion cannot safely produce a complete manifest."""


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
) -> tuple[str, int, tuple[int, ...]]:
    digest = hashlib.sha256()
    bytes_read = 0
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
    return digest.hexdigest(), bytes_read, metadata_signature(opened_metadata)


def build_manifest(
    input_directory: Path,
    max_files: int = DEFAULT_MAX_FILES,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    max_depth: int = DEFAULT_MAX_DEPTH,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict:
    deadline = time.monotonic() + timeout_seconds
    ensure_before_deadline(deadline)
    files = enumerate_regular_files(
        input_directory, max_files=max_files, max_depth=max_depth, deadline=deadline
    )
    manifest_files = []
    observed_signatures = []
    total_bytes = 0
    for index, (path, expected_metadata) in enumerate(files, start=1):
        checksum, size_bytes, signature = hash_stable_file(
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
        manifest_files.append(
            {
                "raw_id": f"RAW-{index:04d}",
                "relative_path": path.relative_to(input_directory).as_posix(),
                "extension": path.suffix.lower(),
                "size_bytes": size_bytes,
                "sha256": checksum,
                "integrity_status": "INGESTION_BYTES_OBSERVED",
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
    return {
        "schema_version": "1.2",
        "integrity_semantics": INTEGRITY_SEMANTICS,
        "scan_policy": {
            "max_depth": max_depth,
            "max_file_bytes": max_file_bytes,
            "max_files": max_files,
            "max_total_bytes": max_total_bytes,
            "timeout_seconds": timeout_seconds,
        },
        "summary": {"file_count": len(manifest_files), "total_bytes": total_bytes},
        "files": manifest_files,
    }


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
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as target:
            target.write(payload)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, output)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def main() -> int:
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
