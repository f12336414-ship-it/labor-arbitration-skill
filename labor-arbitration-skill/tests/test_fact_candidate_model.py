import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIRECTORY = SKILL_ROOT / "scripts"
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from fact_candidate_policy import (  # noqa: E402
    FactCandidateError,
    build_fact_candidate,
    calculate_fact_candidate_id,
    calculate_fact_candidate_snapshot,
    invalidate_fact_candidate,
    validate_fact_candidate_record,
)
from parser_extraction_policy import (  # noqa: E402
    calculate_anchor_id,
    calculate_parse_id,
    calculate_parser_record_snapshot,
)


def make_parse_record(texts=("January wage was 5000", "Payment date was 2026-02-05")):
    content_hash = hashlib.sha256("\n".join(texts).encode()).hexdigest()
    binding = {
        "workspace_id": "WORKSPACE-" + "A" * 24,
        "workspace_snapshot_sha256": "b" * 64,
        "raw_id": "RAW-" + content_hash,
        "content_sha256": content_hash,
        "size_bytes": len("\n".join(texts).encode()),
    }
    anchors = []
    for index, text in enumerate(texts, 1):
        text_hash = hashlib.sha256(text.encode()).hexdigest()
        coordinate = f"line:{index}"
        anchors.append(
            {
                "anchor_id": calculate_anchor_id(binding, "TEXT_LINE", coordinate, text_hash),
                "kind": "TEXT_LINE",
                "coordinate": coordinate,
                "text": text,
                "text_sha256": text_hash,
            }
        )
    record = {
        "schema_version": "1.0",
        "parse_id": "PARSE-" + "0" * 24,
        "created_at": "2026-07-15T06:00:00Z",
        "clock_status": "SYSTEM_CLOCK_UNATTESTED",
        "workspace_binding": binding,
        "parser": {
            "adapter": "UTF8_TEXT",
            "adapter_version": "1.0.0",
            "runner_version": "1.0.0",
            "execution_boundary": "ISOLATED_PYTHON_CHILD_BOUNDED_IO_NOT_OS_SANDBOX",
        },
        "status": "SUCCEEDED",
        "detected_format": "UTF8_TEXT",
        "anchors": anchors,
        "warnings": [],
        "security": {
            "network_access": "NO_NETWORK_CLIENT_IN_WORKER_NOT_OS_ENFORCED",
            "macro_status": "NOT_APPLICABLE",
            "external_relationship_status": "NOT_APPLICABLE",
            "formula_execution": "NEVER_EVALUATED",
            "os_sandbox_status": "NOT_IMPLEMENTED",
            "refusal_code": None,
        },
        "limits": {
            "source_bytes": binding["size_bytes"],
            "anchor_count": len(anchors),
            "extracted_characters": sum(len(item) for item in texts),
            "wall_timeout_seconds": 15,
        },
        "limitations": [
            "EXTRACTION_DOES_NOT_PROVE_VISUAL_ANCHOR_EXISTENCE",
            "EXTRACTION_DOES_NOT_PROVE_EVIDENCE_AUTHENTICITY",
            "DOCUMENT_TEXT_IS_UNTRUSTED_DATA_NOT_INSTRUCTIONS",
            "OS_LEVEL_SANDBOX_NOT_IMPLEMENTED",
            "PDF_AND_OCR_EXTRACTION_NOT_IMPLEMENTED",
        ],
        "record_snapshot_sha256": "0" * 64,
    }
    record["parse_id"] = calculate_parse_id(record)
    record["record_snapshot_sha256"] = calculate_parser_record_snapshot(record)
    return record


