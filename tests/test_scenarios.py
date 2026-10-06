from __future__ import annotations

from datetime import datetime, timezone

import pytest

from arvp.evidence import FailureCode, FailureEvidence
from arvp.scenarios import (
    SCENARIO_CONTRACT_VERSION,
    Scenario,
    ScenarioError,
    ScenarioResult,
    run_scenarios,
    write_scenario_manifest,
)

_FP_A = "a" * 64
_FP_B = "b" * 64
_FP_C = "c" * 64
_FP_D = "d" * 64


def _fixed_clock() -> datetime:
    return datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


def _later_clock() -> datetime:
    return datetime(2026, 10, 5, 18, 30, tzinfo=timezone.utc)


def _scenario(
    scenario_id: str,
    *,
    parameters: dict | None = None,
    candidate_fingerprint: str = _FP_A,
    suite_fingerprint: str = _FP_B,
    partition_fingerprint: str = _FP_C,
    execution_mode: str = "in_process",
    configuration: dict | None = None,
    description: str = "desc",
) -> Scenario:
    return Scenario(
        scenario_id,
        description,
        {} if parameters is None else parameters,
        candidate_fingerprint=candidate_fingerprint,
        suite_fingerprint=suite_fingerprint,
        partition_fingerprint=partition_fingerprint,
        execution_mode=execution_mode,
        configuration=configuration,
    )


def test_scenario_contract_version() -> None:
    assert SCENARIO_CONTRACT_VERSION == "arvp.scenario.v2"
    assert _scenario("one").contract_version == SCENARIO_CONTRACT_VERSION


def test_scenario_harness_runs_all_variants_and_has_stable_outcome_fingerprint(
    tmp_path,
) -> None:
    scenarios = [
        _scenario("baseline", parameters={"limit": 2}),
        _scenario("variant", parameters={"limit": 3}),
    ]

    def runner(scenario: Scenario) -> ScenarioResult:
        if scenario.scenario_id == "variant":
            raise RuntimeError("input unavailable")
        return ScenarioResult(
            scenario.scenario_id, 0, request_fingerprint=scenario.fingerprint()
        )

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

    failed_result = first.results[1]
    assert not failed_result.succeeded
    assert failed_result.failure is not None
    assert failed_result.failure.code == "unexpected_exception"
    assert failed_result.failure.exception_type == "RuntimeError"
    assert failed_result.failure.stage == "runner"
    assert failed_result.failure.metadata is None


def test_scenario_fingerprint_changes_with_params_candidate_suite_or_mode() -> None:
    base = _scenario("one", parameters={"limit": 1})
    assert base.fingerprint() != _scenario("one", parameters={"limit": 2}).fingerprint()
    assert (
        base.fingerprint()
        != _scenario("one", candidate_fingerprint=_FP_D).fingerprint()
    )
    assert base.fingerprint() != _scenario("one", suite_fingerprint=_FP_D).fingerprint()
    assert (
        base.fingerprint()
        != _scenario("one", partition_fingerprint=_FP_D).fingerprint()
    )
    assert (
        base.fingerprint()
        != _scenario("one", execution_mode="offline_batch").fingerprint()
    )
    assert (
        base.fingerprint() != _scenario("one", configuration={"seed": 1}).fingerprint()
    )


def test_group_fingerprint_stable_when_only_wall_clock_changes() -> None:
    scenarios = [_scenario("baseline", parameters={"limit": 2})]

    def runner(scenario: Scenario) -> ScenarioResult:
        return ScenarioResult(
            scenario.scenario_id, 0, request_fingerprint=scenario.fingerprint()
        )

    first = run_scenarios(scenarios, runner=runner, clock=_fixed_clock)
    second = run_scenarios(scenarios, runner=runner, clock=_later_clock)
    assert first.group_fingerprint == second.group_fingerprint
    assert first.started_at_utc != second.started_at_utc


def test_scenario_harness_fail_fast_by_default() -> None:
    scenarios = [
        _scenario("baseline", parameters={"limit": 2}),
        _scenario("variant", parameters={"limit": 3}),
    ]

    def runner(scenario: Scenario) -> ScenarioResult:
        if scenario.scenario_id == "variant":
            raise RuntimeError("input unavailable")
        return ScenarioResult(
            scenario.scenario_id, 0, request_fingerprint=scenario.fingerprint()
        )

    with pytest.raises(RuntimeError, match="input unavailable"):
        run_scenarios(scenarios, runner=runner, clock=_fixed_clock)


