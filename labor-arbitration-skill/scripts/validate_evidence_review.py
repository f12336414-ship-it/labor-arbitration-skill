#!/usr/bin/env python3
"""Validate a human-gated local evidence review record offline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bounded_json_input import BoundedJsonInputError, load_bounded_json_object
from evidence_review_policy import validate_evidence_review_record


MAX_RECORD_BYTES = 16 * 1024 * 1024


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record", type=Path)
    args = parser.parse_args()
    try:
        record = load_bounded_json_object(args.record, MAX_RECORD_BYTES, "EVIDENCE_REVIEW_RECORD", "Evidence review record")
    except BoundedJsonInputError as error:
        print(json.dumps({"error": {"code": error.code, "message": str(error)}}))
        return 1
    report = validate_evidence_review_record(record)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["allowed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
