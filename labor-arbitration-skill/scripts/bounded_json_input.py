"""Shared bounded, stable, strict JSON-object input boundary for local CLIs."""

from __future__ import annotations

import json
from pathlib import Path

from validate_case_package import (
    DuplicateKeyError,
    InputTooLargeError,
    InvalidJsonConstantError,
    read_stable_utf8,
    reject_duplicate_keys,
    reject_json_constant,
)


class BoundedJsonInputError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def load_bounded_json_object(
    path: Path,
    maximum_bytes: int,
    code_prefix: str,
    label: str,
) -> dict:
    try:
        raw_input = read_stable_utf8(path, maximum_bytes)
    except InputTooLargeError as error:
        raise BoundedJsonInputError(
            f"{code_prefix}_TOO_LARGE", f"{label} exceeds its byte limit."
        ) from error
    except (OSError, UnicodeError) as error:
        raise BoundedJsonInputError(
            f"{code_prefix}_UNREADABLE", str(error)
        ) from error
    try:
        value = json.loads(
            raw_input,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_json_constant,
        )
    except DuplicateKeyError as error:
        raise BoundedJsonInputError(
            f"{code_prefix}_DUPLICATE_KEY", str(error)
        ) from error
    except InvalidJsonConstantError as error:
        raise BoundedJsonInputError(
            f"{code_prefix}_INVALID_CONSTANT", str(error)
        ) from error
    except json.JSONDecodeError as error:
        raise BoundedJsonInputError(
            f"{code_prefix}_INVALID_JSON",
            f"Invalid JSON at line {error.lineno}, column {error.colno}.",
        ) from error
    except RecursionError as error:
        raise BoundedJsonInputError(
            f"{code_prefix}_TOO_DEEPLY_NESTED", f"{label} nesting is unsafe."
        ) from error
    if not isinstance(value, dict):
        raise BoundedJsonInputError(
            f"{code_prefix}_ROOT_NOT_OBJECT", f"{label} root must be an object."
        )
    return value
