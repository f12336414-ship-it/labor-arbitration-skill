#!/usr/bin/env python3
"""Create an exact, bounded UTF-8 diff between two frozen legal-source texts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from legal_text_diff import (  # noqa: E402
    LegalTextDiffError,
    build_legal_text_diff,
    read_plain_stable_utf8,
)
from validate_case_package import configure_utf8_stdio, emit_input_error  # noqa: E402


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("from_source", type=Path)
    parser.add_argument("to_source", type=Path)
    parser.add_argument("--from-version-id", required=True)
    parser.add_argument("--to-version-id", required=True)
    args = parser.parse_args()
    try:
        from_text = read_plain_stable_utf8(args.from_source)
        to_text = read_plain_stable_utf8(args.to_source)
        record = build_legal_text_diff(
            args.from_version_id,
            args.to_version_id,
            from_text,
            to_text,
        )
    except LegalTextDiffError as error:
        emit_input_error(error.code, str(error))
        return 1
    print(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
