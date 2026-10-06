from __future__ import annotations

from decimal import Decimal

import pytest

from arvp.datasets import (
    CONTENT_IDENTITY_SCHEMA_VERSION,
    DatasetContentIdentity,
    DatasetIdentityError,
    DatasetRequest,
    identify_content,
)
from arvp.provenance import ProvenanceError, RunRecord


def test_content_identity_is_provider_neutral_when_selected_fields_match() -> None:
    file_records = [
        {"ts": 2, "score": Decimal("1.5"), "path": "not selected"},
        {"ts": 1, "score": Decimal("1.0"), "provider": "file"},
    ]
    db_records = [
        {"ts": 1, "score": Decimal("1.0"), "connection": "not selected"},
        {"ts": 2, "score": Decimal("1.5"), "provider": "db"},
    ]

    file_identity = identify_content(
        file_records, fields=("ts", "score"), ordering="unordered"
    )
    db_identity = identify_content(
        db_records, fields=("ts", "score"), ordering="unordered"
    )

    assert file_identity.fingerprint == db_identity.fingerprint
    assert file_identity.record_count == 2


def test_dataset_request_and_content_identity_are_separate() -> None:
    request = DatasetRequest("benchmark-corpus", "2026-10", {"split": "validation"})
    content = identify_content(
        [{"id": "a", "label": 1}], fields=("id", "label"), ordering="ordered"
    )

    assert request.fingerprint() != content.fingerprint


def test_dataset_identity_rejects_path_and_missing_selected_field() -> None:
    with pytest.raises(DatasetIdentityError, match="forbidden"):
        DatasetRequest("d", "v1", {"path": "private-location"})
    with pytest.raises(DatasetIdentityError, match="missing selected"):
        identify_content([{"id": "a"}], fields=("id", "label"), ordering="ordered")


def test_run_record_fails_closed_for_invalid_lifecycle() -> None:
    with pytest.raises(ProvenanceError, match="failed records require"):
        RunRecord(
            run_id="run-" + ("b" * 12) + "-0001",
            provenance_fingerprint="b" * 64,
            status="failed",
            started_at_utc="2026-10-05T12:00:00Z",
            finished_at_utc="2026-10-05T12:00:01Z",
        )


def test_identify_content_wraps_canonicalization_errors() -> None:
    with pytest.raises(DatasetIdentityError, match="canonical"):
        identify_content(
            [{"id": {"nested": {1: "x"}}}],
            fields=("id",),
            ordering="ordered",
        )


def test_dataset_content_identity_v2_self_validates() -> None:
    assert CONTENT_IDENTITY_SCHEMA_VERSION == "arvp.dataset-content.v2"
    valid = DatasetContentIdentity(
        schema_version=CONTENT_IDENTITY_SCHEMA_VERSION,
        ordering="ordered",
        record_count=0,
        fingerprint="a" * 64,
    )
    assert valid.record_count == 0

    with pytest.raises(DatasetIdentityError, match="schema_version"):
        DatasetContentIdentity("arvp.dataset-content.v1", "ordered", 0, "a" * 64)
    with pytest.raises(DatasetIdentityError, match="ordering"):
        DatasetContentIdentity(CONTENT_IDENTITY_SCHEMA_VERSION, "sorted", 0, "a" * 64)  # type: ignore[arg-type]
    with pytest.raises(DatasetIdentityError, match="record_count"):
        DatasetContentIdentity(CONTENT_IDENTITY_SCHEMA_VERSION, "ordered", -1, "a" * 64)
    with pytest.raises(DatasetIdentityError, match="record_count"):
        DatasetContentIdentity(
            CONTENT_IDENTITY_SCHEMA_VERSION, "ordered", True, "a" * 64
        )  # type: ignore[arg-type]
    with pytest.raises(DatasetIdentityError, match="fingerprint"):
        DatasetContentIdentity(CONTENT_IDENTITY_SCHEMA_VERSION, "ordered", 0, "ABC")


def test_ordered_content_identity_changes_with_record_order() -> None:
    first = identify_content(
        [{"id": "a"}, {"id": "b"}], fields=("id",), ordering="ordered"
    )
    second = identify_content(
        [{"id": "b"}, {"id": "a"}], fields=("id",), ordering="ordered"
    )

    assert first.ordering == "ordered"
    assert first.fingerprint != second.fingerprint


def test_unordered_content_identity_ignores_order_but_preserves_duplicates() -> None:
    left = identify_content(
        [{"id": "a"}, {"id": "a"}, {"id": "b"}],
        fields=("id",),
        ordering="unordered",
    )
    reordered = identify_content(
        [{"id": "b"}, {"id": "a"}, {"id": "a"}],
        fields=("id",),
        ordering="unordered",
    )
    deduplicated = identify_content(
        [{"id": "a"}, {"id": "b"}], fields=("id",), ordering="unordered"
    )

    assert left == reordered
    assert left.record_count == 3
    assert left.fingerprint != deduplicated.fingerprint


def test_identify_content_allows_empty_dataset_with_explicit_fields() -> None:
    identity = identify_content([], fields=("id", "label"), ordering="unordered")

    assert identity.schema_version == CONTENT_IDENTITY_SCHEMA_VERSION
    assert identity.ordering == "unordered"
    assert identity.record_count == 0
    assert len(identity.fingerprint) == 64


def test_dataset_identity_does_not_guess_cross_type_equivalence() -> None:
    integer = identify_content([{"value": 1}], fields=("value",), ordering="ordered")
    floating = identify_content([{"value": 1.0}], fields=("value",), ordering="ordered")
    text = identify_content([{"value": "1"}], fields=("value",), ordering="ordered")
    decimal = identify_content(
        [{"value": Decimal("1")}], fields=("value",), ordering="ordered"
    )

    assert (
        len(
            {
                integer.fingerprint,
                floating.fingerprint,
                text.fingerprint,
                decimal.fingerprint,
            }
        )
        == 4
    )


def test_dataset_request_defensively_owns_nested_parameters() -> None:
    source = {"nested": {"thresholds": [1, 2]}}
    request = DatasetRequest("benchmark-corpus", "v1", source)
    before = request.fingerprint()

    source["nested"]["thresholds"].append(3)  # type: ignore[index]

    assert request.parameters == {"nested": {"thresholds": [1, 2]}}
    assert request.fingerprint() == before


def test_dataset_ordering_rejects_non_string_values_with_domain_error() -> None:
    with pytest.raises(DatasetIdentityError, match="ordering"):
        DatasetContentIdentity(
            CONTENT_IDENTITY_SCHEMA_VERSION,
            [],  # type: ignore[arg-type]
            0,
            "a" * 64,
        )
    with pytest.raises(DatasetIdentityError, match="ordering"):
        identify_content([], fields=("id",), ordering=[])  # type: ignore[arg-type]
