#!/usr/bin/env python3
"""Build privacy-gated classification metadata for a frozen official public case."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from frozen_source_store import validate_frozen_source_record  # noqa: E402
from bounded_json_input import (  # noqa: E402
    BoundedJsonInputError,
    load_bounded_json_object,
)
from official_case_policy import (  # noqa: E402
    OfficialCaseRecordError,
    build_official_case_record,
)
from validate_case_package import (  # noqa: E402
    configure_utf8_stdio,
    emit_input_error,
)


CATEGORIES = (
    "WAGE_OR_WAGE_DIFFERENCE",
    "OVERTIME_PAY",
    "UNSIGNED_CONTRACT_DOUBLE_WAGE",
    "TERMINATION_COMPENSATION",
    "ANNUAL_LEAVE_PAY",
    "SOCIAL_INSURANCE",
    "EMPLOYMENT_RELATIONSHIP",
    "OTHER_OR_UNDETERMINED",
)


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("frozen_record", type=Path)
    parser.add_argument("--store", required=True, type=Path)
    parser.add_argument("--category", action="append", required=True, choices=CATEGORIES)
    parser.add_argument(
        "--document-type",
        required=True,
        choices=("OFFICIAL_TYPICAL_CASE", "PUBLIC_JUDGMENT", "PUBLIC_RULING", "OTHER_OFFICIAL_CASE_MATERIAL"),
    )
    parser.add_argument(
        "--procedural-stage",
        required=True,
        choices=("ARBITRATION", "FIRST_INSTANCE", "SECOND_INSTANCE", "RETRIAL", "MIXED_OR_UNDETERMINED"),
    )
    parser.add_argument(
        "--jurisdiction-scope",
        required=True,
        choices=("BEIJING", "NATIONAL", "OTHER_OR_UNDETERMINED"),
    )
    args = parser.parse_args()
    try:
        frozen_record = load_bounded_json_object(
            args.frozen_record,
            1024 * 1024,
            "OFFICIAL_CASE_FROZEN_RECORD",
            "Frozen record",
        )
    except BoundedJsonInputError as error:
        emit_input_error(error.code, str(error))
        return 1
    frozen_report = validate_frozen_source_record(frozen_record, args.store)
    if not frozen_report["allowed"]:
        print(json.dumps(frozen_report, ensure_ascii=False, indent=2, sort_keys=True))
        return 2
    try:
        record = build_official_case_record(
            frozen_record,
            dispute_categories=args.category,
            document_type=args.document_type,
            procedural_stage=args.procedural_stage,
            jurisdiction_scope=args.jurisdiction_scope,
        )
    except OfficialCaseRecordError as error:
        emit_input_error(error.code, str(error))
        return 2
    print(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
