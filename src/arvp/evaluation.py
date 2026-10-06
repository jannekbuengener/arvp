"""Evaluation splits, deterministic stability summaries, comparison, and gates."""

from __future__ import annotations

import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from arvp.canonical import (
    FingerprintFormatError,
    canonical_hash,
    validate_fingerprint,
)
from arvp.evidence import (
    FailureEvidence,
    PortableEvidenceError,
    validate_portable_metadata,
)


class EvaluationError(ValueError):
    """Raised when an evaluation input is incomplete or internally inconsistent."""


def _require_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvaluationError(f"{field} must be a non-empty string")
    return value.strip()


def _assert_evidence_safe(value: Any) -> None:
    """Fail closed when evidence could include a path, secret, or DSN.

    Delegates to the shared portable evidence boundary.
    """
    try:
        validate_portable_metadata(value)
    except PortableEvidenceError as exc:
        raise EvaluationError(str(exc)) from exc


def _decimal(value: object, field: str) -> Decimal:
    if isinstance(value, bool):
        raise EvaluationError(f"{field} must be numeric, not bool")
    try:
        converted = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise EvaluationError(f"{field} must be numeric") from exc
    if not converted.is_finite():
        raise EvaluationError(f"{field} must be finite")
    return converted


@dataclass(frozen=True, slots=True)
class EvaluationWindow:
    window_id: str
    start: int
    end: int
    role: Literal["train", "calibrate", "validate"] | None = None

    def __post_init__(self) -> None:
        _require_text(self.window_id, "window_id")
        for field in ("start", "end"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int):
                raise EvaluationError(f"{field} must be an integer")
        if self.start > self.end:
            raise EvaluationError("start must be <= end")
        if self.role not in {None, "train", "calibrate", "validate"}:
            raise EvaluationError("role must be train, calibrate, validate, or None")

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "end": self.end,
            "start": self.start,
            "window_id": self.window_id,
        }
        if self.role is not None:
            payload["role"] = self.role
        return payload


@dataclass(frozen=True, slots=True)
class EvaluationPlan:
    plan_id: str
    windows: tuple[EvaluationWindow, ...]

    def __post_init__(self) -> None:
        _require_text(self.plan_id, "plan_id")
        if not isinstance(self.windows, tuple) or not self.windows:
            raise EvaluationError("windows must be a non-empty tuple")
        identifiers: set[str] = set()
        previous: EvaluationWindow | None = None
        for window in self.windows:
            if not isinstance(window, EvaluationWindow):
                raise EvaluationError("windows must contain EvaluationWindow instances")
            if window.window_id in identifiers:
                raise EvaluationError(f"duplicate window_id: {window.window_id}")
            if previous is not None and window.start < previous.end:
                raise EvaluationError("windows must be ordered and non-overlapping")
            identifiers.add(window.window_id)
            previous = window

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "windows": [window.to_dict() for window in self.windows],
        }

    def fingerprint(self) -> str:
        return canonical_hash(self.to_dict())


@dataclass(frozen=True, slots=True)
class WindowResult:
    window_id: str
    succeeded: bool
    metrics: Mapping[str, Any] | None = None
    failure: FailureEvidence | None = None

    def __post_init__(self) -> None:
        _require_text(self.window_id, "window_id")
        if not isinstance(self.succeeded, bool):
            raise EvaluationError("succeeded must be bool")
        if self.succeeded and self.failure is not None:
            raise EvaluationError("successful result cannot have a failure")
        if not self.succeeded and self.failure is None:
            raise EvaluationError("failed result requires a failure")
        if self.failure is not None and not isinstance(self.failure, FailureEvidence):
            raise EvaluationError("failure must be a FailureEvidence instance")
        if self.metrics is not None:
            if not isinstance(self.metrics, Mapping):
                raise EvaluationError("metrics must be a mapping")
            _assert_evidence_safe(self.metrics)


RunnerExceptionPolicy = Literal["raise", "capture"]


def run_evaluation_plan(
    plan: EvaluationPlan,
    *,
    runner: Callable[[EvaluationWindow], WindowResult],
    unexpected_exceptions: RunnerExceptionPolicy = "raise",
) -> tuple[WindowResult, ...]:
    """Execute all declared windows.

    Unexpected runner exceptions:
    - "raise" (default): propagate the exception (fail-fast)
    - "capture": convert to FailureEvidence with code "unexpected_exception"
    """
    if not isinstance(plan, EvaluationPlan):
        raise EvaluationError("plan must be an EvaluationPlan")
    results: list[WindowResult] = []
    for window in plan.windows:
        try:
            result = runner(window)
        except Exception as exc:
            if unexpected_exceptions == "raise":
                raise
            result = WindowResult(
                window_id=window.window_id,
                succeeded=False,
                failure=FailureEvidence.from_unexpected_exception(exc, stage="runner"),
            )
        if not isinstance(result, WindowResult) or result.window_id != window.window_id:
            raise EvaluationError("runner must return a matching WindowResult")
        results.append(result)
    return tuple(results)


