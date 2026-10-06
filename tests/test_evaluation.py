from __future__ import annotations

from decimal import Decimal

import pytest

from arvp.evaluation import (
    CandidateScore,
    EvaluationError,
    EvaluationPlan,
    EvaluationWindow,
    GateCriterion,
    StabilityConfig,
    WindowResult,
    evaluate_gate,
    rank_candidates,
    resample_stability,
    run_evaluation_plan,
)
from arvp.evidence import FailureEvidence


def test_evaluation_plan_requires_ordered_non_overlapping_windows() -> None:
    plan = EvaluationPlan(
        "experiment-1",
        (
            EvaluationWindow("train", 0, 10, "train"),
            EvaluationWindow("validate", 10, 20, "validate"),
        ),
    )

    assert len(plan.windows) == 2
    assert len(plan.fingerprint()) == 64
    with pytest.raises(EvaluationError, match="ordered"):
        EvaluationPlan(
            "bad", (EvaluationWindow("a", 0, 10), EvaluationWindow("b", 9, 20))
        )


def test_run_evaluation_plan_fail_fast_by_default() -> None:
    plan = EvaluationPlan(
        "p", (EvaluationWindow("one", 0, 1), EvaluationWindow("two", 2, 3))
    )

    def runner(window: EvaluationWindow) -> WindowResult:
        if window.window_id == "one":
            raise RuntimeError("missing")
        return WindowResult("two", True)

    # Default policy is "raise" - should propagate the exception
    with pytest.raises(RuntimeError, match="missing"):
        run_evaluation_plan(plan, runner=runner)


def test_run_evaluation_plan_capture_policy() -> None:
    plan = EvaluationPlan(
        "p", (EvaluationWindow("one", 0, 1), EvaluationWindow("two", 2, 3))
    )

    def runner(window: EvaluationWindow) -> WindowResult:
        if window.window_id == "one":
            raise RuntimeError("missing")
        return WindowResult("two", True)

    results = run_evaluation_plan(plan, runner=runner, unexpected_exceptions="capture")
    assert [result.succeeded for result in results] == [False, True]

    # Check failure evidence structure
    failed_result = results[0]
    assert not failed_result.succeeded
    assert failed_result.failure is not None
    assert failed_result.failure.code == "unexpected_exception"
    assert failed_result.failure.exception_type == "RuntimeError"
    assert failed_result.failure.stage == "runner"
    assert failed_result.failure.metadata is None


def test_run_evaluation_plan_records_runner_exceptions_explicit() -> None:
    plan = EvaluationPlan(
        "p", (EvaluationWindow("one", 0, 1), EvaluationWindow("two", 2, 3))
    )

    def runner(window: EvaluationWindow) -> WindowResult:
        if window.window_id == "one":
            raise RuntimeError("missing")
        return WindowResult("two", True)

    results = run_evaluation_plan(plan, runner=runner, unexpected_exceptions="capture")
    assert [result.succeeded for result in results] == [False, True]

    # Verify the failure evidence matches expected structure
    failed_result = results[0]
    assert failed_result.failure.code == "unexpected_exception"
    assert failed_result.failure.exception_type == "RuntimeError"


def test_stability_is_deterministic_and_gate_is_explicit() -> None:
    config = StabilityConfig(sample_count=50, blocks_per_sample=3, seed=42)
    blocks = [{"score": "1.0"}, {"score": Decimal("2.0")}, {"score": "3.0"}]
    first = resample_stability(blocks, metric="score", config=config)
    second = resample_stability(blocks, metric="score", config=config)
    decision = evaluate_gate(
        {"score": first.p05}, [GateCriterion("score", "gte", Decimal("2"))]
    )

    assert first == second
    assert first.baseline == Decimal("6.0")
    assert decision.passed is True


def test_gate_and_candidate_comparison_fail_closed_and_tie_break_stably() -> None:
    with pytest.raises(EvaluationError, match="missing metric"):
        evaluate_gate({}, [GateCriterion("score", "gte", Decimal("1"))])

    ranked = rank_candidates(
        [
            CandidateScore("zeta", Decimal("2"), "a" * 64),
            CandidateScore("alpha", Decimal("2"), "b" * 64),
        ]
    )
    assert [candidate.candidate_id for candidate in ranked] == ["alpha", "zeta"]


def test_window_result_failure_evidence_expected_domain_failure() -> None:
    result = WindowResult(
        "test",
        False,
        failure=FailureEvidence.expected_domain_failure(
            stage="runner", metadata={"reason": "timeout"}
        ),
    )
    assert result.failure.code == "expected_domain_failure"
    assert result.failure.metadata == {"reason": "timeout"}
    assert result.failure.exception_type is None
    assert result.failure.stage == "runner"


def test_window_result_rejects_failure_on_success() -> None:
    with pytest.raises(EvaluationError, match="cannot have a failure"):
        WindowResult("test", True, failure=FailureEvidence(code="invalid_input"))


def test_window_result_requires_failure_on_failure() -> None:
    with pytest.raises(EvaluationError, match="failed result requires a failure"):
        WindowResult("test", False)


def test_run_evaluation_plan_rejects_unknown_exception_policy_before_runner() -> None:
    plan = EvaluationPlan("p", (EvaluationWindow("one", 0, 1),))

    with pytest.raises(EvaluationError, match="unexpected_exceptions"):
        run_evaluation_plan(
            plan,
            runner=lambda window: WindowResult(window.window_id, True),
            unexpected_exceptions="ignore",  # type: ignore[arg-type]
        )


def test_window_result_validates_and_sorts_typed_metrics_via_metric_contract() -> None:
    from arvp.metrics import MetricContract, MetricDefinition

    contract = MetricContract(
        (
            MetricDefinition("tempo.error", "minimize", "bpm", True),
            MetricDefinition("runtime.ms", "neutral", "ms", False),
        )
    )
    result = WindowResult(
        "test",
        True,
        metrics=(
            contract.value("tempo.error", "measured", 2),
            contract.value("runtime.ms", "unknown"),
        ),
        metric_contract=contract,
    )
    assert result.metric_contract == contract
    assert [value.metric_id for value in result.metrics] == [
        "runtime.ms",
        "tempo.error",
    ]


def test_window_result_rejects_untyped_metrics_and_missing_metric_contract() -> None:
    from arvp.metrics import MetricContract, MetricDefinition

    contract = MetricContract((MetricDefinition("score", "maximize", "1", True),))
    with pytest.raises(EvaluationError, match="tuple of MetricValue"):
        WindowResult("test", True, metrics={"score": 1})  # type: ignore[arg-type]
    with pytest.raises(EvaluationError, match="metric_contract"):
        WindowResult("test", True, metrics=(contract.value("score", "measured", 1),))
