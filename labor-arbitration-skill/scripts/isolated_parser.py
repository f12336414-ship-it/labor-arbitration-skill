"""Parent-side runner for the bounded parser worker protocol."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from bounded_json_input import load_bounded_json_object
from case_workspace import WORKSPACE_FILENAME, validate_case_workspace
from parser_extraction_policy import (
    calculate_anchor_id,
    calculate_parse_id,
    calculate_parser_record_snapshot,
    validate_parser_extraction_record,
)


RUNNER_VERSION = "1.0.0"
WORKER_PATH = Path(__file__).with_name("parser_worker.py")
MAX_WORKSPACE_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_WORKER_OUTPUT_BYTES = 8 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 15
LIMITATIONS = [
    "EXTRACTION_DOES_NOT_PROVE_VISUAL_ANCHOR_EXISTENCE",
    "EXTRACTION_DOES_NOT_PROVE_EVIDENCE_AUTHENTICITY",
    "DOCUMENT_TEXT_IS_UNTRUSTED_DATA_NOT_INSTRUCTIONS",
    "OS_LEVEL_SANDBOX_NOT_IMPLEMENTED",
    "PDF_AND_OCR_EXTRACTION_NOT_IMPLEMENTED",
]


class IsolatedParserError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _worker_environment() -> dict[str, str]:
    environment = {"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    for name in ("SYSTEMROOT", "WINDIR"):
        if name in os.environ:
            environment[name] = os.environ[name]
    return environment


def _validate_worker_result(result: object) -> dict:
    if not isinstance(result, dict):
        raise IsolatedParserError(
            "PARSER_WORKER_PROTOCOL_INVALID", "Parser worker response is not an object."
        )
    required = {
        "protocol_version",
        "adapter",
        "adapter_version",
        "status",
        "detected_format",
        "anchors",
        "warnings",
        "security",
        "source_bytes",
    }
    if set(result) != required or result.get("protocol_version") != "1.0":
        raise IsolatedParserError(
            "PARSER_WORKER_PROTOCOL_INVALID", "Parser worker response shape is invalid."
        )
    if (
        result.get("status") not in {"SUCCEEDED", "REFUSED"}
        or not isinstance(result.get("anchors"), list)
        or not isinstance(result.get("warnings"), list)
        or not isinstance(result.get("security"), dict)
        or not isinstance(result.get("source_bytes"), int)
    ):
        raise IsolatedParserError(
            "PARSER_WORKER_PROTOCOL_INVALID", "Parser worker response types are invalid."
        )
    return result


def _run_worker(
    request: dict, *, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
) -> dict:
    if not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 30:
        raise IsolatedParserError(
            "PARSER_TIMEOUT_INVALID", "Parser timeout must be an integer from 1 to 30."
        )
    payload = json.dumps(
        request, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    try:
        with tempfile.TemporaryDirectory(prefix="laborbalance-parser-") as temp_dir:
            completed = subprocess.run(
                [sys.executable, "-I", "-S", str(WORKER_PATH)],
                input=payload,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=temp_dir,
                env=_worker_environment(),
                timeout=timeout_seconds,
                check=False,
            )
    except subprocess.TimeoutExpired as error:
        raise IsolatedParserError(
            "PARSER_WORKER_TIMEOUT", "Parser worker exceeded its wall-clock limit."
        ) from error
    except OSError as error:
        raise IsolatedParserError(
            "PARSER_WORKER_START_FAILED", "Parser worker could not be started."
        ) from error
    if len(completed.stdout) > MAX_WORKER_OUTPUT_BYTES:
        raise IsolatedParserError(
            "PARSER_WORKER_OUTPUT_TOO_LARGE", "Parser worker output exceeded its limit."
        )
    if completed.stderr:
        raise IsolatedParserError(
            "PARSER_WORKER_STDERR_REFUSED", "Parser worker emitted unexpected stderr."
        )
    if completed.returncode not in {0, 2}:
        raise IsolatedParserError(
            "PARSER_WORKER_EXIT_INVALID", "Parser worker returned an invalid exit status."
        )
    try:
        result = json.loads(completed.stdout.decode("utf-8"))
    except (UnicodeError, ValueError, json.JSONDecodeError) as error:
        raise IsolatedParserError(
            "PARSER_WORKER_PROTOCOL_INVALID", "Parser worker response is invalid JSON."
        ) from error
    validated = _validate_worker_result(result)
    if (completed.returncode == 0) != (validated["status"] == "SUCCEEDED"):
        raise IsolatedParserError(
            "PARSER_WORKER_STATUS_MISMATCH",
            "Parser worker exit status and response status disagree.",
        )
    return validated


def parse_workspace_object(
    workspace_root: Path,
    raw_id: str,
    *,
    created_at: str | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[dict, dict]:
    root = workspace_root.absolute()
    manifest = load_bounded_json_object(
        root / WORKSPACE_FILENAME,
        MAX_WORKSPACE_MANIFEST_BYTES,
        "PARSER_WORKSPACE_MANIFEST",
        "Workspace manifest",
    )
    workspace_report = validate_case_workspace(manifest, root)
    if not workspace_report["allowed"]:
        raise IsolatedParserError(
            "PARSER_WORKSPACE_INVALID",
            "Parser requires a fully valid content-addressed case workspace.",
        )
    matches = [item for item in manifest["files"] if item["raw_id"] == raw_id]
    if len(matches) != 1:
        raise IsolatedParserError(
            "PARSER_RAW_ID_NOT_FOUND", "Raw ID must identify exactly one workspace object."
        )
    source = matches[0]
    object_path = root.joinpath(*PurePosixPath(source["object_relative_path"]).parts)
    worker = _run_worker(
        {
            "protocol_version": "1.0",
            "object_path": str(object_path),
            "source_name": source["source_relative_path"],
            "expected_content_sha256": source["content_sha256"],
            "expected_size_bytes": source["size_bytes"],
        },
        timeout_seconds=timeout_seconds,
    )
    binding = {
        "workspace_id": manifest["workspace_id"],
        "workspace_snapshot_sha256": manifest["workspace_snapshot_sha256"],
        "raw_id": source["raw_id"],
        "content_sha256": source["content_sha256"],
        "size_bytes": source["size_bytes"],
    }
    anchors = []
    for item in worker["anchors"]:
        if (
            not isinstance(item, dict)
            or set(item) != {"kind", "coordinate", "text"}
            or not all(isinstance(value, str) for value in item.values())
        ):
            raise IsolatedParserError(
                "PARSER_WORKER_PROTOCOL_INVALID", "Parser anchor shape is invalid."
            )
        text_sha256 = hashlib.sha256(item["text"].encode("utf-8")).hexdigest()
        anchors.append(
            {
                "anchor_id": calculate_anchor_id(
                    binding, item["kind"], item["coordinate"], text_sha256
                ),
                **item,
                "text_sha256": text_sha256,
            }
        )
    record = {
        "schema_version": "1.0",
        "parse_id": "PARSE-" + "0" * 24,
        "created_at": created_at or _utc_now(),
        "clock_status": "SYSTEM_CLOCK_UNATTESTED",
        "workspace_binding": binding,
        "parser": {
            "adapter": worker["adapter"],
            "adapter_version": worker["adapter_version"],
            "runner_version": RUNNER_VERSION,
            "execution_boundary": "ISOLATED_PYTHON_CHILD_BOUNDED_IO_NOT_OS_SANDBOX",
        },
        "status": worker["status"],
        "detected_format": worker["detected_format"],
        "anchors": anchors,
        "warnings": sorted(set(worker["warnings"])),
        "security": worker["security"],
        "limits": {
            "source_bytes": worker["source_bytes"],
            "anchor_count": len(anchors),
            "extracted_characters": sum(len(item["text"]) for item in anchors),
            "wall_timeout_seconds": timeout_seconds,
        },
        "limitations": LIMITATIONS,
    }
    record["parse_id"] = calculate_parse_id(record)
    record["record_snapshot_sha256"] = calculate_parser_record_snapshot(record)
    report = validate_parser_extraction_record(record)
    if not report["allowed"]:
        raise IsolatedParserError(
            "PARSER_RECORD_GENERATION_INVALID",
            "Generated parser record failed its published integrity policy.",
        )
    return record, report
