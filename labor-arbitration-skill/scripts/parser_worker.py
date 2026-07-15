"""Standalone stdlib-only worker for bounded, inert document extraction."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import posixpath
import stat
import sys
import zipfile
from email import policy
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
from xml.etree import ElementTree


PROTOCOL_VERSION = "1.0"
ADAPTER_VERSION = "1.0.0"
MAX_PROTOCOL_BYTES = 64 * 1024
MAX_SOURCE_BYTES = 20 * 1024 * 1024
MAX_MEMBER_BYTES = 5 * 1024 * 1024
MAX_ARCHIVE_BYTES = 20 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 1000
MAX_COMPRESSION_RATIO = 100
MAX_ANCHORS = 10000
MAX_EXTRACTED_CHARACTERS = 2_000_000
MAX_TEXT_PER_ANCHOR = 10000
MAX_EMAIL_PARTS = 100


class WorkerRefusal(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _apply_resource_limits() -> None:
    try:
        import resource
    except ImportError:
        return
    limits = (
        (getattr(resource, "RLIMIT_CPU", None), 10),
        (getattr(resource, "RLIMIT_AS", None), 256 * 1024 * 1024),
        (getattr(resource, "RLIMIT_FSIZE", None), 8 * 1024 * 1024),
        (getattr(resource, "RLIMIT_NOFILE", None), 32),
    )
    for kind, maximum in limits:
        if kind is None:
            continue
        try:
            resource.setrlimit(kind, (maximum, maximum))
        except (OSError, ValueError):
            continue


def _read_protocol() -> dict:
    payload = sys.stdin.buffer.read(MAX_PROTOCOL_BYTES + 1)
    if len(payload) > MAX_PROTOCOL_BYTES:
        raise WorkerRefusal("PARSER_PROTOCOL_TOO_LARGE")
    try:
        request = json.loads(payload.decode("utf-8"))
    except (UnicodeError, ValueError, json.JSONDecodeError) as error:
        raise WorkerRefusal("PARSER_PROTOCOL_INVALID") from error
    if (
        not isinstance(request, dict)
        or set(request) != {
            "protocol_version",
            "object_path",
            "source_name",
            "expected_content_sha256",
            "expected_size_bytes",
        }
        or request["protocol_version"] != PROTOCOL_VERSION
        or not isinstance(request["object_path"], str)
        or not isinstance(request["source_name"], str)
        or not isinstance(request["expected_content_sha256"], str)
        or len(request["expected_content_sha256"]) != 64
        or not isinstance(request["expected_size_bytes"], int)
        or request["expected_size_bytes"] < 0
        or request["expected_size_bytes"] > MAX_SOURCE_BYTES
    ):
        raise WorkerRefusal("PARSER_PROTOCOL_INVALID")
    return request


def _read_stable_object(request: dict) -> bytes:
    path = Path(request["object_path"])
    try:
        supplied = os.lstat(path)
        if not stat.S_ISREG(supplied.st_mode) or stat.S_ISLNK(supplied.st_mode):
            raise WorkerRefusal("PARSER_OBJECT_PATH_UNSAFE")
        with path.open("rb") as source:
            before = os.fstat(source.fileno())
            payload = source.read(MAX_SOURCE_BYTES + 1)
            after = os.fstat(source.fileno())
        final = os.lstat(path)
    except WorkerRefusal:
        raise
    except OSError as error:
        raise WorkerRefusal("PARSER_OBJECT_UNREADABLE") from error
    signature = lambda item: (
        item.st_dev,
        item.st_ino,
        item.st_mode,
        item.st_size,
        item.st_mtime_ns,
    )
    if (
        len(payload) > MAX_SOURCE_BYTES
        or len(payload) != request["expected_size_bytes"]
        or signature(supplied) != signature(before)
        or signature(before) != signature(after)
        or signature(after) != signature(final)
    ):
        raise WorkerRefusal("PARSER_OBJECT_CHANGED_OR_SIZE_MISMATCH")
    if hashlib.sha256(payload).hexdigest() != request["expected_content_sha256"]:
        raise WorkerRefusal("PARSER_OBJECT_HASH_MISMATCH")
    return payload


def _anchor(kind: str, coordinate: str, text: str) -> dict:
    if len(text) > MAX_TEXT_PER_ANCHOR:
        raise WorkerRefusal("PARSER_ANCHOR_TEXT_TOO_LARGE")
    return {"kind": kind, "coordinate": coordinate, "text": text}


def _check_anchor_limits(anchors: list[dict]) -> None:
    if len(anchors) > MAX_ANCHORS:
        raise WorkerRefusal("PARSER_ANCHOR_LIMIT_EXCEEDED")
    if sum(len(item["text"]) for item in anchors) > MAX_EXTRACTED_CHARACTERS:
        raise WorkerRefusal("PARSER_EXTRACTED_TEXT_LIMIT_EXCEEDED")


def _safe_archive_name(name: str) -> PurePosixPath:
    if not name or "\x00" in name or "\\" in name or len(name) > 4096:
        raise WorkerRefusal("PARSER_ARCHIVE_PATH_UNSAFE")
    candidate = PurePosixPath(name)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        raise WorkerRefusal("PARSER_ARCHIVE_PATH_UNSAFE")
    if candidate.parts and ":" in candidate.parts[0]:
        raise WorkerRefusal("PARSER_ARCHIVE_PATH_UNSAFE")
    return candidate


def _inspect_zip(payload: bytes) -> tuple[zipfile.ZipFile, dict[str, zipfile.ZipInfo]]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
        entries = archive.infolist()
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        raise WorkerRefusal("PARSER_ARCHIVE_INVALID") from error
    if len(entries) > MAX_ARCHIVE_ENTRIES:
        archive.close()
        raise WorkerRefusal("PARSER_ARCHIVE_ENTRY_LIMIT_EXCEEDED")
    by_name = {}
    total = 0
    for entry in entries:
        name = _safe_archive_name(entry.filename)
        normalized = name.as_posix().rstrip("/")
        if normalized in by_name:
            archive.close()
            raise WorkerRefusal("PARSER_ARCHIVE_DUPLICATE_ENTRY")
        if entry.flag_bits & 0x1:
            archive.close()
            raise WorkerRefusal("PARSER_ARCHIVE_ENCRYPTED")
        mode = entry.external_attr >> 16
        if stat.S_ISLNK(mode):
            archive.close()
            raise WorkerRefusal("PARSER_ARCHIVE_LINK_REFUSED")
        if entry.file_size > MAX_MEMBER_BYTES:
            archive.close()
            raise WorkerRefusal("PARSER_ARCHIVE_MEMBER_TOO_LARGE")
        total += entry.file_size
        if total > MAX_ARCHIVE_BYTES:
            archive.close()
            raise WorkerRefusal("PARSER_ARCHIVE_EXPANDED_SIZE_EXCEEDED")
        if entry.file_size and (
            entry.compress_size == 0
            or entry.file_size / entry.compress_size > MAX_COMPRESSION_RATIO
        ):
            archive.close()
            raise WorkerRefusal("PARSER_ARCHIVE_COMPRESSION_RATIO_REFUSED")
        by_name[normalized] = entry
    return archive, by_name


def _read_member(archive: zipfile.ZipFile, entry: zipfile.ZipInfo) -> bytes:
    try:
        with archive.open(entry) as source:
            payload = source.read(MAX_MEMBER_BYTES + 1)
    except (OSError, RuntimeError, ValueError, zipfile.BadZipFile) as error:
        raise WorkerRefusal("PARSER_ARCHIVE_MEMBER_UNREADABLE") from error
    if len(payload) > MAX_MEMBER_BYTES or len(payload) != entry.file_size:
        raise WorkerRefusal("PARSER_ARCHIVE_MEMBER_SIZE_MISMATCH")
    return payload


def _parse_xml(payload: bytes):
    upper = payload.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise WorkerRefusal("PARSER_XML_ACTIVE_DECLARATION_REFUSED")
    try:
        return ElementTree.fromstring(payload)
    except ElementTree.ParseError as error:
        raise WorkerRefusal("PARSER_XML_INVALID") from error


def _relationship_is_external(root) -> bool:
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != "Relationship":
            continue
        target = element.attrib.get("Target", "")
        parsed = urlsplit(target)
        if (
            element.attrib.get("TargetMode", "").lower() == "external"
            or parsed.scheme
            or parsed.netloc
            or target.startswith("//")
            or "\\" in target
        ):
            return True
    return False


def _check_ooxml_active_content(
    archive: zipfile.ZipFile, entries: dict[str, zipfile.ZipInfo]
) -> None:
    lowered = {name.lower() for name in entries}
    forbidden_parts = (
        "vbaproject.bin",
        "externalLinks/",
        "embeddings/",
        "oleobject",
    )
    if any(any(part.lower() in name for part in forbidden_parts) for name in lowered):
        raise WorkerRefusal("PARSER_OOXML_ACTIVE_CONTENT_REFUSED")
    content_types = entries.get("[Content_Types].xml")
    if content_types is None:
        raise WorkerRefusal("PARSER_OOXML_STRUCTURE_INVALID")
    content_payload = _read_member(archive, content_types)
    if b"macroEnabled".lower() in content_payload.lower():
        raise WorkerRefusal("PARSER_OOXML_MACRO_REFUSED")
    for name, entry in entries.items():
        if name.endswith(".rels"):
            if _relationship_is_external(_parse_xml(_read_member(archive, entry))):
                raise WorkerRefusal("PARSER_OOXML_EXTERNAL_RELATIONSHIP_REFUSED")


def _parse_text(payload: bytes) -> tuple[str, list[dict], list[str]]:
    if b"\x00" in payload:
        raise WorkerRefusal("PARSER_TEXT_NUL_REFUSED")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise WorkerRefusal("PARSER_TEXT_NOT_UTF8") from error
    anchors = [
        _anchor("TEXT_LINE", f"line:{index}", line)
        for index, line in enumerate(text.splitlines(), start=1)
    ]
    return "UTF8_TEXT", anchors, []


def _parse_csv(payload: bytes) -> tuple[str, list[dict], list[str]]:
    if b"\x00" in payload:
        raise WorkerRefusal("PARSER_TEXT_NUL_REFUSED")
    try:
        text = payload.decode("utf-8-sig")
        rows = csv.reader(io.StringIO(text, newline=""), strict=True)
        anchors = []
        for row_index, row in enumerate(rows, start=1):
            if row_index > MAX_ANCHORS:
                raise WorkerRefusal("PARSER_CSV_ROW_LIMIT_EXCEEDED")
            for column_index, value in enumerate(row, start=1):
                anchors.append(
                    _anchor("CSV_CELL", f"R{row_index}C{column_index}", value)
                )
                if len(anchors) > MAX_ANCHORS:
                    raise WorkerRefusal("PARSER_ANCHOR_LIMIT_EXCEEDED")
    except (UnicodeDecodeError, csv.Error) as error:
        raise WorkerRefusal("PARSER_CSV_INVALID") from error
    return "CSV", anchors, []


def _parse_docx(
    archive: zipfile.ZipFile, entries: dict[str, zipfile.ZipInfo]
) -> tuple[str, list[dict], list[str]]:
    _check_ooxml_active_content(archive, entries)
    document = entries.get("word/document.xml")
    if document is None:
        raise WorkerRefusal("PARSER_DOCX_STRUCTURE_INVALID")
    root = _parse_xml(_read_member(archive, document))
    anchors = []
    paragraph_index = 0
    for paragraph in root.iter():
        if paragraph.tag.rsplit("}", 1)[-1] != "p":
            continue
        paragraph_index += 1
        fragments = [
            node.text or ""
            for node in paragraph.iter()
            if node.tag.rsplit("}", 1)[-1] == "t"
        ]
        anchors.append(
            _anchor(
                "DOCX_PARAGRAPH",
                f"word/document.xml#paragraph:{paragraph_index}",
                "".join(fragments),
            )
        )
    return "DOCX", anchors, []


def _xlsx_shared_strings(
    archive: zipfile.ZipFile, entries: dict[str, zipfile.ZipInfo]
) -> list[str]:
    entry = entries.get("xl/sharedStrings.xml")
    if entry is None:
        return []
    root = _parse_xml(_read_member(archive, entry))
    return [
        "".join(
            node.text or ""
            for node in item.iter()
            if node.tag.rsplit("}", 1)[-1] == "t"
        )
        for item in root
        if item.tag.rsplit("}", 1)[-1] == "si"
    ]


def _parse_xlsx(
    archive: zipfile.ZipFile, entries: dict[str, zipfile.ZipInfo]
) -> tuple[str, list[dict], list[str]]:
    _check_ooxml_active_content(archive, entries)
    workbook_entry = entries.get("xl/workbook.xml")
    rels_entry = entries.get("xl/_rels/workbook.xml.rels")
    if workbook_entry is None or rels_entry is None:
        raise WorkerRefusal("PARSER_XLSX_STRUCTURE_INVALID")
    workbook = _parse_xml(_read_member(archive, workbook_entry))
    rels = _parse_xml(_read_member(archive, rels_entry))
    relationships = {
        item.attrib.get("Id"): item.attrib.get("Target")
        for item in rels.iter()
        if item.tag.rsplit("}", 1)[-1] == "Relationship"
    }
    shared = _xlsx_shared_strings(archive, entries)
    anchors = []
    warnings = set()
    for sheet in workbook.iter():
        if sheet.tag.rsplit("}", 1)[-1] != "sheet":
            continue
        sheet_name = sheet.attrib.get("name", "")
        relationship_id = next(
            (value for key, value in sheet.attrib.items() if key.endswith("}id")), None
        )
        target = relationships.get(relationship_id)
        if not target:
            raise WorkerRefusal("PARSER_XLSX_RELATIONSHIP_INVALID")
        normalized = posixpath.normpath(posixpath.join("xl", target)).lstrip("/")
        if not normalized.startswith("xl/worksheets/") or normalized not in entries:
            raise WorkerRefusal("PARSER_XLSX_RELATIONSHIP_INVALID")
        worksheet = _parse_xml(_read_member(archive, entries[normalized]))
        for cell in worksheet.iter():
            if cell.tag.rsplit("}", 1)[-1] != "c":
                continue
            coordinate = cell.attrib.get("r")
            if not coordinate:
                raise WorkerRefusal("PARSER_XLSX_CELL_INVALID")
            cell_type = cell.attrib.get("t")
            formula = None
            value = None
            inline_fragments = []
            for node in cell.iter():
                local = node.tag.rsplit("}", 1)[-1]
                if local == "f":
                    formula = node.text or ""
                elif local == "v" and value is None:
                    value = node.text or ""
                elif local == "t" and cell_type == "inlineStr":
                    inline_fragments.append(node.text or "")
            if formula is not None:
                text = "=" + formula
                warnings.add("SPREADSHEET_FORMULA_PRESENT_NOT_EVALUATED")
            elif cell_type == "s":
                try:
                    text = shared[int(value or "")]
                except (ValueError, IndexError) as error:
                    raise WorkerRefusal("PARSER_XLSX_SHARED_STRING_INVALID") from error
            elif cell_type == "inlineStr":
                text = "".join(inline_fragments)
            else:
                text = value or ""
            anchors.append(
                _anchor("XLSX_CELL", f"sheet:{sheet_name}!{coordinate}", text)
            )
    return "XLSX", anchors, sorted(warnings)


def _parse_email(payload: bytes) -> tuple[str, list[dict], list[str]]:
    try:
        message = BytesParser(policy=policy.default).parsebytes(payload)
    except (ValueError, TypeError) as error:
        raise WorkerRefusal("PARSER_EMAIL_INVALID") from error
    anchors = []
    for header in ("Subject", "From", "To", "Date", "Message-ID"):
        value = message.get(header)
        if value is not None:
            anchors.append(_anchor("EMAIL_HEADER", f"header:{header.lower()}", str(value)))
    part_count = 0
    decoded_bytes = 0
    warnings = set()
    for part in message.walk():
        part_count += 1
        if part_count > MAX_EMAIL_PARTS:
            raise WorkerRefusal("PARSER_EMAIL_PART_LIMIT_EXCEEDED")
        if part.is_multipart():
            continue
        disposition = part.get_content_disposition()
        if disposition == "attachment":
            warnings.add("EMAIL_ATTACHMENTS_NOT_RECURSIVELY_PARSED")
            continue
        if part.get_content_type() != "text/plain":
            if part.get_content_type() == "text/html":
                warnings.add("EMAIL_HTML_NOT_RENDERED")
            continue
        try:
            content = part.get_content()
        except (LookupError, UnicodeError, ValueError) as error:
            raise WorkerRefusal("PARSER_EMAIL_TEXT_DECODE_FAILED") from error
        if not isinstance(content, str):
            continue
        decoded_bytes += len(content.encode("utf-8"))
        if decoded_bytes > MAX_MEMBER_BYTES:
            raise WorkerRefusal("PARSER_EMAIL_DECODED_SIZE_EXCEEDED")
        for line_index, line in enumerate(content.splitlines(), start=1):
            anchors.append(
                _anchor(
                    "EMAIL_TEXT_LINE",
                    f"part:{part_count}:line:{line_index}",
                    line,
                )
            )
    return "EML", anchors, sorted(warnings)


def _parse_zip_inspection(entries: dict[str, zipfile.ZipInfo]):
    anchors = [
        _anchor("ARCHIVE_ENTRY", f"entry:{index}", name)
        for index, name in enumerate(sorted(entries), start=1)
    ]
    return "ZIP", anchors, ["ARCHIVE_CONTENT_NOT_RECURSIVELY_PARSED"]


def _extract(payload: bytes, source_name: str):
    extension = Path(source_name).suffix.lower()
    if payload.startswith(b"%PDF-"):
        raise WorkerRefusal("PARSER_PDF_ADAPTER_NOT_IMPLEMENTED")
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise WorkerRefusal("PARSER_IMAGE_OCR_NOT_IMPLEMENTED")
    if payload.startswith(b"\xff\xd8\xff"):
        raise WorkerRefusal("PARSER_IMAGE_OCR_NOT_IMPLEMENTED")
    if zipfile.is_zipfile(io.BytesIO(payload)):
        archive, entries = _inspect_zip(payload)
        try:
            if "word/document.xml" in entries:
                return _parse_docx(archive, entries)
            if "xl/workbook.xml" in entries:
                return _parse_xlsx(archive, entries)
            return _parse_zip_inspection(entries)
        finally:
            archive.close()
    if extension == ".csv":
        return _parse_csv(payload)
    if extension in {".eml", ".email"} or b"MIME-Version:" in payload[:8192]:
        return _parse_email(payload)
    if extension in {".txt", ".md", ".markdown", ".log"}:
        return _parse_text(payload)
    raise WorkerRefusal("PARSER_FORMAT_UNSUPPORTED")


def _detected_format(payload: bytes, source_name: str) -> str:
    extension = Path(source_name).suffix.lower()
    if payload.startswith(b"%PDF-"):
        return "PDF"
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if payload.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if zipfile.is_zipfile(io.BytesIO(payload)):
        try:
            archive, entries = _inspect_zip(payload)
            archive.close()
        except WorkerRefusal:
            return "ZIP"
        if "word/document.xml" in entries:
            return "DOCX"
        if "xl/workbook.xml" in entries:
            return "XLSX"
        return "ZIP"
    if extension == ".csv":
        return "CSV"
    if extension in {".eml", ".email"} or b"MIME-Version:" in payload[:8192]:
        return "EML"
    if extension in {".txt", ".md", ".markdown", ".log"}:
        return "UTF8_TEXT"
    return "UNKNOWN"


def _security(format_name: str, refusal_code: str | None) -> dict:
    ooxml = format_name in {"DOCX", "XLSX"}
    return {
        "network_access": "NO_NETWORK_CLIENT_IN_WORKER_NOT_OS_ENFORCED",
        "macro_status": (
            "DETECTED_REFUSED"
            if refusal_code in {"PARSER_OOXML_ACTIVE_CONTENT_REFUSED", "PARSER_OOXML_MACRO_REFUSED"}
            else "NOT_DETECTED" if ooxml else "NOT_APPLICABLE"
        ),
        "external_relationship_status": (
            "DETECTED_REFUSED"
            if refusal_code == "PARSER_OOXML_EXTERNAL_RELATIONSHIP_REFUSED"
            else "NOT_DETECTED" if ooxml else "NOT_APPLICABLE"
        ),
        "formula_execution": "NEVER_EVALUATED",
        "os_sandbox_status": "NOT_IMPLEMENTED",
        "refusal_code": refusal_code,
    }


def main() -> int:
    _apply_resource_limits()
    detected = "UNKNOWN"
    source_size = 0
    try:
        request = _read_protocol()
        payload = _read_stable_object(request)
        source_size = len(payload)
        detected = _detected_format(payload, request["source_name"])
        detected, anchors, warnings = _extract(payload, request["source_name"])
        _check_anchor_limits(anchors)
        result = {
            "protocol_version": PROTOCOL_VERSION,
            "adapter": "ZIP_INSPECTION" if detected == "ZIP" else detected,
            "adapter_version": ADAPTER_VERSION,
            "status": "SUCCEEDED",
            "detected_format": detected,
            "anchors": anchors,
            "warnings": warnings,
            "security": _security(detected, None),
            "source_bytes": source_size,
        }
        exit_code = 0
    except WorkerRefusal as error:
        result = {
            "protocol_version": PROTOCOL_VERSION,
            "adapter": "UNSUPPORTED",
            "adapter_version": ADAPTER_VERSION,
            "status": "REFUSED",
            "detected_format": detected,
            "anchors": [],
            "warnings": [],
            "security": _security(detected, error.code),
            "source_bytes": source_size,
        }
        exit_code = 2
    except BaseException:
        result = {
            "protocol_version": PROTOCOL_VERSION,
            "adapter": "UNSUPPORTED",
            "adapter_version": ADAPTER_VERSION,
            "status": "REFUSED",
            "detected_format": detected,
            "anchors": [],
            "warnings": [],
            "security": _security(detected, "PARSER_WORKER_UNEXPECTED_FAILURE"),
            "source_bytes": source_size,
        }
        exit_code = 2
    sys.stdout.buffer.write(
        json.dumps(
            result, ensure_ascii=False, sort_keys=True, allow_nan=False
        ).encode("utf-8")
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
