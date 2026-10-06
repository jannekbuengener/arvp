from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from arvp.canonical import (
    CANONICAL_CONTRACT_VERSION,
    canonical_hash,
    canonical_json_dumps,
)
from arvp.datasets import (
    CONTENT_IDENTITY_SCHEMA_VERSION,
    DatasetContentIdentity,
    identify_content,
)
from arvp.identities import CandidateSpec, EvaluationPartition

FIXTURE = Path(__file__).parent / "fixtures" / "identity_contracts_v1_golden.json"


def _load_vectors() -> dict[str, Any]:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert payload["canonical_contract_version"] == CANONICAL_CONTRACT_VERSION
    return payload


def test_identity_golden_vectors() -> None:
    for vector in _load_vectors()["vectors"]:
        kind = vector["kind"]
        if kind == "dataset":
            records = list(vector["records"])
            ordering = vector["ordering"]
            if ordering == "unordered":
                records = sorted(records, key=canonical_json_dumps)
            preimage = {
                "fields": sorted(vector["fields"]),
                "ordering": ordering,
                "records": records,
                "schema_version": CONTENT_IDENTITY_SCHEMA_VERSION,
            }
            identity = identify_content(
                vector["records"],
                fields=tuple(vector["fields"]),
                ordering=ordering,
            )
            actual_json = canonical_json_dumps(preimage)
            actual_fingerprint = identity.fingerprint
        elif kind == "candidate":
            candidate = CandidateSpec(
                vector["candidate_id"],
                vector["implementation_id"],
                vector["revision"],
                vector["configuration"],
            )
            actual_json = canonical_json_dumps(candidate.to_dict())
            actual_fingerprint = candidate.fingerprint()
        elif kind == "partition":
            raw = vector["content_identity"]
            content = DatasetContentIdentity(
                schema_version=raw["schema_version"],
                ordering=raw["ordering"],
                record_count=raw["record_count"],
                fingerprint=raw["fingerprint"],
            )
            partition = EvaluationPartition(
                vector["partition_id"], vector["role"], content
            )
            actual_json = canonical_json_dumps(partition.to_dict())
            actual_fingerprint = partition.fingerprint()
        else:
            raise AssertionError(f"unknown golden vector kind: {kind}")

        assert actual_json == vector["expected_json"], vector["name"]
        assert actual_fingerprint == vector["expected_fingerprint"], vector["name"]
        assert (
            canonical_hash(json.loads(actual_json)) == vector["expected_fingerprint"]
        ), vector["name"]


def test_platform_smoke_exercises_identity_contracts() -> None:
    from tools.platform_smoke import probe_identity_contracts

    probe_identity_contracts()
