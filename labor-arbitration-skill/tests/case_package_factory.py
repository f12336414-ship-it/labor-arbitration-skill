import copy
import hashlib
import json


INTEGRITY_SEMANTICS = "Hashes verify bytes observed at ingestion, not authenticity."


def calculate_snapshot(package):
    snapshot_content = copy.deepcopy(package)
    snapshot_content.pop("requested_state", None)
    snapshot_content.pop("package_snapshot_sha256", None)
    snapshot_content.pop("approvals", None)
    encoded = json.dumps(
        snapshot_content,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def calculate_json_snapshot(value):
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def make_intake_manifest(package):
    return {
        "schema_version": "1.1",
        "integrity_semantics": INTEGRITY_SEMANTICS,
        "files": copy.deepcopy(package["raw_files"]),
    }


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


def calculate_document_snapshot(package):
    return calculate_json_snapshot({"statements": package.get("statements", [])})


def make_valid_machine_candidate():
    package = {
        "schema_version": "1.1",
        "requested_state": "MACHINE_VALIDATED_CANDIDATE",
        "jurisdiction": {"country": "CN", "province": "Beijing"},
        "dependency_snapshot_sha256": "d" * 64,
        "document_snapshot_sha256": "e" * 64,
        "raw_files": [
            {
                "raw_id": "RAW-0001",
                "relative_path": "synthetic-evidence.txt",
                "extension": ".txt",
                "size_bytes": 18,
                "sha256": "f" * 64,
                "integrity_status": "INGESTION_INTEGRITY_VERIFIED",
            }
        ],
        "source_artifacts": [
            {
                "source_id": "SRC-001",
                "canonical_url": "https://flk.npc.gov.cn/detail?id=synthetic-test-only",
                "publisher": "Synthetic official-source fixture",
                "document_title": "Synthetic labor rule for tests",
                "document_type": "LAW",
                "legal_hierarchy": "LAW",
                "binding_status": "BINDING",
                "jurisdiction": {"country": "CN", "province": "Beijing"},
                "retrieved_at": "2026-07-14T00:00:00Z",
                "content_sha256": "1" * 64,
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
                "status": "VERIFIED_CURRENT",
                "verified_at": "2026-07-14T00:00:00Z",
                "verified_by": "LEGAL-REVIEWER-001",
                "verification_actor_type": "HUMAN",
                "supersedes": [],
                "superseded_by": None,
            }
        ],
        "evidence": [
            {
                "evidence_id": "E-001",
                "raw_id": "RAW-0001",
                "location": {"type": "line", "value": "1"},
                "integrity_status": "INGESTION_INTEGRITY_VERIFIED",
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
                        "proof_status": "SUPPORTED",
                        "burden_stage": "APPLICANT_INITIAL",
                        "evidence_controller": "APPLICANT",
                        "initial_burden_satisfied": True,
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
                    "calculated_deadline": "2027-01-01",
                    "deadline_status": "WITHIN_LIMITATION",
                    "evidence_ids": ["E-001"],
                    "review_status": "REVIEWED",
                },
                "calculation_ids": ["CALC-001"],
            }
        ],
        "calculations": [
            {
                "calculation_id": "CALC-001",
                "calculator_version": "1.0.0",
                "formula_id": "SUM_DECIMAL_INPUTS_V1",
                "status": "EXACT_GIVEN_ASSUMPTIONS",
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
            "status": "COMPLETED",
            "reviewed_by": "PRIVACY-REVIEWER-001",
            "reviewed_at": "2026-07-14T00:00:00Z",
            "reviewer_actor_type": "HUMAN",
        },
        "approvals": [],
    }
    package["intake_manifest_sha256"] = calculate_json_snapshot(
        make_intake_manifest(package)
    )
    package["dependency_snapshot_sha256"] = calculate_dependency_snapshot(package)
    package["document_snapshot_sha256"] = calculate_document_snapshot(package)
    package["package_snapshot_sha256"] = calculate_snapshot(package)
    return package
