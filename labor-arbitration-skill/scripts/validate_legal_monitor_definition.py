#!/usr/bin/env python3
"""Validate a locked legal-update monitor definition."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from bounded_json_input import BoundedJsonInputError, load_bounded_json_object  # noqa: E402
from legal_monitor_policy import validate_legal_monitor_definition  # noqa: E402
from validate_case_package import configure_utf8_stdio, emit_input_error  # noqa: E402


MAX_INPUT_BYTES = 4 * 1024 * 1024


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("definition", type=Path)
    args = parser.parse_args()
    try:
        definition = load_bounded_json_object(
            args.definition,
            MAX_INPUT_BYTES,
            "LEGAL_MONITOR_DEFINITION",
            "Legal monitor definition",
        )
    except BoundedJsonInputError as error:
        emit_input_error(error.code, str(error))
        return 1
    report = validate_legal_monitor_definition(definition)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["allowed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
