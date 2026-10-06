from __future__ import annotations

from decimal import Decimal

import pytest

from arvp.datasets import identify_content
from arvp.gates import GateContractError, compare_observation_scope
from arvp.identities import CandidateSpec, EvaluationPartition
from arvp.metrics import MetricContract, MetricDefinition, Observation


def _contract() -> MetricContract:
    return MetricContract(
        (
            MetricDefinition("bias", "neutral", "1", False),
            MetricDefinition("error.rate", "minimize", "1", True),
            MetricDefinition("quality.score", "maximize", "1", True),
        )
    )


def _partition(
    seed: str = "a", partition_id: str = "validation"
) -> EvaluationPartition:
    content = identify_content([{"id": seed}], fields=("id",), ordering="ordered")
    return EvaluationPartition(partition_id, "validation", content)


def _candidate(candidate_id: str) -> CandidateSpec:
    return CandidateSpec(candidate_id, "impl.eval", "r1", {"depth": 2})


def _observation(
    contract: MetricContract,
    *,
    candidate_id: str,
    partition: EvaluationPartition,
    metric_id: str,
    status: str = "measured",
    value: int | float | Decimal | None = None,
    observation_id: str = "aggregate",
) -> Observation:
    metric = contract.value(metric_id, status, value)  # type: ignore[arg-type]
    return Observation(
        observation_id=observation_id,
        candidate=_candidate(candidate_id),
        partition=partition,
        metric_contract=contract,
        metric=metric,
    )


def test_comparison_maximize_preserves_raw_and_directional_delta() -> None:
    contract = _contract()
    partition = _partition()
    baseline = _observation(
        contract,
        candidate_id="baseline",
        partition=partition,
        metric_id="quality.score",
        value=100,
    )
    candidate = _observation(
        contract,
        candidate_id="candidate",
        partition=partition,
        metric_id="quality.score",
        value=110,
    )

    (comparison,) = compare_observation_scope(
        baseline=(baseline,), candidate=(candidate,), metric_contract=contract
    )

    assert comparison.status == "complete"
    assert comparison.absolute_delta == Decimal("10")
    assert comparison.relative_delta == Decimal("0.1")
    assert comparison.directional_relative_delta == Decimal("0.1")
    assert comparison.direction_result == "improved"
    assert comparison.reasons == ()


def test_comparison_minimize_flips_directional_interpretation_only() -> None:
    contract = _contract()
    partition = _partition()
    baseline = _observation(
        contract,
        candidate_id="baseline",
        partition=partition,
        metric_id="error.rate",
        value=10,
    )
    candidate = _observation(
        contract,
        candidate_id="candidate",
        partition=partition,
        metric_id="error.rate",
        value=8,
    )

    (comparison,) = compare_observation_scope(
        baseline=(baseline,), candidate=(candidate,), metric_contract=contract
    )

    assert comparison.absolute_delta == Decimal("-2")
    assert comparison.relative_delta == Decimal("-0.2")
    assert comparison.directional_relative_delta == Decimal("0.2")
    assert comparison.direction_result == "improved"


def test_comparison_neutral_keeps_raw_delta_without_better_worse_claim() -> None:
    contract = _contract()
    partition = _partition()
    baseline = _observation(
        contract,
        candidate_id="baseline",
        partition=partition,
        metric_id="bias",
        value=-2,
    )
    candidate = _observation(
        contract,
        candidate_id="candidate",
        partition=partition,
        metric_id="bias",
        value=1,
    )

    (comparison,) = compare_observation_scope(
        baseline=(baseline,), candidate=(candidate,), metric_contract=contract
    )

    assert comparison.absolute_delta == Decimal("3")
    assert comparison.relative_delta == Decimal("1.5")
    assert comparison.directional_relative_delta is None
    assert comparison.direction_result is None


