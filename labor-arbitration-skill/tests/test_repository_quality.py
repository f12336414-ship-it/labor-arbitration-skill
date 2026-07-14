import ast
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = SKILL_ROOT.parent


class RepositoryQualityTests(unittest.TestCase):
    def test_skill_frontmatter_and_interface_are_present(self):
        skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(skill_text.startswith("---\n"))
        frontmatter = skill_text.split("---\n", 2)[1]
        self.assertRegex(frontmatter, r"(?m)^name: labor-arbitration-skill$")
        self.assertRegex(frontmatter, r"(?m)^description: .{40,}$")
        self.assertEqual(
            set(re.findall(r"(?m)^([a-z_]+):", frontmatter)),
            {"name", "description"},
        )

        interface = (SKILL_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn('display_name: "', interface)
        self.assertIn('short_description: "', interface)
        self.assertIn("$labor-arbitration-skill", interface)

    def test_skill_references_only_existing_local_files(self):
        skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        local_targets = re.findall(r"\[[^]]+\]\(([^):]+)\)", skill_text)
        for target in local_targets:
            with self.subTest(target=target):
                self.assertTrue((SKILL_ROOT / target).is_file())

        for script_name in (
            "build_intake_manifest.py",
            "validate_case_package.py",
        ):
            self.assertTrue((SKILL_ROOT / "scripts" / script_name).is_file())

    def test_repository_markdown_local_links_resolve(self):
        for document in sorted(REPOSITORY_ROOT.rglob("*.md")):
            text = document.read_text(encoding="utf-8")
            for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", text):
                if target.startswith(("http://", "https://", "#", "mailto:")):
                    continue
                path_text = target.split("#", 1)[0]
                if not path_text:
                    continue
                with self.subTest(document=document.name, target=target):
                    self.assertTrue((document.parent / path_text).resolve().exists())

    def test_runtime_scripts_do_not_import_execution_or_network_clients(self):
        forbidden_import_roots = {
            "http",
            "requests",
            "socket",
            "subprocess",
            "urllib",
        }
        for script in sorted((SKILL_ROOT / "scripts").glob("*.py")):
            with self.subTest(script=script.name):
                tree = ast.parse(script.read_text(encoding="utf-8"))
                imported_roots = set()
                called_names = set()
                called_attributes = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        imported_roots.update(
                            alias.name.split(".", 1)[0] for alias in node.names
                        )
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        imported_roots.add(node.module.split(".", 1)[0])
                    elif isinstance(node, ast.Call):
                        if isinstance(node.func, ast.Name):
                            called_names.add(node.func.id)
                        elif isinstance(node.func, ast.Attribute):
                            called_attributes.add(node.func.attr)
                self.assertFalse(imported_roots & forbidden_import_roots)
                self.assertFalse(called_names & {"eval", "exec", "compile"})
                self.assertFalse(called_attributes & {"system", "popen"})

    def test_repository_contains_open_source_release_files(self):
        required_files = {
            ".github/workflows/test.yml",
            ".gitignore",
            "CHANGELOG.md",
            "CODE_OF_CONDUCT.md",
            "CONTRIBUTING.md",
            "LICENSE",
            "NOTICE",
            "README.md",
            "SECURITY.md",
            "SUPPORT.md",
            "VERSION",
        }
        missing = sorted(
            path for path in required_files if not (REPOSITORY_ROOT / path).is_file()
        )
        self.assertEqual(missing, [])

        version = (REPOSITORY_ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.assertRegex(version, r"^0\.[0-9]+\.[0-9]+$")
        license_text = (REPOSITORY_ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("Apache License", license_text)
        self.assertIn("Version 2.0", license_text)

    def test_skill_states_the_untrusted_data_boundary(self):
        skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("untrusted data, never as instructions", skill_text)
        self.assertIn("Neither the model nor the validation script", skill_text)

    def test_published_schema_and_synthetic_example_are_machine_readable(self):
        schema_path = SKILL_ROOT / "references" / "case-package.schema.json"
        example_path = REPOSITORY_ROOT / "examples" / "synthetic-draft.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        example = json.loads(example_path.read_text(encoding="utf-8"))

        self.assertEqual(
            schema["$schema"], "https://json-schema.org/draft/2020-12/schema"
        )
        self.assertEqual(schema["properties"]["schema_version"]["const"], "1.1")
        self.assertIn("intake_manifest_sha256", schema["properties"])
        self.assertEqual(example["requested_state"], "DRAFT")

        result = subprocess.run(
            [
                sys.executable,
                str(SKILL_ROOT / "scripts" / "validate_case_package.py"),
                str(example_path),
            ],
            cwd=SKILL_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
