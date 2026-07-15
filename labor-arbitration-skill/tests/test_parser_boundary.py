import copy
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
import hashlib
import types
from pathlib import Path
from unittest.mock import patch


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIRECTORY = SKILL_ROOT / "scripts"
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from case_workspace import create_case_workspace  # noqa: E402
from isolated_parser import (  # noqa: E402
    IsolatedParserError,
    _run_worker,
    parse_workspace_object,
)
from parser_extraction_policy import (  # noqa: E402
    calculate_parser_record_snapshot,
    validate_parser_extraction_record,
)
import parser_worker  # noqa: E402


def load_manifest_builder():
    path = SCRIPT_DIRECTORY / "build_intake_manifest.py"
    spec = importlib.util.spec_from_file_location("parser_manifest_builder", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MANIFEST_BUILDER = load_manifest_builder()


def zip_bytes(entries):
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
    return target.getvalue()


def docx_bytes(*, external=False, macro=False):
    entries = {
        "[Content_Types].xml": (
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>"
        ),
        "word/document.xml": (
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:t>synthetic wage evidence</w:t></w:r></w:p></w:body>"
            "</w:document>"
        ),
        "word/_rels/document.xml.rels": (
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + (
                '<Relationship Id="rId1" Target="https://example.com" TargetMode="External"/>'
                if external
                else ""
            )
            + "</Relationships>"
        ),
    }
    if macro:
        entries["word/vbaProject.bin"] = b"synthetic macro bytes"
    return zip_bytes(entries)


def docx_with_unlabelled_external_target():
    payload = docx_bytes()
    with zipfile.ZipFile(io.BytesIO(payload)) as original:
        entries = {item.filename: original.read(item) for item in original.infolist()}
    entries["word/_rels/document.xml.rels"] = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Target="https://example.com/unlabelled"/>'
        "</Relationships>"
    )
    return zip_bytes(entries)


def xlsx_bytes():
    return zip_bytes(
        {
            "[Content_Types].xml": (
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Override PartName="/xl/workbook.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                "</Types>"
            ),
            "xl/workbook.xml": (
                '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                '<sheets><sheet name="工资" sheetId="1" r:id="rId1"/></sheets></workbook>'
            ),
            "xl/_rels/workbook.xml.rels": (
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/>'
                "</Relationships>"
            ),
            "xl/worksheets/sheet1.xml": (
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                '<sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>月份</t></is></c>'
                '<c r="B1"><f>1+1</f><v>2</v></c></row></sheetData></worksheet>'
            ),
        }
    )


def make_workspace(root, filename, payload):
    source = root / "source"
    source.mkdir()
    (source / filename).write_bytes(payload)
    intake = MANIFEST_BUILDER.build_manifest(source)
    workspace_root = root / "workspace"
    _path, workspace = create_case_workspace(
        source, intake, workspace_root, created_at="2026-07-15T06:00:00Z"
    )
    return workspace_root, workspace, workspace["files"][0]["raw_id"]