def test_scenario_harness_explicit_capture_policy() -> None:
    scenarios = [_scenario("flaky", parameters={"attempt": 1})]

    def runner(scenario: Scenario) -> ScenarioResult:
        raise RuntimeError("input unavailable")

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
    assert first.to_dict() == second.to_dict()
    failed_result = first.results[0]
    assert failed_result.failure is not None
    assert failed_result.failure.code == "unexpected_exception"
    assert failed_result.failure.exception_type == "RuntimeError"


def test_scenario_harness_rejects_wrong_runner_contract() -> None:
    scenario = _scenario("one")
    with pytest.raises(ScenarioError, match="ScenarioResult"):
        run_scenarios([scenario], runner=lambda _: "wrong")  # type: ignore[arg-type]


def test_scenario_rejects_sensitive_parameters() -> None:
    with pytest.raises(ScenarioError, match="forbidden"):
        _scenario("one", parameters={"token": "secret"})


def test_run_scenarios_rejects_duplicate_scenario_ids() -> None:
    scenarios = [_scenario("dup"), _scenario("dup")]
    with pytest.raises(ScenarioError, match="duplicate scenario_id"):
        run_scenarios(
            scenarios,
            runner=lambda item: ScenarioResult(
                item.scenario_id, 0, request_fingerprint=item.fingerprint()
            ),
            clock=_fixed_clock,
        )


def test_run_scenarios_wraps_group_id_canonicalization_error() -> None:
    scenario = _scenario("\ud800")

    with pytest.raises(ScenarioError, match="canonical"):
        run_scenarios(
            [scenario],
            runner=lambda item: ScenarioResult(
                item.scenario_id, 0, request_fingerprint=item.fingerprint()
            ),
            clock=_fixed_clock,
        )


def test_scenario_result_failure_evidence_expected_domain_failure() -> None:
    result = ScenarioResult(
        "test",
        1,
        request_fingerprint=_FP_A,
        failure=FailureEvidence.expected_domain_failure(
            stage="runner", metadata={"reason": "timeout"}
        ),
    )
    assert result.failure is not None
    assert result.failure.code == "expected_domain_failure"
    assert result.failure.metadata == {"reason": "timeout"}


def test_scenario_result_rejects_failure_on_success() -> None:
    with pytest.raises(ScenarioError, match="cannot have a failure"):
        ScenarioResult(
            "test",
            0,
            request_fingerprint=_FP_A,
            failure=FailureEvidence(code="invalid_input"),
        )


def test_scenario_result_requires_failure_on_failure() -> None:
    with pytest.raises(ScenarioError, match="failed scenarios require a failure"):
        ScenarioResult("test", 1, request_fingerprint=_FP_A)


def test_failure_evidence_codes() -> None:
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
    scenario = _scenario("one")

    with pytest.raises(ScenarioError, match="unexpected_exceptions"):
        run_scenarios(
            [scenario],
            runner=lambda item: ScenarioResult(
                item.scenario_id, 0, request_fingerprint=item.fingerprint()
            ),
            clock=_fixed_clock,
            unexpected_exceptions="ignore",  # type: ignore[arg-type]
        )


def test_scenario_result_validates_and_serializes_typed_metrics_via_metric_contract() -> (
    None
):
    from arvp.metrics import MetricContract, MetricDefinition

    contract = MetricContract(
        (
            MetricDefinition("tempo.error", "minimize", "bpm", True),
            MetricDefinition("runtime.ms", "neutral", "ms", False),
        )
    )
    result = ScenarioResult(
        "test",
        0,
        request_fingerprint=_FP_A,
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
    assert result.to_dict()["metric_contract_fingerprint"] == contract.fingerprint()


def test_scenario_result_rejects_untyped_metrics_and_missing_metric_contract() -> None:
    from arvp.metrics import MetricContract, MetricDefinition

    contract = MetricContract((MetricDefinition("score", "maximize", "1", True),))
    with pytest.raises(ScenarioError, match="tuple of MetricValue"):
        ScenarioResult("test", 0, request_fingerprint=_FP_A, metrics={"score": 1})  # type: ignore[arg-type]
    with pytest.raises(ScenarioError, match="metric_contract"):
        ScenarioResult(
            "test",
            0,
            request_fingerprint=_FP_A,
            metrics=(contract.value("score", "measured", 1),),
        )
