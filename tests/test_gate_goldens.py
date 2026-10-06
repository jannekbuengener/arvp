from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from arvp.canonical import CANONICAL_CONTRACT_VERSION, canonical_json_dumps
from arvp.datasets import DatasetContentIdentity
from arvp.gates import (
    GATE_DECISION_CONTRACT_VERSION,
    GATE_POLICY_CONTRACT_VERSION,
    METRIC_COMPARISON_CONTRACT_VERSION,
    AbsoluteThresholdCriterion,
    GatePolicy,
    RelativeBaselineCriterion,
    compare_observation_scope,
    evaluate_gate,
)
from arvp.identities import CandidateSpec, EvaluationPartition
from arvp.metrics import MetricContract, MetricDefinition, Observation

FIXTURE = Path(__file__).parent / "fixtures" / "gate_contracts_v1_golden.json"


def _load() -> dict[str, Any]:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert payload["canonical_contract_version"] == CANONICAL_CONTRACT_VERSION
    assert payload["comparison_contract_version"] == METRIC_COMPARISON_CONTRACT_VERSION
    assert payload["gate_policy_contract_version"] == GATE_POLICY_CONTRACT_VERSION
    assert payload["gate_decision_contract_version"] == GATE_DECISION_CONTRACT_VERSION
    return payload


def _contract(definitions: list[dict[str, Any]]) -> MetricContract:
    return MetricContract(
        tuple(
            MetricDefinition(
                raw["metric_id"], raw["direction"], raw["unit"], raw["required"]
            )
            for raw in definitions
        )
    )


def _partition(raw: dict[str, Any]) -> EvaluationPartition:
    content = raw["content_identity"]
    identity = DatasetContentIdentity(
        schema_version=content["schema_version"],
        ordering=content["ordering"],
        record_count=content["record_count"],
        fingerprint=content["fingerprint"],
    )
    return EvaluationPartition(raw["partition_id"], raw["partition_role"], identity)


def _candidate(raw: dict[str, Any]) -> CandidateSpec:
    return CandidateSpec(
        raw["candidate_id"],
        raw["implementation_id"],
        raw["revision"],
        raw["configuration"],
    )


def _observation(
    contract: MetricContract,
    side: dict[str, Any],
    metric: dict[str, Any],
) -> Observation:
    value_raw = metric.get("value")
    value = Decimal(value_raw) if value_raw is not None else None
    return Observation(
        observation_id=metric["observation_id"],
        candidate=_candidate(side["candidate"]),
        partition=_partition(side["partition"]),
        metric_contract=contract,
        metric=contract.value(metric["metric_id"], metric["status"], value),
    )


def _side_observations(
    contract: MetricContract, side: dict[str, Any] | None
) -> tuple[Observation, ...]:
    if side is None:
        return ()
    return tuple(_observation(contract, side, metric) for metric in side["metrics"])


def _criterion(raw: dict[str, Any]):
    if raw["criterion_type"] == "absolute_threshold":
        return AbsoluteThresholdCriterion(
            raw["criterion_id"],
            raw["metric_id"],
            raw["operator"],
            Decimal(raw["threshold"]),
        )
    if raw["criterion_type"] == "relative_baseline":
        return RelativeBaselineCriterion(
            raw["criterion_id"],
            raw["metric_id"],
            raw["mode"],
            Decimal(raw["threshold"]),
        )
    raise AssertionError(f"unknown criterion type: {raw['criterion_type']}")


def _comparisons(contract: MetricContract, vector: dict[str, Any]):
    return compare_observation_scope(
        baseline=_side_observations(contract, vector.get("baseline")),
        candidate=_side_observations(contract, vector.get("candidate")),
        metric_contract=contract,
    )


def test_gate_golden_vectors() -> None:
    for vector in _load()["vectors"]:
        contract = _contract(vector["definitions"])
        kind = vector["kind"]
        if kind == "comparison":
            items = _comparisons(contract, vector)
            assert len(items) == 1, vector["name"]
            item = items[0]
        elif kind == "policy":
            item = GatePolicy(
                vector["policy_id"],
                contract,
                tuple(_criterion(raw) for raw in vector["criteria"]),
            )
        elif kind == "decision":
            policy = GatePolicy(
                vector["policy_id"],
                contract,
                tuple(_criterion(raw) for raw in vector["criteria"]),
            )
            item = evaluate_gate(
                policy=policy,
                comparisons=_comparisons(contract, vector),
                metric_contract=contract,
            )
        else:
            raise AssertionError(f"unknown gate golden kind: {kind}")

        assert canonical_json_dumps(item.to_dict()) == vector["expected_json"], vector[
            "name"
        ]
        assert item.fingerprint() == vector["expected_fingerprint"], vector["name"]


def test_platform_smoke_exercises_gate_contracts() -> None:
    from tools.platform_smoke import probe_gate_contracts

    probe_gate_contracts()
