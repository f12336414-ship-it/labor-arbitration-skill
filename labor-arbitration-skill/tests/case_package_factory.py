import copy
import hashlib

import rfc8785


INTEGRITY_SEMANTICS = (
    "Hashes and sizes describe bytes read from stable opened file descriptors during "
    "ingestion; they do not prove authenticity, semantic meaning, or later immutability."
)


def calculate_snapshot(package):
    snapshot_content = copy.deepcopy(package)
    snapshot_content.pop("package_snapshot_sha256", None)
    snapshot_content.pop("state_request_sha256", None)
    snapshot_content.pop("approvals", None)
    return hashlib.sha256(rfc8785.dumps(snapshot_content)).hexdigest()


def calculate_json_snapshot(value):
    return hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def calculate_raw_id(relative_path, content_sha256):
    digest = hashlib.sha256()
    digest.update(relative_path.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(bytes.fromhex(content_sha256))
    return "RAW-" + digest.hexdigest()


def make_intake_manifest(package):
    total_bytes = sum(item["size_bytes"] for item in package["raw_files"])
    manifest = {
        "schema_version": "1.3",
        "integrity_semantics": INTEGRITY_SEMANTICS,
        "canonicalization": "RFC8785",
        "generator": {
            "name": "labor-arbitration-skill/intake-manifest-builder",
            "version": "0.3.0",
            "build_identity_status": "UNATTESTED",
            "runtime_source_sha256": "a" * 64,
            "dependency_contract_sha256": "b" * 64,
            "dependency_contract_kind": "HASH_LOCK",
            "python_version": "3.10.0",
            "platform": "Synthetic",
        },
        "provenance_boundary": {
            "system_observations": "SYSTEM_OBSERVED_UNATTESTED",
            "user_declarations": "NOT_PROVIDED",
            "generator_authenticity": "NOT_VERIFIED",
        },
        "scan_observation": {
            "started_at": "2026-07-14T00:00:00Z",
            "completed_at": "2026-07-14T00:00:01Z",
            "clock_status": "SYSTEM_CLOCK_UNATTESTED",
            "tree_walks_completed": 2,
        },
        "output_security": {
            "permissions_enforcement": "WINDOWS_DIRECTORY_ACL_INHERITED_NOT_VERIFIED",
            "absolute_paths_emitted": False,
            "relative_paths_may_contain_sensitive_data": True,
        },
        "scan_policy": {
            "max_depth": 20,
            "max_file_bytes": 100 * 1024 * 1024,
            "max_files": 10_000,
            "max_total_bytes": 1024 * 1024 * 1024,
            "timeout_seconds": 60.0,
        },
        "summary": {
            "file_count": len(package["raw_files"]),
            "total_bytes": total_bytes,
        },
        "relationships": [],
        "files": copy.deepcopy(package["raw_files"]),
    }
    manifest["manifest_payload_sha256"] = calculate_json_snapshot(manifest)
    return manifest


def calculate_dependency_snapshot(package):
    return calculate_json_snapshot(
        {
            "source_artifacts": package.get("source_artifacts", []),
            "legal_rules": package.get("legal_rules", []),
            "calculators": [
                {
                    "calculator_version": calculation.get("calculator_version"),
                    "formula_id": calculation.get("formula_id"),
                    "rounding_policy": calculation.get("rounding_policy"),
                }
                for calculation in package.get("calculations", [])
            ],
        }
    )


def calculate_statement_snapshot(package):
    return calculate_json_snapshot({"statements": package.get("statements", [])})


def calculate_state_request(package):
    return calculate_json_snapshot(
        {
            "requested_state": package.get("requested_state"),
            "package_snapshot_sha256": package.get("package_snapshot_sha256"),
            "dependency_snapshot_sha256": package.get("dependency_snapshot_sha256"),
            "statement_snapshot_sha256": package.get("statement_snapshot_sha256"),
            "intake_manifest_sha256": package.get("intake_manifest_sha256"),
        }
    )


def make_valid_reference_integrity_package():
    package = {
        "schema_version": "1.3",
        "requested_state": "REFERENCE_INTEGRITY_VALIDATED",
        "snapshot_canonicalization": "RFC8785",
        "jurisdiction": {"country": "CN", "province": "Beijing"},
        "dependency_snapshot_sha256": "d" * 64,
        "statement_snapshot_sha256": "e" * 64,
        "state_request_sha256": "c" * 64,
        "raw_files": [
            {
                "raw_id": calculate_raw_id("synthetic-evidence.txt", "f" * 64),
                "relative_path": "synthetic-evidence.txt",
                "path_sha256": hashlib.sha256(
                    b"synthetic-evidence.txt"
                ).hexdigest(),
                "extension": ".txt",
                "detected_media_type": "text/plain",
                "media_type_detection": "MAGIC_PREFIX_V1",
                "extension_media_type_mismatch": False,
                "size_bytes": 18,
                "sha256": "f" * 64,
                "modified_at_ns": "0",
                "filesystem_identity_sha256": "9" * 64,
                "integrity_status": "INGESTION_BYTES_OBSERVED",
                "observation_status": "SYSTEM_OBSERVED_UNATTESTED",
                "user_provenance_status": "NOT_PROVIDED",
            }
        ],
        "source_artifacts": [
            {
                "source_id": "SRC-001",
                "canonical_url": "https://flk.npc.gov.cn/detail?id=synthetic-test-only",
                "publisher": "Synthetic official-source fixture",
                "publisher_code": "NATIONAL_LAWS_REGULATIONS_DATABASE",
                "document_title": "Synthetic labor rule for tests",
                "document_type": "LAW",
                "legal_hierarchy": "LAW",
                "binding_status": "BINDING",
                "jurisdiction": {"country": "CN", "province": "Beijing"},
                "retrieved_at": "2026-07-14T00:00:00Z",
                "content_sha256": "1" * 64,
                "content_hash_status": "DECLARED_UNVERIFIED",
            }
        ],
        "legal_rules": [
            {
                "rule_id": "RULE-001",
                "source_id": "SRC-001",
                "provision": "Synthetic article 1",
                "jurisdiction": {"country": "CN", "province": "Beijing"},
                "effective_from": "2020-01-01",
                "effective_to": None,
                "status": "UNVERIFIED_CANDIDATE",
                "verified_at": None,
                "verified_by": None,
                "verification_actor_type": None,
                "supersedes": [],
                "superseded_by": None,
            }
        ],
        "evidence": [
            {
                "evidence_id": "E-001",
                "raw_id": calculate_raw_id("synthetic-evidence.txt", "f" * 64),
                "location": {"type": "line", "value": "1"},
                "integrity_status": "INGESTION_BYTES_OBSERVED",
            }
        ],
        "facts": [
            {
                "fact_id": "FACT-001",
                "status": "EVIDENCE_LINKED",
                "evidence_ids": ["E-001"],
            }
        ],
        "claims": [
            {
                "claim_id": "CLAIM-001",
                "elements": [
                    {
                        "element_id": "ELEMENT-001",
                        "assertion_status": "ASSERTED",
                        "proof_status": "EVIDENCE_LINKED_UNVERIFIED",
                        "burden_stage": "APPLICANT_INITIAL",
                        "evidence_controller": "APPLICANT",
                        "initial_burden_status": "UNVERIFIED",
                        "production_request": None,
                        "adverse_consequence_candidate": False,
                        "fact_ids": ["FACT-001"],
                        "evidence_ids": ["E-001"],
                        "rule_ids": ["RULE-001"],
                    }
                ],
                "limitation_analysis": {
                    "accrual_basis": "synthetic accrual basis",
                    "knowledge_date": "2026-01-01",
                    "relationship_end_date": "2026-01-31",
                    "interruption_events": [],
                    "suspension_intervals": [],
                    "special_rule": None,
                    "calculated_deadline": None,
                    "deadline_status": "UNVERIFIED",
                    "evidence_ids": ["E-001"],
                    "review_status": "PENDING_LEGAL_REVIEW",
                },
                "calculation_ids": ["CALC-001"],
            }
        ],
        "calculations": [
            {
                "calculation_id": "CALC-001",
                "calculator_version": "1.0.0",
                "formula_id": "SUM_DECIMAL_INPUTS_V1",
                "status": "ARITHMETIC_RECOMPUTED",
                "inputs": [
                    {"name": "amount", "value": "100.00", "evidence_id": "E-001"}
                ],
                "result": "100.00",
                "rounding_policy": "ROUND_HALF_UP_2",
                "intermediate_steps": ["100.00"],
                "assumptions": ["Synthetic fixture only"],
            }
        ],
        "conflicts": [],
        "statements": [
            {
                "statement_id": "ST-001",
                "text": "Synthetic formal statement.",
                "fact_ids": ["FACT-001"],
                "rule_ids": ["RULE-001"],
                "calculation_ids": ["CALC-001"],
            }
        ],
        "adversarial_findings": [],
        "privacy_review": {
            "status": "EXTERNAL_REVIEW_REQUIRED",
            "reviewed_by": None,
            "reviewed_at": None,
            "reviewer_actor_type": None,
        },
        "approvals": [],
    }
    package["intake_manifest_sha256"] = calculate_json_snapshot(
        make_intake_manifest(package)
    )
    package["dependency_snapshot_sha256"] = calculate_dependency_snapshot(package)
    package["statement_snapshot_sha256"] = calculate_statement_snapshot(package)
    package["package_snapshot_sha256"] = calculate_snapshot(package)
    package["state_request_sha256"] = calculate_state_request(package)
    return package


def make_valid_machine_candidate():
    """Compatibility test-helper name returning the current v1.3 safe fixture."""
    return make_valid_reference_integrity_package()
