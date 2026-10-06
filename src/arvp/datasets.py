"""Domain-independent dataset request and content identities."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from arvp.canonical import (
    CanonicalizationError,
    canonical_hash,
    canonical_json_dumps,
)
from arvp.evidence import (
    PortableEvidenceError,
    validate_portable_metadata,
)

CONTENT_IDENTITY_SCHEMA_VERSION = "arvp.dataset-content.v1"


class DatasetIdentityError(ValueError):
    """Raised when a dataset identity is malformed or unsafe."""


def _require_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DatasetIdentityError(f"{field} must be a non-empty string")
    return value.strip()


def assert_evidence_safe(value: Any) -> None:
    """Fail closed when evidence could include a path, secret, or DSN.

    Delegates to the shared portable evidence boundary.
    """
    try:
        validate_portable_metadata(value)
    except PortableEvidenceError as exc:
        raise DatasetIdentityError(str(exc)) from exc


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

        # Validate keys: exact str, not "$arvp"
        for key in self.parameters.keys():
            if type(key) is not str:
                raise DatasetIdentityError("parameter keys must be strings")
            if key == "$arvp":
                raise DatasetIdentityError(r"reserved key '\$arvp' not allowed")

        # Copy original portable values
        copied = dict(self.parameters)

        # Evidence safety (shared boundary)
        assert_evidence_safe(copied)

        # Canonicalizability check (fails if any value not portable)
        try:
            canonical_json_dumps(copied)
        except CanonicalizationError as exc:
            raise DatasetIdentityError(
                f"parameters not canonicalizable: {exc}"
            ) from exc

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

    The ``order_by`` field uses canonical JSON total order as identity sort key,
    not numeric/lexical order. This ensures provider-neutral deterministic
    fingerprints. Example: ``1``, ``2``, ``10`` sort as ``1``, ``10``, ``2``
    (JSON string order).
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
        selected_records.append({field: record[field] for field in selected_fields})

    try:
        if order_by is not None:
            selected_records.sort(
                key=lambda record: (
                    canonical_json_dumps(record[order_by]),
                    canonical_hash(record),
                )
            )

        payload = {"records": selected_records, "schema_version": schema_version}
        assert_evidence_safe(payload)
        fingerprint = canonical_hash(payload)
    except CanonicalizationError as exc:
        raise DatasetIdentityError(f"content not canonicalizable: {exc}") from exc

    return DatasetContentIdentity(
        schema_version=schema_version,
        record_count=len(selected_records),
        fingerprint=fingerprint,
    )
