import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = SKILL_ROOT.parent
SCRIPT_DIRECTORY = SKILL_ROOT / "scripts"
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from legal_version_graph_policy import (  # noqa: E402
    calculate_legal_version_graph_snapshot,
    validate_legal_version_graph,
)


EXAMPLE_PATH = (
    REPOSITORY_ROOT
    / "examples"
    / "legal-sources"
    / "synthetic-version-graph.json"
)
SCRIPT = SCRIPT_DIRECTORY / "validate_legal_version_graph.py"


def load_example():
    return json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))


def lock(graph):
    graph["graph_snapshot_sha256"] = calculate_legal_version_graph_snapshot(graph)
    return graph


def finding_codes(graph):
    return {item["code"] for item in validate_legal_version_graph(graph)["findings"]}


class LegalVersionGraphTests(unittest.TestCase):
    def run_cli(self, payload):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "graph.json"
            if isinstance(payload, str):
                path.write_text(payload, encoding="utf-8")
            else:
                path.write_text(json.dumps(payload), encoding="utf-8")
            return subprocess.run(
                [sys.executable, str(SCRIPT), str(path)],
                cwd=SKILL_ROOT,
                capture_output=True,
                encoding="utf-8",
                check=False,
            )

    def test_published_example_passes_only_as_unverified_structure(self):
        report = validate_legal_version_graph(load_example())

        self.assertTrue(report["allowed"], report["findings"])
        self.assertEqual(
            report["allowed_scope"],
            "UNVERIFIED_LEGAL_VERSION_GRAPH_STRUCTURE_ONLY",
        )
        self.assertTrue(report["legal_review_required"])
        self.assertFalse(report["submission_ready"])
        self.assertIn("LEGAL_CURRENTNESS", report["validation_scope"]["not_verified"])

    def test_unknown_relationship_reference_is_blocked(self):
        graph = load_example()
        graph["relationships"][0]["to_version_id"] = "VERSION_UNKNOWN"
        lock(graph)

        self.assertIn("LEGAL_RELATIONSHIP_VERSION_UNKNOWN", finding_codes(graph))

    def test_self_relationship_is_blocked(self):
        graph = load_example()
        graph["relationships"][0]["to_version_id"] = "VERSION_2025"
        lock(graph)

        self.assertIn("LEGAL_RELATIONSHIP_SELF_REFERENCE", finding_codes(graph))

    def test_directed_cycle_is_blocked(self):
        graph = load_example()
        graph["relationships"].append(
            {
                "relationship_id": "REL_2024_CORRECTS_2025",
                "from_version_id": "VERSION_2024",
                "to_version_id": "VERSION_2025",
                "relationship_type": "CORRECTS",
                "basis_frozen_record_snapshot_sha256": "6" * 64,
                "text_diff_snapshot_sha256": "7" * 64,
                "status": "UNVERIFIED_RELATIONSHIP_CANDIDATE",
            }
        )
        lock(graph)

        self.assertIn("LEGAL_VERSION_GRAPH_CYCLE", finding_codes(graph))

    def test_duplicate_version_id_is_blocked(self):
        graph = load_example()
        duplicate = copy.deepcopy(graph["versions"][0])
        graph["versions"].append(duplicate)
        lock(graph)

        self.assertIn("LEGAL_VERSION_DUPLICATE_ID", finding_codes(graph))

    def test_duplicate_edge_is_blocked(self):
        graph = load_example()
        duplicate = copy.deepcopy(graph["relationships"][0])
        duplicate["relationship_id"] = "REL_DUPLICATE_EDGE"
        graph["relationships"].append(duplicate)
        lock(graph)

        self.assertIn("LEGAL_RELATIONSHIP_DUPLICATE_EDGE", finding_codes(graph))

    def test_inverted_effective_dates_are_blocked(self):
        graph = load_example()
        graph["versions"][0]["effective_to_candidate"] = "2023-12-31"
        lock(graph)

        self.assertIn("LEGAL_VERSION_DATE_INTERVAL_INVALID", finding_codes(graph))

    def test_off_allowlist_source_is_blocked(self):
        graph = load_example()
        graph["versions"][0]["source_url"] = "https://example.com/rule"
        lock(graph)

        self.assertIn("LEGAL_VERSION_SOURCE_NOT_ALLOWLISTED", finding_codes(graph))

    def test_mutation_without_new_snapshot_is_blocked(self):
        graph = load_example()
        graph["versions"][0]["content_sha256"] = "a" * 64

        self.assertIn("LEGAL_VERSION_GRAPH_SNAPSHOT_MISMATCH", finding_codes(graph))

    def test_cli_accepts_published_example(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(EXAMPLE_PATH)],
            cwd=SKILL_ROOT,
            capture_output=True,
            encoding="utf-8",
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(json.loads(result.stdout)["submission_ready"])

    def test_cli_rejects_duplicate_keys(self):
        result = self.run_cli('{"schema_version":"1.0","schema_version":"1.0"}')

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            json.loads(result.stdout)["error"]["code"],
            "LEGAL_GRAPH_INPUT_DUPLICATE_KEY",
        )

    def test_cli_rejects_non_standard_number_and_non_object(self):
        invalid_number = self.run_cli('{"value":NaN}')
        invalid_root = self.run_cli([])

        self.assertEqual(invalid_number.returncode, 1)
        self.assertEqual(
            json.loads(invalid_number.stdout)["error"]["code"],
            "LEGAL_GRAPH_INPUT_INVALID_CONSTANT",
        )
        self.assertEqual(invalid_root.returncode, 1)
        self.assertEqual(
            json.loads(invalid_root.stdout)["error"]["code"],
            "LEGAL_GRAPH_INPUT_ROOT_NOT_OBJECT",
        )


if __name__ == "__main__":
    unittest.main()
