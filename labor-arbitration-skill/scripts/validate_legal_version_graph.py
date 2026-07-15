#!/usr/bin/env python3
"""Validate an unverified legal-source version candidate graph."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from legal_version_graph_policy import validate_legal_version_graph  # noqa: E402
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
    args = parser.parse_args()
    try:
        graph = load_bounded_json_object(
            args.graph, MAX_GRAPH_BYTES, "LEGAL_GRAPH_INPUT", "Legal version graph"
        )
    except BoundedJsonInputError as error:
        emit_input_error(error.code, str(error))
        return 1
    report = validate_legal_version_graph(graph)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["allowed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
