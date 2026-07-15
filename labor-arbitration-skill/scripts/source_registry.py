"""Load the reviewed official-source candidate registry fail-closed."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema


REFERENCE_DIRECTORY = Path(__file__).resolve().parents[1] / "references"
REGISTRY_PATH = REFERENCE_DIRECTORY / "official-source-registry.json"
REGISTRY_SCHEMA_PATH = REFERENCE_DIRECTORY / "official-source-registry.schema.json"


class SourceRegistryError(ValueError):
    pass


def load_source_registry() -> dict[str, dict]:
    try:
        schema = json.loads(REGISTRY_SCHEMA_PATH.read_text(encoding="utf-8"))
        registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.Draft202012Validator(
            schema, format_checker=jsonschema.FormatChecker()
        ).validate(registry)
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        jsonschema.SchemaError,
        jsonschema.ValidationError,
    ) as error:
        raise SourceRegistryError("Official-source registry is unavailable or invalid.") from error

    entries = {}
    seen_hosts = {}
    for entry in registry["entries"]:
        publisher_code = entry["publisher_code"]
        if publisher_code in entries:
            raise SourceRegistryError(f"Duplicate publisher code: {publisher_code}")
        for host in entry["hosts"]:
            owner = seen_hosts.get(host)
            if owner is not None and owner != publisher_code:
                raise SourceRegistryError(
                    f"Official host {host} is assigned to multiple publishers."
                )
            seen_hosts[host] = publisher_code
        entries[publisher_code] = entry
    return entries


try:
    OFFICIAL_SOURCE_REGISTRY = load_source_registry()
except SourceRegistryError:
    OFFICIAL_SOURCE_REGISTRY = {}


def registry_entry(publisher_code: str) -> dict | None:
    return OFFICIAL_SOURCE_REGISTRY.get(publisher_code)
