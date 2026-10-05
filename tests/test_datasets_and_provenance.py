from __future__ import annotations

from decimal import Decimal

import pytest

from arvp.datasets import DatasetIdentityError, DatasetRequest, identify_content
from arvp.provenance import JsonlRunRegistry, ProvenanceError, RunProvenance, RunRecord


def test_content_identity_is_provider_neutral_when_selected_fields_match() -> None:
    file_records = [
        {"ts": 2, "score": 1.5, "path": "not selected"},
        {"ts": 1, "score": 1.0, "provider": "file"},
    ]
    db_records = [
        {"ts": 1, "score": Decimal("1.0"), "connection": "not selected"},
        {"ts": 2, "score": Decimal("1.5"), "provider": "db"},
    ]

    file_identity = identify_content(
        file_records, fields=("ts", "score"), order_by="ts"
    )
    db_identity = identify_content(
        db_records, fields=("ts", "score"), order_by="ts"
    )

    assert file_identity.fingerprint == db_identity.fingerprint
    assert file_identity.record_count == 2


def test_dataset_request_and_content_identity_are_separate() -> None:
    request = DatasetRequest("benchmark-corpus", "2026-10", {"split": "validation"})
    content = identify_content([{"id": "a", "label": 1}], fields=("id", "label"))

    assert request.fingerprint() != content.fingerprint


def test_dataset_identity_rejects_path_and_missing_selected_field() -> None:
    with pytest.raises(DatasetIdentityError, match="forbidden"):
        DatasetRequest("d", "v1", {"path": "private-location"})
    with pytest.raises(DatasetIdentityError, match="missing selected"):
        identify_content([{"id": "a"}], fields=("id", "label"))


def test_provenance_registry_round_trip_and_attempts(tmp_path) -> None:
    provenance = RunProvenance(
        candidate_id="candidate-a",
        dataset_fingerprint="a" * 64,
        code_revision="abc123",
        configuration={"threshold": 0.8},
    )
    record = RunRecord(
        run_id=provenance.run_id(1),
        provenance_fingerprint=provenance.fingerprint(),
        status="completed",
        started_at_utc="2026-10-05T12:00:00+00:00",
        finished_at_utc="2026-10-05T12:00:01+00:00",
        result={"accuracy": 0.9},
    )
    registry = JsonlRunRegistry(tmp_path / "registry.jsonl")

    registry.append(record)

    assert registry.load_all() == [record]
    assert registry.next_attempt(provenance) == 2


def test_run_record_fails_closed_for_invalid_lifecycle() -> None:
    with pytest.raises(ProvenanceError, match="failed records require"):
        RunRecord(
            run_id="run-0123456789ab-0001",
            provenance_fingerprint="b" * 64,
            status="failed",
            started_at_utc="2026-10-05T12:00:00+00:00",
            finished_at_utc="2026-10-05T12:00:01+00:00",
        )
