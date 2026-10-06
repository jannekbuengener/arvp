"""Cross-platform smoke probe for ARVP portable identity contracts."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from arvp.canonical import CanonicalizationError, canonical_hash, canonical_json_dumps
from arvp.datasets import DatasetContentIdentity, identify_content
from arvp.identities import CandidateSpec, EvaluationPartition
from arvp.metrics import MetricContract, MetricDefinition, Observation

try:
    from canonical_v2_golden import load_golden_vectors, reconstruct_source
except ImportError:
    from tools.canonical_v2_golden import load_golden_vectors, reconstruct_source


_IDENTITY_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "fixtures"
    / "identity_contracts_v1_golden.json"
)
_METRIC_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "fixtures"
    / "metric_contracts_v1_golden.json"
)
_GATE_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "fixtures"
    / "gate_contracts_v1_golden.json"
)


def probe_golden_vectors() -> None:
    """Verify all canonical-v2 golden vectors."""
    for vec in load_golden_vectors():
        source = reconstruct_source(vec)
        if "expect_error" in vec:
            try:
                canonical_json_dumps(source)
            except CanonicalizationError:
                pass
            else:
                raise AssertionError(
                    f"Vector {vec['name']}: expected {vec['expect_error']}, but succeeded"
                )
        else:
            actual_json = canonical_json_dumps(source)
            assert actual_json == vec["expected_json"], (
                f"Vector {vec['name']}: canonical JSON mismatch\n"
                f"  expected: {vec['expected_json']}\n"
                f"  actual:   {actual_json}"
            )
            actual_fp = canonical_hash(source)
            assert actual_fp == vec["expected_fingerprint"], (
                f"Vector {vec['name']}: fingerprint mismatch\n"
                f"  expected: {vec['expected_fingerprint']}\n"
                f"  actual:   {actual_fp}"
            )


def probe_identity_contracts() -> None:
    """Verify dataset, candidate, and partition golden identities."""
    fixture = json.loads(_IDENTITY_FIXTURE.read_text(encoding="utf-8"))
    for vector in fixture["vectors"]:
        kind = vector["kind"]
        if kind == "dataset":
            identity = identify_content(
                vector["records"],
                fields=tuple(vector["fields"]),
                ordering=vector["ordering"],
            )
            actual_fingerprint = identity.fingerprint
        elif kind == "candidate":
            candidate = CandidateSpec(
                vector["candidate_id"],
                vector["implementation_id"],
                vector["revision"],
                vector["configuration"],
            )
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
            actual_fingerprint = partition.fingerprint()
        else:
            raise AssertionError(f"unknown identity golden kind: {kind}")
        assert actual_fingerprint == vector["expected_fingerprint"], vector["name"]


def probe_metric_contracts() -> None:
    """Verify metric definitions, values, contracts, and observation goldens."""
    fixture = json.loads(_METRIC_FIXTURE.read_text(encoding="utf-8"))

    def build_definition(raw):
        return MetricDefinition(
            raw["metric_id"], raw["direction"], raw["unit"], raw["required"]
        )

    def build_contract(raw):
        return MetricContract(tuple(build_definition(item) for item in raw))

    def build_value(contract, vector):
        raw = vector.get("value")
        value = Decimal(raw) if raw is not None else None
        return contract.value(vector["metric_id"], vector["status"], value)

    for vector in fixture["vectors"]:
        kind = vector["kind"]
        if kind == "definition":
            item = build_definition(vector["definition"])
        elif kind == "contract":
            item = build_contract(vector["definitions"])
        elif kind == "value":
            contract = build_contract(vector["definitions"])
            item = build_value(contract, vector)
        elif kind == "observation":
            contract = build_contract(vector["definitions"])
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
                metric=build_value(contract, vector),
            )
        else:
            raise AssertionError(f"unknown metric golden kind: {kind}")

        assert canonical_json_dumps(item.to_dict()) == vector["expected_json"], vector[
            "name"
        ]
        assert item.fingerprint() == vector["expected_fingerprint"], vector["name"]


def probe_platform_repeatability() -> None:
    """Additional repeatability checks for cross-platform validation."""
    payload = {
        "z": 26,
        "a": 1,
        "nested": {"gamma": [3, 2, 1], "alpha": None},
        "decimal": "1.234",
        "negative_zero": -0.0,
    }
    first = canonical_json_dumps(payload)
    second = canonical_json_dumps(dict(reversed(list(payload.items()))))
    assert first == canonical_json_dumps(payload), "canonical_json_dumps not repeatable"
    assert first == second, "canonical_json_dumps depends on mapping order"
    assert isinstance(first, str)

    payload2 = {
        "rows": [{"id": 3, "score": "1.5"}, {"id": 1, "score": "0.5"}],
        "count": 2,
    }
    first_hash = canonical_hash(payload2)
    second_hash = canonical_hash(payload2)
    assert first_hash == second_hash, "canonical_hash not repeatable"
    assert len(first_hash) == 64, f"expected 64 hex characters, got {len(first_hash)}"


def probe_gate_contracts() -> None:
    """Reconstruct frozen gate goldens through public APIs and verify them."""
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

    fixture = json.loads(_GATE_FIXTURE.read_text(encoding="utf-8"))
    assert fixture["canonical_contract_version"] == "arvp.canonical.v2"
    assert fixture["comparison_contract_version"] == METRIC_COMPARISON_CONTRACT_VERSION
    assert fixture["gate_policy_contract_version"] == GATE_POLICY_CONTRACT_VERSION
    assert fixture["gate_decision_contract_version"] == GATE_DECISION_CONTRACT_VERSION

    def build_contract(raw_definitions):
        return MetricContract(
            tuple(
                MetricDefinition(
                    raw["metric_id"], raw["direction"], raw["unit"], raw["required"]
                )
                for raw in raw_definitions
            )
        )

    def build_observation(contract, side, metric):
        value_raw = metric.get("value")
        value = Decimal(str(value_raw)) if value_raw is not None else None
        raw_candidate = side["candidate"]
        candidate = CandidateSpec(
            raw_candidate["candidate_id"],
            raw_candidate["implementation_id"],
            raw_candidate["revision"],
            raw_candidate["configuration"],
        )
        raw_content = side["partition"]["content_identity"]
        content = DatasetContentIdentity(
            schema_version=raw_content["schema_version"],
            ordering=raw_content["ordering"],
            record_count=raw_content["record_count"],
            fingerprint=raw_content["fingerprint"],
        )
        partition = EvaluationPartition(
            side["partition"]["partition_id"],
            side["partition"]["partition_role"],
            content,
        )
        return Observation(
            observation_id=metric["observation_id"],
            candidate=candidate,
            partition=partition,
            metric_contract=contract,
            metric=contract.value(metric["metric_id"], metric["status"], value),
        )

    def build_comparisons(contract, vector):
        def side_observations(side):
            if side is None:
                return ()
            return tuple(
                build_observation(contract, side, metric) for metric in side["metrics"]
            )

        return compare_observation_scope(
            baseline=side_observations(vector.get("baseline")),
            candidate=side_observations(vector.get("candidate")),
            metric_contract=contract,
        )

    def build_criterion(raw):
        if raw["criterion_type"] == "absolute_threshold":
            return AbsoluteThresholdCriterion(
                raw["criterion_id"],
                raw["metric_id"],
                raw["operator"],
                Decimal(str(raw["threshold"])),
            )
        if raw["criterion_type"] == "relative_baseline":
            return RelativeBaselineCriterion(
                raw["criterion_id"],
                raw["metric_id"],
                raw["mode"],
                Decimal(str(raw["threshold"])),
            )
        raise AssertionError(f"unknown criterion type: {raw['criterion_type']}")

    for vector in fixture["vectors"]:
        contract = build_contract(vector["definitions"])
        kind = vector["kind"]
        if kind == "comparison":
            items = build_comparisons(contract, vector)
            assert len(items) == 1, vector["name"]
            item = items[0]
        elif kind == "policy":
            item = GatePolicy(
                vector["policy_id"],
                contract,
                tuple(build_criterion(raw) for raw in vector["criteria"]),
            )
        elif kind == "decision":
            policy = GatePolicy(
                vector["policy_id"],
                contract,
                tuple(build_criterion(raw) for raw in vector["criteria"]),
            )
            item = evaluate_gate(
                policy=policy,
                comparisons=build_comparisons(contract, vector),
                metric_contract=contract,
            )
        else:
            raise AssertionError(f"unknown gate golden kind: {kind}")

        assert canonical_json_dumps(item.to_dict()) == vector["expected_json"], vector[
            "name"
        ]
        assert item.fingerprint() == vector["expected_fingerprint"], vector["name"]


def probe_evidence_bundle_schemas() -> None:
    """Prove packaged Evidence Bundle schemas are reachable from an install."""
    from arvp.bundle import EVIDENCE_BUNDLE_CONTRACT_VERSION, EvidenceBundle
    from arvp.schemas import SCHEMA_ASSET_NAMES, load_schema

    assert EVIDENCE_BUNDLE_CONTRACT_VERSION == "arvp.evidence.v1"
    assert SCHEMA_ASSET_NAMES == (
        "evidence_bundle_v1.json",
        "evaluation_input_v1.json",
        "evaluation_suite_v1.json",
        "metric_observation_v1.json",
    )
    for name in SCHEMA_ASSET_NAMES:
        schema = load_schema(name)
        assert isinstance(schema, dict)
        assert "$schema" in schema
    fixture = (
        Path(__file__).resolve().parents[1]
        / "tests"
        / "fixtures"
        / "evidence_bundle_v1_golden.json"
    )
    payload = json.loads(fixture.read_text(encoding="utf-8"))["bundle"]
    bundle = EvidenceBundle.from_dict(payload)
    assert bundle.evidence_fingerprint == payload["evidence_fingerprint"]


def probe_integer_threshold_evaluation_input() -> None:
    """Prove EvaluationInput schema asset is present after install."""
    from arvp.adapters import EVALUATION_INPUT_CONTRACT_VERSION
    from arvp.schemas import load_schema

    assert EVALUATION_INPUT_CONTRACT_VERSION == "arvp.evaluation-input.v1"
    schema = load_schema("evaluation_input_v1.json")
    assert schema["properties"]["contract_version"]["const"] == (
        "arvp.evaluation-input.v1"
    )
    assert "baseline_observations" in schema["properties"]
    assert "candidate_observations" in schema["properties"]


def main() -> int:
    probe_golden_vectors()
    probe_identity_contracts()
    probe_metric_contracts()
    probe_platform_repeatability()
    probe_gate_contracts()
    probe_evidence_bundle_schemas()
    probe_integer_threshold_evaluation_input()
    print(
        "platform smoke ok: canonical v2, identity, metric, gate, evidence, "
        "and evaluation-input verified"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
