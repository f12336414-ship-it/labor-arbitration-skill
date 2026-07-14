import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SKILL_ROOT = Path(__file__).resolve().parents[1]


def load_script(module_name, filename):
    spec = importlib.util.spec_from_file_location(
        module_name, SKILL_ROOT / "scripts" / filename
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MANIFEST_BUILDER = load_script(
    "manifest_builder_for_metadata_tests", "build_intake_manifest.py"
)
PACKAGE_VALIDATOR = load_script(
    "package_validator_for_metadata_tests", "validate_case_package.py"
)


def metadata(base, *, mtime_ns=None, ctime_ns=None):
    return SimpleNamespace(
        st_dev=base.st_dev,
        st_ino=base.st_ino,
        st_mode=base.st_mode,
        st_size=base.st_size,
        st_mtime_ns=base.st_mtime_ns if mtime_ns is None else mtime_ns,
        st_ctime_ns=base.st_ctime_ns if ctime_ns is None else ctime_ns,
    )


class FileMetadataCompatibilityTests(unittest.TestCase):
    def test_validator_tolerates_ctime_change_when_content_metadata_is_stable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "input.json"
            path.write_text("{}", encoding="utf-8")
            base = os.stat(path)
            before = metadata(base, ctime_ns=base.st_ctime_ns)
            after = metadata(base, ctime_ns=base.st_ctime_ns + 1)

            with patch.object(
                PACKAGE_VALIDATOR.os, "fstat", side_effect=[before, after]
            ), patch.object(PACKAGE_VALIDATOR.os, "stat", return_value=after):
                payload = PACKAGE_VALIDATOR.read_stable_utf8(path, 1024)

            self.assertEqual(payload, "{}")

    def test_validator_rejects_mtime_change_during_read(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "input.json"
            path.write_text("{}", encoding="utf-8")
            base = os.stat(path)
            before = metadata(base, mtime_ns=base.st_mtime_ns)
            after = metadata(base, mtime_ns=base.st_mtime_ns + 1)

            with patch.object(
                PACKAGE_VALIDATOR.os, "fstat", side_effect=[before, after]
            ):
                with self.assertRaises(PACKAGE_VALIDATOR.InputChangedError):
                    PACKAGE_VALIDATOR.read_stable_utf8(path, 1024)

    def test_scanner_signatures_ignore_ctime_but_retain_mtime(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "input.txt"
            path.write_text("stable", encoding="utf-8")
            base = os.stat(path)
            ctime_changed = metadata(base, ctime_ns=base.st_ctime_ns + 1)
            mtime_changed = metadata(base, mtime_ns=base.st_mtime_ns + 1)

            self.assertEqual(
                MANIFEST_BUILDER.metadata_signature(base),
                MANIFEST_BUILDER.metadata_signature(ctime_changed),
            )
            self.assertEqual(
                MANIFEST_BUILDER.entry_observation_signature(base),
                MANIFEST_BUILDER.entry_observation_signature(ctime_changed),
            )
            self.assertNotEqual(
                MANIFEST_BUILDER.metadata_signature(base),
                MANIFEST_BUILDER.metadata_signature(mtime_changed),
            )
            self.assertNotEqual(
                MANIFEST_BUILDER.entry_observation_signature(base),
                MANIFEST_BUILDER.entry_observation_signature(mtime_changed),
            )
