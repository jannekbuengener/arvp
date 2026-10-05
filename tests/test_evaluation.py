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


def test_run_evaluation_plan_records_runner_exceptions() -> None:
    plan = EvaluationPlan(
        "p", (EvaluationWindow("one", 0, 1), EvaluationWindow("two", 2, 3))
    )

    def runner(window: EvaluationWindow) -> WindowResult:
        if window.window_id == "one":
            raise RuntimeError("missing")
        return WindowResult("two", True, {"score": 1})

    results = run_evaluation_plan(plan, runner=runner)
    assert [result.succeeded for result in results] == [False, True]
    assert results[0].failure_reason == "RuntimeError: missing"


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
