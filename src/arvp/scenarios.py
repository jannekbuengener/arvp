"""Scenario Harness v2: decision-relevant scenario identity and orchestration.

Scenario and group fingerprints bind:
- scenario specification + parameters
- candidate fingerprint
- dataset/partition/suite fingerprint
- execution mode/configuration
- safe result semantics

Volatile wall-clock timestamps are recorded for presentation only and never
enter semantic fingerprints.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from arvp.canonical import (
    CanonicalizationError,
    FingerprintFormatError,
    canonical_hash,
    canonical_json_dumps,
    validate_fingerprint,
)
from arvp.evidence import (
    FailureEvidence,
    PortableEvidenceError,
    validate_portable_metadata,
)
from arvp.metrics import MetricContract, MetricContractError, MetricValue

SCENARIO_CONTRACT_VERSION = "arvp.scenario.v2"
SCENARIO_MANIFEST_CONTRACT_VERSION = "arvp.scenario-manifest.v2"
_GROUP_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_EXECUTION_MODE_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")


class ScenarioError(ValueError):
    """Raised when a scenario specification or result violates its contract."""


def _require_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ScenarioError(f"{field} must be a non-empty string")
    return value.strip()


def _require_fingerprint(value: object, field: str) -> str:
    try:
        return validate_fingerprint(value, field)
    except FingerprintFormatError as exc:
        raise ScenarioError(str(exc)) from exc


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _assert_evidence_safe(value: Any) -> None:
    try:
        validate_portable_metadata(value)
    except PortableEvidenceError as exc:
        raise ScenarioError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class Scenario:
    """Decision-relevant scenario request for Harness v2."""

    scenario_id: str
    description: str
    parameters: Mapping[str, Any]
    candidate_fingerprint: str
    suite_fingerprint: str
    partition_fingerprint: str
    execution_mode: str = "in_process"
    configuration: Mapping[str, Any] | None = None
    contract_version: str = SCENARIO_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_text(self.scenario_id, "scenario_id")
        _require_text(self.description, "description")
        if not isinstance(self.parameters, Mapping):
            raise ScenarioError("parameters must be a mapping")
        parameters = copy.deepcopy(dict(self.parameters))
        _assert_evidence_safe(parameters)
        try:
            canonical_json_dumps(parameters)
        except CanonicalizationError as exc:
            raise ScenarioError(f"parameters not canonicalizable: {exc}") from exc
        object.__setattr__(self, "parameters", parameters)
        object.__setattr__(
            self,
            "candidate_fingerprint",
            _require_fingerprint(self.candidate_fingerprint, "candidate_fingerprint"),
        )
        object.__setattr__(
            self,
            "suite_fingerprint",
            _require_fingerprint(self.suite_fingerprint, "suite_fingerprint"),
        )
        object.__setattr__(
            self,
            "partition_fingerprint",
            _require_fingerprint(self.partition_fingerprint, "partition_fingerprint"),
        )
        if (
            type(self.execution_mode) is not str
            or _EXECUTION_MODE_RE.fullmatch(self.execution_mode) is None
        ):
            raise ScenarioError("execution_mode must match ^[a-z][a-z0-9_.-]{0,63}$")
        if self.configuration is None:
            configuration: dict[str, Any] = {}
        else:
            if not isinstance(self.configuration, Mapping):
                raise ScenarioError("configuration must be a mapping or None")
            configuration = copy.deepcopy(dict(self.configuration))
            _assert_evidence_safe(configuration)
            try:
                canonical_json_dumps(configuration)
            except CanonicalizationError as exc:
                raise ScenarioError(
                    f"configuration not canonicalizable: {exc}"
                ) from exc
        object.__setattr__(self, "configuration", configuration)
        if self.contract_version != SCENARIO_CONTRACT_VERSION:
            raise ScenarioError(
                f"contract_version must be {SCENARIO_CONTRACT_VERSION!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        configuration = self.configuration if self.configuration is not None else {}
        return {
            "candidate_fingerprint": self.candidate_fingerprint,
            "configuration": dict(configuration),
            "contract_version": self.contract_version,
            "description": self.description,
            "execution_mode": self.execution_mode,
            "parameters": dict(self.parameters),
            "partition_fingerprint": self.partition_fingerprint,
            "scenario_id": self.scenario_id,
            "suite_fingerprint": self.suite_fingerprint,
        }

    def fingerprint(self) -> str:
        """Semantic scenario identity; excludes wall-clock timestamps."""
        return canonical_hash(self.to_dict())


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    scenario_id: str
    exit_code: int
    request_fingerprint: str
    metrics: tuple[MetricValue, ...] | None = None
    failure: FailureEvidence | None = None
    metric_contract: MetricContract | None = None

    def __post_init__(self) -> None:
        _require_text(self.scenario_id, "scenario_id")
        if isinstance(self.exit_code, bool) or not isinstance(self.exit_code, int):
            raise ScenarioError("exit_code must be an integer, not bool")
        object.__setattr__(
            self,
            "request_fingerprint",
            _require_fingerprint(self.request_fingerprint, "request_fingerprint"),
        )
        if self.exit_code == 0 and self.failure is not None:
            raise ScenarioError("successful scenarios cannot have a failure")
        if self.exit_code != 0 and self.failure is None:
            raise ScenarioError("failed scenarios require a failure")
        if self.failure is not None and not isinstance(self.failure, FailureEvidence):
            raise ScenarioError("failure must be a FailureEvidence instance")
        if self.metrics is None:
            if self.metric_contract is not None:
                raise ScenarioError("metric_contract requires metrics")
            return
        if type(self.metrics) is not tuple:
            raise ScenarioError("metrics must be a tuple of MetricValue instances")
        if type(self.metric_contract) is not MetricContract:
            raise ScenarioError("metrics require a metric_contract")
        try:
            validated = self.metric_contract.validate_values(self.metrics)
        except MetricContractError as exc:
            raise ScenarioError(str(exc)) from exc
        object.__setattr__(self, "metrics", validated)

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "exit_code": self.exit_code,
            "request_fingerprint": self.request_fingerprint,
            "scenario_id": self.scenario_id,
        }
        if self.metrics is not None:
            assert self.metric_contract is not None
            payload["metric_contract_fingerprint"] = self.metric_contract.fingerprint()
            payload["metrics"] = [value.to_dict() for value in self.metrics]
        if self.failure is not None:
            payload["failure"] = self.failure.to_dict()
        return payload

    def semantic_dict(self) -> dict[str, Any]:
        """Result payload used for group fingerprints (no volatile fields)."""
        return self.to_dict()


@dataclass(frozen=True, slots=True)
class ScenarioManifest:
    group_id: str
    group_fingerprint: str
    started_at_utc: str
    finished_at_utc: str
    results: tuple[ScenarioResult, ...]
    contract_version: str = SCENARIO_MANIFEST_CONTRACT_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
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
    try:
        fingerprint = canonical_hash({"scenario_ids": normalized})
    except CanonicalizationError as exc:
        raise ScenarioError(f"scenario_ids not canonicalizable: {exc}") from exc
    return f"sg-{fingerprint[:12]}"


RunnerExceptionPolicy = Literal["raise", "capture"]


def run_scenarios(
    scenarios: Sequence[Scenario],
    *,
    runner: Callable[[Scenario], ScenarioResult],
    group_id: str | None = None,
    clock: Callable[[], datetime] = _utc_now,
    unexpected_exceptions: RunnerExceptionPolicy = "raise",
) -> ScenarioManifest:
    """Run every declared scenario in order.

    Unexpected runner exceptions:
    - "raise" (default): propagate the exception (fail-fast)
    - "capture": convert to FailureEvidence with code "unexpected_exception"
    """
    if not scenarios:
        raise ScenarioError("scenarios must not be empty")
    if unexpected_exceptions not in {"raise", "capture"}:
        raise ScenarioError("unexpected_exceptions must be either 'raise' or 'capture'")
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
    request_fingerprints: list[str] = []
    for scenario in scenarios:
        request_fp = scenario.fingerprint()
        request_fingerprints.append(request_fp)
        try:
            result = runner(scenario)
        except Exception as exc:
            if unexpected_exceptions == "raise":
                raise
            result = ScenarioResult(
                scenario_id=scenario.scenario_id,
                exit_code=2,
                request_fingerprint=request_fp,
                failure=FailureEvidence.from_unexpected_exception(exc, stage="runner"),
            )
        if not isinstance(result, ScenarioResult):
            raise ScenarioError("runner must return a ScenarioResult")
        if result.scenario_id != scenario.scenario_id:
            raise ScenarioError("runner returned a result for a different scenario")
        if result.request_fingerprint != request_fp:
            raise ScenarioError(
                "runner returned a result for a different scenario request"
            )
        results.append(result)

    try:
        fingerprint = canonical_hash(
            {
                "contract_version": SCENARIO_MANIFEST_CONTRACT_VERSION,
                "group_id": resolved_group_id,
                "requests": request_fingerprints,
                "results": [result.semantic_dict() for result in results],
            }
        )
    except CanonicalizationError as exc:
        raise ScenarioError(f"scenario outcomes not canonicalizable: {exc}") from exc
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
    except CanonicalizationError as exc:
        raise ScenarioError(f"manifest not canonicalizable: {exc}") from exc
