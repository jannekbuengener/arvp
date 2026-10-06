from __future__ import annotations

from datetime import datetime, timezone

import pytest

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

    first = run_scenarios(scenarios, runner=runner, clock=_fixed_clock)
    second = run_scenarios(scenarios, runner=runner, clock=_fixed_clock)
    write_scenario_manifest(first, tmp_path / "manifest.json")

    assert [result.succeeded for result in first.results] == [True, False]
    assert first.group_fingerprint == second.group_fingerprint
    assert (tmp_path / "manifest.json").is_file()


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
