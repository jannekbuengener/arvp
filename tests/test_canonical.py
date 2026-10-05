from __future__ import annotations

from decimal import Decimal

import pytest

from arvp.canonical import CanonicalizationError, canonical_hash, canonical_json_dumps


def test_canonical_hash_is_stable_across_mapping_order() -> None:
    left = {"b": 2, "a": {"missing": None, "value": 1.0}}
    right = {"a": {"value": 1.0, "missing": None}, "b": 2}

    assert canonical_json_dumps(left) == '{"a":{"value":1.0},"b":2}'
    assert canonical_hash(left) == canonical_hash(right)


def test_canonical_serialization_preserves_list_positions_and_normalizes_decimals() -> None:
    value = {"values": [None, Decimal("2.500"), -0.0]}

    assert canonical_json_dumps(value) == '{"values":[null,"2.5",0.0]}'


def test_canonicalization_fails_closed_for_unknown_types() -> None:
    with pytest.raises(CanonicalizationError, match="unsupported"):
        canonical_json_dumps({"set": {1, 2}})
