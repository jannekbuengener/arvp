from __future__ import annotations

from datetime import datetime, timezone

import pytest

from arvp.evidence import FailureCode
from arvp.scenarios import (
    Scenario,
    ScenarioError,
    ScenarioResult,
    run_scenarios,
    write_scenario_manifest,
)


def _fixed_clock() -> datetime:
    return datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


def test_scenario_harness_runs_all_variants_and_has_stable_outcome_fingerprint(
    tmp_path,
) -> None:
    scenarios = [
        Scenario("baseline", "Reference candidate", {"limit": 2}),
        Scenario("variant", "Changed candidate", {"limit": 3}),
    ]

    def runner(scenario: Scenario) -> ScenarioResult:
        if scenario.scenario_id == "variant":
            raise RuntimeError("input unavailable")
        return ScenarioResult(scenario.scenario_id, 0, metrics={"score": 1})

    first = run_scenarios(
        scenarios, runner=runner, clock=_fixed_clock, unexpected_exceptions="capture"
    )
    second = run_scenarios(
        scenarios, runner=runner, clock=_fixed_clock, unexpected_exceptions="capture"
    )
    write_scenario_manifest(first, tmp_path / "manifest.json")

    assert [result.succeeded for result in first.results] == [True, False]
    assert first.group_fingerprint == second.group_fingerprint
    assert (tmp_path / "manifest.json").is_file()

    # Check failure evidence structure
    failed_result = first.results[1]
    assert not failed_result.succeeded
    assert failed_result.failure is not None
    assert failed_result.failure.code == "unexpected_exception"
    assert failed_result.failure.exception_type == "RuntimeError"
    assert failed_result.failure.stage == "runner"
    assert failed_result.failure.metadata is None


def test_scenario_harness_fail_fast_by_default() -> None:
    scenarios = [
        Scenario("baseline", "Reference candidate", {"limit": 2}),
        Scenario("variant", "Changed candidate", {"limit": 3}),
    ]

    def runner(scenario: Scenario) -> ScenarioResult:
        if scenario.scenario_id == "variant":
            raise RuntimeError("input unavailable")
        return ScenarioResult(scenario.scenario_id, 0, metrics={"score": 1})

    # Default policy is "raise" - should propagate the exception
    with pytest.raises(RuntimeError, match="input unavailable"):
        run_scenarios(scenarios, runner=runner, clock=_fixed_clock)


def test_scenario_harness_explicit_capture_policy() -> None:
    scenarios = [
        Scenario("flaky", "Always unavailable candidate", {"attempt": 1}),
    ]

    def runner(scenario: Scenario) -> ScenarioResult:
        raise RuntimeError("input unavailable")

    # Explicit capture policy
    first = run_scenarios(
        scenarios,
        runner=runner,
        clock=_fixed_clock,
        unexpected_exceptions="capture",
    )
    second = run_scenarios(
        scenarios,
        runner=runner,
        clock=_fixed_clock,
        unexpected_exceptions="capture",
    )

    assert [result.succeeded for result in first.results] == [False]
    assert first.to_dict() == second.to_dict(), "failure evidence not repeatable"

    # Check failure evidence structure
    failed_result = first.results[0]
    assert not failed_result.succeeded
    assert failed_result.failure is not None
    assert failed_result.failure.code == "unexpected_exception"
    assert failed_result.failure.exception_type == "RuntimeError"
    assert failed_result.failure.stage == "runner"
    assert failed_result.failure.metadata is None


def test_scenario_harness_rejects_wrong_runner_contract() -> None:
    scenario = Scenario("one", "Only", {})
    with pytest.raises(ScenarioError, match="ScenarioResult"):
        run_scenarios([scenario], runner=lambda _: "wrong")  # type: ignore[arg-type]


def test_scenario_rejects_sensitive_parameters() -> None:
    with pytest.raises(ScenarioError, match="forbidden"):
        Scenario("one", "Only", {"token": "secret"})


def test_run_scenarios_wraps_group_id_canonicalization_error() -> None:
    scenario = Scenario("\ud800", "Only", {})

    with pytest.raises(ScenarioError, match="canonical"):
        run_scenarios(
            [scenario],
            runner=lambda item: ScenarioResult(item.scenario_id, 0, metrics={}),
            clock=_fixed_clock,
        )


def test_scenario_result_failure_evidence_expected_domain_failure() -> None:
    from arvp.evidence import FailureEvidence

    result = ScenarioResult(
        "test",
        1,
        failure=FailureEvidence.expected_domain_failure(
            stage="runner", metadata={"reason": "timeout"}
        ),
    )
    assert result.failure.code == "expected_domain_failure"
    assert result.failure.metadata == {"reason": "timeout"}
    assert result.failure.exception_type is None
    assert result.failure.stage == "runner"


def test_scenario_result_rejects_failure_on_success() -> None:
    from arvp.evidence import FailureEvidence

    with pytest.raises(ScenarioError, match="cannot have a failure"):
        ScenarioResult("test", 0, failure=FailureEvidence(code="invalid_input"))


def test_scenario_result_requires_failure_on_failure() -> None:
    with pytest.raises(ScenarioError, match="failed scenarios require a failure"):
        ScenarioResult("test", 1)


def test_failure_evidence_codes() -> None:
    from arvp.evidence import FailureEvidence

    # Test all valid failure codes
    codes: list[FailureCode] = [
        "expected_domain_failure",
        "input_unavailable",
        "invalid_input",
        "unexpected_exception",
        "insufficient_evidence",
    ]
    for code in codes:
        evidence = FailureEvidence(code=code)
        assert evidence.code == code


def test_run_scenarios_rejects_unknown_exception_policy_before_runner() -> None:
    scenario = Scenario("one", "Only", {})

    with pytest.raises(ScenarioError, match="unexpected_exceptions"):
        run_scenarios(
            [scenario],
            runner=lambda item: ScenarioResult(item.scenario_id, 0, metrics={}),
            clock=_fixed_clock,
            unexpected_exceptions="ignore",  # type: ignore[arg-type]
        )
