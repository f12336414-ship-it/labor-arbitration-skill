import hashlib
import importlib.util
import json
import unittest
from pathlib import Path

import rfc8785
from hypothesis import given, settings, strategies as st


SKILL_ROOT = Path(__file__).resolve().parents[1]


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, SKILL_ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PRIMITIVES = load_module("integrity_primitives_under_test", "integrity_primitives.py")
VALIDATOR = load_module("validator_property_under_test", "validate_case_package.py")

UNICODE_TEXT = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)), max_size=40
)
JSON_SCALARS = st.one_of(st.none(), st.booleans(), st.integers(-1_000_000, 1_000_000), UNICODE_TEXT)


class IntegrityPropertyTests(unittest.TestCase):
    def test_published_cross_language_rfc8785_vectors(self):
        vectors = json.loads(
            (SKILL_ROOT / "references" / "rfc8785-vectors.json").read_text(
                encoding="utf-8"
            )
        )["vectors"]
        for vector in vectors:
            with self.subTest(vector=vector["name"]):
                canonical = PRIMITIVES.canonicalize_json(vector["input"])
                self.assertEqual(
                    canonical, vector["canonical_json"].encode("utf-8")
                )
                self.assertEqual(
                    hashlib.sha256(canonical).hexdigest(), vector["sha256"]
                )

    @settings(max_examples=100, deadline=None)
    @given(
        relative_path=UNICODE_TEXT.filter(bool),
        content=st.binary(max_size=256),
    )
    def test_stable_raw_id_is_deterministic_for_unicode_paths(self, relative_path, content):
        content_sha256 = hashlib.sha256(content).hexdigest()
        first = PRIMITIVES.expected_raw_id(relative_path, content_sha256)
        second = PRIMITIVES.expected_raw_id(relative_path, content_sha256)

        self.assertEqual(first, second)
        self.assertRegex(first, r"^RAW-[0-9a-f]{64}$")

    @settings(max_examples=100, deadline=None)
    @given(st.dictionaries(UNICODE_TEXT, JSON_SCALARS, max_size=12))
    def test_rfc8785_round_trips_json_values_and_ignores_insertion_order(self, value):
        reversed_value = dict(reversed(list(value.items())))
        canonical = PRIMITIVES.canonicalize_json(value)

        self.assertEqual(canonical, PRIMITIVES.canonicalize_json(reversed_value))
        self.assertEqual(json.loads(canonical.decode("utf-8")), value)

    @settings(max_examples=50, deadline=None)
    @given(notes=JSON_SCALARS)
    def test_arbitrary_draft_notes_never_crash_the_validator(self, notes):
        report = VALIDATOR.validate_case_package(
            {"schema_version": "1.3", "requested_state": "DRAFT", "notes": notes}
        )
        self.assertIsInstance(report["allowed"], bool)
        self.assertIsInstance(report["findings"], list)

    def test_non_i_json_integer_is_fail_closed_for_snapshot_comparison(self):
        with self.assertRaises(rfc8785.IntegerDomainError):
            PRIMITIVES.canonicalize_json({"value": 2**60})
        self.assertFalse(
            PRIMITIVES.snapshot_matches("0" * 64, {"value": 2**60})
        )

    def test_non_i_json_path_is_fail_closed_without_unicode_traceback(self):
        self.assertIsNone(PRIMITIVES.expected_raw_id("bad-\ud800", "0" * 64))
        self.assertFalse(VALIDATOR.is_safe_relative_path("bad-\ud800"))


if __name__ == "__main__":
    unittest.main()
