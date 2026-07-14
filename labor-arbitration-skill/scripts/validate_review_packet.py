#!/usr/bin/env python3
"""Validate a rule, claim, or calculator cross-validation review packet."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from review_packet_policy import validate_review_packet  # noqa: E402
from validate_case_package import (  # noqa: E402
    DuplicateKeyError,
    InputTooLargeError,
    InvalidJsonConstantError,
    configure_utf8_stdio,
    emit_input_error,
    read_stable_utf8,
    reject_duplicate_keys,
    reject_json_constant,
)


MAX_REVIEW_PACKET_BYTES = 2 * 1024 * 1024


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_packet", type=Path)
    args = parser.parse_args()

    try:
        raw_input = read_stable_utf8(
            args.review_packet,
            MAX_REVIEW_PACKET_BYTES,
        )
    except InputTooLargeError:
        emit_input_error(
            "REVIEW_PACKET_INPUT_TOO_LARGE",
            f"Review packet exceeds the {MAX_REVIEW_PACKET_BYTES}-byte limit.",
        )
        return 1
    except (OSError, UnicodeError) as error:
        emit_input_error("REVIEW_PACKET_INPUT_UNREADABLE", str(error))
        return 1

    try:
        packet = json.loads(
            raw_input,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_json_constant,
        )
    except DuplicateKeyError as error:
        emit_input_error(
            "REVIEW_PACKET_INPUT_DUPLICATE_KEY",
            f"Duplicate JSON object key: {error}",
        )
        return 1
    except InvalidJsonConstantError as error:
        emit_input_error(
            "REVIEW_PACKET_INPUT_INVALID_CONSTANT",
            f"Non-standard JSON numeric constant: {error}",
        )
        return 1
    except json.JSONDecodeError as error:
        emit_input_error(
            "REVIEW_PACKET_INPUT_INVALID_JSON",
            f"Invalid JSON at line {error.lineno}, column {error.colno}.",
        )
        return 1
    except RecursionError:
        emit_input_error(
            "REVIEW_PACKET_INPUT_TOO_DEEPLY_NESTED",
            "Review-packet JSON nesting exceeds the parser safety limit.",
        )
        return 1

    if not isinstance(packet, dict):
        emit_input_error(
            "REVIEW_PACKET_INPUT_ROOT_NOT_OBJECT",
            "The review-packet JSON root must be an object.",
        )
        return 1

    report = validate_review_packet(packet)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["allowed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
