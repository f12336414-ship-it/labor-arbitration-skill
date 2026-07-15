import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from copy import deepcopy


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIRECTORY = SKILL_ROOT / "scripts"
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from case_workspace import (  # noqa: E402
    CaseWorkspaceError,
    calculate_case_workspace_snapshot,
    create_case_workspace,
    validate_case_workspace,
)


def load_manifest_builder():
    path = SCRIPT_DIRECTORY / "build_intake_manifest.py"
    spec = importlib.util.spec_from_file_location("workspace_manifest_builder", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MANIFEST_BUILDER = load_manifest_builder()


def make_source(root):
    source = root / "source"
    source.mkdir()
    (source / "a.txt").write_text("same synthetic bytes", encoding="utf-8")
    (source / "b.txt").write_text("same synthetic bytes", encoding="utf-8")
    return source, MANIFEST_BUILDER.build_manifest(source)


def make_object_writable(path):
    if os.name == "nt":
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
    else:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


class CaseWorkspaceTests(unittest.TestCase):
    def test_create_deduplicates_and_replays_hashes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source, intake = make_source(root)
            workspace_root = root / "workspace"
            _path, workspace = create_case_workspace(
                source,
                intake,
                workspace_root,
                created_at="2026-07-15T05:00:00Z",
            )
            report = validate_case_workspace(workspace, workspace_root)

            self.assertTrue(report["allowed"], report["findings"])
            self.assertEqual(workspace["summary"]["file_count"], 2)
            self.assertEqual(workspace["summary"]["unique_object_count"], 1)
            self.assertFalse(report["submission_ready"])

    def test_creation_is_idempotent_for_same_intake(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source, intake = make_source(root)
            workspace_root = root / "workspace"
            first_path, first = create_case_workspace(
                source,
                intake,
                workspace_root,
                created_at="2026-07-15T05:00:00Z",
            )
            second_path, second = create_case_workspace(
                source,
                intake,
                workspace_root,
                created_at="2026-07-15T06:00:00Z",
            )

            self.assertEqual(first_path, second_path)
            self.assertEqual(first, second)

    def test_source_change_after_intake_is_refused(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source, intake = make_source(root)
            (source / "a.txt").write_text("changed synthetic bytes", encoding="utf-8")

            with self.assertRaises(CaseWorkspaceError) as context:
                create_case_workspace(source, intake, root / "workspace")

        self.assertIn(
            context.exception.code,
            {"CASE_WORKSPACE_SOURCE_CHANGED", "CASE_WORKSPACE_SOURCE_HASH_MISMATCH"},
        )

    def test_tampered_object_is_detected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source, intake = make_source(root)
            workspace_root = root / "workspace"
            _path, workspace = create_case_workspace(source, intake, workspace_root)
            object_path = workspace_root.joinpath(
                *Path(workspace["files"][0]["object_relative_path"]).parts
            )
            make_object_writable(object_path)
            object_path.write_bytes(b"tampered workspace")

            report = validate_case_workspace(workspace, workspace_root)

        codes = {item["code"] for item in report["findings"]}
        self.assertTrue(
            {
                "CASE_WORKSPACE_OBJECT_CHANGED_OR_SIZE_MISMATCH",
                "CASE_WORKSPACE_OBJECT_HASH_MISMATCH",
            }
            & codes
        )

    def test_workspace_id_and_raw_ids_cannot_be_rebound(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source, intake = make_source(root)
            workspace_root = root / "workspace"
            _path, workspace = create_case_workspace(source, intake, workspace_root)
            workspace["workspace_id"] = "WORKSPACE-AAAAAAAAAAAAAAAAAAAAAAAA"
            workspace["files"][0]["raw_id"] = "RAW-" + "a" * 64

            report = validate_case_workspace(workspace, workspace_root)

        codes = {item["code"] for item in report["findings"]}
        self.assertIn("CASE_WORKSPACE_ID_MISMATCH", codes)
        self.assertIn("CASE_WORKSPACE_RAW_ID_MISMATCH", codes)

    def test_unexpected_object_is_detected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source, intake = make_source(root)
            workspace_root = root / "workspace"
            _path, workspace = create_case_workspace(source, intake, workspace_root)
            used_prefixes = {
                item["content_sha256"][:2] for item in workspace["files"]
            }
            extra_prefix = next(
                f"{value:02x}" for value in range(256) if f"{value:02x}" not in used_prefixes
            )
            extra_dir = workspace_root / "objects" / extra_prefix
            extra_dir.mkdir()
            (extra_dir / ("f" * 64 + ".bin")).write_bytes(b"extra")

            report = validate_case_workspace(workspace, workspace_root)

        self.assertIn(
            "CASE_WORKSPACE_UNEXPECTED_OBJECT",
            {item["code"] for item in report["findings"]},
        )

    def test_migrated_workspace_validates_at_new_absolute_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source, intake = make_source(root)
            original = root / "workspace-original"
            _path, workspace = create_case_workspace(source, intake, original)
            migrated = root / "workspace-migrated"
            shutil.move(str(original), str(migrated))

            report = validate_case_workspace(workspace, migrated)

            self.assertTrue(report["allowed"], report["findings"])

    def test_recovery_can_rebuild_new_workspace_from_intake_and_sources(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source, intake = make_source(root)
            damaged = root / "workspace-damaged"
            _path, damaged_record = create_case_workspace(source, intake, damaged)
            damaged_object = damaged.joinpath(
                *Path(damaged_record["files"][0]["object_relative_path"]).parts
            )
            make_object_writable(damaged_object)
            damaged_object.write_bytes(b"damaged")
            restored = root / "workspace-restored"
            _path, restored_record = create_case_workspace(source, intake, restored)

            damaged_report = validate_case_workspace(damaged_record, damaged)
            restored_report = validate_case_workspace(restored_record, restored)

        self.assertFalse(damaged_report["allowed"])
        self.assertTrue(restored_report["allowed"], restored_report["findings"])
        self.assertEqual(
            damaged_record["source_intake_manifest_sha256"],
            restored_record["source_intake_manifest_sha256"],
        )

    def test_source_and_workspace_must_not_overlap(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source, intake = make_source(root)
            with self.assertRaises(CaseWorkspaceError) as context:
                create_case_workspace(source, intake, source / "workspace")

        self.assertEqual(context.exception.code, "CASE_WORKSPACE_PATH_OVERLAP")

    def test_invalid_intake_and_nonempty_workspace_are_refused(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source, intake = make_source(root)
            invalid = deepcopy(intake)
            invalid["manifest_payload_sha256"] = "0" * 64
            with self.assertRaises(CaseWorkspaceError) as captured:
                create_case_workspace(source, invalid, root / "invalid-workspace")
            self.assertEqual(
                captured.exception.code, "CASE_WORKSPACE_INTAKE_SNAPSHOT_MISMATCH"
            )

            workspace_root = root / "nonempty-workspace"
            workspace_root.mkdir()
            (workspace_root / "unrelated.txt").write_text("synthetic")
            with self.assertRaises(CaseWorkspaceError) as captured:
                create_case_workspace(source, intake, workspace_root)
            self.assertEqual(captured.exception.code, "CASE_WORKSPACE_NOT_EMPTY")

    def test_invalid_existing_manifest_and_creation_time_are_refused(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source, intake = make_source(root)
            workspace_root = root / "existing"
            workspace_root.mkdir()
            (workspace_root / "workspace.json").write_text("not-json")
            with self.assertRaises(CaseWorkspaceError) as captured:
                create_case_workspace(source, intake, workspace_root)
            self.assertEqual(captured.exception.code, "CASE_WORKSPACE_EXISTING_INVALID")

            with self.assertRaises(CaseWorkspaceError) as captured:
                create_case_workspace(
                    source, intake, root / "bad-time", created_at="not-a-time"
                )
            self.assertEqual(captured.exception.code, "CASE_WORKSPACE_TIME_INVALID")

    def test_conflicting_preexisting_object_is_refused(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source, intake = make_source(root)
            workspace_root = root / "workspace"
            digest = intake["files"][0]["sha256"]
            object_directory = workspace_root / "objects" / digest[:2]
            object_directory.mkdir(parents=True)
            source_payload = (source / "a.txt").read_bytes()
            (object_directory / f"{digest}.bin").write_bytes(b"x" * len(source_payload))

            with self.assertRaises(CaseWorkspaceError) as captured:
                create_case_workspace(source, intake, workspace_root)

        self.assertIn(
            captured.exception.code,
            {"CASE_WORKSPACE_OBJECT_CONFLICT"},
        )

    def test_manifest_policy_detects_identity_path_summary_and_snapshot_damage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source, intake = make_source(root)
            workspace_root = root / "workspace"
            _path, workspace = create_case_workspace(source, intake, workspace_root)
            identity_damage = deepcopy(workspace)
            identity_damage["files"][1]["raw_id"] = identity_damage["files"][0]["raw_id"]
            identity_damage["files"][1]["source_relative_path"] = identity_damage["files"][0][
                "source_relative_path"
            ]
            identity_report = validate_case_workspace(identity_damage, workspace_root)

            path_damage = deepcopy(workspace)
            path_damage["files"][0]["object_relative_path"] = (
                "objects/00/" + "0" * 64 + ".bin"
            )
            path_report = validate_case_workspace(path_damage, workspace_root)

            summary_damage = deepcopy(workspace)
            summary_damage["summary"]["logical_bytes"] = 0
            summary_report = validate_case_workspace(summary_damage, workspace_root)

        self.assertIn(
            "CASE_WORKSPACE_FILE_IDENTITY_DUPLICATE",
            {item["code"] for item in identity_report["findings"]},
        )
        self.assertIn(
            "CASE_WORKSPACE_OBJECT_PATH_MISMATCH",
            {item["code"] for item in path_report["findings"]},
        )
        summary_codes = {item["code"] for item in summary_report["findings"]}
        self.assertIn("CASE_WORKSPACE_SUMMARY_MISMATCH", summary_codes)
        self.assertIn("CASE_WORKSPACE_SNAPSHOT_MISMATCH", summary_codes)

    def test_missing_root_and_unsafe_object_tree_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source, intake = make_source(root)
            workspace_root = root / "workspace"
            _path, workspace = create_case_workspace(source, intake, workspace_root)

            missing_report = validate_case_workspace(workspace, root / "missing")
            unsafe_prefix = workspace_root / "objects" / "unsafe-prefix"
            unsafe_prefix.mkdir()
            unsafe_report = validate_case_workspace(workspace, workspace_root)

        self.assertIn(
            "CASE_WORKSPACE_PATH_UNSAFE",
            {item["code"] for item in missing_report["findings"]},
        )
        self.assertIn(
            "CASE_WORKSPACE_OBJECT_TREE_UNSAFE",
            {item["code"] for item in unsafe_report["findings"]},
        )

    def test_source_path_rebinding_is_detected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source, intake = make_source(root)
            workspace_root = root / "workspace"
            _path, workspace = create_case_workspace(source, intake, workspace_root)
            workspace["files"][0]["source_relative_path"] = "other.txt"
            workspace["workspace_snapshot_sha256"] = calculate_case_workspace_snapshot(
                workspace
            )
            report = validate_case_workspace(workspace, workspace_root)

        self.assertIn(
            "CASE_WORKSPACE_RAW_ID_MISMATCH",
            {item["code"] for item in report["findings"]},
        )

    def test_unsafe_source_path_and_invalid_schema_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source, intake = make_source(root)
            workspace_root = root / "workspace"
            _path, workspace = create_case_workspace(source, intake, workspace_root)

            unsafe = deepcopy(workspace)
            unsafe["files"][0]["source_relative_path"] = "../a.txt"
            unsafe["workspace_snapshot_sha256"] = calculate_case_workspace_snapshot(
                unsafe
            )
            unsafe_report = validate_case_workspace(unsafe, workspace_root)
            schema_report = validate_case_workspace({}, workspace_root)

        self.assertIn(
            "CASE_WORKSPACE_SOURCE_PATH_UNSAFE",
            {item["code"] for item in unsafe_report["findings"]},
        )
        self.assertFalse(schema_report["allowed"])

    def test_existing_workspace_cannot_be_rebound_to_new_intake(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source, intake = make_source(root)
            workspace_root = root / "workspace"
            create_case_workspace(source, intake, workspace_root)
            (source / "c.txt").write_text("new synthetic bytes", encoding="utf-8")
            new_intake = MANIFEST_BUILDER.build_manifest(source)

            with self.assertRaises(CaseWorkspaceError) as captured:
                create_case_workspace(source, new_intake, workspace_root)

        self.assertEqual(captured.exception.code, "CASE_WORKSPACE_EXISTING_INVALID")

    def test_create_and_validate_clis(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source, intake = make_source(root)
            intake_path = root / "intake.json"
            intake_path.write_text(json.dumps(intake), encoding="utf-8")
            workspace_root = root / "workspace"
            created = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_DIRECTORY / "create_case_workspace.py"),
                    str(source),
                    str(intake_path),
                    str(workspace_root),
                ],
                cwd=SKILL_ROOT,
                capture_output=True,
                encoding="utf-8",
                check=False,
            )
            validated = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_DIRECTORY / "validate_case_workspace.py"),
                    str(workspace_root),
                ],
                cwd=SKILL_ROOT,
                capture_output=True,
                encoding="utf-8",
                check=False,
            )

        self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
        self.assertEqual(validated.returncode, 0, validated.stdout + validated.stderr)
        self.assertEqual(
            json.loads(validated.stdout)["allowed_scope"],
            "LOCAL_CASE_WORKSPACE_BYTE_INTEGRITY_ONLY",
        )


if __name__ == "__main__":
    unittest.main()
