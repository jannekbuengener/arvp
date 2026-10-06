from __future__ import annotations

from decimal import Decimal

import pytest

from arvp.datasets import identify_content
from arvp.identities import CandidateSpec, EvaluationPartition
from arvp.metrics import MetricContract, MetricDefinition, Observation
from arvp.stability import (
    StabilityConfig,
    StabilityError,
    paired_resample_stability,
)


def _contract() -> MetricContract:
    return MetricContract(
        (
            MetricDefinition("quality.score", "maximize", "1", True),
            MetricDefinition("error.rate", "minimize", "1", True),
        )
    )


def _partition(seed: str = "a") -> EvaluationPartition:
    content = identify_content([{"id": seed}], fields=("id",), ordering="ordered")
    return EvaluationPartition("validation", "validation", content)


def _candidate(candidate_id: str) -> CandidateSpec:
    return CandidateSpec(candidate_id, "impl.eval", "r1", {"depth": 1})


def _obs(
    contract: MetricContract,
    *,
    candidate_id: str,
    metric_id: str,
    observation_id: str,
    value: Decimal | int,
    partition: EvaluationPartition | None = None,
) -> Observation:
    part = partition if partition is not None else _partition()
    return Observation(
        observation_id=observation_id,
        candidate=_candidate(candidate_id),
        partition=part,
        metric_contract=contract,
        metric=contract.value(metric_id, "measured", value),
    )


def test_identical_inputs_and_seed_are_deterministic() -> None:
    contract = _contract()
    baseline = (
        _obs(
            contract,
            candidate_id="b",
            metric_id="quality.score",
            observation_id="o1",
            value=1,
        ),
        _obs(
            contract,
            candidate_id="b",
            metric_id="quality.score",
            observation_id="o2",
            value=3,
        ),
        _obs(
            contract,
            candidate_id="b",
            metric_id="quality.score",
            observation_id="o3",
            value=5,
        ),
    )
    candidate = (
        _obs(
            contract,
            candidate_id="c",
            metric_id="quality.score",
            observation_id="o2",
            value=4,
        ),
        _obs(
            contract,
            candidate_id="c",
            metric_id="quality.score",
            observation_id="o1",
            value=2,
        ),
        _obs(
            contract,
            candidate_id="c",
            metric_id="quality.score",
            observation_id="o3",
            value=6,
        ),
    )
    config = StabilityConfig(
        aggregation="mean", sample_count=40, blocks_per_sample=3, seed=7
    )
    first = paired_resample_stability(
        baseline=baseline,
        candidate=candidate,
        metric_contract=contract,
        metric_id="quality.score",
        config=config,
    )
    second = paired_resample_stability(
        baseline=baseline,
        candidate=candidate,
        metric_contract=contract,
        metric_id="quality.score",
        config=config,
    )
    assert first == second
    assert first.status == "complete"
    assert first.observed_delta == Decimal("1")
    assert first.p05 <= first.p50 <= first.p95
    assert first.favors_candidate is True


def test_different_seed_changes_distribution_not_observed_aggregate() -> None:
    contract = _contract()
    # Heterogeneous pair deltas so resampling distribution depends on seed.
    baseline_values = (1, 2, 3, 4, 10)
    candidate_values = (2, 2, 5, 9, 11)
    baseline = tuple(
        _obs(
            contract,
            candidate_id="b",
            metric_id="quality.score",
            observation_id=f"o{i}",
            value=baseline_values[i],
        )
        for i in range(5)
    )
    candidate = tuple(
        _obs(
            contract,
            candidate_id="c",
            metric_id="quality.score",
            observation_id=f"o{i}",
            value=candidate_values[i],
        )
        for i in range(5)
    )
    left = paired_resample_stability(
        baseline=baseline,
        candidate=candidate,
        metric_contract=contract,
        metric_id="quality.score",
        config=StabilityConfig("mean", 80, 5, seed=1),
    )
    right = paired_resample_stability(
        baseline=baseline,
        candidate=candidate,
        metric_contract=contract,
        metric_id="quality.score",
        config=StabilityConfig("mean", 80, 5, seed=2),
    )
    assert left.observed_delta == right.observed_delta
    assert (left.p05, left.p50, left.p95) != (right.p05, right.p50, right.p95)


def test_mean_and_sum_are_not_conflated() -> None:
    contract = _contract()
    baseline = (
        _obs(
            contract,
            candidate_id="b",
            metric_id="quality.score",
            observation_id="o1",
            value=2,
        ),
        _obs(
            contract,
            candidate_id="b",
            metric_id="quality.score",
            observation_id="o2",
            value=4,
        ),
    )
    candidate = (
        _obs(
            contract,
            candidate_id="c",
            metric_id="quality.score",
            observation_id="o1",
            value=4,
        ),
        _obs(
            contract,
            candidate_id="c",
            metric_id="quality.score",
            observation_id="o2",
            value=6,
        ),
    )
    mean_result = paired_resample_stability(
        baseline=baseline,
        candidate=candidate,
        metric_contract=contract,
        metric_id="quality.score",
        config=StabilityConfig("mean", 20, 2, seed=3),
    )
    sum_result = paired_resample_stability(
        baseline=baseline,
        candidate=candidate,
        metric_contract=contract,
        metric_id="quality.score",
        config=StabilityConfig("sum", 20, 2, seed=3),
    )
    assert mean_result.observed_delta == Decimal("2")
    assert sum_result.observed_delta == Decimal("4")
    assert mean_result.request_fingerprint != sum_result.request_fingerprint