class ParserBoundaryIntegrationTests(unittest.TestCase):
    def parse(self, filename, payload):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        workspace_root, workspace, raw_id = make_workspace(root, filename, payload)
        record, report = parse_workspace_object(
            workspace_root,
            raw_id,
            created_at="2026-07-15T06:05:00Z",
        )
        return temporary, workspace_root, workspace, raw_id, record, report

    def test_utf8_text_is_line_anchored_and_deterministic(self):
        temp, workspace_root, _workspace, raw_id, first, report = self.parse(
            "工资说明.txt", "一月工资\n二月工资\n".encode("utf-8")
        )
        try:
            second, _ = parse_workspace_object(
                workspace_root,
                raw_id,
                created_at="2026-07-15T07:05:00Z",
            )
        finally:
            temp.cleanup()

        self.assertTrue(report["allowed"], report["findings"])
        self.assertEqual(first["status"], "SUCCEEDED")
        self.assertEqual(first["parser"]["adapter"], "UTF8_TEXT")
        self.assertEqual(first["anchors"][0]["coordinate"], "line:1")
        self.assertEqual(first["parse_id"], second["parse_id"])
        self.assertNotEqual(
            first["record_snapshot_sha256"], second["record_snapshot_sha256"]
        )

    def test_csv_docx_xlsx_and_email_adapters_emit_structural_anchors(self):
        email_bytes = (
            "From: employee@example.invalid\r\n"
            "To: employer@example.invalid\r\n"
            "Subject: synthetic wage request\r\n"
            "MIME-Version: 1.0\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n\r\n"
            "wage line one\r\nwage line two\r\n"
        ).encode("utf-8")
        cases = [
            ("wage.csv", "month,amount\n1,100\n".encode(), "CSV", "CSV_CELL"),
            ("contract.docx", docx_bytes(), "DOCX", "DOCX_PARAGRAPH"),
            ("payroll.xlsx", xlsx_bytes(), "XLSX", "XLSX_CELL"),
            ("notice.eml", email_bytes, "EML", "EMAIL_HEADER"),
        ]
        xlsx_warnings = []
        for filename, payload, adapter, anchor_kind in cases:
            with self.subTest(adapter=adapter):
                temp, _root, _workspace, _raw_id, record, report = self.parse(
                    filename, payload
                )
                temp.cleanup()
                self.assertTrue(report["allowed"], report["findings"])
                self.assertEqual(record["parser"]["adapter"], adapter)
                self.assertIn(anchor_kind, {item["kind"] for item in record["anchors"]})
                if adapter == "XLSX":
                    xlsx_warnings = record["warnings"]
        self.assertIn(
            "SPREADSHEET_FORMULA_PRESENT_NOT_EVALUATED",
            xlsx_warnings,
        )

    def test_macro_external_relationship_pdf_and_image_are_refused_without_anchors(self):
        cases = [
            ("macro.docx", docx_bytes(macro=True), "PARSER_OOXML_ACTIVE_CONTENT_REFUSED"),
            (
                "external.docx",
                docx_bytes(external=True),
                "PARSER_OOXML_EXTERNAL_RELATIONSHIP_REFUSED",
            ),
            ("file.pdf", b"%PDF-1.7\nsynthetic", "PARSER_PDF_ADAPTER_NOT_IMPLEMENTED"),
            (
                "scan.png",
                b"\x89PNG\r\n\x1a\nsynthetic",
                "PARSER_IMAGE_OCR_NOT_IMPLEMENTED",
            ),
        ]
        for filename, payload, refusal_code in cases:
            with self.subTest(refusal_code=refusal_code):
                temp, _root, _workspace, _raw_id, record, report = self.parse(
                    filename, payload
                )
                temp.cleanup()
                self.assertTrue(report["allowed"], report["findings"])
                self.assertEqual(record["status"], "REFUSED")
                self.assertEqual(record["anchors"], [])
                self.assertEqual(record["security"]["refusal_code"], refusal_code)

    def test_zip_is_inspected_without_extraction_and_traversal_is_refused(self):
        safe = zip_bytes({"folder/a.txt": b"synthetic"})
        unsafe = zip_bytes({"../escape.txt": b"synthetic"})
        safe_temp, _root, _workspace, _raw_id, safe_record, _ = self.parse(
            "evidence.zip", safe
        )
        unsafe_temp, _root, _workspace, _raw_id, unsafe_record, _ = self.parse(
            "unsafe.zip", unsafe
        )
        safe_temp.cleanup()
        unsafe_temp.cleanup()

        self.assertEqual(safe_record["parser"]["adapter"], "ZIP_INSPECTION")
        self.assertEqual(safe_record["anchors"][0]["text"], "folder/a.txt")
        self.assertEqual(
            unsafe_record["security"]["refusal_code"],
            "PARSER_ARCHIVE_PATH_UNSAFE",
        )

    def test_invalid_workspace_or_raw_id_is_refused_before_worker(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace_root, workspace, raw_id = make_workspace(
                root, "evidence.txt", b"synthetic"
            )
            with self.assertRaises(IsolatedParserError) as missing:
                parse_workspace_object(workspace_root, "RAW-" + "0" * 64)
            object_path = workspace_root.joinpath(
                *Path(workspace["files"][0]["object_relative_path"]).parts
            )
            object_path.chmod(0o600)
            object_path.write_bytes(b"tampered")
            with self.assertRaises(IsolatedParserError) as damaged:
                parse_workspace_object(workspace_root, raw_id)

        self.assertEqual(missing.exception.code, "PARSER_RAW_ID_NOT_FOUND")
        self.assertEqual(damaged.exception.code, "PARSER_WORKSPACE_INVALID")

    def test_cli_emits_record_and_offline_validator_accepts_it(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace_root, _workspace, raw_id = make_workspace(
                root, "evidence.txt", b"synthetic line"
            )
            parsed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_DIRECTORY / "parse_case_workspace.py"),
                    str(workspace_root),
                    raw_id,
                ],
                cwd=SKILL_ROOT,
                capture_output=True,
                encoding="utf-8",
                check=False,
            )
            record_path = root / "parse.json"
            record_path.write_text(parsed.stdout, encoding="utf-8")
            validated = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_DIRECTORY / "validate_parser_extraction.py"),
                    str(record_path),
                ],
                cwd=SKILL_ROOT,
                capture_output=True,
                encoding="utf-8",
                check=False,
            )

        self.assertEqual(parsed.returncode, 0, parsed.stdout + parsed.stderr)
        self.assertEqual(validated.returncode, 0, validated.stdout + validated.stderr)
        self.assertTrue(json.loads(validated.stdout)["human_anchor_confirmation_required"])


