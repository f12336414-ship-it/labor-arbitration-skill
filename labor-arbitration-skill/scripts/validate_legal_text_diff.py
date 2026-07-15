#!/usr/bin/env python3
"""Validate an exact UTF-8 legal-source text diff record."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from legal_text_diff import validate_legal_text_diff_record  # noqa: E402
from bounded_json_input import (  # noqa: E402
    BoundedJsonInputError,
    load_bounded_json_object,
)
from validate_case_package import (  # noqa: E402
    configure_utf8_stdio,
    emit_input_error,
)


MAX_DIFF_BYTES = 4 * 1024 * 1024


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("diff", type=Path)
    args = parser.parse_args()
    try:
        record = load_bounded_json_object(
            args.diff, MAX_DIFF_BYTES, "LEGAL_TEXT_DIFF_RECORD", "Diff record"
        )
    except BoundedJsonInputError as error:
        emit_input_error(error.code, str(error))
        return 1
    report = validate_legal_text_diff_record(record)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["allowed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
