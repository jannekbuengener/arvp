from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from arvp.adapters import (
    EVALUATION_INPUT_CONTRACT_VERSION,
    AdapterError,
    ObservationProducer,
    build_evaluation_input,
    dumps_evaluation_input,
    evaluate_artifacts,
    evaluate_evaluation_input,
    produce_observations,
)
from arvp.datasets import identify_content
from arvp.gates import (
    AbsoluteThresholdCriterion,
    GatePolicy,
    RelativeBaselineCriterion,
)
from arvp.identities import CandidateSpec, EvaluationPartition
from arvp.metrics import MetricContract, MetricDefinition, Observation
from arvp.provenance import RunProvenance
from arvp.schemas import SCHEMA_ASSET_NAMES, load_schema
from arvp.suite import EvaluationSuite


def _contract() -> MetricContract:
    return MetricContract((MetricDefinition("quality.score", "maximize", "1", True),))


def _partition() -> EvaluationPartition:
    content = identify_content([{"id": "a"}], fields=("id",), ordering="ordered")
    return EvaluationPartition("validation", "validation", content)


def _candidate(candidate_id: str, *, depth: int = 2) -> CandidateSpec:
    return CandidateSpec(candidate_id, "impl.eval", "r1", {"depth": depth})


def _suite() -> tuple[EvaluationSuite, GatePolicy, MetricContract, CandidateSpec]:
    contract = _contract()
    policy = GatePolicy(
        "release.default",
        contract,
        (
            AbsoluteThresholdCriterion(
                "quality.floor", "quality.score", "gte", Decimal("0.5")
            ),
            RelativeBaselineCriterion(
                "quality.improve",
                "quality.score",
                "minimum_improvement",
                Decimal("0.05"),
            ),
        ),
    )
    content = identify_content([{"id": "root"}], fields=("id",), ordering="ordered")
    baseline = _candidate("baseline", depth=1)
    suite = EvaluationSuite(
        "release.default",
        content,
        (_partition(),),
        contract,
        policy,
        baseline,
    )
    return suite, policy, contract, baseline


def _observation(
    *,
    observation_id: str,
    candidate: CandidateSpec,
    partition: EvaluationPartition,
    contract: MetricContract,
    value: Decimal | None,
    status: str = "measured",
) -> Observation:
    if status in {"measured", "derived"}:
        assert value is not None
        metric = contract.value("quality.score", status, value)
    else:
        metric = contract.value("quality.score", status)
    return Observation(
        observation_id=observation_id,
        candidate=candidate,
        partition=partition,
        metric_contract=contract,
        metric=metric,
    )


class _AlphaProducer:
    def produce(self, *, candidate, partition, metric_contract):
        return (
            _observation(
                observation_id="obs-1",
                candidate=candidate,
                partition=partition,
                contract=metric_contract,
                value=Decimal("0.9"),
            ),
        )


class _BetaProducer:
    def produce(self, *, candidate, partition, metric_contract):
        return (
            _observation(
                observation_id="obs-1",
                candidate=candidate,
                partition=partition,
                contract=metric_contract,
                value=Decimal("0.7"),
            ),
        )


def test_two_independent_adapters_call_same_core_without_core_changes() -> None:
    suite, _policy, contract, _baseline = _suite()
    partition = suite.partition("validation")
    candidate = _candidate("cand")
    alpha = produce_observations(
        _AlphaProducer(),
        candidate=candidate,
        partition=partition,
        metric_contract=contract,
    )
    beta = produce_observations(
        _BetaProducer(),
        candidate=candidate,
        partition=partition,
        metric_contract=contract,
    )
    assert isinstance(_AlphaProducer(), ObservationProducer)
    assert isinstance(_BetaProducer(), ObservationProducer)
    assert alpha[0].metric.value == Decimal("0.9")
    assert beta[0].metric.value == Decimal("0.7")
    assert alpha[0].candidate_fingerprint == beta[0].candidate_fingerprint


