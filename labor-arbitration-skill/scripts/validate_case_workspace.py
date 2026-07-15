#!/usr/bin/env python3
"""Replay-validate a migrated or restored local content-addressed case workspace."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from case_workspace import MAX_WORKSPACE_MANIFEST_BYTES, validate_case_workspace  # noqa: E402
from bounded_json_input import (  # noqa: E402
    BoundedJsonInputError,
    load_bounded_json_object,
)
from validate_case_package import (  # noqa: E402
    configure_utf8_stdio,
    emit_input_error,
)


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    args = parser.parse_args()
    manifest_path = args.workspace / "workspace.json"
    try:
        workspace = load_bounded_json_object(
            manifest_path,
            MAX_WORKSPACE_MANIFEST_BYTES,
            "CASE_WORKSPACE_MANIFEST",
            "Workspace manifest",
        )
    except BoundedJsonInputError as error:
        emit_input_error(error.code, str(error))
        return 1
    report = validate_case_workspace(workspace, args.workspace)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["allowed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
