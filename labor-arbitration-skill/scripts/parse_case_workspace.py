#!/usr/bin/env python3
"""Parse one immutable workspace object through the isolated worker boundary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bounded_json_input import BoundedJsonInputError
from isolated_parser import IsolatedParserError, parse_workspace_object


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace", type=Path)
    parser.add_argument("raw_id")
    parser.add_argument("--timeout-seconds", type=int, default=15)
    arguments = parser.parse_args()
    try:
        record, _report = parse_workspace_object(
            arguments.workspace,
            arguments.raw_id,
            timeout_seconds=arguments.timeout_seconds,
        )
    except (BoundedJsonInputError, IsolatedParserError) as error:
        print(
            json.dumps(
                {
                    "allowed": False,
                    "error": {"code": error.code, "message": str(error)},
                    "submission_ready": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if record["status"] == "SUCCEEDED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
