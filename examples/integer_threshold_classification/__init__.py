"""Integer-threshold classification reference domain (outside ARVP core).

Ground-truth rule lives only here: label = 1 if x >= 10 else 0.
Candidates are threshold configurations; ARVP core stays domain-neutral.

Observation layout:
- per-case ``correct`` (0/1) for paired stability evidence
- single aggregate ``accuracy`` (mean of correct) for PASS/FAIL/HOLD gates
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

from arvp.adapters import (
    build_evaluation_input,
    dumps_evaluation_input,
    evaluate_evaluation_input,
)
from arvp.bundle import EvidenceBundle
from arvp.datasets import identify_content
from arvp.gates import AbsoluteThresholdCriterion, GatePolicy, RelativeBaselineCriterion
from arvp.identities import CandidateSpec, EvaluationPartition
from arvp.metrics import MetricContract, MetricDefinition, Observation
from arvp.provenance import RunProvenance
from arvp.stability import StabilityConfig
from arvp.suite import EvaluationSuite

FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "integer_threshold"
    / "cases.json"
)
GENERATED_AT = "2026-10-06T18:00:00Z"
CORRECT_METRIC_ID = "correct"
ACCURACY_METRIC_ID = "accuracy"


def load_fixture(path: Path | None = None) -> dict[str, Any]:
    destination = FIXTURE_PATH if path is None else Path(path)
    return json.loads(destination.read_text(encoding="utf-8"))


def predict_label(x: int, *, threshold: int) -> int:
    return 1 if x >= threshold else 0


def case_correct(case: Mapping[str, Any], *, threshold: int) -> int:
    predicted = predict_label(int(case["x"]), threshold=threshold)
    return 1 if predicted == int(case["expected_label"]) else 0


def metric_contract() -> MetricContract:
    return MetricContract(
        (
            MetricDefinition(CORRECT_METRIC_ID, "maximize", "1", True),
            MetricDefinition(ACCURACY_METRIC_ID, "maximize", "1", True),
        )
    )


def gate_policy(contract: MetricContract) -> GatePolicy:
    # Gate only on aggregate accuracy so evaluate_gate sees one comparison/metric.
    return GatePolicy(
        "integer.threshold.release",
        contract,
        (
            AbsoluteThresholdCriterion(
                "accuracy.floor", ACCURACY_METRIC_ID, "gte", Decimal("0.5")
            ),
            RelativeBaselineCriterion(
                "accuracy.improve",
                ACCURACY_METRIC_ID,
                "minimum_improvement",
                Decimal("0.05"),
            ),
        ),
    )


def build_suite(
    cases: Sequence[Mapping[str, Any]],
    *,
    baseline: CandidateSpec,
    contract: MetricContract,
    policy: GatePolicy,
) -> EvaluationSuite:
    records = [{"id": case["id"]} for case in cases]
    content = identify_content(records, fields=("id",), ordering="ordered")
    partition = EvaluationPartition("validation", "validation", content)
    return EvaluationSuite(
        "integer.threshold.v1",
        content,
        (partition,),
        contract,
        policy,
        baseline,
    )


def candidate_spec(candidate_id: str, *, threshold: int) -> CandidateSpec:
    return CandidateSpec(
        candidate_id,
        "integer.threshold.classifier",
        "r1",
        {"threshold": threshold},
    )


def _accuracy(cases: Sequence[Mapping[str, Any]], *, threshold: int) -> Decimal:
    if not cases:
        raise ValueError("cases must not be empty")
    total = sum(case_correct(case, threshold=threshold) for case in cases)
    return Decimal(total) / Decimal(len(cases))


def observations_for_threshold(
    cases: Sequence[Mapping[str, Any]],
    *,
    candidate: CandidateSpec,
    partition: EvaluationPartition,
    contract: MetricContract,
    threshold: int,
) -> tuple[Observation, ...]:
    observations: list[Observation] = [
        Observation(
            observation_id=str(case["id"]),
            candidate=candidate,
            partition=partition,
            metric_contract=contract,
            metric=contract.value(
                CORRECT_METRIC_ID,
                "measured",
                Decimal(case_correct(case, threshold=threshold)),
            ),
        )
        for case in cases
    ]
    observations.append(
        Observation(
            observation_id="accuracy",
            candidate=candidate,
            partition=partition,
            metric_contract=contract,
            metric=contract.value(
                ACCURACY_METRIC_ID,
                "measured",
                _accuracy(cases, threshold=threshold),
            ),
        )
    )
    return tuple(observations)


def build_run(
    *,
    candidate_key: str,
    include_candidate_observations: bool = True,
    fixture_path: Path | None = None,
) -> tuple[EvidenceBundle, str]:
    """Build serialized EvaluationInput and evaluate it through the #12 envelope."""
    fixture = load_fixture(fixture_path)
    cases = fixture["cases"]
    thresholds = fixture["candidates"]
    contract = metric_contract()
    policy = gate_policy(contract)
    baseline = candidate_spec(
        "baseline", threshold=int(thresholds["baseline"]["threshold"])
    )
    candidate = candidate_spec(
        candidate_key, threshold=int(thresholds[candidate_key]["threshold"])
    )
    suite = build_suite(cases, baseline=baseline, contract=contract, policy=policy)
    partition = suite.partition("validation")
    baseline_obs = observations_for_threshold(
        cases,
        candidate=baseline,
        partition=partition,
        contract=contract,
        threshold=int(thresholds["baseline"]["threshold"]),
    )
    if include_candidate_observations:
        candidate_obs = observations_for_threshold(
            cases,
            candidate=candidate,
            partition=partition,
            contract=contract,
            threshold=int(thresholds[candidate_key]["threshold"]),
        )
    else:
        candidate_obs = ()
    provenance = RunProvenance.bind(
        candidate_fingerprint=candidate.fingerprint(),
        suite=suite,
        partition_id="validation",
        code_revision="integer-threshold-proof",
        configuration={"domain": "integer_threshold_classification"},
        arvp_version="0.1.0-test",
    )
    stability = StabilityConfig(
        aggregation="mean",
        sample_count=32,
        blocks_per_sample=1,
        seed=13,
    )
    evaluation_input = build_evaluation_input(
        suite=suite,
        metric_contract=contract,
        gate_policy=policy,
        baseline_candidate=baseline,
        candidate_fingerprint=candidate.fingerprint(),
        partition_id="validation",
        run_provenance=provenance,
        baseline_observations=baseline_obs,
        candidate_observations=candidate_obs,
        stability_config=stability,
        configuration={"proof": "issue-13"},
    )
    serialized = dumps_evaluation_input(evaluation_input)
    bundle = evaluate_evaluation_input(
        json.loads(serialized), generated_at=GENERATED_AT
    )
    return bundle, serialized


def accuracy_from_bundle(bundle: EvidenceBundle) -> Decimal | None:
    """Read candidate-side aggregate accuracy from the evidence bundle."""
    candidate_fp = bundle.candidate_fingerprint
    for observation in bundle.observations:
        if observation.get("candidate_fingerprint") != candidate_fp:
            continue
        metric = observation.get("metric", {})
        if metric.get("metric_id") != ACCURACY_METRIC_ID:
            continue
        if metric.get("status") != "measured":
            continue
        value = metric.get("value")
        if value is None:
            return None
        return Decimal(str(value))
    return None
