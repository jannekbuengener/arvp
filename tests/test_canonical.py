from __future__ import annotations

import json
from decimal import Decimal
from enum import IntEnum

import pytest

from arvp.canonical import (
    CANONICAL_CONTRACT_VERSION,
    CanonicalizationError,
    FingerprintFormatError,
    canonical_hash,
    canonical_json_dumps,
    validate_fingerprint,
)
from tools.canonical_v2_golden import (
    FIXTURE_PATH,
    load_golden_vectors,
    reconstruct_source,
    validate_all_descriptors,
    validate_descriptor,
)


def test_fixture_contract_version_matches() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert CANONICAL_CONTRACT_VERSION == fixture["contract_version"]


def test_fixture_descriptors_are_valid() -> None:
    validate_all_descriptors()


@pytest.mark.parametrize("vec", load_golden_vectors())
def test_canonical_v2_golden(vec: dict) -> None:
    source = reconstruct_source(vec)
    if "expect_error" in vec:
        with pytest.raises(CanonicalizationError):
            canonical_json_dumps(source)
    else:
        assert canonical_json_dumps(source) == vec["expected_json"]
        assert canonical_hash(source) == vec["expected_fingerprint"]


def test_identity_matrix_collisions_and_distinctions() -> None:
    # int vs float
    assert canonical_hash(1) != canonical_hash(1.0)
    # int vs Decimal
    assert canonical_hash(1) != canonical_hash(Decimal("1"))
    # float vs Decimal
    assert canonical_hash(1.0) != canonical_hash(Decimal("1"))
    # str vs Decimal
    assert canonical_hash("1") != canonical_hash(Decimal("1"))
    # bool vs int
    assert canonical_hash(True) != canonical_hash(1)
    assert canonical_hash(False) != canonical_hash(0)
    # float signed zero collapsed
    assert canonical_hash(0.0) == canonical_hash(-0.0)
    # Decimal signed zero collapsed
    assert canonical_hash(Decimal("0")) == canonical_hash(Decimal("-0"))
    # Decimal value identity
    assert canonical_hash(Decimal("1")) == canonical_hash(Decimal("1.00"))
    assert canonical_hash(Decimal("0.10")) == canonical_hash(Decimal("0.100"))
    # list vs tuple same portable sequence identity
    assert canonical_hash([1, 2]) == canonical_hash((1, 2))
    # explicit null vs missing
    assert canonical_hash({"x": None}) != canonical_hash({})


def test_validate_fingerprint_strict() -> None:
    fp = "a" * 64
    assert validate_fingerprint(fp) == fp

    with pytest.raises(FingerprintFormatError, match="must be str"):
        validate_fingerprint(123)
    with pytest.raises(FingerprintFormatError, match="must be str"):
        validate_fingerprint(None)
    with pytest.raises(FingerprintFormatError, match="64 chars"):
        validate_fingerprint("short")
    with pytest.raises(FingerprintFormatError, match="lowercase hex"):
        validate_fingerprint("A" * 64)
    with pytest.raises(FingerprintFormatError, match="lowercase hex"):
        validate_fingerprint("g" * 64)
    with pytest.raises(FingerprintFormatError, match="lowercase hex"):
        validate_fingerprint(" " + "a" * 63)
    with pytest.raises(FingerprintFormatError, match="64 chars"):
        validate_fingerprint("sha256:" + "a" * 58)


def test_fingerprint_format_error_is_value_error() -> None:
    assert issubclass(FingerprintFormatError, ValueError)


def test_canonical_contract_version_constant() -> None:
    assert CANONICAL_CONTRACT_VERSION == "arvp.canonical.v2"


def test_intenum_rejected() -> None:
    class MyEnum(IntEnum):
        A = 1

    with pytest.raises(CanonicalizationError):
        canonical_json_dumps(MyEnum.A)


def test_dict_subclass_rejected() -> None:
    class MyDict(dict):
        pass

    with pytest.raises(CanonicalizationError):
        canonical_json_dumps(MyDict({"a": 1}))


def test_list_subclass_rejected() -> None:
    class MyList(list):
        pass

    with pytest.raises(CanonicalizationError):
        canonical_json_dumps(MyList([1, 2]))


def test_set_rejected() -> None:
    with pytest.raises(CanonicalizationError):
        canonical_json_dumps({1, 2})


def test_reserved_namespace_rejected() -> None:
    with pytest.raises(CanonicalizationError):
        canonical_json_dumps({"$arvp": "user"})
    with pytest.raises(CanonicalizationError):
        canonical_json_dumps({"nested": {"$arvp": {}}})