def test_comparison_negative_baseline_uses_absolute_baseline_magnitude() -> None:
    contract = _contract()
    partition = _partition()
    baseline = _observation(
        contract,
        candidate_id="baseline",
        partition=partition,
        metric_id="quality.score",
        value=-100,
    )
    candidate = _observation(
        contract,
        candidate_id="candidate",
        partition=partition,
        metric_id="quality.score",
        value=-90,
    )

    (comparison,) = compare_observation_scope(
        baseline=(baseline,), candidate=(candidate,), metric_contract=contract
    )

    assert comparison.absolute_delta == Decimal("10")
    assert comparison.relative_delta == Decimal("0.1")
    assert comparison.directional_relative_delta == Decimal("0.1")


def test_comparison_zero_baseline_keeps_absolute_delta_and_marks_relative_undefined() -> (
    None
):
    contract = _contract()
    partition = _partition()
    baseline = _observation(
        contract,
        candidate_id="baseline",
        partition=partition,
        metric_id="quality.score",
        value=0,
    )
    candidate = _observation(
        contract,
        candidate_id="candidate",
        partition=partition,
        metric_id="quality.score",
        value=5,
    )

    (comparison,) = compare_observation_scope(
        baseline=(baseline,), candidate=(candidate,), metric_contract=contract
    )

    assert comparison.status == "complete"
    assert comparison.absolute_delta == Decimal("5")
    assert comparison.relative_delta is None
    assert comparison.relative_delta_reason == "baseline_zero"
    assert comparison.directional_relative_delta is None


def test_comparison_unknown_is_incomplete_without_numeric_delta() -> None:
    contract = _contract()
    partition = _partition()
    baseline = _observation(
        contract,
        candidate_id="baseline",
        partition=partition,
        metric_id="quality.score",
        value=100,
    )
    candidate = _observation(
        contract,
        candidate_id="candidate",
        partition=partition,
        metric_id="quality.score",
        status="unknown",
    )

    (comparison,) = compare_observation_scope(
        baseline=(baseline,), candidate=(candidate,), metric_contract=contract
    )

    assert comparison.status == "incomplete"
    assert comparison.absolute_delta is None
    assert comparison.candidate_value is None
    assert "unknown_value" in comparison.reasons


def test_comparison_not_applicable_is_explicit() -> None:
    contract = _contract()
    partition = _partition()
    baseline = _observation(
        contract,
        candidate_id="baseline",
        partition=partition,
        metric_id="bias",
        status="not_applicable",
    )
    candidate = _observation(
        contract,
        candidate_id="candidate",
        partition=partition,
        metric_id="bias",
        status="not_applicable",
    )

    (comparison,) = compare_observation_scope(
        baseline=(baseline,), candidate=(candidate,), metric_contract=contract
    )

    assert comparison.status == "not_applicable"
    assert comparison.absolute_delta is None
    assert comparison.reasons == ("not_applicable",)


def test_comparison_missing_candidate_preserves_baseline_evidence() -> None:
    contract = _contract()
    partition = _partition()
    baseline = _observation(
        contract,
        candidate_id="baseline",
        partition=partition,
        metric_id="quality.score",
        value=100,
    )

    (comparison,) = compare_observation_scope(
        baseline=(baseline,), candidate=(), metric_contract=contract
    )

    assert comparison.status == "incomplete"
    assert comparison.baseline_value == Decimal("100")
    assert comparison.candidate_value is None
    assert comparison.candidate_fingerprint is None
    assert comparison.reasons == ("missing_candidate",)


def test_comparison_partition_mismatch_never_calculates_delta() -> None:
    contract = _contract()
    baseline = _observation(
        contract,
        candidate_id="baseline",
        partition=_partition("a"),
        metric_id="quality.score",
        value=100,
    )
    candidate = _observation(
        contract,
        candidate_id="candidate",
        partition=_partition("b"),
        metric_id="quality.score",
        value=110,
    )

    (comparison,) = compare_observation_scope(
        baseline=(baseline,), candidate=(candidate,), metric_contract=contract
    )

    assert comparison.status == "incomplete"
    assert comparison.absolute_delta is None
    assert "partition_mismatch" in comparison.reasons


