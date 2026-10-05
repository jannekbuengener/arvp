"""Explicit scenario orchestration with deterministic outcome evidence."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import copy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any

from arvp.canonical import canonical_hash, canonical_json_dumps
from arvp.datasets import assert_evidence_safe


_GROUP_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class ScenarioError(ValueError):
    """Raised when a scenario specification or result violates its contract."""


def _require_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ScenarioError(f"{field} must be a non-empty string")
    return value.strip()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class Scenario:
    scenario_id: str
    description: str
    parameters: Mapping[str, Any]

    def __post_init__(self) -> None:
        _require_text(self.scenario_id, "scenario_id")
        _require_text(self.description, "description")
        if not isinstance(self.parameters, Mapping):
            raise ScenarioError("parameters must be a mapping")
        parameters = copy.deepcopy(dict(self.parameters))
        try:
            assert_evidence_safe(parameters)
        except ValueError as exc:
            raise ScenarioError(str(exc)) from exc
        object.__setattr__(self, "parameters", parameters)

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "parameters": dict(self.parameters),
            "scenario_id": self.scenario_id,
        }


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    scenario_id: str
    exit_code: int
    metrics: Mapping[str, Any] | None = None
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.scenario_id, "scenario_id")
        if isinstance(self.exit_code, bool) or not isinstance(self.exit_code, int):
            raise ScenarioError("exit_code must be an integer, not bool")
        if self.exit_code == 0 and self.failure_reason is not None:
            raise ScenarioError("successful scenarios cannot have a failure_reason")
        if self.exit_code != 0 and self.failure_reason is None:
            raise ScenarioError("failed scenarios require a failure_reason")
        if self.failure_reason is not None:
            _require_text(self.failure_reason, "failure_reason")
        if self.metrics is not None:
            if not isinstance(self.metrics, Mapping):
                raise ScenarioError("metrics must be a mapping")
            metrics = copy.deepcopy(dict(self.metrics))
            try:
                assert_evidence_safe(metrics)
            except ValueError as exc:
                raise ScenarioError(str(exc)) from exc
            object.__setattr__(self, "metrics", metrics)

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "exit_code": self.exit_code,
            "scenario_id": self.scenario_id,
        }
        if self.metrics is not None:
            payload["metrics"] = dict(self.metrics)
        if self.failure_reason is not None:
            payload["failure_reason"] = self.failure_reason
        return payload


@dataclass(frozen=True, slots=True)
class ScenarioManifest:
    group_id: str
    group_fingerprint: str
    started_at_utc: str
    finished_at_utc: str
    results: tuple[ScenarioResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "failed_count": sum(not result.succeeded for result in self.results),
            "finished_at_utc": self.finished_at_utc,
            "group_fingerprint": self.group_fingerprint,
            "group_id": self.group_id,
            "results": [result.to_dict() for result in self.results],
            "started_at_utc": self.started_at_utc,
            "succeeded_count": sum(result.succeeded for result in self.results),
            "total_scenarios": len(self.results),
        }


def build_group_id(scenario_ids: Sequence[str]) -> str:
    if not scenario_ids:
        raise ScenarioError("scenario_ids must not be empty")
    normalized = [_require_text(value, "scenario_id") for value in scenario_ids]
    return f"sg-{canonical_hash({'scenario_ids': normalized})[:12]}"


def run_scenarios(
    scenarios: Sequence[Scenario],
    *,
    runner: Callable[[Scenario], ScenarioResult],
    group_id: str | None = None,
    clock: Callable[[], datetime] = _utc_now,
) -> ScenarioManifest:
    """Run every declared scenario in order; unexpected runner errors are evidence."""
    if not scenarios:
        raise ScenarioError("scenarios must not be empty")
    if group_id is not None and not _GROUP_ID_RE.fullmatch(group_id):
        raise ScenarioError("group_id must use 1-64 letters, digits, '_' or '-'")
    seen: set[str] = set()
    for scenario in scenarios:
        if not isinstance(scenario, Scenario):
            raise ScenarioError("scenarios must contain Scenario instances")
        if scenario.scenario_id in seen:
            raise ScenarioError(f"duplicate scenario_id: {scenario.scenario_id}")
        seen.add(scenario.scenario_id)

    resolved_group_id = group_id or build_group_id(
        [scenario.scenario_id for scenario in scenarios]
    )
    started = clock().astimezone(timezone.utc).isoformat()
    results: list[ScenarioResult] = []
    for scenario in scenarios:
        try:
            result = runner(scenario)
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
            result = ScenarioResult(
                scenario_id=scenario.scenario_id,
                exit_code=2,
                failure_reason=f"runner raised unexpected exception: {detail}",
            )
        if not isinstance(result, ScenarioResult):
            raise ScenarioError("runner must return a ScenarioResult")
        if result.scenario_id != scenario.scenario_id:
            raise ScenarioError("runner returned a result for a different scenario")
        results.append(result)

    outcomes = [
        {"exit_code": result.exit_code, "scenario_id": result.scenario_id}
        for result in results
    ]
    fingerprint = canonical_hash({"group_id": resolved_group_id, "outcomes": outcomes})
    finished = clock().astimezone(timezone.utc).isoformat()
    return ScenarioManifest(
        group_id=resolved_group_id,
        group_fingerprint=fingerprint,
        started_at_utc=started,
        finished_at_utc=finished,
        results=tuple(results),
    )


def write_scenario_manifest(manifest: ScenarioManifest, path: Path | str) -> None:
    """Persist an explicitly chosen scenario artifact path."""
    if not isinstance(manifest, ScenarioManifest):
        raise ScenarioError("manifest must be a ScenarioManifest")
    destination = Path(path)
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            canonical_json_dumps(manifest.to_dict()), encoding="utf-8"
        )
    except OSError as exc:
        raise ScenarioError(f"could not write scenario manifest: {exc}") from exc
