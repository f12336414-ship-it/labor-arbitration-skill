#!/usr/bin/env python3
"""Build a human-gated local evidence review from bound candidates and views."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bounded_json_input import BoundedJsonInputError, load_bounded_json_object
from evidence_review_policy import EvidenceReviewError, build_evidence_review


MAX_SPECIFICATION_BYTES = 32 * 1024 * 1024


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("specification", type=Path)
    args = parser.parse_args()
    try:
        specification = load_bounded_json_object(args.specification, MAX_SPECIFICATION_BYTES, "EVIDENCE_REVIEW_INPUT", "Evidence review specification")
        record = build_evidence_review(specification)
    except (BoundedJsonInputError, EvidenceReviewError) as error:
        code = getattr(error, "code", "EVIDENCE_REVIEW_INPUT_INVALID")
        print(json.dumps({"error": {"code": code, "message": str(error)}}, ensure_ascii=False))
        return 2
    print(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
