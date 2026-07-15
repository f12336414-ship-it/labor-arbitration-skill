#!/usr/bin/env python3
"""Validate a bounded parser extraction record offline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bounded_json_input import BoundedJsonInputError, load_bounded_json_object
from parser_extraction_policy import validate_parser_extraction_record


MAX_RECORD_BYTES = 8 * 1024 * 1024


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("record", type=Path)
    arguments = parser.parse_args()
    try:
        record = load_bounded_json_object(
            arguments.record,
            MAX_RECORD_BYTES,
            "PARSER_EXTRACTION_INPUT",
            "Parser extraction record",
        )
    except BoundedJsonInputError as error:
        print(json.dumps({"error": {"code": error.code, "message": str(error)}}))
        return 1
    report = validate_parser_extraction_record(record)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["allowed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
