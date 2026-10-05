"""Domain-independent dataset request and content identities."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from arvp.canonical import canonical_hash

CONTENT_IDENTITY_SCHEMA_VERSION = "arvp.dataset-content.v1"
_FORBIDDEN_EVIDENCE_KEYS = frozenset(
    {
        "api_key",
        "api_secret",
        "authorization",
        "connection_string",
        "database_url",
        "dsn",
        "file_path",
        "password",
        "path",
        "secret",
        "token",
    }
)


class DatasetIdentityError(ValueError):
    """Raised when a dataset identity is malformed or unsafe."""


def _require_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DatasetIdentityError(f"{field} must be a non-empty string")
    return value.strip()


def forbidden_evidence_keys(value: Any) -> tuple[str, ...]:
    """Find key names that must never occur in portable evidence."""
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, Mapping):
            for key, item in node.items():
                key_text = str(key)
                if key_text.casefold() in _FORBIDDEN_EVIDENCE_KEYS:
                    found.add(key_text)
                walk(item)
        elif isinstance(node, Sequence) and not isinstance(
            node, (str, bytes, bytearray)
        ):
            for item in node:
                walk(item)

    walk(value)
    return tuple(sorted(found))


def assert_evidence_safe(value: Any) -> None:
    """Fail closed when evidence could include a path, secret, or DSN."""
    forbidden = forbidden_evidence_keys(value)
    if forbidden:
        raise DatasetIdentityError(
            "evidence contains forbidden key names: " + ", ".join(forbidden)
        )


def _normalize_content_value(value: Any) -> Any:
    """Normalize Decimal values to the same numeric route as JSON floats."""
    if isinstance(value, Decimal):
        if not value.is_finite():
            return None
        try:
            return float(format(value.normalize(), "f"))
        except (InvalidOperation, ValueError, OverflowError) as exc:
            raise DatasetIdentityError("decimal field cannot be normalized") from exc
    if isinstance(value, Mapping):
        return {str(key): _normalize_content_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_normalize_content_value(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class DatasetRequest:
    """A portable description of what data was requested, never where it lived."""

    dataset_id: str
    revision: str
    parameters: Mapping[str, Any]

    def __post_init__(self) -> None:
        _require_text(self.dataset_id, "dataset_id")
        _require_text(self.revision, "revision")
        if not isinstance(self.parameters, Mapping):
            raise DatasetIdentityError("parameters must be a mapping")
        copied = {
            str(key): _normalize_content_value(value)
            for key, value in self.parameters.items()
        }
        assert_evidence_safe(copied)
        object.__setattr__(self, "parameters", copied)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "parameters": dict(self.parameters),
            "revision": self.revision,
        }

    def fingerprint(self) -> str:
        return canonical_hash(self.to_dict())


@dataclass(frozen=True, slots=True)
class DatasetContentIdentity:
    """Versioned identity of selected, loaded content rather than its location."""

    schema_version: str
    record_count: int
    fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "record_count": self.record_count,
            "schema_version": self.schema_version,
        }


def identify_content(
    records: Sequence[Mapping[str, Any]],
    *,
    fields: Sequence[str],
    order_by: str | None = None,
    schema_version: str = CONTENT_IDENTITY_SCHEMA_VERSION,
) -> DatasetContentIdentity:
    """Fingerprint explicitly selected record fields.

    Callers choose the portable semantic fields. This prevents an accidental
    path, credential, provider-specific metadata, or unrelated field from
    entering the identity. ``order_by`` makes record order provider-neutral.
    """
    _require_text(schema_version, "schema_version")
    if not records:
        raise DatasetIdentityError("records must not be empty")
    selected_fields = tuple(_require_text(field, "field") for field in fields)
    if not selected_fields or len(set(selected_fields)) != len(selected_fields):
        raise DatasetIdentityError(
            "fields must be a non-empty sequence of unique strings"
        )
    assert_evidence_safe({field: None for field in selected_fields})
    if order_by is not None and order_by not in selected_fields:
        raise DatasetIdentityError("order_by must be one of fields")

    selected_records: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            raise DatasetIdentityError(f"record {index} must be a mapping")
        missing = [field for field in selected_fields if field not in record]
        if missing:
            raise DatasetIdentityError(
                f"record {index} is missing selected field(s): {', '.join(missing)}"
            )
        selected_records.append(
            {
                field: _normalize_content_value(record[field])
                for field in selected_fields
            }
        )

    if order_by is not None:
        selected_records.sort(
            key=lambda record: (str(record[order_by]), canonical_hash(record))
        )

    payload = {"records": selected_records, "schema_version": schema_version}
    assert_evidence_safe(payload)
    return DatasetContentIdentity(
        schema_version=schema_version,
        record_count=len(selected_records),
        fingerprint=canonical_hash(payload),
    )
