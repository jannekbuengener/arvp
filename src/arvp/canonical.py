"""Canonical JSON serialization and SHA-256 identities.

The representation is deliberately small and stable: mapping keys are sorted,
dictionary values that normalize to ``None`` are omitted, and list positions
are preserved. It is suitable for reproducible artifacts and fingerprints;
it is not a general-purpose object serializer.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from typing import Any


class CanonicalizationError(ValueError):
    """Raised when a value cannot be represented in canonical JSON."""


def _decimal_text(value: Decimal) -> str | None:
    if not value.is_finite():
        return None
    try:
        text = format(value.normalize(), "f")
    except (InvalidOperation, ValueError) as exc:
        raise CanonicalizationError("decimal cannot be normalized") from exc
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in {"", "-0", "+0"}:
        return "0"
    return text


def canonicalize(value: Any) -> Any:
    """Return the JSON-safe canonical form of ``value``.

    Decimal values are represented as normalized strings so no binary floating
    point conversion changes an evidence artifact. Non-finite floats and
    Decimals normalize to ``None``.
    """
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, Decimal):
        return _decimal_text(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        rounded = round(value, 10)
        return 0.0 if rounded == 0.0 else rounded
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalizationError("mapping keys must be strings")
            normalized = canonicalize(item)
            if normalized is not None:
                result[key] = normalized
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [canonicalize(item) for item in value]
    raise CanonicalizationError(
        f"unsupported canonical JSON type: {type(value).__name__}"
    )


def canonical_json_dumps(value: Any) -> str:
    """Serialize ``value`` to compact, sorted, UTF-8-safe canonical JSON."""
    return json.dumps(
        canonicalize(value),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def sha256_hex(data: bytes) -> str:
    """Return the lowercase SHA-256 digest for raw bytes."""
    return hashlib.sha256(data).hexdigest()


def canonical_hash(value: Any) -> str:
    """Return the SHA-256 identity of a canonical JSON value."""
    return sha256_hex(canonical_json_dumps(value).encode("utf-8"))