def test_surrogate_rejection() -> None:
    with pytest.raises(CanonicalizationError):
        canonical_json_dumps("\ud800")
    with pytest.raises(CanonicalizationError):
        canonical_json_dumps("\udfff")
    with pytest.raises(CanonicalizationError):
        canonical_json_dumps({"\ud800": "x"})


def test_cycle_detection() -> None:
    x = []
    x.append(x)
    with pytest.raises(CanonicalizationError, match="cyclic"):
        canonical_json_dumps(x)

    d = {}
    d["self"] = d
    with pytest.raises(CanonicalizationError, match="cyclic"):
        canonical_json_dumps(d)


def test_shared_acyclic_reference_allowed() -> None:
    shared = {"x": 1}
    value = [shared, shared]
    # Should not raise
    result = canonical_json_dumps(value)
    assert result == '[{"x":1},{"x":1}]'


def test_null_preserved_not_filtered() -> None:
    result = canonical_json_dumps({"x": None})
    assert result == '{"x":null}'


def test_float_nonfinite_rejected() -> None:
    with pytest.raises(CanonicalizationError):
        canonical_json_dumps(float("nan"))
    with pytest.raises(CanonicalizationError):
        canonical_json_dumps(float("inf"))
    with pytest.raises(CanonicalizationError):
        canonical_json_dumps(float("-inf"))


def test_decimal_nonfinite_rejected() -> None:
    with pytest.raises(CanonicalizationError):
        canonical_json_dumps(Decimal("NaN"))
    with pytest.raises(CanonicalizationError):
        canonical_json_dumps(Decimal("Infinity"))
    with pytest.raises(CanonicalizationError):
        canonical_json_dumps(Decimal("-Infinity"))


def test_float_no_rounding_collision() -> None:
    # These must have different fingerprints (no 10-digit rounding)
    assert canonical_hash(0.12345678901) != canonical_hash(0.12345678902)
    assert canonical_hash(1.234567890123456) != canonical_hash(1.234567890123457)


def test_decimal_coefficient_format() -> None:
    # Negative coefficient has minus sign, no "-0"
    import json

    d1 = canonical_json_dumps(Decimal("-123.4500"))
    parsed = json.loads(d1)
    assert parsed["$arvp"]["coefficient"] == "-12345"
    assert parsed["$arvp"]["exponent"] == -2

    d0 = canonical_json_dumps(Decimal("-0"))
    parsed0 = json.loads(d0)
    assert parsed0["$arvp"]["coefficient"] == "0"
    assert parsed0["$arvp"]["exponent"] == 0


def test_decimal_extension_keys_sorted() -> None:
    # Keys must be sorted: coefficient, exponent, type
    d = canonical_json_dumps(Decimal("1"))
    # The $arvp object keys must be in lexicographic order
    assert d == '{"$arvp":{"coefficient":"1","exponent":0,"type":"decimal"}}'


def test_revive_canonical_round_trips_decimal_extensions() -> None:
    import json

    from arvp.canonical import revive_canonical

    source = {
        "score": Decimal("0.900"),
        "nested": [{"delta": Decimal("-1.25")}, None],
    }
    parsed = json.loads(canonical_json_dumps(source))
    revived = revive_canonical(parsed)
    assert revived["score"] == Decimal("0.9")
    assert revived["nested"][0]["delta"] == Decimal("-1.25")
    assert canonical_hash(source) == canonical_hash(revived)


def test_decimal_subclass_rejected() -> None:
    class DecimalSubclass(Decimal):
        pass

    with pytest.raises(CanonicalizationError):
        canonical_json_dumps(DecimalSubclass("1"))


def test_golden_descriptor_rejects_extra_source_fields() -> None:
    descriptor = {
        "name": "bad-extra-source",
        "source": {"kind": "json", "text": "{}", "extra": True},
        "expected_json": "{}",
        "expected_fingerprint": "a" * 64,
    }
    with pytest.raises(ValueError, match="source.*unexpected"):
        validate_descriptor(descriptor)


def test_golden_descriptor_positive_requires_fingerprint() -> None:
    descriptor = {
        "name": "missing-fingerprint",
        "source": {"kind": "json", "text": "{}"},
        "expected_json": "{}",
    }
    with pytest.raises(ValueError, match="expected_fingerprint"):
        validate_descriptor(descriptor)
