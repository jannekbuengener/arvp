from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from arvp.canonical import CANONICAL_CONTRACT_VERSION, canonical_json_dumps
from arvp.datasets import DatasetContentIdentity
from arvp.identities import CandidateSpec, EvaluationPartition
from arvp.metrics import (
    METRIC_CONTRACT_VERSION,
    METRIC_DEFINITION_CONTRACT_VERSION,
    METRIC_VALUE_CONTRACT_VERSION,
    OBSERVATION_CONTRACT_VERSION,
    MetricContract,
    MetricDefinition,
    Observation,
)

FIXTURE = Path(__file__).parent / "fixtures" / "metric_contracts_v1_golden.json"


def _load() -> dict[str, Any]:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert payload["canonical_contract_version"] == CANONICAL_CONTRACT_VERSION
    assert (
        payload["metric_definition_contract_version"]
        == METRIC_DEFINITION_CONTRACT_VERSION
    )
    assert payload["metric_contract_version"] == METRIC_CONTRACT_VERSION
    assert payload["metric_value_contract_version"] == METRIC_VALUE_CONTRACT_VERSION
    assert payload["observation_contract_version"] == OBSERVATION_CONTRACT_VERSION
    return payload


def _definition(raw: dict[str, Any]) -> MetricDefinition:
    return MetricDefinition(
        raw["metric_id"], raw["direction"], raw["unit"], raw["required"]
    )


def _contract(raw: list[dict[str, Any]]) -> MetricContract:
    return MetricContract(tuple(_definition(item) for item in raw))


def _value(contract: MetricContract, vector: dict[str, Any]):
    raw = vector.get("value")
    value = Decimal(raw) if raw is not None else None
    return contract.value(vector["metric_id"], vector["status"], value)


def test_metric_golden_vectors() -> None:
    for vector in _load()["vectors"]:
        kind = vector["kind"]
        if kind == "definition":
            item = _definition(vector["definition"])
        elif kind == "contract":
            item = _contract(vector["definitions"])
        elif kind == "value":
            contract = _contract(vector["definitions"])
            item = _value(contract, vector)
        elif kind == "observation":
            contract = _contract(vector["definitions"])
            raw_content = vector["content_identity"]
            content = DatasetContentIdentity(
                schema_version=raw_content["schema_version"],
                ordering=raw_content["ordering"],
                record_count=raw_content["record_count"],
                fingerprint=raw_content["fingerprint"],
            )
            partition = EvaluationPartition(
                vector["partition_id"], vector["partition_role"], content
            )
            raw_candidate = vector["candidate"]
            candidate = CandidateSpec(
                raw_candidate["candidate_id"],
                raw_candidate["implementation_id"],
                raw_candidate["revision"],
                raw_candidate["configuration"],
            )
            item = Observation(
                observation_id=vector["observation_id"],
                candidate=candidate,
                partition=partition,
                metric_contract=contract,
                metric=_value(contract, vector),
            )
        else:
            raise AssertionError(f"unknown metric golden kind: {kind}")

        assert canonical_json_dumps(item.to_dict()) == vector["expected_json"], vector[
            "name"
        ]
        assert item.fingerprint() == vector["expected_fingerprint"], vector["name"]


def test_platform_smoke_exercises_metric_contracts() -> None:
    from tools.platform_smoke import probe_metric_contracts

    probe_metric_contracts()
