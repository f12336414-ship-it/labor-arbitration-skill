"""Build bounded, exact UTF-8 text diffs for frozen legal-source versions."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import stat
from pathlib import Path

from integrity_primitives import calculate_json_snapshot
from schema_validation import validate_published_legal_text_diff
from finding_model import finding


MAX_SOURCE_BYTES = 1024 * 1024
MAX_SERIALIZED_DIFF_BYTES = 4 * 1024 * 1024
IDENTIFIER = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")


class LegalTextDiffError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _is_reparse(metadata: os.stat_result) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(metadata, "st_file_attributes", 0) & reparse_flag)


def read_plain_stable_utf8(path: Path) -> str:
    try:
        supplied = os.lstat(path)
        if (
            not stat.S_ISREG(supplied.st_mode)
            or stat.S_ISLNK(supplied.st_mode)
            or _is_reparse(supplied)
        ):
            raise LegalTextDiffError(
                "LEGAL_TEXT_DIFF_INPUT_PATH_UNSAFE",
                "Diff inputs must be plain local regular files.",
            )
        with path.open("rb") as source:
            before = os.fstat(source.fileno())
            if before.st_size > MAX_SOURCE_BYTES:
                raise LegalTextDiffError(
                    "LEGAL_TEXT_DIFF_INPUT_TOO_LARGE",
                    "Each decoded source is limited to 1 MiB.",
                )
            payload = source.read(MAX_SOURCE_BYTES + 1)
            after = os.fstat(source.fileno())
        final = os.lstat(path)
    except LegalTextDiffError:
        raise
    except OSError as error:
        raise LegalTextDiffError(
            "LEGAL_TEXT_DIFF_INPUT_UNREADABLE",
            "Diff input cannot be read safely.",
        ) from error
    signature = lambda item: (
        item.st_dev,
        item.st_ino,
        item.st_mode,
        item.st_size,
        item.st_mtime_ns,
    )
    if (
        len(payload) > MAX_SOURCE_BYTES
        or len(payload) != before.st_size
        or signature(supplied) != signature(before)
        or signature(before) != signature(after)
        or signature(after) != signature(final)
    ):
        raise LegalTextDiffError(
            "LEGAL_TEXT_DIFF_INPUT_CHANGED",
            "Diff input changed while it was being read.",
        )
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise LegalTextDiffError(
            "LEGAL_TEXT_DIFF_INPUT_NOT_UTF8",
            "Exact text diff accepts UTF-8 text only; extraction is a separate step.",
        ) from error


def calculate_legal_text_diff_snapshot(record: dict) -> str:
    return calculate_json_snapshot(
        {
            key: value
            for key, value in record.items()
            if key != "diff_snapshot_sha256"
        }
    )


def build_legal_text_diff(
    from_version_id: str,
    to_version_id: str,
    from_text: str,
    to_text: str,
) -> dict:
    if not IDENTIFIER.fullmatch(from_version_id) or not IDENTIFIER.fullmatch(to_version_id):
        raise LegalTextDiffError(
            "LEGAL_TEXT_DIFF_VERSION_ID_INVALID",
            "Version identifiers must use the published uppercase identifier format.",
        )
    if not isinstance(from_text, str) or not isinstance(to_text, str):
        raise LegalTextDiffError(
            "LEGAL_TEXT_DIFF_INPUT_TYPE_INVALID", "Diff inputs must be decoded text."
        )
    from_bytes = from_text.encode("utf-8")
    to_bytes = to_text.encode("utf-8")
    if max(len(from_bytes), len(to_bytes)) > MAX_SOURCE_BYTES:
        raise LegalTextDiffError(
            "LEGAL_TEXT_DIFF_INPUT_TOO_LARGE", "Each decoded source is limited to 1 MiB."
        )

    from_lines = from_text.splitlines(keepends=True)
    to_lines = to_text.splitlines(keepends=True)
    matcher = difflib.SequenceMatcher(None, from_lines, to_lines, autojunk=True)
    operations = []
    added = 0
    removed = 0
    for tag, from_start, from_end, to_start, to_end in matcher.get_opcodes():
        if tag == "equal":
            continue
        added += to_end - to_start
        removed += from_end - from_start
        operations.append(
            {
                "tag": tag.upper(),
                "from_start_line": from_start,
                "from_end_line": from_end,
                "to_start_line": to_start,
                "to_end_line": to_end,
                "removed_text": "".join(from_lines[from_start:from_end]),
                "added_text": "".join(to_lines[to_start:to_end]),
            }
        )
    unified_diff = "".join(
        difflib.unified_diff(
            from_lines,
            to_lines,
            fromfile=from_version_id,
            tofile=to_version_id,
            lineterm="\n",
        )
    )
    from_content_sha256 = hashlib.sha256(from_bytes).hexdigest()
    to_content_sha256 = hashlib.sha256(to_bytes).hexdigest()
    identity = calculate_json_snapshot(
        {
            "from_content_sha256": from_content_sha256,
            "from_version_id": from_version_id,
            "to_content_sha256": to_content_sha256,
            "to_version_id": to_version_id,
        }
    )
    record = {
        "schema_version": "1.0",
        "diff_id": f"DIFF-{identity[:24].upper()}",
        "from_version_id": from_version_id,
        "to_version_id": to_version_id,
        "from_content_sha256": from_content_sha256,
        "to_content_sha256": to_content_sha256,
        "encoding": "UTF-8",
        "unicode_normalization": "NONE",
        "algorithm": "PYTHON_UNIFIED_DIFF_EXACT_LINES_V1",
        "from_character_count": len(from_text),
        "to_character_count": len(to_text),
        "from_line_count": len(from_lines),
        "to_line_count": len(to_lines),
        "change_summary": {
            "equal": from_bytes == to_bytes,
            "added_line_units": added,
            "removed_line_units": removed,
        },
        "operations": operations,
        "unified_diff": unified_diff,
        "diff_truncated": False,
        "limitations": [
            "TEXT_DIFF_HAS_NO_LEGAL_SEMANTIC_INTERPRETATION",
            "INPUT_VERSION_IDENTITY_DEPENDS_ON_BOUND_CONTENT_HASHES",
            "PDF_OR_HTML_EXTRACTION_NOT_PERFORMED",
        ],
    }
    serialized_size = len(
        json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    if serialized_size > MAX_SERIALIZED_DIFF_BYTES:
        raise LegalTextDiffError(
            "LEGAL_TEXT_DIFF_OUTPUT_TOO_LARGE",
            "Exact diff exceeds 4 MiB and is refused instead of being truncated.",
        )
    record["diff_snapshot_sha256"] = calculate_legal_text_diff_snapshot(record)
    if validate_published_legal_text_diff(record):
        raise LegalTextDiffError(
            "LEGAL_TEXT_DIFF_GENERATION_INVALID",
            "Generated diff does not conform to its published schema.",
        )
    return record


def validate_legal_text_diff_record(record: dict) -> dict:
    findings = validate_published_legal_text_diff(record)
    if findings:
        return _report(record, findings)

    operations = record["operations"]
    previous_from_end = 0
    previous_to_end = 0
    added = 0
    removed = 0
    for index, operation in enumerate(operations):
        path = f"$.operations[{index}]"
        from_count = operation["from_end_line"] - operation["from_start_line"]
        to_count = operation["to_end_line"] - operation["to_start_line"]
        if (
            from_count < 0
            or to_count < 0
            or operation["from_end_line"] > record["from_line_count"]
            or operation["to_end_line"] > record["to_line_count"]
            or operation["from_start_line"] < previous_from_end
            or operation["to_start_line"] < previous_to_end
        ):
            findings.append(
                finding(
                    "LEGAL_TEXT_DIFF_OPERATION_RANGE_INVALID",
                    path,
                    "Diff operation line ranges must be ordered and inside both source line counts.",
                    "P0",
                )
            )
        expected_shape = {
            "DELETE": (from_count > 0 and to_count == 0 and not operation["added_text"]),
            "INSERT": (from_count == 0 and to_count > 0 and not operation["removed_text"]),
            "REPLACE": (from_count > 0 and to_count > 0),
        }[operation["tag"]]
        if not expected_shape:
            findings.append(
                finding(
                    "LEGAL_TEXT_DIFF_OPERATION_SHAPE_INVALID",
                    path,
                    "Insert, delete, and replace operations must have matching non-empty line ranges.",
                    "P0",
                )
            )
        if len(operation["removed_text"].splitlines(keepends=True)) != from_count:
            findings.append(
                finding(
                    "LEGAL_TEXT_DIFF_OPERATION_TEXT_MISMATCH",
                    f"{path}.removed_text",
                    "Removed text line units must match the declared source range.",
                    "P0",
                )
            )
        if len(operation["added_text"].splitlines(keepends=True)) != to_count:
            findings.append(
                finding(
                    "LEGAL_TEXT_DIFF_OPERATION_TEXT_MISMATCH",
                    f"{path}.added_text",
                    "Added text line units must match the declared target range.",
                    "P0",
                )
            )
        added += max(to_count, 0)
        removed += max(from_count, 0)
        previous_from_end = max(previous_from_end, operation["from_end_line"])
        previous_to_end = max(previous_to_end, operation["to_end_line"])

    summary = record["change_summary"]
    equal_hashes = record["from_content_sha256"] == record["to_content_sha256"]
    if (
        summary["added_line_units"] != added
        or summary["removed_line_units"] != removed
        or summary["equal"] != equal_hashes
        or (equal_hashes and (operations or record["unified_diff"]))
        or (not equal_hashes and not operations)
    ):
        findings.append(
            finding(
                "LEGAL_TEXT_DIFF_SUMMARY_MISMATCH",
                "$.change_summary",
                "Diff summary must match the content hashes, operations, and presentation diff.",
                "P0",
            )
        )
    try:
        expected_snapshot = calculate_legal_text_diff_snapshot(record)
    except (TypeError, ValueError):
        findings.append(
            finding(
                "LEGAL_TEXT_DIFF_CANONICALIZATION_FAILED",
                "$",
                "Text diff cannot be canonicalized as RFC 8785 I-JSON.",
                "P0",
            )
        )
    else:
        if record["diff_snapshot_sha256"] != expected_snapshot:
            findings.append(
                finding(
                    "LEGAL_TEXT_DIFF_SNAPSHOT_MISMATCH",
                    "$.diff_snapshot_sha256",
                    "Text diff changed without a new RFC 8785 snapshot.",
                    "P0",
                )
            )
    return _report(record, findings)


def _report(record: dict, findings: list[dict]) -> dict:
    findings.sort(key=lambda item: (item["code"], item["path"], item["message"]))
    allowed = not findings
    return {
        "allowed": allowed,
        "allowed_scope": "EXACT_UTF8_TEXT_DIFF_INTEGRITY_ONLY",
        "diff_id": record.get("diff_id"),
        "findings": findings,
        "legal_review_required": True,
        "submission_ready": False,
        "validation_scope": {
            "verified": (
                ["DIFF_OPERATION_INTEGRITY", "RFC8785_DIFF_SNAPSHOT"]
                if allowed
                else []
            ),
            "not_verified": [
                "LEGAL_EFFECT_OF_TEXT_CHANGES",
                "SOURCE_EXTRACTION_CORRECTNESS",
                "SOURCE_VERSION_IDENTITY",
            ],
        },
    }