def test_sum_rejects_silent_scale_mismatch() -> None:
    contract = _contract()
    baseline = (
        _obs(
            contract,
            candidate_id="b",
            metric_id="quality.score",
            observation_id="o1",
            value=1,
        ),
        _obs(
            contract,
            candidate_id="b",
            metric_id="quality.score",
            observation_id="o2",
            value=1,
        ),
        _obs(
            contract,
            candidate_id="b",
            metric_id="quality.score",
            observation_id="o3",
            value=1,
        ),
    )
    candidate = (
        _obs(
            contract,
            candidate_id="c",
            metric_id="quality.score",
            observation_id="o1",
            value=2,
        ),
        _obs(
            contract,
            candidate_id="c",
            metric_id="quality.score",
            observation_id="o2",
            value=2,
        ),
        _obs(
            contract,
            candidate_id="c",
            metric_id="quality.score",
            observation_id="o3",
            value=2,
        ),
    )
    with pytest.raises(StabilityError, match="scale mismatch"):
        paired_resample_stability(
            baseline=baseline,
            candidate=candidate,
            metric_contract=contract,
            metric_id="quality.score",
            config=StabilityConfig("sum", 10, 2, seed=1),
        )


def test_pairing_is_order_independent() -> None:
    contract = _contract()
    baseline = (
        _obs(
            contract,
            candidate_id="b",
            metric_id="quality.score",
            observation_id="z",
            value=1,
        ),
        _obs(
            contract,
            candidate_id="b",
            metric_id="quality.score",
            observation_id="a",
            value=2,
        ),
    )
    candidate_a = (
        _obs(
            contract,
            candidate_id="c",
            metric_id="quality.score",
            observation_id="a",
            value=4,
        ),
        _obs(
            contract,
            candidate_id="c",
            metric_id="quality.score",
            observation_id="z",
            value=3,
        ),
    )
    candidate_b = (
        _obs(
            contract,
            candidate_id="c",
            metric_id="quality.score",
            observation_id="z",
            value=3,
        ),
        _obs(
            contract,
            candidate_id="c",
            metric_id="quality.score",
            observation_id="a",
            value=4,
        ),
    )
    config = StabilityConfig("mean", 30, 2, seed=9)
    left = paired_resample_stability(
        baseline=baseline,
        candidate=candidate_a,
        metric_contract=contract,
        metric_id="quality.score",
        config=config,
    )
    right = paired_resample_stability(
        baseline=baseline,
        candidate=candidate_b,
        metric_contract=contract,
        metric_id="quality.score",
        config=config,
    )
    assert left == right


def test_missing_pair_is_incomplete() -> None:
    contract = _contract()
    baseline = (
        _obs(
            contract,
            candidate_id="b",
            metric_id="quality.score",
            observation_id="o1",
            value=1,
        ),
        _obs(
            contract,
            candidate_id="b",
            metric_id="quality.score",
            observation_id="o2",
            value=2,
        ),
    )
    candidate = (
        _obs(
            contract,
            candidate_id="c",
            metric_id="quality.score",
            observation_id="o1",
            value=3,
        ),
    )
    result = paired_resample_stability(
        baseline=baseline,
        candidate=candidate,
        metric_contract=contract,
        metric_id="quality.score",
        config=StabilityConfig("mean", 10, 1, seed=1),
    )
    assert result.status == "incomplete"
    assert "missing_candidate_pairs" in result.reasons
    assert result.observed_delta is None


def test_minimize_direction_interpretation() -> None:
    contract = _contract()
    baseline = (
        _obs(
            contract,
            candidate_id="b",
            metric_id="error.rate",
            observation_id="o1",
            value=5,
        ),
    )
    candidate = (
        _obs(
            contract,
            candidate_id="c",
            metric_id="error.rate",
            observation_id="o1",
            value=3,
        ),
    )
    result = paired_resample_stability(
        baseline=baseline,
        candidate=candidate,
        metric_contract=contract,
        metric_id="error.rate",
        config=StabilityConfig("mean", 12, 1, seed=4),
    )
    assert result.observed_delta == Decimal("-2")
    assert result.favors_candidate is True


def test_config_fingerprint_changes_with_seed_and_aggregation() -> None:
    a = StabilityConfig("mean", 10, 2, seed=1)
    b = StabilityConfig("mean", 10, 2, seed=2)
    c = StabilityConfig("sum", 10, 2, seed=1)
    assert a.fingerprint() != b.fingerprint()
    assert a.fingerprint() != c.fingerprint()
