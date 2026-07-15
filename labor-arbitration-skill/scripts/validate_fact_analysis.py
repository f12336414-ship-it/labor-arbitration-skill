#!/usr/bin/env python3
"""Validate a structured-fact conflict record and its direct predecessor."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bounded_json_input import BoundedJsonInputError, load_bounded_json_object
from fact_analysis_policy import validate_fact_analysis_record


MAX_RECORD_BYTES = 16 * 1024 * 1024


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record", type=Path)
    parser.add_argument("--previous-record", type=Path)
    args = parser.parse_args()
    try:
        record = _load(args.record, "FACT_ANALYSIS_RECORD", "Fact analysis record")
        previous = _load(args.previous_record, "FACT_ANALYSIS_PREVIOUS", "Previous fact analysis record") if args.previous_record else None
    except BoundedJsonInputError as error:
        print(json.dumps({"error": {"code": error.code, "message": str(error)}}))
        return 1
    report = validate_fact_analysis_record(record, previous)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["allowed"] else 2


def _load(path: Path, code: str, label: str) -> dict:
    return load_bounded_json_object(path, MAX_RECORD_BYTES, code, label)


if __name__ == "__main__":
    raise SystemExit(main())
