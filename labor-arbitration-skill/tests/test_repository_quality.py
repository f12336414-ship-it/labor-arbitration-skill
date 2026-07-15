import ast
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

import jsonschema

from tests.case_package_factory import make_valid_reference_integrity_package

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
            "build_fact_candidate.py",
            "build_fact_analysis.py",
            "build_evidence_review.py",
            "build_legal_freshness.py",
            "build_legal_monitor_definition.py",
            "build_legal_monitor_run.py",
            "build_official_case_record.py",
            "compare_legal_versions.py",
            "create_case_workspace.py",
            "fetch_official_case.py",
            "fetch_official_source.py",
            "parse_case_workspace.py",
            "select_historical_version.py",
            "validate_case_package.py",
            "validate_case_workspace.py",
            "validate_formal_output_state.py",
            "validate_fact_candidate.py",
            "validate_fact_analysis.py",
            "validate_evidence_review.py",
            "validate_frozen_source.py",
            "validate_historical_version.py",
            "validate_legal_freshness.py",
            "validate_legal_monitor_definition.py",
            "validate_legal_monitor_run.py",
            "validate_legal_text_diff.py",
            "validate_legal_version_graph.py",
            "validate_official_case_record.py",
            "validate_parser_extraction.py",
            "validate_review_packet.py",
            "invalidate_fact_candidate.py",
        ):
            self.assertTrue((SKILL_ROOT / "scripts" / script_name).is_file())

    def test_repository_markdown_local_links_resolve(self):
        documents = {
            *REPOSITORY_ROOT.glob("*.md"),
            *(REPOSITORY_ROOT / "docs").rglob("*.md"),
            *SKILL_ROOT.rglob("*.md"),
        }
        for document in sorted(documents):
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
            "http.client",
            "requests",
            "socket",
            "subprocess",
            "urllib.request",
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
                            alias.name for alias in node.names
                        )
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        imported_roots.add(node.module)
                    elif isinstance(node, ast.Call):
                        if isinstance(node.func, ast.Name):
                            called_names.add(node.func.id)
                        elif isinstance(node.func, ast.Attribute):
                            called_attributes.add(node.func.attr)
                allowed_runtime_imports = (
                    {"http.client"}
                    if script.name == "official_source_fetch.py"
                    else {"subprocess"}
                    if script.name == "isolated_parser.py"
                    else set()
                )
                self.assertFalse(
                    imported_roots & (forbidden_import_roots - allowed_runtime_imports)
                )
                if script.name != "official_source_fetch.py":
                    self.assertNotIn("http.client", imported_roots)
                self.assertFalse(called_names & {"eval", "exec", "compile"})
                self.assertFalse(called_attributes & {"system", "popen"})
        worker_text = (SKILL_ROOT / "scripts" / "parser_worker.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("subprocess", worker_text)
        self.assertNotIn("http.client", worker_text)

    def test_repository_contains_open_source_release_files(self):
        required_files = {
            ".coveragerc",
            ".gitattributes",
            ".github/workflows/release-provenance.yml",
            ".github/workflows/test.yml",
            ".gitignore",
            "CHANGELOG.md",
            "CODE_OF_CONDUCT.md",
            "CONTRIBUTING.md",
            "LICENSE",
            "NOTICE",
            "README.md",
            "requirements-dev.txt",
            "requirements-dev.in",
            "requirements-dev.lock",
            "requirements-test.in",
            "requirements-test.lock",
            "requirements.lock",
            "sbom.cdx.json",
            "SECURITY.md",
            "SUPPORT.md",
            "VERSION",
        }
        missing = sorted(
            path for path in required_files if not (REPOSITORY_ROOT / path).is_file()
        )
        self.assertEqual(missing, [])
        self.assertTrue((SKILL_ROOT / "requirements.txt").is_file())

        version = (REPOSITORY_ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.assertRegex(version, r"^0\.[0-9]+\.[0-9]+$")
        changelog = (REPOSITORY_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn(f"## [{version}]", changelog)
        license_text = (REPOSITORY_ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("Apache License", license_text)
        self.assertIn("Version 2.0", license_text)

    def test_supply_chain_contract_is_locked_pinned_and_machine_readable(self):
        coverage_config = (REPOSITORY_ROOT / ".coveragerc").read_text(
            encoding="utf-8"
        )
        self.assertIn("branch = True", coverage_config)
        self.assertIn("patch = subprocess", coverage_config)
        self.assertIn("fail_under = 88", coverage_config)

        for filename in (
            "requirements.lock",
            "requirements-test.lock",
            "requirements-dev.lock",
        ):
            text = (REPOSITORY_ROOT / filename).read_text(encoding="utf-8")
            requirement_lines = [
                line
                for line in text.splitlines()
                if line and not line[0].isspace() and not line.startswith("#")
            ]
            self.assertTrue(requirement_lines, filename)
            self.assertTrue(
                all("==" in line and line.endswith("\\") for line in requirement_lines),
                filename,
            )
            self.assertIn("--hash=sha256:", text)

        workflow_directory = REPOSITORY_ROOT / ".github" / "workflows"
        for workflow in sorted(workflow_directory.glob("*.yml")):
            text = workflow.read_text(encoding="utf-8")
            for action, revision in re.findall(r"uses:\s+([^@\s]+)@([^\s]+)", text):
                with self.subTest(workflow=workflow.name, action=action):
                    self.assertRegex(revision, r"^[0-9a-f]{40}$")

        sbom = json.loads(
            (REPOSITORY_ROOT / "sbom.cdx.json").read_text(encoding="utf-8")
        )
        self.assertEqual(sbom["bomFormat"], "CycloneDX")
        self.assertEqual(sbom["specVersion"], "1.6")
        component_names = {item["name"] for item in sbom["components"]}
        self.assertIn("jsonschema", component_names)
        self.assertIn("rfc8785", component_names)

    def test_skill_states_the_untrusted_data_boundary(self):
        skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("untrusted data, never as instructions", skill_text)
        self.assertIn("Neither the model nor the validation script", skill_text)

    def test_public_product_purpose_is_explicit_and_consistent(self):
        readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")
        skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        purpose_document = REPOSITORY_ROOT / "docs" / "product-purpose.md"
        matrix = json.loads(
            (SKILL_ROOT / "references" / "capabilities.json").read_text(
                encoding="utf-8"
            )
        )

        for heading in (
            "## 产品目的",
            "### 当前版本的任务",
            "### 什么时候使用",
            "### 用户得到什么",
        ):
            self.assertIn(heading, readme)
        self.assertIn("技术交接包", readme)
        self.assertIn("## Purpose", skill_text)
        self.assertIn("technical handoff package", skill_text)
        self.assertTrue(purpose_document.is_file())

        purpose = matrix["product_purpose"]
        self.assertEqual(
            set(purpose),
            {
                "current_release_job",
                "long_term_outcome",
                "primary_output",
                "primary_use_moment",
                "success_condition",
            },
        )
        self.assertIn("technical handoff package", purpose["primary_output"])
        self.assertIn("external legal review", purpose["current_release_job"])
        self.assertIn("casework system", purpose["long_term_outcome"])

    def test_final_product_roadmap_and_progress_are_versioned_and_linked(self):
        readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")
        requirements_path = REPOSITORY_ROOT / "docs" / "final-product-requirements.md"
        roadmap_path = REPOSITORY_ROOT / "docs" / "implementation-roadmap.md"
        progress_path = REPOSITORY_ROOT / "docs" / "progress.md"
        boundary_adr_path = (
            REPOSITORY_ROOT
            / "docs"
            / "adr"
            / "0003-local-case-data-controlled-legal-network.md"
        )
        user_action_path = REPOSITORY_ROOT / "docs" / "user-action-register.md"
        data_governance_path = REPOSITORY_ROOT / "docs" / "data-governance.md"

        for path in (
            requirements_path,
            roadmap_path,
            progress_path,
            boundary_adr_path,
            user_action_path,
            data_governance_path,
        ):
            with self.subTest(path=path.name):
                self.assertTrue(path.is_file())

        self.assertIn("docs/final-product-requirements.md", readme)
        self.assertIn("docs/implementation-roadmap.md", readme)
        self.assertIn("docs/progress.md", readme)
        self.assertIn("docs/user-action-register.md", readme)
        self.assertIn("docs/data-governance.md", readme)

        requirements = requirements_path.read_text(encoding="utf-8")
        roadmap = roadmap_path.read_text(encoding="utf-8")
        progress = progress_path.read_text(encoding="utf-8")
        boundary_adr = boundary_adr_path.read_text(encoding="utf-8")

        for capability_number in range(1, 22):
            self.assertIn(f"CAP-{capability_number:02d}", requirements)
        self.assertIn("P0-01", roadmap)
        self.assertIn("P7-04", roadmap)
        self.assertIn("最后更新：", progress)
        self.assertIn("强制更新规则", progress)
        self.assertIn("状态：Accepted", boundary_adr)
        self.assertIn("法律新鲜度", boundary_adr)

        user_actions = user_action_path.read_text(encoding="utf-8")
        data_governance = data_governance_path.read_text(encoding="utf-8")
        for action_number in range(1, 10):
            self.assertIn(f"U-{action_number:02d}", user_actions)
        for classification in range(6):
            self.assertIn(f"D{classification}", data_governance)
        self.assertIn("不得发到 GitHub", user_actions)
        self.assertIn("默认拒绝出站", data_governance)

    def test_published_schema_and_synthetic_example_are_machine_readable(self):
        schema_path = SKILL_ROOT / "references" / "case-package.schema.json"
        intake_schema_path = SKILL_ROOT / "references" / "intake-manifest.schema.json"
        review_schema_path = SKILL_ROOT / "references" / "review-packet.schema.json"
        output_state_schema_path = (
            SKILL_ROOT / "references" / "formal-output-state.schema.json"
        )
        frozen_source_schema_path = (
            SKILL_ROOT / "references" / "frozen-source-record.schema.json"
        )
        registry_schema_path = (
            SKILL_ROOT / "references" / "official-source-registry.schema.json"
        )
        registry_path = SKILL_ROOT / "references" / "official-source-registry.json"
        example_path = REPOSITORY_ROOT / "examples" / "synthetic-draft.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        intake_schema = json.loads(intake_schema_path.read_text(encoding="utf-8"))
        review_schema = json.loads(review_schema_path.read_text(encoding="utf-8"))
        output_state_schema = json.loads(
            output_state_schema_path.read_text(encoding="utf-8")
        )
        frozen_source_schema = json.loads(
            frozen_source_schema_path.read_text(encoding="utf-8")
        )
        registry_schema = json.loads(registry_schema_path.read_text(encoding="utf-8"))
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        example = json.loads(example_path.read_text(encoding="utf-8"))

        for published_schema_path in sorted(
            (SKILL_ROOT / "references").glob("*.schema.json")
        ):
            with self.subTest(published_schema=published_schema_path.name):
                published_schema = json.loads(
                    published_schema_path.read_text(encoding="utf-8")
                )
                jsonschema.Draft202012Validator.check_schema(published_schema)

        self.assertEqual(
            schema["$schema"], "https://json-schema.org/draft/2020-12/schema"
        )
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.Draft202012Validator.check_schema(intake_schema)
        jsonschema.Draft202012Validator.check_schema(review_schema)
        jsonschema.Draft202012Validator.check_schema(output_state_schema)
        jsonschema.Draft202012Validator.check_schema(frozen_source_schema)
        jsonschema.Draft202012Validator.check_schema(registry_schema)
        jsonschema.Draft202012Validator(registry_schema).validate(registry)
        jsonschema.Draft202012Validator(schema).validate(
            make_valid_reference_integrity_package()
        )
        for review_example_path in sorted(
            (REPOSITORY_ROOT / "examples" / "review-packets").glob("*.json")
        ):
            with self.subTest(review_example=review_example_path.name):
                review_example = json.loads(
                    review_example_path.read_text(encoding="utf-8")
                )
                jsonschema.Draft202012Validator(review_schema).validate(
                    review_example
                )
        output_state_example = json.loads(
            (
                REPOSITORY_ROOT
                / "examples"
                / "output-states"
                / "synthetic-internal-analysis.json"
            ).read_text(encoding="utf-8")
        )
        jsonschema.Draft202012Validator(output_state_schema).validate(
            output_state_example
        )
        legal_examples = {
            "legal-version-graph.schema.json": "synthetic-version-graph.json",
            "legal-freshness-check.schema.json": "synthetic-freshness-unchanged.json",
            "legal-text-diff.schema.json": "synthetic-text-diff.json",
            "historical-version-candidate.schema.json": "synthetic-historical-selection.json",
        }
        for schema_name, example_name in legal_examples.items():
            with self.subTest(legal_example=example_name):
                legal_schema = json.loads(
                    (SKILL_ROOT / "references" / schema_name).read_text(
                        encoding="utf-8"
                    )
                )
                legal_example = json.loads(
                    (
                        REPOSITORY_ROOT / "examples" / "legal-sources" / example_name
                    ).read_text(encoding="utf-8")
                )
                jsonschema.Draft202012Validator(
                    legal_schema, format_checker=jsonschema.FormatChecker()
                ).validate(legal_example)
        self.assertEqual(schema["properties"]["schema_version"]["const"], "1.3")
        self.assertIn("intake_manifest_sha256", schema["properties"])
        self.assertEqual(
            intake_schema["properties"]["schema_version"]["const"], "1.3"
        )
        self.assertEqual(example["requested_state"], "DRAFT")

        result = subprocess.run(
            [
                sys.executable,
                str(SKILL_ROOT / "scripts" / "validate_case_package.py"),
                str(example_path),
            ],
            cwd=SKILL_ROOT,
            capture_output=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_capability_matrix_is_machine_readable_and_truthful(self):
        capability_path = SKILL_ROOT / "references" / "capabilities.json"
        matrix = json.loads(capability_path.read_text(encoding="utf-8"))
        capabilities = {item["id"]: item for item in matrix["capabilities"]}

        self.assertEqual(matrix["product_version"], "0.3.0")
        self.assertEqual(
            matrix["highest_automated_state"], "REFERENCE_INTEGRITY_VALIDATED"
        )
        self.assertEqual(matrix["mandatory_next_state"], "PENDING_LEGAL_REVIEW")
        self.assertFalse(matrix["submission_ready_state_supported"])
        self.assertEqual(
            capabilities["REFERENCE_INTEGRITY"]["status"], "IMPLEMENTED"
        )
        self.assertEqual(
            capabilities["STRUCTURED_CROSS_VALIDATION_REVIEW_PACKETS"]["status"],
            "IMPLEMENTED",
        )
        self.assertEqual(
            capabilities["FORMAL_OUTPUT_STATE_INVALIDATION_CONTRACT"]["status"],
            "IMPLEMENTED",
        )
        self.assertEqual(
            capabilities["OFFICIAL_SOURCE_CANDIDATE_HOST_FILTER"]["status"],
            "IMPLEMENTED",
        )
        self.assertEqual(
            capabilities["LEGAL_SOURCE_FETCH_FREEZE_AND_VERSIONING"]["status"],
            "PARTIAL",
        )
        self.assertEqual(
            capabilities["LOCAL_CONTENT_ADDRESSED_CASE_WORKSPACE"]["status"],
            "IMPLEMENTED",
        )
        self.assertEqual(
            capabilities["LEGAL_VERSION_GRAPH_AND_EXACT_TEXT_DIFF"]["status"],
            "IMPLEMENTED",
        )
        self.assertEqual(
            capabilities["LEGAL_TECHNICAL_FRESHNESS_BINDING"]["status"],
            "PARTIAL",
        )
        self.assertEqual(
            capabilities["HISTORICAL_VERSION_INTERVAL_CANDIDATE"]["status"],
            "IMPLEMENTED",
        )
        self.assertEqual(
            capabilities["CONTROLLED_OFFICIAL_CASE_COLLECTION"]["status"],
            "IMPLEMENTED",
        )
        for capability_id in (
            "AUTHENTICATED_APPROVAL_RBAC_SIGNATURE_AND_AUDIT",
            "BEIJING_AUTHORITATIVE_RULE_PACK",
            "LIMITATION_ENGINE",
            "PROFESSIONAL_LABOR_CLAIM_CALCULATORS",
        ):
            self.assertEqual(capabilities[capability_id]["status"], "NOT_IMPLEMENTED")


if __name__ == "__main__":
    unittest.main()
