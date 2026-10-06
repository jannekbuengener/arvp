"""Golden fixture loader and source reconstruction for ARVP canonical v2.

This module is a test/validation helper and must NOT import arvp.canonical.
It is used by both unit tests (from repo root) and platform_smoke.py (from tools/).
"""

import json
from decimal import Decimal
from enum import IntEnum
from pathlib import Path
from typing import Any

FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "fixtures"
    / "canonical_v2_golden.json"
)


def load_golden_vectors() -> list[dict]:
    """Load and return the list of golden vector descriptors."""
    with FIXTURE_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)
    # Ensure contract version matches
    if data.get("contract_version") != "arvp.canonical.v2":
        raise ValueError(
            f"Fixture contract_version mismatch: {data.get('contract_version')}"
        )
    vectors = data.get("vectors")
    if not isinstance(vectors, list):
        raise ValueError("fixture 'vectors' must be a list")
    for descriptor in vectors:
        validate_descriptor(descriptor)
    return vectors


def validate_descriptor(desc: dict) -> None:
    """Strictly validate a single descriptor.

    Raises ValueError for any violation.
    """
    if not isinstance(desc, dict):
        raise ValueError("descriptor must be a dict")

    if "name" not in desc:
        raise ValueError("descriptor missing 'name'")
    if not isinstance(desc["name"], str) or not desc["name"]:
        raise ValueError("descriptor 'name' must be non-empty string")

    if "source" not in desc:
        raise ValueError(f"descriptor {desc['name']}: missing 'source'")
    source = desc["source"]
    if not isinstance(source, dict):
        raise ValueError(f"descriptor {desc['name']}: source must be a dict")
    if "kind" not in source:
        raise ValueError(f"descriptor {desc['name']}: source missing 'kind'")
    kind = source["kind"]
    if not isinstance(kind, str) or not kind:
        raise ValueError(
            f"descriptor {desc['name']}: source kind must be non-empty string"
        )

    # Validate kind-specific source shape with no silent extra fields.
    if kind in {"json", "decimal"}:
        required_source_keys = {"kind", "text"}
        if "text" not in source:
            raise ValueError(f"descriptor {desc['name']}: {kind} source missing 'text'")
        if not isinstance(source["text"], str):
            raise ValueError(f"descriptor {desc['name']}: {kind} text must be string")
    elif kind == "tuple":
        required_source_keys = {"kind", "items"}
        if "items" not in source:
            raise ValueError(f"descriptor {desc['name']}: tuple source missing 'items'")
        if not isinstance(source["items"], list):
            raise ValueError(f"descriptor {desc['name']}: tuple items must be list")
    elif kind in (
        "float_pos_zero",
        "float_neg_zero",
        "float_nan",
        "float_pos_inf",
        "float_neg_inf",
        "decimal_nan",
        "decimal_pos_inf",
        "decimal_neg_inf",
        "non_string_key",
        "int_enum",
        "dict_subclass",
        "list_subclass",
        "unsupported_set",
        "lone_high_surrogate",
        "lone_low_surrogate",
        "surrogate_in_mapping_key",
        "cycle_list",
        "cycle_dict",
        "shared_acyclic_reference",
    ):
        required_source_keys = {"kind"}
    else:
        raise ValueError(f"descriptor {desc['name']}: unknown source kind '{kind}'")

    source_extra = set(source) - required_source_keys
    if source_extra:
        raise ValueError(
            f"descriptor {desc['name']}: source has unexpected fields: {sorted(source_extra)}"
        )

    # Exactly one of expected_json or expect_error must be present
    has_expected = "expected_json" in desc
    has_error = "expect_error" in desc
    if has_expected == has_error:
        raise ValueError(
            f"descriptor {desc['name']}: must have exactly one of 'expected_json' or 'expect_error'"
        )
    if has_expected:
        if not isinstance(desc["expected_json"], str):
            raise ValueError(f"descriptor {desc['name']}: expected_json must be string")
        fingerprint = desc.get("expected_fingerprint")
        if not isinstance(fingerprint, str):
            raise ValueError(
                f"descriptor {desc['name']}: expected_fingerprint must be present for positive vectors"
            )
        if len(fingerprint) != 64 or any(
            c not in "0123456789abcdef" for c in fingerprint
        ):
            raise ValueError(
                f"descriptor {desc['name']}: expected_fingerprint must be 64 lowercase hex chars"
            )
    if has_error:
        if desc["expect_error"] != "CanonicalizationError":
            raise ValueError(
                f"descriptor {desc['name']}: expect_error must be CanonicalizationError"
            )
        if "expected_fingerprint" in desc:
            raise ValueError(
                f"descriptor {desc['name']}: negative vectors cannot define expected_fingerprint"
            )

    # No extra fields allowed beyond the contract
    allowed_keys = {
        "name",
        "source",
        "expected_json",
        "expect_error",
        "expected_fingerprint",
    }
    extra = set(desc.keys()) - allowed_keys
    if extra:
        raise ValueError(
            f"descriptor {desc['name']}: unexpected fields: {sorted(extra)}"
        )


def reconstruct_source(source_or_desc: dict) -> Any:
    """Reconstruct the actual Python object from a source descriptor or source dict.

    Accepts either:
    - Full descriptor dict with "source" key
    - Source dict directly (with "kind" key)
    """
    if "source" in source_or_desc:
        source = source_or_desc["source"]
    else:
        source = source_or_desc
    kind = source["kind"]

    if kind == "json":
        return json.loads(source["text"])
    if kind == "decimal":
        return Decimal(source["text"])
    if kind == "tuple":
        return tuple(source["items"])
    if kind == "float_pos_zero":
        return 0.0
    if kind == "float_neg_zero":
        return -0.0
    if kind == "float_nan":
        return float("nan")
    if kind == "float_pos_inf":
        return float("inf")
    if kind == "float_neg_inf":
        return float("-inf")
    if kind == "decimal_nan":
        return Decimal("NaN")
    if kind == "decimal_pos_inf":
        return Decimal("Infinity")
    if kind == "decimal_neg_inf":
        return Decimal("-Infinity")
    if kind == "non_string_key":
        return {1: "x"}
    if kind == "int_enum":
        return IntEnum("E", {"A": 1}).A
    if kind == "dict_subclass":
        return type("D", (dict,), {})({"a": 1})
    if kind == "list_subclass":
        return type("L", (list,), {})([1, 2])
    if kind == "unsupported_set":
        return {1, 2}
    if kind == "lone_high_surrogate":
        return "\ud800"
    if kind == "lone_low_surrogate":
        return "\udfff"
    if kind == "surrogate_in_mapping_key":
        return {"\ud800": "x"}
    if kind == "cycle_list":
        x = []
        x.append(x)
        return x
    if kind == "cycle_dict":
        d = {}
        d["self"] = d
        return d
    if kind == "shared_acyclic_reference":
        shared = {"x": 1}
        return [shared, shared]

    raise ValueError(f"unknown descriptor kind: {kind}")


def validate_all_descriptors() -> None:
    """Validate all descriptors in the fixture file."""
    vectors = load_golden_vectors()
    for vec in vectors:
        validate_descriptor(vec)
