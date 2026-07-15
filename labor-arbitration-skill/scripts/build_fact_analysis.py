#!/usr/bin/env python3
"""Build a deterministic local structured-fact conflict and invalidation record."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bounded_json_input import BoundedJsonInputError, load_bounded_json_object
from fact_analysis_policy import FactAnalysisError, build_fact_analysis


MAX_SPECIFICATION_BYTES = 32 * 1024 * 1024


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("specification", type=Path)
    args = parser.parse_args()
    try:
        specification = load_bounded_json_object(
            args.specification,
            MAX_SPECIFICATION_BYTES,
            "FACT_ANALYSIS_INPUT",
            "Fact analysis specification",
        )
        record = build_fact_analysis(specification)
    except (BoundedJsonInputError, FactAnalysisError) as error:
        code = getattr(error, "code", "FACT_ANALYSIS_INPUT_INVALID")
        print(json.dumps({"error": {"code": code, "message": str(error)}}, ensure_ascii=False))
        return 2
    print(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
