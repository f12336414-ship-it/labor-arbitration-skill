#!/usr/bin/env python3
"""Validate a fact candidate against its exact parser record and predecessor."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bounded_json_input import BoundedJsonInputError, load_bounded_json_object
from fact_candidate_policy import validate_fact_candidate_record


MAX_RECORD_BYTES = 8 * 1024 * 1024


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record", type=Path)
    parser.add_argument("--parse-record", required=True, type=Path)
    parser.add_argument("--previous-record", type=Path)
    args = parser.parse_args()
    try:
        record = _load(args.record, "FACT_CANDIDATE_INPUT", "Fact candidate")
        parse_record = _load(args.parse_record, "FACT_PARSE_INPUT", "Parser record")
        previous = _load(args.previous_record, "FACT_PREVIOUS_INPUT", "Previous fact record") if args.previous_record else None
    except BoundedJsonInputError as error:
        print(json.dumps({"error": {"code": error.code, "message": str(error)}}))
        return 1
    report = validate_fact_candidate_record(record, parse_record, previous)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["allowed"] else 2


def _load(path: Path, code: str, label: str) -> dict:
    return load_bounded_json_object(path, MAX_RECORD_BYTES, code, label)


if __name__ == "__main__":
    raise SystemExit(main())
