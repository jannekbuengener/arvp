"""Platform smoke probe for ARVP Issue #3.

Runs the same focused semantic probe on every platform so that CI proves the
core contracts execute and repeat identically inside one environment.

This probe deliberately does NOT freeze any hash value as a long-term contract:
canonical v2 semantics and golden vectors belong to Issue #4.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from arvp.canonical import canonical_hash, canonical_json_dumps
from arvp.datasets import identify_content
from arvp.scenarios import Scenario, ScenarioResult, run_scenarios


def fixed_clock() -> datetime:
    return datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)


def probe_canonical_json_dumps_repeatable() -> None:
    payload = {
        "z": 26,
        "a": 1,
        "nested": {"gamma": [3, 2, 1], "alpha": None},
        "decimal": Decimal("2.500"),
        "negative_zero": -0.0,
    }

    first = canonical_json_dumps(payload)
    second = canonical_json_dumps(dict(reversed(list(payload.items()))))

    assert first == canonical_json_dumps(payload), "canonical_json_dumps not repeatable"
    assert first == second, "canonical_json_dumps depends on mapping order"
    assert isinstance(first, str)


def probe_canonical_hash_repeatable() -> None:
    payload = {
        "rows": [{"id": 3, "score": "1.5"}, {"id": 1, "score": "0.5"}],
        "count": 2,
    }

    first = canonical_hash(payload)
    second = canonical_hash(payload)

    assert first == second, "canonical_hash not repeatable"
    assert len(first) == 64, f"expected 64 hex characters, got {len(first)}"


def probe_identify_content_repeatable() -> None:
    records = [
        {"ts": 2, "score": "1.5", "ignored": "x"},
        {"ts": 1, "score": "1.0", "ignored": "y"},
        {"ts": 3, "score": "2.0", "ignored": "z"},
    ]

    first = identify_content(records, fields=("ts", "score"), order_by="ts")
    second = identify_content(records, fields=("ts", "score"), order_by="ts")

    assert first.fingerprint == second.fingerprint, "identify_content not repeatable"
    assert first.record_count == 3, f"unexpected record count {first.record_count}"


def probe_run_scenarios_repeatable() -> None:
    scenarios = [
        Scenario("baseline", "Reference candidate", {"threshold": 1}),
        Scenario("variant", "Modified candidate", {"threshold": 2}),
    ]

    def runner(scenario: Scenario) -> ScenarioResult:
        threshold = int(scenario.parameters["threshold"])
        return ScenarioResult(
            scenario.scenario_id,
            0,
            metrics={"score": Decimal(threshold) / Decimal(10)},
        )

    first = run_scenarios(scenarios, runner=runner, clock=fixed_clock)
    second = run_scenarios(scenarios, runner=runner, clock=fixed_clock)

    assert [result.succeeded for result in first.results] == [True, True], (
        "synthetic scenarios must succeed"
    )
    assert first.group_fingerprint == second.group_fingerprint, (
        "scenario group fingerprint not repeatable"
    )
    assert first.to_dict() == second.to_dict(), "scenario manifest not repeatable"


def probe_run_scenarios_records_failure_deterministically() -> None:
    scenarios = [Scenario("flaky", "Always unavailable candidate", {"attempt": 1})]

    def runner(scenario: Scenario) -> ScenarioResult:
        raise RuntimeError("input unavailable")

    first = run_scenarios(scenarios, runner=runner, clock=fixed_clock)
    second = run_scenarios(scenarios, runner=runner, clock=fixed_clock)

    assert [result.succeeded for result in first.results] == [False]
    assert first.to_dict() == second.to_dict(), "failure evidence not repeatable"


def main() -> int:
    probe_canonical_json_dumps_repeatable()
    probe_canonical_hash_repeatable()
    probe_identify_content_repeatable()
    probe_run_scenarios_repeatable()
    probe_run_scenarios_records_failure_deterministically()

    print("platform smoke ok: canonical, datasets, scenarios repeatable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
