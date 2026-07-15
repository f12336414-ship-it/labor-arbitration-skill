import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import jsonschema


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIRECTORY = SKILL_ROOT / "scripts"
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

import source_registry  # noqa: E402
from source_policy import OFFICIAL_SOURCE_CANDIDATE_HOSTS  # noqa: E402


class SourceRegistryTests(unittest.TestCase):
    def test_published_registry_and_schema_are_valid(self):
        schema = json.loads(
            source_registry.REGISTRY_SCHEMA_PATH.read_text(encoding="utf-8")
        )
        registry = json.loads(
            source_registry.REGISTRY_PATH.read_text(encoding="utf-8")
        )

        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.Draft202012Validator(
            schema, format_checker=jsonschema.FormatChecker()
        ).validate(registry)
        self.assertEqual(set(source_registry.OFFICIAL_SOURCE_REGISTRY), {
            "BEIJING_GOVERNMENT",
            "BEIJING_HRSS",
            "MOHRSS",
            "NATIONAL_LAWS_REGULATIONS_DATABASE",
            "STATE_COUNCIL",
            "SUPREME_PEOPLES_COURT",
        })

    def test_runtime_allowlist_is_derived_from_registry(self):
        expected = {
            code: set(entry["hosts"])
            for code, entry in source_registry.OFFICIAL_SOURCE_REGISTRY.items()
        }
        self.assertEqual(OFFICIAL_SOURCE_CANDIDATE_HOSTS, expected)

    def test_registry_does_not_claim_automated_access_authorization(self):
        for entry in source_registry.OFFICIAL_SOURCE_REGISTRY.values():
            self.assertEqual(
                entry["automated_access_authorization_status"], "NOT_ASSERTED"
            )
            self.assertTrue(entry["single_request_only"])
            if "OFFICIAL_CASE" in entry["permitted_purposes"]:
                self.assertGreaterEqual(entry["minimum_interval_seconds"], 10)

    def test_duplicate_publisher_code_fails_closed(self):
        registry = json.loads(
            source_registry.REGISTRY_PATH.read_text(encoding="utf-8")
        )
        registry["entries"].append(copy.deepcopy(registry["entries"][0]))
        schema = json.loads(
            source_registry.REGISTRY_SCHEMA_PATH.read_text(encoding="utf-8")
        )
        serialized = {
            source_registry.REGISTRY_PATH: json.dumps(registry),
            source_registry.REGISTRY_SCHEMA_PATH: json.dumps(schema),
        }

        def fake_read_text(path, **_kwargs):
            return serialized[Path(path)]

        with patch.object(Path, "read_text", fake_read_text):
            with self.assertRaises(source_registry.SourceRegistryError):
                source_registry.load_source_registry()

    def test_invalid_registry_document_fails_closed(self):
        with patch.object(Path, "read_text", return_value="not-json"):
            with self.assertRaises(source_registry.SourceRegistryError):
                source_registry.load_source_registry()

    def test_one_host_cannot_belong_to_two_publishers(self):
        registry = json.loads(
            source_registry.REGISTRY_PATH.read_text(encoding="utf-8")
        )
        schema = json.loads(
            source_registry.REGISTRY_SCHEMA_PATH.read_text(encoding="utf-8")
        )
        registry["entries"][1]["hosts"] = registry["entries"][0]["hosts"]
        serialized = {
            source_registry.REGISTRY_PATH: json.dumps(registry),
            source_registry.REGISTRY_SCHEMA_PATH: json.dumps(schema),
        }

        def fake_read_text(path, **_kwargs):
            return serialized[Path(path)]

        with patch.object(Path, "read_text", fake_read_text):
            with self.assertRaises(source_registry.SourceRegistryError) as captured:
                source_registry.load_source_registry()
        self.assertIn("multiple publishers", str(captured.exception))


if __name__ == "__main__":
    unittest.main()
