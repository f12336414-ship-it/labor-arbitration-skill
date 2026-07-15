#!/usr/bin/env python3
"""Create a local content-addressed case workspace from a v1.3 intake manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from case_workspace import CaseWorkspaceError, create_case_workspace  # noqa: E402
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
    parser.add_argument("source", type=Path)
    parser.add_argument("intake_manifest", type=Path)
    parser.add_argument("workspace", type=Path)
    args = parser.parse_args()
    try:
        manifest = load_bounded_json_object(
            args.intake_manifest,
            10 * 1024 * 1024,
            "CASE_WORKSPACE_INTAKE",
            "Intake manifest",
        )
    except BoundedJsonInputError as error:
        emit_input_error(error.code, str(error))
        return 1
    try:
        manifest_path, workspace = create_case_workspace(
            args.source, manifest, args.workspace
        )
    except CaseWorkspaceError as error:
        emit_input_error(error.code, str(error))
        return 2
    print(
        json.dumps(
            {
                "allowed": True,
                "allowed_scope": "LOCAL_CASE_WORKSPACE_CREATION_ONLY",
                "manifest_path": manifest_path.name,
                "submission_ready": False,
                "workspace_id": workspace["workspace_id"],
                "workspace_snapshot_sha256": workspace["workspace_snapshot_sha256"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
