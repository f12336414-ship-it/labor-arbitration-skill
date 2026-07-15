#!/usr/bin/env python3
"""Create an immutable invalidation revision for a local fact candidate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bounded_json_input import BoundedJsonInputError, load_bounded_json_object
from fact_candidate_policy import FactCandidateError, invalidate_fact_candidate


MAX_RECORD_BYTES = 8 * 1024 * 1024


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record", type=Path)
    parser.add_argument("--parse-record", required=True, type=Path)
    parser.add_argument("--reason-code", required=True, choices=("SOURCE_CHANGED", "ANCHOR_MISSING", "USER_RETRACTED", "SUPERSEDED", "OTHER"))
    parser.add_argument("--reason", required=True)
    parser.add_argument("--actor-label", required=True)
    parser.add_argument("--created-at", required=True)
    args = parser.parse_args()
    try:
        record = load_bounded_json_object(args.record, MAX_RECORD_BYTES, "FACT_CANDIDATE_INPUT", "Fact candidate")
        parse_record = load_bounded_json_object(args.parse_record, MAX_RECORD_BYTES, "FACT_PARSE_INPUT", "Parser record")
        result = invalidate_fact_candidate(
            record,
            parse_record,
            reason_code=args.reason_code,
            reason=args.reason,
            actor_label=args.actor_label,
            created_at=args.created_at,
        )
    except (BoundedJsonInputError, FactCandidateError) as error:
        code = getattr(error, "code", "FACT_CANDIDATE_INPUT_INVALID")
        print(json.dumps({"error": {"code": code, "message": str(error)}}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
