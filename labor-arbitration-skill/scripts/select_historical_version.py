#!/usr/bin/env python3
"""Select unverified historical legal-version interval candidates from a locked graph."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from historical_version_policy import (  # noqa: E402
    HistoricalVersionError,
    select_historical_version_candidate,
)
from bounded_json_input import (  # noqa: E402
    BoundedJsonInputError,
    load_bounded_json_object,
)
from validate_case_package import (  # noqa: E402
    configure_utf8_stdio,
    emit_input_error,
)


MAX_GRAPH_BYTES = 4 * 1024 * 1024


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("graph", type=Path)
    parser.add_argument("--event-date", required=True)
    parser.add_argument("--country", default="CN")
    parser.add_argument("--province", default="Beijing")
    args = parser.parse_args()
    try:
        graph = load_bounded_json_object(
            args.graph,
            MAX_GRAPH_BYTES,
            "HISTORICAL_VERSION_GRAPH",
            "Version graph",
        )
    except BoundedJsonInputError as error:
        emit_input_error(error.code, str(error))
        return 1
    try:
        selection = select_historical_version_candidate(
            graph,
            args.event_date,
            country=args.country,
            province=args.province,
        )
    except HistoricalVersionError as error:
        emit_input_error(error.code, str(error))
        return 2
    print(json.dumps(selection, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