@dataclass(frozen=True, slots=True)
class StabilityConfig:
    sample_count: int
    blocks_per_sample: int
    seed: int

    def __post_init__(self) -> None:
        for field in ("sample_count", "blocks_per_sample"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise EvaluationError(f"{field} must be a positive integer")
        if (
            isinstance(self.seed, bool)
            or not isinstance(self.seed, int)
            or self.seed < 0
        ):
            raise EvaluationError("seed must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class StabilitySummary:
    input_fingerprint: str
    metric: str
    baseline: Decimal
    p05: Decimal
    p50: Decimal
    p95: Decimal
    sample_count: int

    def to_dict(self) -> dict[str, str | int]:
        return {
            "baseline": str(self.baseline),
            "input_fingerprint": self.input_fingerprint,
            "metric": self.metric,
            "p05": str(self.p05),
            "p50": str(self.p50),
            "p95": str(self.p95),
            "sample_count": self.sample_count,
        }


def resample_stability(
    blocks: Sequence[Mapping[str, object]],
    *,
    metric: str,
    config: StabilityConfig,
) -> StabilitySummary:
    """Compute an empirical bootstrap band over caller-supplied metric blocks."""
    _require_text(metric, "metric")
    if not blocks:
        raise EvaluationError("blocks must not be empty")
    values: list[Decimal] = []
    normalized_blocks: list[dict[str, str]] = []
    for index, block in enumerate(blocks):
        if not isinstance(block, Mapping) or metric not in block:
            raise EvaluationError(f"block {index} must contain metric {metric!r}")
        value = _decimal(block[metric], metric)
        values.append(value)
        normalized_blocks.append({metric: str(value)})
    rng = random.Random(config.seed)
    samples = [
        sum(
            (rng.choice(values) for _ in range(config.blocks_per_sample)),
            Decimal("0"),
        )
        for _ in range(config.sample_count)
    ]
    ordered = sorted(samples)

    def quantile(numerator: int) -> Decimal:
        return ordered[((len(ordered) - 1) * numerator) // 100]

    return StabilitySummary(
        input_fingerprint=canonical_hash(
            {
                "blocks": normalized_blocks,
                "config": {
                    "blocks_per_sample": config.blocks_per_sample,
                    "sample_count": config.sample_count,
                    "seed": config.seed,
                },
                "metric": metric,
            }
        ),
        metric=metric,
        baseline=sum(values, Decimal("0")),
        p05=quantile(5),
        p50=quantile(50),
        p95=quantile(95),
        sample_count=config.sample_count,
    )


@dataclass(frozen=True, slots=True)
class GateCriterion:
    metric: str
    operator: Literal["gte", "lte"]
    threshold: Decimal

    def __post_init__(self) -> None:
        _require_text(self.metric, "metric")
        if self.operator not in {"gte", "lte"}:
            raise EvaluationError("operator must be gte or lte")
        object.__setattr__(self, "threshold", _decimal(self.threshold, "threshold"))


@dataclass(frozen=True, slots=True)
class GateDecision:
    passed: bool
    criteria: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {"criteria": list(self.criteria), "passed": self.passed}


def evaluate_gate(
    metrics: Mapping[str, object], criteria: Sequence[GateCriterion]
) -> GateDecision:
    """Evaluate explicit numeric criteria; missing metrics fail closed."""
    if not isinstance(metrics, Mapping):
        raise EvaluationError("metrics must be a mapping")
    if not criteria:
        raise EvaluationError("criteria must not be empty")
    results: list[dict[str, Any]] = []
    for criterion in criteria:
        if not isinstance(criterion, GateCriterion):
            raise EvaluationError("criteria must contain GateCriterion instances")
        if criterion.metric not in metrics:
            raise EvaluationError(
                f"missing metric required by gate: {criterion.metric}"
            )
        actual = _decimal(metrics[criterion.metric], criterion.metric)
        passed = (
            actual >= criterion.threshold
            if criterion.operator == "gte"
            else actual <= criterion.threshold
        )
        results.append(
            {
                "actual": str(actual),
                "metric": criterion.metric,
                "operator": criterion.operator,
                "passed": passed,
                "threshold": str(criterion.threshold),
            }
        )
    return GateDecision(
        passed=all(item["passed"] for item in results), criteria=tuple(results)
    )


@dataclass(frozen=True, slots=True)
class CandidateScore:
    candidate_id: str
    score: Decimal
    evidence_fingerprint: str

    def __post_init__(self) -> None:
        _require_text(self.candidate_id, "candidate_id")
        object.__setattr__(self, "score", _decimal(self.score, "score"))
        try:
            validate_fingerprint(self.evidence_fingerprint, "evidence_fingerprint")
        except FingerprintFormatError as exc:
            raise EvaluationError(str(exc)) from exc


def rank_candidates(candidates: Sequence[CandidateScore]) -> tuple[CandidateScore, ...]:
    """Return a stable descending score order, breaking ties by candidate id."""
    if not candidates:
        raise EvaluationError("candidates must not be empty")
    if not all(isinstance(candidate, CandidateScore) for candidate in candidates):
        raise EvaluationError("candidates must contain CandidateScore instances")
    if len({candidate.candidate_id for candidate in candidates}) != len(candidates):
        raise EvaluationError("candidate_id values must be unique")
    return tuple(
        sorted(
            candidates, key=lambda candidate: (-candidate.score, candidate.candidate_id)
        )
    )