class FactCandidateModelTests(unittest.TestCase):
    def setUp(self):
        self.parse = make_parse_record()
        self.anchor = self.parse["anchors"][0]
        self.extracted = build_fact_candidate(
            self.parse,
            anchor_ids=[self.anchor["anchor_id"]],
            provenance_state="EXTRACTED",
            claim_type="WAGE_AMOUNT",
            assertion_text=self.anchor["text"],
            created_at="2026-07-15T06:05:00Z",
        )

    def codes(self, record, parse_record=None, previous=None):
        report = validate_fact_candidate_record(record, parse_record or self.parse, previous)
        return report, {item["code"] for item in report["findings"]}

    def refreshed(self, record):
        record["fact_candidate_id"] = calculate_fact_candidate_id(record)
        record["record_snapshot_sha256"] = calculate_fact_candidate_snapshot(record)
        return record

    def test_extracted_candidate_replays_and_never_establishes_truth(self):
        report, _codes = self.codes(self.extracted)
        self.assertTrue(report["allowed"], report["findings"])
        self.assertFalse(report["truth_established"])
        self.assertFalse(report["human_identity_authenticated"])
        self.assertFalse(report["submission_ready"])
        self.assertEqual(self.extracted["truth_status"], "UNVERIFIED")
        self.assertEqual(self.extracted["review"]["confirmation_status"], "NOT_HUMAN_CONFIRMED")

    def test_extracted_requires_one_exact_anchor(self):
        with self.assertRaisesRegex(FactCandidateError, "exact parser anchor"):
            build_fact_candidate(
                self.parse,
                anchor_ids=[self.anchor["anchor_id"]],
                provenance_state="EXTRACTED",
                claim_type="WAGE_AMOUNT",
                assertion_text="The wage was 6000",
                created_at="2026-07-15T06:05:00Z",
            )
        with self.assertRaises(FactCandidateError):
            build_fact_candidate(
                self.parse,
                anchor_ids=[item["anchor_id"] for item in self.parse["anchors"]],
                provenance_state="EXTRACTED",
                claim_type="WAGE_AMOUNT",
                assertion_text=self.anchor["text"],
                created_at="2026-07-15T06:05:00Z",
            )

    def test_user_annotation_is_derived_and_identity_remains_unauthenticated(self):
        record = build_fact_candidate(
            self.parse,
            anchor_ids=[item["anchor_id"] for item in self.parse["anchors"]],
            provenance_state="USER_ANNOTATED",
            claim_type="WAGE_AMOUNT",
            assertion_text="Employee says January wage should have been 6000.",
            created_at="2026-07-15T06:10:00Z",
            actor_label="local-user-1",
            previous_record=self.extracted,
        )
        report, _codes = self.codes(record, previous=self.extracted)
        self.assertTrue(report["allowed"], report["findings"])
        self.assertEqual(record["review"]["actor_assertion"], "USER_SELF_DECLARED_UNAUTHENTICATED")
        self.assertEqual(record["truth_status"], "UNVERIFIED")
        self.assertEqual(record["revision"]["previous_fact_candidate_id"], self.extracted["fact_candidate_id"])

    def test_human_state_requires_active_extracted_predecessor_and_actor(self):
        for kwargs in ({"previous_record": None, "actor_label": "u"}, {"previous_record": self.extracted, "actor_label": None}):
            with self.subTest(kwargs=kwargs), self.assertRaises(FactCandidateError):
                build_fact_candidate(
                    self.parse,
                    anchor_ids=[self.anchor["anchor_id"]],
                    provenance_state="USER_ANNOTATED",
                    claim_type="WAGE_AMOUNT",
                    assertion_text="annotation",
                    created_at="2026-07-15T06:10:00Z",
                    **kwargs,
                )

    def test_human_transition_cannot_switch_away_from_predecessor_anchor(self):
        other_anchor = self.parse["anchors"][1]
        with self.assertRaises(FactCandidateError) as raised:
            build_fact_candidate(
                self.parse,
                anchor_ids=[other_anchor["anchor_id"]],
                provenance_state="USER_ANNOTATED",
                claim_type="PAYMENT_DATE",
                assertion_text="annotation on a different passage",
                created_at="2026-07-15T06:10:00Z",
                actor_label="u",
                previous_record=self.extracted,
            )
        self.assertEqual(raised.exception.code, "FACT_TRANSITION_ANCHOR_MISMATCH")

    def test_adjudicated_is_exact_unverified_transcription_not_a_finding(self):
        record = build_fact_candidate(
            self.parse,
            anchor_ids=[self.anchor["anchor_id"]],
            provenance_state="ADJUDICATED",
            claim_type="WAGE_AMOUNT",
            assertion_text=self.anchor["text"],
            created_at="2026-07-15T06:10:00Z",
            actor_label="document-reviewer",
            adjudicative_document_kind="COURT_JUDGMENT",
            adjudicative_document_reference="synthetic reference",
            previous_record=self.extracted,
        )
        report, _codes = self.codes(record, previous=self.extracted)
        self.assertTrue(report["allowed"], report["findings"])
        self.assertEqual(record["adjudicative_context"]["document_authenticity_status"], "UNVERIFIED")
        self.assertEqual(record["adjudicative_context"]["legal_effect_status"], "UNVERIFIED")
        self.assertIn("not tribunal authentication", "ADJUDICATED means passage classification not tribunal authentication".lower())

    def test_adjudicated_requires_exact_text_and_document_context(self):
        common = dict(
            parse_record=self.parse,
            anchor_ids=[self.anchor["anchor_id"]],
            provenance_state="ADJUDICATED",
            claim_type="WAGE_AMOUNT",
            created_at="2026-07-15T06:10:00Z",
            actor_label="reviewer",
            previous_record=self.extracted,
        )
        with self.assertRaises(FactCandidateError):
            build_fact_candidate(assertion_text="paraphrase", adjudicative_document_kind="COURT_JUDGMENT", adjudicative_document_reference="ref", **common)
        with self.assertRaises(FactCandidateError):
            build_fact_candidate(assertion_text=self.anchor["text"], **common)

    def test_anchor_coordinate_hash_and_id_tampering_fail_replay(self):
        for field, value in (("coordinate", "line:99"), ("text_sha256", "0" * 64), ("anchor_id", "ANCHOR-" + "F" * 24)):
            record = copy.deepcopy(self.extracted)
            record["anchor_bindings"][0][field] = value
            self.refreshed(record)
            report, codes = self.codes(record)
            self.assertFalse(report["allowed"])
            self.assertIn("FACT_ANCHOR_REPLAY_FAILED", codes)

    def test_assertion_tamper_fails_hash_and_snapshot(self):
        record = copy.deepcopy(self.extracted)
        record["assertion"]["text"] = "tampered"
        report, codes = self.codes(record)
        self.assertFalse(report["allowed"])
        self.assertIn("FACT_ASSERTION_HASH_MISMATCH", codes)
        self.assertIn("FACT_SNAPSHOT_MISMATCH", codes)

    def test_parse_snapshot_or_content_change_fails_closed(self):
        changed = make_parse_record(("January wage was 6000", "Payment date was 2026-02-05"))
        report, codes = self.codes(self.extracted, parse_record=changed)
        self.assertFalse(report["allowed"])
        self.assertIn("FACT_PARSE_BINDING_MISMATCH", codes)
        self.assertIn("FACT_ANCHOR_REPLAY_FAILED", codes)

    def test_schema_rejects_truth_or_authenticated_identity_escalation(self):
        for path, value in (("truth_status", "ESTABLISHED"), ("actor_assertion", "AUTHENTICATED_LAWYER")):
            record = copy.deepcopy(self.extracted)
            if path == "truth_status":
                record[path] = value
            else:
                record["review"][path] = value
            report, codes = self.codes(record)
            self.assertFalse(report["allowed"])
            self.assertIn("FACT_CANDIDATE_SCHEMA_VALIDATION_ERROR", codes)

    def test_disputed_is_still_not_established_truth(self):
        record = copy.deepcopy(self.extracted)
        record["truth_status"] = "DISPUTED"
        self.refreshed(record)
        report, _codes = self.codes(record)
        self.assertTrue(report["allowed"], report["findings"])
        self.assertFalse(report["truth_established"])

    def test_invalid_utf8_scalar_is_refused_without_crashing(self):
        with self.assertRaises(FactCandidateError) as raised:
            build_fact_candidate(
                self.parse,
                anchor_ids=[self.anchor["anchor_id"]],
                provenance_state="EXTRACTED",
                claim_type="WAGE_AMOUNT",
                assertion_text="\ud800",
                created_at="2026-07-15T06:05:00Z",
            )
        self.assertEqual(raised.exception.code, "FACT_ASSERTION_UTF8_INVALID")

    def test_invalid_state_semantics_fail_even_with_refreshed_hashes(self):
        record = copy.deepcopy(self.extracted)
        record["review"]["actor_assertion"] = "USER_SELF_DECLARED_UNAUTHENTICATED"
        record["review"]["actor_label"] = "u"
        record["review"]["confirmation_status"] = "USER_CONFIRMED_UNAUTHENTICATED"
        record["review"]["reviewed_at"] = record["created_at"]
        self.refreshed(record)
        report, codes = self.codes(record)
        self.assertFalse(report["allowed"])
        self.assertIn("FACT_STATE_SEMANTICS_MISMATCH", codes)

    def test_human_review_time_must_equal_revision_time(self):
        record = build_fact_candidate(
            self.parse,
            anchor_ids=[self.anchor["anchor_id"]],
            provenance_state="USER_ANNOTATED",
            claim_type="WAGE_AMOUNT",
            assertion_text="annotation",
            created_at="2026-07-15T06:10:00Z",
            actor_label="u",
            previous_record=self.extracted,
        )
        record["review"]["reviewed_at"] = "2026-07-15T06:09:00Z"
        self.refreshed(record)
        report, codes = self.codes(record, previous=self.extracted)
        self.assertFalse(report["allowed"])
        self.assertIn("FACT_STATE_SEMANTICS_MISMATCH", codes)

    def test_derived_record_requires_exact_previous_record(self):
        derived = build_fact_candidate(
            self.parse,
            anchor_ids=[self.anchor["anchor_id"]],
            provenance_state="USER_ANNOTATED",
            claim_type="WAGE_AMOUNT",
            assertion_text="user annotation",
            created_at="2026-07-15T06:10:00Z",
            actor_label="u",
            previous_record=self.extracted,
        )
        report, codes = self.codes(derived)
        self.assertFalse(report["allowed"])
        self.assertIn("FACT_PREVIOUS_RECORD_REQUIRED", codes)
        wrong = copy.deepcopy(self.extracted)
        wrong["record_snapshot_sha256"] = "f" * 64
        report, codes = self.codes(derived, previous=wrong)
        self.assertFalse(report["allowed"])
        self.assertIn("FACT_PREVIOUS_RECORD_MISMATCH", codes)

    def test_derived_record_rejects_intrinsically_tampered_predecessor(self):
        derived = build_fact_candidate(
            self.parse,
            anchor_ids=[self.anchor["anchor_id"]],
            provenance_state="USER_ANNOTATED",
            claim_type="WAGE_AMOUNT",
            assertion_text="annotation",
            created_at="2026-07-15T06:10:00Z",
            actor_label="u",
            previous_record=self.extracted,
        )
        tampered = copy.deepcopy(self.extracted)
        tampered["assertion"]["text"] = "tampered predecessor"
        derived["revision"]["previous_record_snapshot_sha256"] = tampered["record_snapshot_sha256"]
        self.refreshed(derived)
        report, codes = self.codes(derived, previous=tampered)
        self.assertFalse(report["allowed"])
        self.assertIn("FACT_PREVIOUS_RECORD_INVALID", codes)

    def test_timestamp_rollback_fails_transition(self):
        derived = build_fact_candidate(
            self.parse,
            anchor_ids=[self.anchor["anchor_id"]],
            provenance_state="USER_ANNOTATED",
            claim_type="WAGE_AMOUNT",
            assertion_text="annotation",
            created_at="2026-07-15T06:10:00Z",
            actor_label="u",
            previous_record=self.extracted,
        )
        derived["created_at"] = "2026-07-15T06:04:00Z"
        derived["review"]["reviewed_at"] = derived["created_at"]
        self.refreshed(derived)
        report, codes = self.codes(derived, previous=self.extracted)
        self.assertFalse(report["allowed"])
        self.assertIn("FACT_TRANSITION_PRECONDITION_FAILED", codes)

    def test_invalidation_creates_revision_and_preserves_predecessor(self):
        original = copy.deepcopy(self.extracted)
        invalidated = invalidate_fact_candidate(
            self.extracted,
            self.parse,
            reason_code="USER_RETRACTED",
            reason="Synthetic retraction",
            actor_label="local-user-1",
            created_at="2026-07-15T06:20:00Z",
        )
        report, _codes = self.codes(invalidated, previous=self.extracted)
        self.assertTrue(report["allowed"], report["findings"])
        self.assertEqual(self.extracted, original)
        self.assertEqual(invalidated["candidate_status"], "INVALIDATED")
        self.assertEqual(invalidated["revision"]["transition"], "INVALIDATED")

    def test_invalidation_cannot_smuggle_a_semantic_edit(self):
        invalidated = invalidate_fact_candidate(
            self.extracted, self.parse, reason_code="OTHER", reason="reason", actor_label="u", created_at="2026-07-15T06:20:00Z"
        )
        invalidated["assertion"]["text"] = "changed while invalidating"
        invalidated["assertion"]["text_sha256"] = hashlib.sha256(
            invalidated["assertion"]["text"].encode()
        ).hexdigest()
        self.refreshed(invalidated)
        report, codes = self.codes(invalidated, previous=self.extracted)
        self.assertFalse(report["allowed"])
        self.assertIn("FACT_TRANSITION_INVALID", codes)

    def test_human_derived_candidate_can_be_invalidated(self):
        derived = build_fact_candidate(
            self.parse,
            anchor_ids=[self.anchor["anchor_id"]],
            provenance_state="USER_ANNOTATED",
            claim_type="WAGE_AMOUNT",
            assertion_text="annotation",
            created_at="2026-07-15T06:10:00Z",
            actor_label="u",
            previous_record=self.extracted,
        )
        invalidated = invalidate_fact_candidate(
            derived,
            self.parse,
            reason_code="SUPERSEDED",
            reason="New annotation required",
            actor_label="u",
            created_at="2026-07-15T06:20:00Z",
        )
        report, _codes = self.codes(invalidated, previous=derived)
        self.assertTrue(report["allowed"], report["findings"])

    def test_second_invalidation_and_unknown_reason_are_refused(self):
        invalidated = invalidate_fact_candidate(
            self.extracted, self.parse, reason_code="OTHER", reason="reason", actor_label="u", created_at="2026-07-15T06:20:00Z"
        )
        with self.assertRaises(FactCandidateError):
            invalidate_fact_candidate(invalidated, self.parse, reason_code="OTHER", reason="again", actor_label="u", created_at="2026-07-15T06:21:00Z")
        with self.assertRaises(FactCandidateError):
            invalidate_fact_candidate(self.extracted, self.parse, reason_code="UNKNOWN", reason="reason", actor_label="u", created_at="2026-07-15T06:20:00Z")

    def test_non_utc_and_unknown_claim_type_are_refused(self):
        for field, value in (("created_at", "2026-07-15T14:00:00+08:00"), ("claim_type", "LEGAL_CONCLUSION")):
            kwargs = dict(
                parse_record=self.parse,
                anchor_ids=[self.anchor["anchor_id"]],
                provenance_state="EXTRACTED",
                claim_type="WAGE_AMOUNT",
                assertion_text=self.anchor["text"],
                created_at="2026-07-15T06:05:00Z",
            )
            kwargs[field] = value
            with self.assertRaises(FactCandidateError):
                build_fact_candidate(**kwargs)

    def test_cli_build_and_validate_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parse_path = root / "parse.json"
            fact_path = root / "fact.json"
            parse_path.write_text(json.dumps(self.parse), encoding="utf-8")
            build = subprocess.run(
                [sys.executable, str(SCRIPT_DIRECTORY / "build_fact_candidate.py"), str(parse_path), "--anchor-id", self.anchor["anchor_id"], "--state", "EXTRACTED", "--claim-type", "WAGE_AMOUNT", "--assertion", self.anchor["text"], "--created-at", "2026-07-15T06:05:00Z"],
                capture_output=True, text=True, encoding="utf-8", check=False,
            )
            self.assertEqual(build.returncode, 0, build.stderr + build.stdout)
            fact_path.write_text(build.stdout, encoding="utf-8")
            validate = subprocess.run(
                [sys.executable, str(SCRIPT_DIRECTORY / "validate_fact_candidate.py"), str(fact_path), "--parse-record", str(parse_path)],
                capture_output=True, text=True, encoding="utf-8", check=False,
            )
            self.assertEqual(validate.returncode, 0, validate.stderr + validate.stdout)
            self.assertTrue(json.loads(validate.stdout)["allowed"])

    def test_cli_invalidation_round_trip_and_repeat_refusal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parse_path = root / "parse.json"
            fact_path = root / "fact.json"
            invalidated_path = root / "invalidated.json"
            parse_path.write_text(json.dumps(self.parse), encoding="utf-8")
            fact_path.write_text(json.dumps(self.extracted), encoding="utf-8")
            command = [
                sys.executable,
                str(SCRIPT_DIRECTORY / "invalidate_fact_candidate.py"),
                str(fact_path),
                "--parse-record", str(parse_path),
                "--reason-code", "USER_RETRACTED",
                "--reason", "Synthetic CLI retraction",
                "--actor-label", "local-user-1",
                "--created-at", "2026-07-15T06:20:00Z",
            ]
            first = subprocess.run(
                command, capture_output=True, text=True, encoding="utf-8", check=False
            )
            self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
            invalidated = json.loads(first.stdout)
            self.assertEqual(invalidated["candidate_status"], "INVALIDATED")
            invalidated_path.write_text(first.stdout, encoding="utf-8")
            validate = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_DIRECTORY / "validate_fact_candidate.py"),
                    str(invalidated_path),
                    "--parse-record", str(parse_path),
                    "--previous-record", str(fact_path),
                ],
                capture_output=True, text=True, encoding="utf-8", check=False,
            )
            self.assertEqual(validate.returncode, 0, validate.stderr + validate.stdout)
            repeat = subprocess.run(
                [*command[:2], str(invalidated_path), *command[3:]],
                capture_output=True, text=True, encoding="utf-8", check=False,
            )
            self.assertEqual(repeat.returncode, 2)
            self.assertEqual(json.loads(repeat.stdout)["error"]["code"], "FACT_ALREADY_INVALIDATED")

    def test_cli_rejects_oversized_or_non_object_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bad = root / "bad.json"
            bad.write_text("[]", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPT_DIRECTORY / "validate_fact_candidate.py"), str(bad), "--parse-record", str(bad)],
                capture_output=True, text=True, encoding="utf-8", check=False,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("FACT_CANDIDATE_INPUT_ROOT_NOT_OBJECT", result.stdout)


if __name__ == "__main__":
    unittest.main()
