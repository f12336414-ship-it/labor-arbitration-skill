import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIRECTORY = SKILL_ROOT / "scripts"
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from bounded_json_input import (  # noqa: E402
    BoundedJsonInputError,
    load_bounded_json_object,
)
import schema_validation  # noqa: E402


class BoundedJsonInputTests(unittest.TestCase):
    def test_valid_object_is_loaded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "input.json"
            path.write_text('{"value": 1}', encoding="utf-8")
            self.assertEqual(
                load_bounded_json_object(path, 100, "SYNTHETIC", "input"),
                {"value": 1},
            )

    def test_malformed_or_unsafe_inputs_fail_with_stable_codes(self):
        cases = {
            "duplicate": (b'{"a": 1, "a": 2}', "SYNTHETIC_DUPLICATE_KEY", 100),
            "constant": (b'{"a": NaN}', "SYNTHETIC_INVALID_CONSTANT", 100),
            "malformed": (b'{"a":', "SYNTHETIC_INVALID_JSON", 100),
            "array": (b"[]", "SYNTHETIC_ROOT_NOT_OBJECT", 100),
            "invalid-utf8": (b"\xff", "SYNTHETIC_UNREADABLE", 100),
            "oversized": (b'{"a": 1}', "SYNTHETIC_TOO_LARGE", 2),
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for name, (payload, expected, maximum) in cases.items():
                with self.subTest(name=name):
                    path = root / f"{name}.json"
                    path.write_bytes(payload)
                    with self.assertRaises(BoundedJsonInputError) as captured:
                        load_bounded_json_object(path, maximum, "SYNTHETIC", "input")
                    self.assertEqual(captured.exception.code, expected)

            with self.assertRaises(BoundedJsonInputError) as captured:
                load_bounded_json_object(
                    root / "missing.json", 100, "SYNTHETIC", "input"
                )
            self.assertEqual(captured.exception.code, "SYNTHETIC_UNREADABLE")

    def test_pathological_nesting_is_refused(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "deep.json"
            path.write_text(
                '{"a":' + "[" * 1200 + "0" + "]" * 1200 + "}",
                encoding="utf-8",
            )
            with self.assertRaises(BoundedJsonInputError) as captured:
                load_bounded_json_object(path, 10000, "SYNTHETIC", "input")
        self.assertEqual(captured.exception.code, "SYNTHETIC_TOO_DEEPLY_NESTED")

    def test_braces_inside_json_strings_do_not_consume_nesting_budget(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "quoted-braces.json"
            path.write_text('{"value":"' + "[{" * 200 + '"}', encoding="utf-8")
            value = load_bounded_json_object(path, 10000, "SYNTHETIC", "input")
        self.assertEqual(len(value["value"]), 400)


class PublishedSchemaAvailabilityTests(unittest.TestCase):
    def test_every_published_schema_boundary_fails_closed(self):
        validators = [
            schema_validation.validate_published_schema,
            schema_validation.validate_published_intake_schema,
            schema_validation.validate_published_review_packet,
            schema_validation.validate_published_formal_output_state,
            schema_validation.validate_published_frozen_source_record,
            schema_validation.validate_published_legal_version_graph,
            schema_validation.validate_published_legal_freshness_check,
            schema_validation.validate_published_legal_text_diff,
            schema_validation.validate_published_historical_version_candidate,
            schema_validation.validate_published_official_case_record,
            schema_validation.validate_published_case_workspace,
        ]
        with patch.object(schema_validation, "_load_validator", side_effect=OSError):
            for validator in validators:
                with self.subTest(validator=validator.__name__):
                    findings = validator({})
                    self.assertEqual(len(findings), 1)
                    self.assertEqual(findings[0]["severity"], "P0")
                    self.assertIn("UNAVAILABLE", findings[0]["code"])

    def test_schema_errors_are_deduplicated_by_instance_path(self):
        class SyntheticError:
            def __init__(self, path, message):
                self.absolute_path = path
                self.message = message

        class SyntheticValidator:
            def iter_errors(self, _value):
                return [
                    SyntheticError(["same"], "second"),
                    SyntheticError(["same"], "first"),
                    SyntheticError(["other", 0], "third"),
                ]

        findings = schema_validation._collect_errors(
            SyntheticValidator(),
            {},
            code="SYNTHETIC_SCHEMA_ERROR",
            prefix="packet",
            message="synthetic",
        )
        self.assertEqual([item["path"] for item in findings], ["packet.other[0]", "packet.same"])


if __name__ == "__main__":
    unittest.main()
