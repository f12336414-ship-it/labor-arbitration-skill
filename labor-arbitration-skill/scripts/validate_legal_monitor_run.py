#!/usr/bin/env python3
"""Validate a legal-update monitor run and its exact definition/predecessor."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from bounded_json_input import BoundedJsonInputError, load_bounded_json_object  # noqa: E402
from legal_monitor_policy import validate_legal_monitor_run  # noqa: E402
from validate_case_package import configure_utf8_stdio, emit_input_error  # noqa: E402


MAX_INPUT_BYTES = 16 * 1024 * 1024


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--definition", required=True, type=Path)
    parser.add_argument("--previous-run", type=Path)
    args = parser.parse_args()
    try:
        record = _load(args.run, "LEGAL_MONITOR_RUN", "Legal monitor run")
        definition = _load(args.definition, "LEGAL_MONITOR_DEFINITION", "Legal monitor definition")
        previous = _load(args.previous_run, "LEGAL_MONITOR_PREVIOUS_RUN", "Previous legal monitor run") if args.previous_run else None
    except BoundedJsonInputError as error:
        emit_input_error(error.code, str(error))
        return 1
    report = validate_legal_monitor_run(record, definition, previous)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["allowed"] else 2


def _load(path: Path, code: str, label: str) -> dict:
    return load_bounded_json_object(path, MAX_INPUT_BYTES, code, label)


if __name__ == "__main__":
    raise SystemExit(main())
