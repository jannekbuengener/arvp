"""Canonical JSON serialization and SHA-256 identities (v2).

The representation is deliberately small and stable: mapping keys are sorted,
dictionary values that are None are preserved as null, and list/tuple positions
are preserved. It is suitable for reproducible artifacts and fingerprints;
it is not a general-purpose object serializer.

Contract version: arvp.canonical.v2
"""

from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal
from typing import Any

CANONICAL_CONTRACT_VERSION = "arvp.canonical.v2"


class CanonicalizationError(ValueError):
    """Raised when a value cannot be represented in canonical JSON."""


class FingerprintFormatError(ValueError):
    """Raised when a fingerprint string violates the canonical format."""


def _has_surrogate_chars(s: str) -> bool:
    """Check if string contains surrogate codepoints (U+D800–U+DFFF)."""
    return any(0xD800 <= ord(ch) <= 0xDFFF for ch in s)


def _validate_string(value: str, context: str) -> None:
    """Validate string has no surrogate codepoints."""
    if _has_surrogate_chars(value):
        raise CanonicalizationError(f"{context}: string contains surrogate codepoints")


def _decimal_canonical(value: Decimal) -> dict:
    """Return the $arvp decimal extension for a finite Decimal.

    Uses Decimal.as_tuple() only - no context operations, no normalize().
    """
    if not value.is_finite():
        raise CanonicalizationError("non-finite Decimal not allowed")

    sign, digits, exponent = value.as_tuple()

    # After is_finite() check, exponent is guaranteed to be int
    assert isinstance(exponent, int), "exponent must be int for finite Decimal"

    # Zero: single canonical form
    if not any(digits):
        return {"$arvp": {"coefficient": "0", "exponent": 0, "type": "decimal"}}

    # Remove trailing zeros from coefficient
    i = len(digits) - 1
    while i > 0 and digits[i] == 0:
        i -= 1
    coeff_digits = digits[: i + 1]

    # Adjust exponent for removed trailing zeros
    removed = len(digits) - len(coeff_digits)
    exponent += removed

    # Coefficient as string (no sign yet)
    coeff_str = "".join(str(d) for d in coeff_digits)

    # Apply sign
    if sign:
        coeff_str = "-" + coeff_str

    return {
        "$arvp": {"coefficient": coeff_str, "exponent": exponent, "type": "decimal"}
    }


def _canonicalize_float(value: float) -> float:
    """Canonicalize a finite float: collapse -0.0 to 0.0, reject non-finite."""
    if not math.isfinite(value):
        raise CanonicalizationError("non-finite float not allowed")
    return 0.0 if value == 0.0 else value  # -0.0 -> 0.0


def canonicalize(value: Any, _active_ids: set[int] | None = None) -> Any:
    """Return the JSON-safe canonical form of ``value``.

    This is an internal implementation detail. Public API is canonical_json_dumps
    and canonical_hash.
    """
    if _active_ids is None:
        _active_ids = set()

    obj_id = id(value)
    if obj_id in _active_ids:
        raise CanonicalizationError("cyclic reference detected")

    # None
    if value is None:
        return None

    # bool (must check before int since bool is subclass of int)
    if type(value) is bool:
        return value

    # int (exact type, not isinstance)
    if type(value) is int:
        return value

    # float
    if type(value) is float:
        return _canonicalize_float(value)

    # Decimal
    if type(value) is Decimal:
        return _decimal_canonical(value)

    # str
    if type(value) is str:
        _validate_string(value, "string value")
        return value

    # dict (exact type)
    if type(value) is dict:
        _active_ids.add(obj_id)
        try:
            # Validate all keys first
            for key in value.keys():
                if type(key) is not str:
                    raise CanonicalizationError("mapping keys must be strings")
                _validate_string(key, "mapping key")
                if key == "$arvp":
                    raise CanonicalizationError("reserved key '$arvp' not allowed")

            # Recursively canonicalize values (preserve nulls)
            result = {}
            for k, v in value.items():
                result[k] = canonicalize(v, _active_ids)
            return result
        finally:
            _active_ids.remove(obj_id)

    # list (exact type)
    if type(value) is list:
        _active_ids.add(obj_id)
        try:
            return [canonicalize(item, _active_ids) for item in value]
        finally:
            _active_ids.remove(obj_id)

    # tuple (exact type) - portable sequence, same as list
    if type(value) is tuple:
        _active_ids.add(obj_id)
        try:
            return [canonicalize(item, _active_ids) for item in value]
        finally:
            _active_ids.remove(obj_id)

    raise CanonicalizationError(
        f"unsupported canonical JSON type: {type(value).__name__}"
    )


def canonical_json_dumps(value: Any) -> str:
    """Serialize ``value`` to compact, sorted, UTF-8-safe canonical JSON."""
    canonical_value = canonicalize(value)
    return json.dumps(
        canonical_value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _fingerprint_domain_separator() -> bytes:
    return CANONICAL_CONTRACT_VERSION.encode("ascii") + b"\x00"


def canonical_hash(value: Any) -> str:
    """Return the SHA-256 identity of a canonical JSON value."""
    canonical_bytes = canonical_json_dumps(value).encode("utf-8")
    return hashlib.sha256(_fingerprint_domain_separator() + canonical_bytes).hexdigest()


def validate_fingerprint(value: object, field: str = "fingerprint") -> str:
    """Validate a fingerprint string.

    Accepts only:
    - str
    - exactly 64 characters
    - lowercase hex (0-9a-f)
    - no whitespace
    - no prefix
    """
    if not isinstance(value, str):
        raise FingerprintFormatError(
            f"{field}: must be str, got {type(value).__name__}"
        )
    if len(value) != 64:
        raise FingerprintFormatError(f"{field}: must be 64 chars, got {len(value)}")
    if not all(c in "0123456789abcdef" for c in value):
        raise FingerprintFormatError(f"{field}: must be lowercase hex only")
    return value
