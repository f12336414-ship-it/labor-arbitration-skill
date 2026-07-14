#!/usr/bin/env python3
"""Build a deterministic ingestion-integrity manifest for a local directory."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(input_directory: Path) -> dict:
    files = sorted(
        (
            path
            for path in input_directory.rglob("*")
            if path.is_file() and not path.is_symlink()
        ),
        key=lambda path: path.relative_to(input_directory).as_posix(),
    )
    return {
        "schema_version": "1.1",
        "integrity_semantics": "Hashes verify bytes observed at ingestion, not authenticity.",
        "files": [
            {
                "raw_id": f"RAW-{index:04d}",
                "relative_path": path.relative_to(input_directory).as_posix(),
                "extension": path.suffix.lower(),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "integrity_status": "INGESTION_INTEGRITY_VERIFIED",
            }
            for index, path in enumerate(files, start=1)
        ],
    }


def write_manifest_atomically(output: Path, manifest: dict) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
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
    args = parser.parse_args()

    input_directory = args.input_directory.resolve()
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

    manifest = build_manifest(input_directory)
    write_manifest_atomically(output, manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
