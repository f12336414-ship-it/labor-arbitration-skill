import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SKILL_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = SKILL_ROOT.parent
SCRIPT_DIRECTORY = SKILL_ROOT / "scripts"
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from legal_text_diff import (  # noqa: E402
    LegalTextDiffError,
    build_legal_text_diff,
    calculate_legal_text_diff_snapshot,
    validate_legal_text_diff_record,
    read_plain_stable_utf8,
)


EXAMPLE_DIRECTORY = REPOSITORY_ROOT / "examples" / "legal-sources"
DIFF_EXAMPLE = EXAMPLE_DIRECTORY / "synthetic-text-diff.json"
FROM_EXAMPLE = EXAMPLE_DIRECTORY / "synthetic-rule-v1.txt"
TO_EXAMPLE = EXAMPLE_DIRECTORY / "synthetic-rule-v2.txt"
COMPARE_SCRIPT = SCRIPT_DIRECTORY / "compare_legal_versions.py"
VALIDATE_SCRIPT = SCRIPT_DIRECTORY / "validate_legal_text_diff.py"


def load_example():
    return json.loads(DIFF_EXAMPLE.read_text(encoding="utf-8"))


class LegalTextDiffTests(unittest.TestCase):
    def test_published_example_has_exact_changed_text_and_valid_snapshot(self):
        record = load_example()
        report = validate_legal_text_diff_record(record)

        self.assertTrue(report["allowed"], report["findings"])
        self.assertIn("每月五日前", record["operations"][0]["removed_text"])
        self.assertIn("每月十日前", record["operations"][0]["added_text"])
        self.assertFalse(report["submission_ready"])

    def test_builder_matches_published_example(self):
        record = build_legal_text_diff(
            "VERSION_2024",
            "VERSION_2025",
            FROM_EXAMPLE.read_text(encoding="utf-8"),
            TO_EXAMPLE.read_text(encoding="utf-8"),
        )

        self.assertEqual(record, load_example())

    def test_no_unicode_normalization_hides_character_change(self):
        record = build_legal_text_diff(
            "VERSION_COMPOSED",
            "VERSION_DECOMPOSED",
            "é\n",
            "e\u0301\n",
        )

        self.assertFalse(record["change_summary"]["equal"])
        self.assertNotEqual(record["from_content_sha256"], record["to_content_sha256"])
        self.assertEqual(record["unicode_normalization"], "NONE")

    def test_equal_inputs_have_no_operations(self):
        record = build_legal_text_diff(
            "VERSION_ONE", "VERSION_TWO", "same\n", "same\n"
        )

        self.assertTrue(record["change_summary"]["equal"])
        self.assertEqual(record["operations"], [])
        self.assertEqual(record["unified_diff"], "")
        self.assertTrue(validate_legal_text_diff_record(record)["allowed"])

    def test_invalid_operation_range_is_blocked_even_with_new_snapshot(self):
        record = load_example()
        record["operations"][0]["from_end_line"] = 99
        record["diff_snapshot_sha256"] = calculate_legal_text_diff_snapshot(record)

        codes = {
            item["code"]
            for item in validate_legal_text_diff_record(record)["findings"]
        }
        self.assertIn("LEGAL_TEXT_DIFF_OPERATION_RANGE_INVALID", codes)

    def test_mutation_without_new_snapshot_is_blocked(self):
        record = load_example()
        record["unified_diff"] += "changed"

        codes = {
            item["code"]
            for item in validate_legal_text_diff_record(record)["findings"]
        }
        self.assertIn("LEGAL_TEXT_DIFF_SNAPSHOT_MISMATCH", codes)

    def test_builder_refuses_oversized_text(self):
        with self.assertRaises(LegalTextDiffError) as context:
            build_legal_text_diff(
                "VERSION_ONE", "VERSION_TWO", "x" * (1024 * 1024 + 1), ""
            )

        self.assertEqual(context.exception.code, "LEGAL_TEXT_DIFF_INPUT_TOO_LARGE")

    def test_builder_refuses_invalid_ids_and_non_text_inputs(self):
        with self.assertRaises(LegalTextDiffError) as invalid_id:
            build_legal_text_diff("bad", "VERSION_TWO", "", "")
        with self.assertRaises(LegalTextDiffError) as invalid_type:
            build_legal_text_diff("VERSION_ONE", "VERSION_TWO", b"bytes", "")

        self.assertEqual(
            invalid_id.exception.code, "LEGAL_TEXT_DIFF_VERSION_ID_INVALID"
        )
        self.assertEqual(
            invalid_type.exception.code, "LEGAL_TEXT_DIFF_INPUT_TYPE_INVALID"
        )

    def test_builder_refuses_invalid_generated_schema_and_oversized_diff(self):
        with patch(
            "legal_text_diff.validate_published_legal_text_diff",
            return_value=[{"code": "synthetic"}],
        ):
            with self.assertRaises(LegalTextDiffError) as invalid:
                build_legal_text_diff("VERSION_ONE", "VERSION_TWO", "a", "b")
        self.assertEqual(invalid.exception.code, "LEGAL_TEXT_DIFF_GENERATION_INVALID")

        with patch("legal_text_diff.MAX_SERIALIZED_DIFF_BYTES", 1):
            with self.assertRaises(LegalTextDiffError) as oversized:
                build_legal_text_diff("VERSION_ONE", "VERSION_TWO", "a", "b")
        self.assertEqual(oversized.exception.code, "LEGAL_TEXT_DIFF_OUTPUT_TOO_LARGE")

    def test_plain_text_reader_refuses_directory_and_oversized_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with self.assertRaises(LegalTextDiffError) as unsafe:
                read_plain_stable_utf8(root)
            oversized_path = root / "oversized.txt"
            oversized_path.write_bytes(b"x" * (1024 * 1024 + 1))
            with self.assertRaises(LegalTextDiffError) as oversized:
                read_plain_stable_utf8(oversized_path)

        self.assertEqual(unsafe.exception.code, "LEGAL_TEXT_DIFF_INPUT_PATH_UNSAFE")
        self.assertEqual(oversized.exception.code, "LEGAL_TEXT_DIFF_INPUT_TOO_LARGE")

    def test_operation_shape_text_and_summary_damage_are_detected(self):
        record = load_example()
        record["operations"][0]["tag"] = "DELETE"
        record["operations"][0]["added_text"] = "still present\n"
        record["operations"][0]["removed_text"] = ""
        record["change_summary"]["added_line_units"] = 99
        record["diff_snapshot_sha256"] = calculate_legal_text_diff_snapshot(record)

        codes = {
            item["code"]
            for item in validate_legal_text_diff_record(record)["findings"]
        }
        self.assertIn("LEGAL_TEXT_DIFF_OPERATION_SHAPE_INVALID", codes)
        self.assertIn("LEGAL_TEXT_DIFF_OPERATION_TEXT_MISMATCH", codes)
        self.assertIn("LEGAL_TEXT_DIFF_SUMMARY_MISMATCH", codes)

    def test_compare_cli_matches_published_example(self):
        result = subprocess.run(
            [
                sys.executable,
                str(COMPARE_SCRIPT),
                str(FROM_EXAMPLE),
                str(TO_EXAMPLE),
                "--from-version-id",
                "VERSION_2024",
                "--to-version-id",
                "VERSION_2025",
            ],
            cwd=SKILL_ROOT,
            capture_output=True,
            encoding="utf-8",
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), load_example())

    def test_compare_cli_refuses_non_utf8(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            invalid = Path(temp_dir) / "invalid.txt"
            invalid.write_bytes(b"\xff")
            result = subprocess.run(
                [
                    sys.executable,
                    str(COMPARE_SCRIPT),
                    str(invalid),
                    str(TO_EXAMPLE),
                    "--from-version-id",
                    "VERSION_ONE",
                    "--to-version-id",
                    "VERSION_TWO",
                ],
                cwd=SKILL_ROOT,
                capture_output=True,
                encoding="utf-8",
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            json.loads(result.stdout)["error"]["code"],
            "LEGAL_TEXT_DIFF_INPUT_NOT_UTF8",
        )

    def test_validate_cli_accepts_example_and_rejects_duplicate_key(self):
        valid = subprocess.run(
            [sys.executable, str(VALIDATE_SCRIPT), str(DIFF_EXAMPLE)],
            cwd=SKILL_ROOT,
            capture_output=True,
            encoding="utf-8",
            check=False,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            invalid_path = Path(temp_dir) / "invalid.json"
            invalid_path.write_text('{"schema_version":"1.0","schema_version":"1.0"}')
            invalid = subprocess.run(
                [sys.executable, str(VALIDATE_SCRIPT), str(invalid_path)],
                cwd=SKILL_ROOT,
                capture_output=True,
                encoding="utf-8",
                check=False,
            )

        self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)
        self.assertEqual(invalid.returncode, 1)
        self.assertEqual(
            json.loads(invalid.stdout)["error"]["code"],
            "LEGAL_TEXT_DIFF_RECORD_DUPLICATE_KEY",
        )


if __name__ == "__main__":
    unittest.main()
