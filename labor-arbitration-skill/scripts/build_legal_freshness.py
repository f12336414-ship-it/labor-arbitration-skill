#!/usr/bin/env python3
"""Build a technical freshness record from validated frozen source records."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from bounded_json_input import BoundedJsonInputError, load_bounded_json_object
from frozen_source_store import validate_frozen_source_record
from legal_freshness_policy import (
    build_legal_freshness_check,
    frozen_binding,
    validate_legal_freshness_check,
)
from validate_case_package import configure_utf8_stdio


MAX_RECORD_BYTES = 2 * 1024 * 1024


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline_record", type=Path)
    parser.add_argument("--store", required=True, type=Path)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--observation-record", type=Path)
    group.add_argument("--unavailable", action="store_true")
    parser.add_argument("--document-id", required=True)
    parser.add_argument("--publisher-code", required=True)
    parser.add_argument("--checked-at", required=True)
    parser.add_argument("--max-age-hours", required=True, type=int)
    args = parser.parse_args()
    try:
        baseline = _load(args.baseline_record, "LEGAL_FRESHNESS_BASELINE")
        observation = _load(args.observation_record, "LEGAL_FRESHNESS_OBSERVATION") if args.observation_record else None
    except BoundedJsonInputError as error:
        print(json.dumps({"error": {"code": error.code, "message": str(error)}}))
        return 1
    for label, record in (("BASELINE", baseline), ("OBSERVATION", observation)):
        if record is None:
            continue
        report = validate_frozen_source_record(record, args.store)
        if not report["allowed"]:
            print(json.dumps({"error": {"code": f"LEGAL_FRESHNESS_{label}_INVALID", "message": "Frozen source record failed offline replay."}}))
            return 2
    try:
        check = build_legal_freshness_check(
            document_id=args.document_id,
            publisher_code=args.publisher_code,
            baseline=frozen_binding(baseline),
            observation=frozen_binding(observation) if observation else None,
            checked_at=args.checked_at,
            max_age_hours=args.max_age_hours,
        )
    except (KeyError, TypeError, ValueError):
        print(json.dumps({"error": {"code": "LEGAL_FRESHNESS_BUILD_INVALID", "message": "Validated frozen bindings could not produce a freshness record."}}))
        return 2
    report = validate_legal_freshness_check(check)
    if not report["allowed"]:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 2
    print(json.dumps(check, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _load(path: Path, code: str) -> dict:
    return load_bounded_json_object(path, MAX_RECORD_BYTES, code, "Frozen source record")


if __name__ == "__main__":
    raise SystemExit(main())
