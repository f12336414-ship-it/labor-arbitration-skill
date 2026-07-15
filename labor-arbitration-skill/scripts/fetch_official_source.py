#!/usr/bin/env python3
"""Fetch and immutably freeze one explicit official-source candidate URL."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from frozen_source_store import (  # noqa: E402
    FrozenSourceStoreError,
    freeze_fetched_source,
    validate_frozen_source_record,
)
from official_source_fetch import fetch_official_source  # noqa: E402
from source_fetch_policy import FetchRefusal  # noqa: E402
from validate_case_package import configure_utf8_stdio  # noqa: E402


def _emit_error(code: str, message: str) -> None:
    print(
        json.dumps(
            {
                "allowed": False,
                "error": {"code": code, "message": message},
                "submission_ready": False,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--publisher-code", required=True)
    parser.add_argument(
        "--purpose",
        required=True,
        choices=("NORMATIVE_LEGAL_SOURCE", "OFFICIAL_CASE"),
    )
    parser.add_argument("--store", required=True, type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument("--max-response-bytes", type=int)
    args = parser.parse_args()

    try:
        fetched = fetch_official_source(
            args.url,
            args.publisher_code,
            args.purpose,
            timeout_seconds=args.timeout_seconds,
            max_response_bytes=args.max_response_bytes,
        )
        record_path, record = freeze_fetched_source(
            args.store,
            requested_url=args.url,
            publisher_code=args.publisher_code,
            purpose=args.purpose,
            fetched=fetched,
        )
        report = validate_frozen_source_record(record, args.store)
    except (FetchRefusal, FrozenSourceStoreError) as error:
        _emit_error(error.code, str(error))
        return 2
    except Exception:
        _emit_error(
            "FETCH_NETWORK_DEPENDENCY_FAILED",
            "The HTTPS dependency failed without publishing a successful fetch result.",
        )
        return 2

    if not report["allowed"]:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 2
    relative_record = record_path.relative_to(args.store.absolute()).as_posix()
    print(
        json.dumps(
            {
                "allowed": True,
                "allowed_scope": "SINGLE_OFFICIAL_SOURCE_RESPONSE_BODY_FREEZE",
                "content_sha256": record["content_sha256"],
                "fetch_id": record["fetch_id"],
                "object_relative_path": record["object_relative_path"],
                "record_relative_path": relative_record,
                "submission_ready": False,
                "validation_scope": report["validation_scope"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
