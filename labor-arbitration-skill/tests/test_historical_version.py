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

from historical_version_policy import (  # noqa: E402
    HistoricalVersionError,
    calculate_historical_selection_snapshot,
    select_historical_version_candidate,
    validate_historical_version_candidate,
)
from legal_version_graph_policy import calculate_legal_version_graph_snapshot  # noqa: E402


EXAMPLE_DIRECTORY = REPOSITORY_ROOT / "examples" / "legal-sources"
GRAPH_PATH = EXAMPLE_DIRECTORY / "synthetic-version-graph.json"
SELECTION_PATH = EXAMPLE_DIRECTORY / "synthetic-historical-selection.json"
SELECT_SCRIPT = SCRIPT_DIRECTORY / "select_historical_version.py"
VALIDATE_SCRIPT = SCRIPT_DIRECTORY / "validate_historical_version.py"


def load_graph():
    return json.loads(GRAPH_PATH.read_text(encoding="utf-8"))


def load_selection():
    return json.loads(SELECTION_PATH.read_text(encoding="utf-8"))


class HistoricalVersionTests(unittest.TestCase):
    def test_published_selection_is_unique_but_never_legally_applicable(self):
        selection = load_selection()
        report = validate_historical_version_candidate(selection)

        self.assertTrue(report["allowed"], report["findings"])
        self.assertEqual(report["selection_status"], "UNIQUE_CANDIDATE")
        self.assertIn("LEGAL_APPLICABILITY", report["validation_scope"]["not_verified"])
        self.assertFalse(report["submission_ready"])

    def test_generator_matches_published_selection(self):
        selection = select_historical_version_candidate(load_graph(), "2024-06-15")

        self.assertEqual(selection, load_selection())

    def test_effective_interval_boundaries_are_inclusive(self):
        start = select_historical_version_candidate(load_graph(), "2024-02-01")
        end = select_historical_version_candidate(load_graph(), "2024-12-31")
        before = select_historical_version_candidate(load_graph(), "2024-01-31")

        self.assertEqual(start["selection_status"], "UNIQUE_CANDIDATE")
        self.assertEqual(end["selection_status"], "UNIQUE_CANDIDATE")
        self.assertEqual(before["selection_status"], "NO_CANDIDATE")

    def test_overlapping_intervals_return_multiple_candidates(self):
        graph = load_graph()
        graph["versions"][1]["effective_from_candidate"] = "2024-06-01"
        graph["graph_snapshot_sha256"] = calculate_legal_version_graph_snapshot(graph)

        selection = select_historical_version_candidate(graph, "2024-06-15")

        self.assertEqual(selection["selection_status"], "MULTIPLE_CANDIDATES")
        self.assertEqual(len(selection["candidates"]), 2)

    def test_invalid_date_and_jurisdiction_fail_closed(self):
        with self.assertRaises(HistoricalVersionError) as invalid_date:
            select_historical_version_candidate(load_graph(), "2024-02-30")
        with self.assertRaises(HistoricalVersionError) as wrong_region:
            select_historical_version_candidate(
                load_graph(), "2024-06-15", province="Shanghai"
            )

        self.assertEqual(
            invalid_date.exception.code, "HISTORICAL_VERSION_EVENT_DATE_INVALID"
        )
        self.assertEqual(
            wrong_region.exception.code,
            "HISTORICAL_VERSION_JURISDICTION_MISMATCH",
        )

    def test_invalid_graph_fails_closed(self):
        graph = load_graph()
        graph["document_id"] = "MUTATED_DOCUMENT"

        with self.assertRaises(HistoricalVersionError) as context:
            select_historical_version_candidate(graph, "2024-06-15")

        self.assertEqual(context.exception.code, "HISTORICAL_VERSION_GRAPH_INVALID")

    def test_status_must_match_candidate_count(self):
        selection = load_selection()
        selection["selection_status"] = "NO_CANDIDATE"
        selection["selection_snapshot_sha256"] = (
            calculate_historical_selection_snapshot(selection)
        )

        codes = {
            item["code"]
            for item in validate_historical_version_candidate(selection)["findings"]
        }
        self.assertIn("HISTORICAL_VERSION_STATUS_MISMATCH", codes)

    def test_candidate_interval_must_contain_event_date(self):
        selection = load_selection()
        selection["candidates"][0]["effective_from_candidate"] = "2025-01-01"
        selection["selection_snapshot_sha256"] = (
            calculate_historical_selection_snapshot(selection)
        )

        codes = {
            item["code"]
            for item in validate_historical_version_candidate(selection)["findings"]
        }
        self.assertIn("HISTORICAL_VERSION_INTERVAL_MISMATCH", codes)

    def test_mutation_without_new_snapshot_is_blocked(self):
        selection = load_selection()
        selection["document_id"] = "MUTATED_DOCUMENT"

        codes = {
            item["code"]
            for item in validate_historical_version_candidate(selection)["findings"]
        }
        self.assertIn("HISTORICAL_VERSION_SNAPSHOT_MISMATCH", codes)

    def test_select_and_validate_clis_accept_examples(self):
        selected = subprocess.run(
            [
                sys.executable,
                str(SELECT_SCRIPT),
                str(GRAPH_PATH),
                "--event-date",
                "2024-06-15",
            ],
            cwd=SKILL_ROOT,
            capture_output=True,
            encoding="utf-8",
            check=False,
        )
        validated = subprocess.run(
            [sys.executable, str(VALIDATE_SCRIPT), str(SELECTION_PATH)],
            cwd=SKILL_ROOT,
            capture_output=True,
            encoding="utf-8",
            check=False,
        )

        self.assertEqual(selected.returncode, 0, selected.stdout + selected.stderr)
        self.assertEqual(json.loads(selected.stdout), load_selection())
        self.assertEqual(validated.returncode, 0, validated.stdout + validated.stderr)

    def test_validate_cli_rejects_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "selection.json"
            path.write_text('{"schema_version":"1.0","schema_version":"1.0"}')
            result = subprocess.run(
                [sys.executable, str(VALIDATE_SCRIPT), str(path)],
                cwd=SKILL_ROOT,
                capture_output=True,
                encoding="utf-8",
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            json.loads(result.stdout)["error"]["code"],
            "HISTORICAL_VERSION_INPUT_DUPLICATE_KEY",
        )


if __name__ == "__main__":
    unittest.main()