class ParserWorkerAndPolicyTests(unittest.TestCase):
    def test_worker_applies_available_posix_resource_limits_fail_closed_enough(self):
        calls = []

        def set_limit(kind, value):
            calls.append((kind, value))
            if kind == 2:
                raise OSError("synthetic unsupported limit")

        fake_resource = types.SimpleNamespace(
            RLIMIT_CPU=1,
            RLIMIT_AS=2,
            RLIMIT_FSIZE=3,
            RLIMIT_NOFILE=4,
            setrlimit=set_limit,
        )
        with patch.dict(sys.modules, {"resource": fake_resource}):
            parser_worker._apply_resource_limits()
        self.assertEqual({item[0] for item in calls}, {1, 2, 3, 4})

    def test_worker_adapters_are_directly_covered_without_site_injection(self):
        email_bytes = (
            "From: employee@example.invalid\r\n"
            "Subject: synthetic\r\n"
            "MIME-Version: 1.0\r\n"
            "Content-Type: multipart/mixed; boundary=x\r\n\r\n"
            "--x\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nline one\r\n"
            "--x\r\nContent-Type: text/html\r\n\r\n<p>ignored</p>\r\n"
            "--x\r\nContent-Disposition: attachment; filename=a.txt\r\n\r\nignored\r\n--x--\r\n"
        ).encode("utf-8")
        cases = [
            (b"line one\nline two\n", "evidence.txt", "UTF8_TEXT", "TEXT_LINE"),
            (b"month,amount\n1,100\n", "wage.csv", "CSV", "CSV_CELL"),
            (docx_bytes(), "contract.docx", "DOCX", "DOCX_PARAGRAPH"),
            (xlsx_bytes(), "payroll.xlsx", "XLSX", "XLSX_CELL"),
            (email_bytes, "notice.eml", "EML", "EMAIL_HEADER"),
            (
                zip_bytes({"folder/a.txt": b"synthetic"}),
                "bundle.zip",
                "ZIP",
                "ARCHIVE_ENTRY",
            ),
        ]
        for payload, name, expected_format, expected_kind in cases:
            with self.subTest(expected_format=expected_format):
                detected, anchors, _warnings = parser_worker._extract(payload, name)
                parser_worker._check_anchor_limits(anchors)
                self.assertEqual(detected, expected_format)
                self.assertIn(expected_kind, {item["kind"] for item in anchors})
                self.assertEqual(
                    parser_worker._detected_format(payload, name), expected_format
                )

    def test_worker_direct_refusal_paths_are_stable(self):
        cases = [
            (b"\x00", "evidence.txt", "PARSER_TEXT_NUL_REFUSED"),
            (b"\xff", "evidence.txt", "PARSER_TEXT_NOT_UTF8"),
            (b'"unterminated', "evidence.csv", "PARSER_CSV_INVALID"),
            (docx_bytes(macro=True), "macro.docx", "PARSER_OOXML_ACTIVE_CONTENT_REFUSED"),
            (
                docx_bytes(external=True),
                "external.docx",
                "PARSER_OOXML_EXTERNAL_RELATIONSHIP_REFUSED",
            ),
            (
                docx_with_unlabelled_external_target(),
                "unlabelled-external.docx",
                "PARSER_OOXML_EXTERNAL_RELATIONSHIP_REFUSED",
            ),
            (b"%PDF-1.7\n", "evidence.pdf", "PARSER_PDF_ADAPTER_NOT_IMPLEMENTED"),
            (
                b"\x89PNG\r\n\x1a\nsynthetic",
                "image.png",
                "PARSER_IMAGE_OCR_NOT_IMPLEMENTED",
            ),
            (
                b"\xff\xd8\xffsynthetic",
                "image.jpg",
                "PARSER_IMAGE_OCR_NOT_IMPLEMENTED",
            ),
            (b"binary", "unknown.bin", "PARSER_FORMAT_UNSUPPORTED"),
        ]
        for payload, name, expected in cases:
            with self.subTest(expected=expected):
                with self.assertRaises(parser_worker.WorkerRefusal) as captured:
                    parser_worker._extract(payload, name)
                self.assertEqual(captured.exception.code, expected)
        self.assertEqual(parser_worker._detected_format(b"%PDF-1.7", "x"), "PDF")
        self.assertEqual(
            parser_worker._detected_format(b"\x89PNG\r\n\x1a\n", "x"), "PNG"
        )
        self.assertEqual(parser_worker._detected_format(b"\xff\xd8\xff", "x"), "JPEG")
        self.assertEqual(
            parser_worker._detected_format(zip_bytes({"../x": b"x"}), "x.zip"),
            "ZIP",
        )

    def test_worker_protocol_and_stable_object_binding(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "object.bin"
            payload = b"synthetic"
            path.write_bytes(payload)
            request = {
                "protocol_version": "1.0",
                "object_path": str(path),
                "source_name": "evidence.txt",
                "expected_content_sha256": hashlib.sha256(payload).hexdigest(),
                "expected_size_bytes": len(payload),
            }
            protocol = io.TextIOWrapper(
                io.BytesIO(json.dumps(request).encode("utf-8")), encoding="utf-8"
            )
            with patch.object(parser_worker.sys, "stdin", protocol):
                loaded = parser_worker._read_protocol()
            self.assertEqual(parser_worker._read_stable_object(loaded), payload)

            wrong = dict(loaded, expected_content_sha256="0" * 64)
            with self.assertRaises(parser_worker.WorkerRefusal) as bad_hash:
                parser_worker._read_stable_object(wrong)
            directory_request = dict(loaded, object_path=temp_dir)
            with self.assertRaises(parser_worker.WorkerRefusal) as unsafe:
                parser_worker._read_stable_object(directory_request)

        self.assertEqual(bad_hash.exception.code, "PARSER_OBJECT_HASH_MISMATCH")
        self.assertEqual(unsafe.exception.code, "PARSER_OBJECT_PATH_UNSAFE")

    def test_worker_protocol_rejects_oversized_and_invalid_messages(self):
        cases = [
            b"x" * (parser_worker.MAX_PROTOCOL_BYTES + 1),
            b"not-json",
            b"[]",
            json.dumps(
                {
                    "protocol_version": "9.9",
                    "object_path": "x",
                    "source_name": "x",
                    "expected_content_sha256": "0" * 64,
                    "expected_size_bytes": 0,
                }
            ).encode("utf-8"),
        ]
        for payload in cases:
            with self.subTest(size=len(payload)):
                stdin = io.TextIOWrapper(io.BytesIO(payload), encoding="utf-8")
                with patch.object(parser_worker.sys, "stdin", stdin):
                    with self.assertRaises(parser_worker.WorkerRefusal):
                        parser_worker._read_protocol()

    def test_worker_main_returns_bounded_success_refusal_and_generic_failure(self):
        def run_main(request, *, unexpected=False):
            stdin = io.TextIOWrapper(
                io.BytesIO(json.dumps(request).encode("utf-8")), encoding="utf-8"
            )
            output_bytes = io.BytesIO()
            stdout = io.TextIOWrapper(output_bytes, encoding="utf-8")
            patches = [
                patch.object(parser_worker.sys, "stdin", stdin),
                patch.object(parser_worker.sys, "stdout", stdout),
                patch.object(parser_worker, "_apply_resource_limits"),
            ]
            if unexpected:
                patches.append(
                    patch.object(parser_worker, "_read_protocol", side_effect=RuntimeError)
                )
            for active in patches:
                active.start()
            try:
                code = parser_worker.main()
                stdout.flush()
                result = json.loads(output_bytes.getvalue().decode("utf-8"))
            finally:
                for active in reversed(patches):
                    active.stop()
            return code, result

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "object.txt"
            path.write_bytes(b"synthetic")
            request = {
                "protocol_version": "1.0",
                "object_path": str(path),
                "source_name": "evidence.txt",
                "expected_content_sha256": hashlib.sha256(b"synthetic").hexdigest(),
                "expected_size_bytes": 9,
            }
            success_code, success = run_main(request)
            refused_code, refused = run_main(dict(request, source_name="unknown.bin"))
            failed_code, failed = run_main(request, unexpected=True)

        self.assertEqual(success_code, 0)
        self.assertEqual(success["status"], "SUCCEEDED")
        self.assertEqual(refused_code, 2)
        self.assertEqual(refused["security"]["refusal_code"], "PARSER_FORMAT_UNSUPPORTED")
        self.assertEqual(failed_code, 2)
        self.assertEqual(
            failed["security"]["refusal_code"], "PARSER_WORKER_UNEXPECTED_FAILURE"
        )

    def test_worker_rejects_zip_bomb_ratio_and_xml_declarations(self):
        bomb = zip_bytes({"repeated.txt": b"0" * 20000})
        with self.assertRaises(parser_worker.WorkerRefusal) as ratio:
            parser_worker._inspect_zip(bomb)
        with self.assertRaises(parser_worker.WorkerRefusal) as xml:
            parser_worker._parse_xml(b'<!DOCTYPE x [<!ENTITY y "z">]><x>&y;</x>')
        with self.assertRaises(parser_worker.WorkerRefusal) as malformed_xml:
            parser_worker._parse_xml(b"<not-closed>")

        self.assertEqual(
            ratio.exception.code, "PARSER_ARCHIVE_COMPRESSION_RATIO_REFUSED"
        )
        self.assertEqual(
            xml.exception.code, "PARSER_XML_ACTIVE_DECLARATION_REFUSED"
        )
        self.assertEqual(malformed_xml.exception.code, "PARSER_XML_INVALID")

    def test_archive_and_anchor_boundary_helpers_refuse_unsafe_values(self):
        for name in ("../escape", "/absolute", "C:/drive", "bad\\name"):
            with self.subTest(name=name):
                with self.assertRaises(parser_worker.WorkerRefusal):
                    parser_worker._safe_archive_name(name)
        with self.assertRaises(parser_worker.WorkerRefusal) as anchor_text:
            parser_worker._anchor("TEXT_LINE", "line:1", "x" * 10001)
        with self.assertRaises(parser_worker.WorkerRefusal) as anchor_count:
            parser_worker._check_anchor_limits(
                [{"text": ""}] * (parser_worker.MAX_ANCHORS + 1)
            )
        self.assertEqual(anchor_text.exception.code, "PARSER_ANCHOR_TEXT_TOO_LARGE")
        self.assertEqual(anchor_count.exception.code, "PARSER_ANCHOR_LIMIT_EXCEEDED")

    def test_parent_timeout_and_worker_protocol_failure_are_stable(self):
        request = {
            "protocol_version": "1.0",
            "object_path": "synthetic",
            "source_name": "synthetic.txt",
            "expected_content_sha256": "0" * 64,
            "expected_size_bytes": 0,
        }
        with patch(
            "isolated_parser.subprocess.run",
            side_effect=subprocess.TimeoutExpired("worker", 1),
        ):
            with self.assertRaises(IsolatedParserError) as timeout:
                _run_worker(request, timeout_seconds=1)
        with self.assertRaises(IsolatedParserError) as invalid_timeout:
            _run_worker(request, timeout_seconds=0)

        self.assertEqual(timeout.exception.code, "PARSER_WORKER_TIMEOUT")
        self.assertEqual(invalid_timeout.exception.code, "PARSER_TIMEOUT_INVALID")

    def test_parent_rejects_worker_process_and_protocol_anomalies(self):
        request = {
            "protocol_version": "1.0",
            "object_path": "synthetic",
            "source_name": "synthetic.txt",
            "expected_content_sha256": "0" * 64,
            "expected_size_bytes": 0,
        }
        cases = [
            (OSError("start"), "PARSER_WORKER_START_FAILED"),
            (
                subprocess.CompletedProcess([], 0, b"{}", b"unexpected"),
                "PARSER_WORKER_STDERR_REFUSED",
            ),
            (
                subprocess.CompletedProcess([], 3, b"{}", b""),
                "PARSER_WORKER_EXIT_INVALID",
            ),
            (
                subprocess.CompletedProcess([], 0, b"not-json", b""),
                "PARSER_WORKER_PROTOCOL_INVALID",
            ),
            (
                subprocess.CompletedProcess([], 0, b"[]", b""),
                "PARSER_WORKER_PROTOCOL_INVALID",
            ),
            (
                subprocess.CompletedProcess(
                    [], 0, b"x" * (8 * 1024 * 1024 + 1), b""
                ),
                "PARSER_WORKER_OUTPUT_TOO_LARGE",
            ),
        ]
        for outcome, expected in cases:
            with self.subTest(expected=expected), patch(
                "isolated_parser.subprocess.run",
                side_effect=outcome if isinstance(outcome, BaseException) else None,
                return_value=None if isinstance(outcome, BaseException) else outcome,
            ):
                with self.assertRaises(IsolatedParserError) as captured:
                    _run_worker(request)
                self.assertEqual(captured.exception.code, expected)

        valid_refused = {
            "protocol_version": "1.0",
            "adapter": "UNSUPPORTED",
            "adapter_version": "1.0.0",
            "status": "REFUSED",
            "detected_format": "UNKNOWN",
            "anchors": [],
            "warnings": [],
            "security": {},
            "source_bytes": 0,
        }
        with patch(
            "isolated_parser.subprocess.run",
            return_value=subprocess.CompletedProcess(
                [], 0, json.dumps(valid_refused).encode(), b""
            ),
        ):
            with self.assertRaises(IsolatedParserError) as mismatch:
                _run_worker(request)
        self.assertEqual(mismatch.exception.code, "PARSER_WORKER_STATUS_MISMATCH")

    def test_policy_detects_anchor_and_record_mutation(self):
        temp, _root, _workspace, _raw_id, record, _ = ParserBoundaryIntegrationTests().parse(
            "evidence.txt", b"synthetic"
        )
        temp.cleanup()
        damaged = copy.deepcopy(record)
        damaged["anchors"][0]["text"] = "mutated"
        damaged["record_snapshot_sha256"] = calculate_parser_record_snapshot(damaged)
        report = validate_parser_extraction_record(damaged)

        codes = {item["code"] for item in report["findings"]}
        self.assertIn("PARSER_ANCHOR_TEXT_HASH_MISMATCH", codes)
        self.assertIn("PARSER_PARSE_ID_MISMATCH", codes)

    def test_policy_failure_modes_are_independently_reported(self):
        temp, _root, _workspace, _raw_id, record, _ = ParserBoundaryIntegrationTests().parse(
            "evidence.txt", b"synthetic"
        )
        temp.cleanup()
        self.assertFalse(validate_parser_extraction_record({})["allowed"])

        duplicate = copy.deepcopy(record)
        duplicate["anchors"].append(copy.deepcopy(duplicate["anchors"][0]))
        duplicate["limits"]["anchor_count"] = 2
        duplicate["limits"]["extracted_characters"] *= 2
        duplicate_report = validate_parser_extraction_record(duplicate)

        status = copy.deepcopy(record)
        status["security"]["refusal_code"] = "PARSER_SYNTHETIC_REFUSAL"
        status_report = validate_parser_extraction_record(status)

        refused = copy.deepcopy(status)
        refused["status"] = "REFUSED"
        refused_report = validate_parser_extraction_record(refused)

        adapter = copy.deepcopy(record)
        adapter["parser"]["adapter"] = "UNSUPPORTED"
        adapter_report = validate_parser_extraction_record(adapter)

        snapshot = copy.deepcopy(record)
        snapshot["record_snapshot_sha256"] = "0" * 64
        snapshot_report = validate_parser_extraction_record(snapshot)

        codes = lambda report: {item["code"] for item in report["findings"]}
        self.assertIn("PARSER_ANCHOR_IDENTITY_DUPLICATE", codes(duplicate_report))
        self.assertIn("PARSER_REFUSAL_STATUS_MISMATCH", codes(status_report))
        self.assertIn("PARSER_REFUSAL_HAS_ANCHORS", codes(refused_report))
        self.assertIn("PARSER_ADAPTER_STATUS_MISMATCH", codes(adapter_report))
        self.assertIn("PARSER_RECORD_SNAPSHOT_MISMATCH", codes(snapshot_report))

    def test_policy_date_and_canonicalization_guards_do_not_depend_on_schema(self):
        temp, _root, _workspace, _raw_id, record, _ = ParserBoundaryIntegrationTests().parse(
            "evidence.txt", b"synthetic"
        )
        temp.cleanup()
        invalid_date = copy.deepcopy(record)
        invalid_date["created_at"] = "not-a-time"
        noncanonical = copy.deepcopy(record)
        noncanonical["warnings"] = [float("nan")]
        with patch(
            "parser_extraction_policy.validate_published_parser_extraction_record",
            side_effect=lambda _record: [],
        ):
            date_report = validate_parser_extraction_record(invalid_date)
            canonical_report = validate_parser_extraction_record(noncanonical)
        codes = lambda report: {item["code"] for item in report["findings"]}
        self.assertIn("DATE_FORMAT_INVALID", codes(date_report))
        self.assertIn("PARSER_RECORD_CANONICALIZATION_FAILED", codes(canonical_report))


if __name__ == "__main__":
    unittest.main()
