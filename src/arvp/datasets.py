"""Domain-independent dataset request and content identities."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from arvp.canonical import (
    CanonicalizationError,
    FingerprintFormatError,
    canonical_hash,
    canonical_json_dumps,
    validate_fingerprint,
)
from arvp.evidence import PortableEvidenceError, validate_portable_metadata

CONTENT_IDENTITY_SCHEMA_VERSION = "arvp.dataset-content.v2"
DatasetOrdering = Literal["ordered", "unordered"]
_VALID_ORDERINGS = frozenset({"ordered", "unordered"})


class DatasetIdentityError(ValueError):
    """Raised when a dataset identity is malformed or unsafe."""


def _require_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DatasetIdentityError(f"{field} must be a non-empty string")
    return value.strip()


def assert_evidence_safe(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and defensively copy portable dataset metadata."""
    try:
        return validate_portable_metadata(value)
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
        for key in self.parameters:
            if type(key) is not str:
                raise DatasetIdentityError("parameter keys must be strings")
            if key == "$arvp":
                raise DatasetIdentityError(r"reserved key '\$arvp' not allowed")
        copied = assert_evidence_safe(dict(self.parameters))
        object.__setattr__(self, "parameters", copied)

    def to_dict(self) -> dict[str, Any]:
        parameters = assert_evidence_safe(dict(self.parameters))
        return {
            "dataset_id": self.dataset_id,
            "parameters": parameters,
            "revision": self.revision,
        }

    def fingerprint(self) -> str:
        return canonical_hash(self.to_dict())


@dataclass(frozen=True, slots=True)
class DatasetContentIdentity:
    """Self-validating identity of loaded dataset content."""

    schema_version: str
    ordering: DatasetOrdering
    record_count: int
    fingerprint: str

    def __post_init__(self) -> None:
        if self.schema_version != CONTENT_IDENTITY_SCHEMA_VERSION:
            raise DatasetIdentityError(
                f"schema_version must be {CONTENT_IDENTITY_SCHEMA_VERSION!r}"
            )
        if type(self.ordering) is not str or self.ordering not in _VALID_ORDERINGS:
            raise DatasetIdentityError("ordering must be 'ordered' or 'unordered'")
        if type(self.record_count) is not int or self.record_count < 0:
            raise DatasetIdentityError("record_count must be a non-negative integer")
        try:
            validate_fingerprint(self.fingerprint, "fingerprint")
        except FingerprintFormatError as exc:
            raise DatasetIdentityError(str(exc)) from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "ordering": self.ordering,
            "record_count": self.record_count,
            "schema_version": self.schema_version,
        }


def identify_content(
    records: Sequence[Mapping[str, Any]],
    *,
    fields: Sequence[str],
    ordering: DatasetOrdering,
) -> DatasetContentIdentity:
    """Fingerprint caller-selected portable record fields.

    ``ordered`` preserves input record order exactly. ``unordered`` sorts the
    selected records by their Canonical-v2 JSON representation while preserving
    duplicate multiplicity. ARVP never coerces domain values into guessed
    equivalence; callers normalize domain semantics before calling this function.
    """
    if type(ordering) is not str or ordering not in _VALID_ORDERINGS:
        raise DatasetIdentityError("ordering must be 'ordered' or 'unordered'")

    selected_fields = tuple(_require_text(field, "field") for field in fields)
    if not selected_fields or len(set(selected_fields)) != len(selected_fields):
        raise DatasetIdentityError(
            "fields must be a non-empty sequence of unique strings"
        )
    assert_evidence_safe({field: None for field in selected_fields})

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
        if ordering == "unordered":
            selected_records.sort(key=canonical_json_dumps)
        payload = {
            "fields": sorted(selected_fields),
            "ordering": ordering,
            "records": selected_records,
            "schema_version": CONTENT_IDENTITY_SCHEMA_VERSION,
        }
        safe_payload = assert_evidence_safe(payload)
        fingerprint = canonical_hash(safe_payload)
    except CanonicalizationError as exc:
        raise DatasetIdentityError(f"content not canonicalizable: {exc}") from exc

    return DatasetContentIdentity(
        schema_version=CONTENT_IDENTITY_SCHEMA_VERSION,
        ordering=ordering,
        record_count=len(selected_records),
        fingerprint=fingerprint,
    )
