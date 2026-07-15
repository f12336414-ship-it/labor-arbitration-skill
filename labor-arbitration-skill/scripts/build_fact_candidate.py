#!/usr/bin/env python3
"""Create an initial or human-labelled local fact candidate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bounded_json_input import BoundedJsonInputError, load_bounded_json_object
from fact_candidate_policy import FactCandidateError, build_fact_candidate


MAX_RECORD_BYTES = 8 * 1024 * 1024


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("parse_record", type=Path)
    parser.add_argument("--anchor-id", action="append", required=True)
    parser.add_argument("--state", required=True, choices=("EXTRACTED", "USER_ANNOTATED", "ADJUDICATED"))
    parser.add_argument("--claim-type", required=True)
    parser.add_argument("--assertion", required=True)
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--actor-label")
    parser.add_argument("--document-kind")
    parser.add_argument("--document-reference")
    parser.add_argument("--previous-record", type=Path)
    args = parser.parse_args()
    try:
        parse_record = _load(args.parse_record, "FACT_PARSE_INPUT", "Parser record")
        previous = _load(args.previous_record, "FACT_PREVIOUS_INPUT", "Previous fact record") if args.previous_record else None
        record = build_fact_candidate(
            parse_record,
            anchor_ids=args.anchor_id,
            provenance_state=args.state,
            claim_type=args.claim_type,
            assertion_text=args.assertion,
            created_at=args.created_at,
            actor_label=args.actor_label,
            adjudicative_document_kind=args.document_kind,
            adjudicative_document_reference=args.document_reference,
            previous_record=previous,
        )
    except (BoundedJsonInputError, FactCandidateError) as error:
        code = getattr(error, "code", "FACT_CANDIDATE_INPUT_INVALID")
        print(json.dumps({"error": {"code": code, "message": str(error)}}, ensure_ascii=False))
        return 2
    print(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _load(path: Path, code: str, label: str) -> dict:
    return load_bounded_json_object(path, MAX_RECORD_BYTES, code, label)


if __name__ == "__main__":
    raise SystemExit(main())