def test_evaluate_serialized_evaluation_input_without_consumer_modules(
    tmp_path: Path,
) -> None:
    suite, policy, contract, baseline = _suite()
    candidate = _candidate("cand")
    partition = suite.partition("validation")
    baseline_obs = _observation(
        observation_id="obs-1",
        candidate=baseline,
        partition=partition,
        contract=contract,
        value=Decimal("0.8"),
    )
    candidate_obs = _observation(
        observation_id="obs-1",
        candidate=candidate,
        partition=partition,
        contract=contract,
        value=Decimal("0.9"),
    )
    provenance = RunProvenance.bind(
        candidate_fingerprint=candidate.fingerprint(),
        suite=suite,
        partition_id="validation",
        code_revision="deadbeef",
        configuration={"seed": 7},
        arvp_version="0.1.0-test",
    )
    evaluation_input = build_evaluation_input(
        suite=suite,
        metric_contract=contract,
        gate_policy=policy,
        baseline_candidate=baseline,
        candidate_fingerprint=candidate.fingerprint(),
        partition_id="validation",
        run_provenance=provenance,
        baseline_observations=(baseline_obs,),
        candidate_observations=(candidate_obs,),
    )
    assert evaluation_input.contract_version == EVALUATION_INPUT_CONTRACT_VERSION
    assert "baseline_observations" in evaluation_input.to_dict()
    assert "candidate_observations" in evaluation_input.to_dict()
    serialized = dumps_evaluation_input(evaluation_input)
    portable = json.loads(serialized)
    # Simulate a foreign package consuming only JSON, no consumer imports.
    bundle = evaluate_evaluation_input(portable, generated_at="2026-10-06T12:00:00Z")
    assert bundle.candidate_fingerprint == candidate.fingerprint()
    assert bundle.gate_decision["verdict"] == "PASS"
    assert bundle.evidence_fingerprint

    path = tmp_path / "evaluation-input.json"
    path.write_text(serialized, encoding="utf-8")
    from_path = evaluate_evaluation_input(path, generated_at="2026-10-06T12:00:00Z")
    assert from_path.evidence_fingerprint == bundle.evidence_fingerprint


def test_missing_candidate_side_holds_via_separated_observations() -> None:
    suite, policy, contract, baseline = _suite()
    candidate = _candidate("cand")
    partition = suite.partition("validation")
    baseline_obs = _observation(
        observation_id="obs-1",
        candidate=baseline,
        partition=partition,
        contract=contract,
        value=Decimal("0.8"),
    )
    provenance = RunProvenance.bind(
        candidate_fingerprint=candidate.fingerprint(),
        suite=suite,
        partition_id="validation",
        code_revision="deadbeef",
        configuration={"seed": 7},
        arvp_version="0.1.0-test",
    )
    bundle = evaluate_artifacts(
        suite=suite,
        metric_contract=contract,
        gate_policy=policy,
        partition_id="validation",
        candidate_fingerprint=candidate.fingerprint(),
        baseline_observations=(baseline_obs,),
        candidate_observations=(),
        run_provenance=provenance,
        generated_at="2026-10-06T12:00:00Z",
    )
    assert bundle.gate_decision["verdict"] == "HOLD"


def test_schema_asset_validates_evaluation_input() -> None:
    try:
        import jsonschema
    except ImportError:
        pytest.skip("jsonschema unavailable on this host")

    suite, policy, contract, baseline = _suite()
    candidate = _candidate("cand")
    partition = suite.partition("validation")
    evaluation_input = build_evaluation_input(
        suite=suite,
        metric_contract=contract,
        gate_policy=policy,
        baseline_candidate=baseline,
        candidate_fingerprint=candidate.fingerprint(),
        partition_id="validation",
        run_provenance=RunProvenance.bind(
            candidate_fingerprint=candidate.fingerprint(),
            suite=suite,
            partition_id="validation",
            code_revision="deadbeef",
            arvp_version="0.1.0-test",
        ),
        baseline_observations=(
            _observation(
                observation_id="obs-1",
                candidate=baseline,
                partition=partition,
                contract=contract,
                value=Decimal("0.8"),
            ),
        ),
        candidate_observations=(
            _observation(
                observation_id="obs-1",
                candidate=candidate,
                partition=partition,
                contract=contract,
                value=Decimal("0.9"),
            ),
        ),
    )
    portable = json.loads(dumps_evaluation_input(evaluation_input))
    assert "evaluation_input_v1.json" in SCHEMA_ASSET_NAMES
    jsonschema.Draft202012Validator(load_schema("evaluation_input_v1.json")).validate(
        portable
    )


def test_evaluate_artifacts_rejects_non_suite() -> None:
    with pytest.raises(AdapterError, match="EvaluationSuite"):
        evaluate_artifacts(
            suite="wrong",  # type: ignore[arg-type]
            metric_contract=_contract(),
            gate_policy=GatePolicy(
                "p",
                _contract(),
                (
                    AbsoluteThresholdCriterion(
                        "q", "quality.score", "gte", Decimal("0")
                    ),
                ),
            ),
            partition_id="validation",
            candidate_fingerprint="a" * 64,
            baseline_observations=(),
            candidate_observations=(),
            run_provenance=RunProvenance(
                candidate_fingerprint="a" * 64,
                suite_fingerprint="b" * 64,
                partition_id="validation",
                partition_fingerprint="c" * 64,
                code_revision="r",
                configuration={},
                arvp_version="0.1.0-test",
            ),
            generated_at="2026-10-06T12:00:00Z",
        )