def test_comparison_metric_contract_mismatch_never_calculates_delta() -> None:
    contract = _contract()
    foreign = MetricContract(
        (
            MetricDefinition("bias", "neutral", "1", False),
            MetricDefinition("error.rate", "minimize", "1", True),
            MetricDefinition("quality.score", "maximize", "percent", True),
        )
    )
    partition = _partition()
    baseline = _observation(
        contract,
        candidate_id="baseline",
        partition=partition,
        metric_id="quality.score",
        value=100,
    )
    candidate = _observation(
        foreign,
        candidate_id="candidate",
        partition=partition,
        metric_id="quality.score",
        value=110,
    )

    (comparison,) = compare_observation_scope(
        baseline=(baseline,), candidate=(candidate,), metric_contract=contract
    )

    assert comparison.status == "incomplete"
    assert comparison.candidate_value == Decimal("110")
    assert comparison.candidate_compatible is False
    assert comparison.absolute_delta is None
    assert "metric_contract_mismatch" in comparison.reasons


def test_comparison_output_order_is_input_order_independent() -> None:
    contract = _contract()
    partition = _partition()
    baseline = (
        _observation(
            contract,
            candidate_id="baseline",
            partition=partition,
            metric_id="quality.score",
            value=100,
        ),
        _observation(
            contract,
            candidate_id="baseline",
            partition=partition,
            metric_id="error.rate",
            value=10,
        ),
    )
    candidate = (
        _observation(
            contract,
            candidate_id="candidate",
            partition=partition,
            metric_id="quality.score",
            value=105,
        ),
        _observation(
            contract,
            candidate_id="candidate",
            partition=partition,
            metric_id="error.rate",
            value=9,
        ),
    )

    first = compare_observation_scope(
        baseline=baseline, candidate=candidate, metric_contract=contract
    )
    second = compare_observation_scope(
        baseline=tuple(reversed(baseline)),
        candidate=tuple(reversed(candidate)),
        metric_contract=contract,
    )

    assert [item.metric_id for item in first] == ["error.rate", "quality.score"]
    assert [item.to_dict() for item in first] == [item.to_dict() for item in second]
    assert [item.fingerprint() for item in first] == [
        item.fingerprint() for item in second
    ]


def test_comparison_rejects_mixed_candidate_scope_within_one_side() -> None:
    contract = _contract()
    partition = _partition()
    baseline = (
        _observation(
            contract,
            candidate_id="baseline-a",
            partition=partition,
            metric_id="quality.score",
            value=100,
        ),
        _observation(
            contract,
            candidate_id="baseline-b",
            partition=partition,
            metric_id="error.rate",
            value=10,
        ),
    )

    with pytest.raises(GateContractError, match="one candidate"):
        compare_observation_scope(
            baseline=baseline, candidate=(), metric_contract=contract
        )


def test_comparison_rejects_mixed_partition_scope_within_one_side() -> None:
    contract = _contract()
    baseline = (
        _observation(
            contract,
            candidate_id="baseline",
            partition=_partition("a"),
            metric_id="quality.score",
            value=100,
        ),
        _observation(
            contract,
            candidate_id="baseline",
            partition=_partition("b"),
            metric_id="error.rate",
            value=10,
        ),
    )

    with pytest.raises(GateContractError, match="one partition"):
        compare_observation_scope(
            baseline=baseline, candidate=(), metric_contract=contract
        )


def test_comparison_rejects_duplicate_metric_observation_key() -> None:
    contract = _contract()
    partition = _partition()
    item = _observation(
        contract,
        candidate_id="baseline",
        partition=partition,
        metric_id="quality.score",
        value=100,
    )

    with pytest.raises(GateContractError, match="duplicate observation key"):
        compare_observation_scope(
            baseline=(item, item), candidate=(), metric_contract=contract
        )


def test_comparison_rejects_both_sides_empty() -> None:
    with pytest.raises(GateContractError, match="at least one observation"):
        compare_observation_scope(
            baseline=(), candidate=(), metric_contract=_contract()
        )
