"""Versioned JSON Schema assets shipped with the ARVP wheel."""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

SCHEMA_ASSET_NAMES = (
    "evidence_bundle_v1.json",
    "evaluation_input_v1.json",
    "evaluation_suite_v1.json",
    "metric_observation_v1.json",
)


class SchemaAssetError(LookupError):
    """Raised when a packaged schema asset cannot be loaded."""


def schema_path(name: str) -> Any:
    """Return an importlib.resources path handle for a schema asset."""
    if name not in SCHEMA_ASSET_NAMES:
        raise SchemaAssetError(f"unknown schema asset: {name!r}")
    root = resources.files("arvp.schemas")
    path = root.joinpath(name)
    if not path.is_file():
        raise SchemaAssetError(f"schema asset missing from package: {name}")
    return path


def load_schema(name: str) -> dict[str, Any]:
    """Load a packaged JSON Schema document by asset filename."""
    path = schema_path(name)
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise SchemaAssetError(f"schema asset must be a JSON object: {name}")
    return payload
