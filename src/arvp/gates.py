"""Portable baseline comparison and deterministic gate contracts."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from arvp.canonical import canonical_hash
from arvp.metrics import (
    MetricContract,
    MetricContractError,
    MetricDirection,
    MetricValueStatus,
    Observation,
)

METRIC_COMPARISON_CONTRACT_VERSION = "arvp.metric-comparison.v1"
GATE_POLICY_CONTRACT_VERSION = "arvp.gate-policy.v1"

ComparisonStatus = Literal["complete", "incomplete", "not_applicable"]
ComparisonReason = Literal[
    "missing_baseline",
    "missing_candidate",
    "metric_contract_mismatch",
    "partition_mismatch",
    "unknown_value",
    "not_applicable",
]
RelativeDeltaReason = Literal["baseline_zero"]
DirectionResult = Literal["improved", "regressed", "equal"]
GateOperator = Literal["gte", "lte"]
RelativeMode = Literal["no_regression_beyond", "minimum_improvement"]

_REASON_ORDER: tuple[ComparisonReason, ...] = (
    "missing_baseline",
    "missing_candidate",
    "metric_contract_mismatch",
    "partition_mismatch",
    "unknown_value",
    "not_applicable",
)
_NUMERIC_STATUSES = frozenset({"measured", "derived"})


class GateContractError(ValueError):
    """Raised when comparison/gate contracts are structurally malformed."""


_STABLE_ID_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_VALID_OPERATORS = frozenset({"gte", "lte"})
_VALID_RELATIVE_MODES = frozenset({"no_regression_beyond", "minimum_improvement"})


def _require_stable_id(value: object, field: str) -> str:
    if type(value) is not str or _STABLE_ID_RE.fullmatch(value) is None:
        raise GateContractError(f"{field} must match ^[a-z][a-z0-9_.-]{{0,63}}$")
    return value


def _finite_decimal(value: object, field: str) -> Decimal:
    if type(value) is int:
        result = Decimal(value)
    elif type(value) is float:
        if not math.isfinite(value):
            raise GateContractError(f"{field} must be a finite numeric threshold")
        result = Decimal(str(value))
    elif type(value) is Decimal:
        result = value
    else:
        raise GateContractError(f"{field} must be a finite numeric threshold")
    if not result.is_finite():
        raise GateContractError(f"{field} must be a finite numeric threshold")
    return result


@dataclass(frozen=True, slots=True)
class AbsoluteThresholdCriterion:
    criterion_id: str
    metric_id: str
    operator: GateOperator
    threshold: Decimal

    def __post_init__(self) -> None:
        _require_stable_id(self.criterion_id, "criterion_id")
        _require_stable_id(self.metric_id, "metric_id")
        if type(self.operator) is not str or self.operator not in _VALID_OPERATORS:
            raise GateContractError("operator must be gte or lte")
        object.__setattr__(
            self, "threshold", _finite_decimal(self.threshold, "threshold")
        )

    @property
    def criterion_type(self) -> str:
        return "absolute_threshold"

    def to_dict(self) -> dict[str, Any]:
        return {
            "criterion_id": self.criterion_id,
            "criterion_type": self.criterion_type,
            "metric_id": self.metric_id,
            "operator": self.operator,
            "threshold": self.threshold,
        }


@dataclass(frozen=True, slots=True)
class RelativeBaselineCriterion:
    criterion_id: str
    metric_id: str
    mode: RelativeMode
    threshold: Decimal

    def __post_init__(self) -> None:
        _require_stable_id(self.criterion_id, "criterion_id")
        _require_stable_id(self.metric_id, "metric_id")
        if type(self.mode) is not str or self.mode not in _VALID_RELATIVE_MODES:
            raise GateContractError(
                "mode must be no_regression_beyond or minimum_improvement"
            )
        threshold = _finite_decimal(self.threshold, "threshold")
        if threshold < 0:
            raise GateContractError("relative threshold must be non-negative")
        object.__setattr__(self, "threshold", threshold)

    @property
    def criterion_type(self) -> str:
        return "relative_baseline"

    def to_dict(self) -> dict[str, Any]:
        return {
            "criterion_id": self.criterion_id,
            "criterion_type": self.criterion_type,
            "metric_id": self.metric_id,
            "mode": self.mode,
            "threshold": self.threshold,
        }


GateCriterion = AbsoluteThresholdCriterion | RelativeBaselineCriterion


@dataclass(frozen=True, slots=True, init=False)
class GatePolicy:
    policy_id: str
    metric_contract_fingerprint: str
    criteria: tuple[GateCriterion, ...]
    contract_version: str

    def __init__(
        self,
        policy_id: str,
        metric_contract: MetricContract,
        criteria: Sequence[GateCriterion],
    ) -> None:
        _require_stable_id(policy_id, "policy_id")
        if type(metric_contract) is not MetricContract:
            raise GateContractError("metric_contract must be a MetricContract")
        if (
            isinstance(criteria, (str, bytes))
            or not isinstance(criteria, Sequence)
            or not criteria
        ):
            raise GateContractError("criteria must be a non-empty sequence")
        normalized: list[GateCriterion] = []
        seen: set[str] = set()
        for criterion in criteria:
            if type(criterion) not in {
                AbsoluteThresholdCriterion,
                RelativeBaselineCriterion,
            }:
                raise GateContractError("criteria must contain supported gate criteria")
            if criterion.criterion_id in seen:
                raise GateContractError(
                    f"duplicate criterion_id: {criterion.criterion_id}"
                )
            try:
                definition = metric_contract.definition(criterion.metric_id)
            except MetricContractError as exc:
                raise GateContractError(str(exc)) from exc
            if (
                type(criterion) is RelativeBaselineCriterion
                and definition.direction == "neutral"
            ):
                raise GateContractError(
                    "relative criteria are invalid for neutral metrics"
                )
            seen.add(criterion.criterion_id)
            normalized.append(criterion)
        object.__setattr__(self, "policy_id", policy_id)
        object.__setattr__(
            self, "metric_contract_fingerprint", metric_contract.fingerprint()
        )
        object.__setattr__(
            self,
            "criteria",
            tuple(sorted(normalized, key=lambda item: item.criterion_id)),
        )
        object.__setattr__(self, "contract_version", GATE_POLICY_CONTRACT_VERSION)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "criteria": [criterion.to_dict() for criterion in self.criteria],
            "metric_contract_fingerprint": self.metric_contract_fingerprint,
            "policy_id": self.policy_id,
        }

    def fingerprint(self) -> str:
        return canonical_hash(self.to_dict())


@dataclass(frozen=True, slots=True, init=False)
class MetricComparison:
    metric_id: str
    direction: MetricDirection
    unit: str
    required: bool
    observation_id: str
    metric_contract_fingerprint: str
    baseline_candidate_fingerprint: str | None
    candidate_fingerprint: str | None
    baseline_partition_id: str | None
    candidate_partition_id: str | None
    baseline_partition_fingerprint: str | None
    candidate_partition_fingerprint: str | None
    baseline_metric_contract_fingerprint: str | None
    candidate_metric_contract_fingerprint: str | None
    baseline_status: MetricValueStatus | None
    candidate_status: MetricValueStatus | None
    baseline_value: Decimal | None
    candidate_value: Decimal | None
    baseline_compatible: bool
    candidate_compatible: bool
    absolute_delta: Decimal | None
    relative_delta: Decimal | None
    relative_delta_reason: RelativeDeltaReason | None
    directional_relative_delta: Decimal | None
    direction_result: DirectionResult | None
    status: ComparisonStatus
    reasons: tuple[ComparisonReason, ...]
    contract_version: str

    @classmethod
    def _create(
        cls,
        *,
        metric_id: str,
        direction: MetricDirection,
        unit: str,
        required: bool,
        observation_id: str,
        metric_contract_fingerprint: str,
        baseline_candidate_fingerprint: str | None,
        candidate_fingerprint: str | None,
        baseline_partition_id: str | None,
        candidate_partition_id: str | None,
        baseline_partition_fingerprint: str | None,
        candidate_partition_fingerprint: str | None,
        baseline_metric_contract_fingerprint: str | None,
        candidate_metric_contract_fingerprint: str | None,
        baseline_status: MetricValueStatus | None,
        candidate_status: MetricValueStatus | None,
        baseline_value: Decimal | None,
        candidate_value: Decimal | None,
        baseline_compatible: bool,
        candidate_compatible: bool,
        absolute_delta: Decimal | None,
        relative_delta: Decimal | None,
        relative_delta_reason: RelativeDeltaReason | None,
        directional_relative_delta: Decimal | None,
        direction_result: DirectionResult | None,
        status: ComparisonStatus,
        reasons: tuple[ComparisonReason, ...],
    ) -> MetricComparison:
        instance = object.__new__(cls)
        values = {
            "metric_id": metric_id,
            "direction": direction,
            "unit": unit,
            "required": required,
            "observation_id": observation_id,
            "metric_contract_fingerprint": metric_contract_fingerprint,
            "baseline_candidate_fingerprint": baseline_candidate_fingerprint,
            "candidate_fingerprint": candidate_fingerprint,
            "baseline_partition_id": baseline_partition_id,
            "candidate_partition_id": candidate_partition_id,
            "baseline_partition_fingerprint": baseline_partition_fingerprint,
            "candidate_partition_fingerprint": candidate_partition_fingerprint,
            "baseline_metric_contract_fingerprint": baseline_metric_contract_fingerprint,
            "candidate_metric_contract_fingerprint": candidate_metric_contract_fingerprint,
            "baseline_status": baseline_status,
            "candidate_status": candidate_status,
            "baseline_value": baseline_value,
            "candidate_value": candidate_value,
            "baseline_compatible": baseline_compatible,
            "candidate_compatible": candidate_compatible,
            "absolute_delta": absolute_delta,
            "relative_delta": relative_delta,
            "relative_delta_reason": relative_delta_reason,
            "directional_relative_delta": directional_relative_delta,
            "direction_result": direction_result,
            "status": status,
            "reasons": reasons,
            "contract_version": METRIC_COMPARISON_CONTRACT_VERSION,
        }
        for field, value in values.items():
            object.__setattr__(instance, field, value)
        return instance

    def to_dict(self) -> dict[str, Any]:
        return {
            "absolute_delta": self.absolute_delta,
            "baseline_candidate_fingerprint": self.baseline_candidate_fingerprint,
            "baseline_compatible": self.baseline_compatible,
            "baseline_metric_contract_fingerprint": self.baseline_metric_contract_fingerprint,
            "baseline_partition_fingerprint": self.baseline_partition_fingerprint,
            "baseline_partition_id": self.baseline_partition_id,
            "baseline_status": self.baseline_status,
            "baseline_value": self.baseline_value,
            "candidate_compatible": self.candidate_compatible,
            "candidate_fingerprint": self.candidate_fingerprint,
            "candidate_metric_contract_fingerprint": self.candidate_metric_contract_fingerprint,
            "candidate_partition_fingerprint": self.candidate_partition_fingerprint,
            "candidate_partition_id": self.candidate_partition_id,
            "candidate_status": self.candidate_status,
            "candidate_value": self.candidate_value,
            "contract_version": self.contract_version,
            "direction": self.direction,
            "direction_result": self.direction_result,
            "directional_relative_delta": self.directional_relative_delta,
            "metric_contract_fingerprint": self.metric_contract_fingerprint,
            "metric_id": self.metric_id,
            "observation_id": self.observation_id,
            "reasons": self.reasons,
            "relative_delta": self.relative_delta,
            "relative_delta_reason": self.relative_delta_reason,
            "required": self.required,
            "status": self.status,
            "unit": self.unit,
        }

    def fingerprint(self) -> str:
        return canonical_hash(self.to_dict())


@dataclass(frozen=True, slots=True)
class _SideScope:
    observations: dict[tuple[str, str], Observation]
    candidate_fingerprint: str | None
    partition_id: str | None
    partition_fingerprint: str | None
    metric_contract_fingerprint: str | None


def _normalize_side(
    name: str,
    observations: Sequence[Observation],
    metric_contract: MetricContract,
) -> _SideScope:
    if isinstance(observations, (str, bytes)) or not isinstance(observations, Sequence):
        raise GateContractError(f"{name} must be a sequence of Observation instances")
    indexed: dict[tuple[str, str], Observation] = {}
    candidate_fingerprints: set[str] = set()
    partitions: set[tuple[str, str]] = set()
    metric_contract_fingerprints: set[str] = set()
    for observation in observations:
        if type(observation) is not Observation:
            raise GateContractError(f"{name} must contain Observation instances")
        try:
            metric_contract.definition(observation.metric.metric_id)
        except MetricContractError as exc:
            raise GateContractError(str(exc)) from exc
        key = (observation.metric.metric_id, observation.observation_id)
        if key in indexed:
            raise GateContractError(
                f"{name} contains duplicate observation key: {key!r}"
            )
        indexed[key] = observation
        candidate_fingerprints.add(observation.candidate_fingerprint)
        partitions.add((observation.partition_id, observation.partition_fingerprint))
        metric_contract_fingerprints.add(observation.metric.metric_contract_fingerprint)
    if len(candidate_fingerprints) > 1:
        raise GateContractError(f"{name} must contain observations from one candidate")
    if len(partitions) > 1:
        raise GateContractError(f"{name} must contain observations from one partition")
    if len(metric_contract_fingerprints) > 1:
        raise GateContractError(
            f"{name} must contain observations from one metric contract"
        )
    partition = next(iter(partitions), None)
    return _SideScope(
        observations=indexed,
        candidate_fingerprint=next(iter(candidate_fingerprints), None),
        partition_id=partition[0] if partition else None,
        partition_fingerprint=partition[1] if partition else None,
        metric_contract_fingerprint=next(iter(metric_contract_fingerprints), None),
    )


def _direction_result(
    direction: MetricDirection, absolute_delta: Decimal
) -> DirectionResult | None:
    if direction == "neutral":
        return None
    if absolute_delta == 0:
        return "equal"
    if direction == "maximize":
        return "improved" if absolute_delta > 0 else "regressed"
    return "improved" if absolute_delta < 0 else "regressed"


def compare_observation_scope(
    *,
    baseline: Sequence[Observation],
    candidate: Sequence[Observation],
    metric_contract: MetricContract,
) -> tuple[MetricComparison, ...]:
    """Compare one explicit baseline/candidate observation scope deterministically."""
    if type(metric_contract) is not MetricContract:
        raise GateContractError("metric_contract must be a MetricContract")
    baseline_scope = _normalize_side("baseline", baseline, metric_contract)
    candidate_scope = _normalize_side("candidate", candidate, metric_contract)
    if not baseline_scope.observations and not candidate_scope.observations:
        raise GateContractError("at least one observation is required")

    expected_contract_fingerprint = metric_contract.fingerprint()
    keys = sorted(set(baseline_scope.observations) | set(candidate_scope.observations))
    comparisons: list[MetricComparison] = []

    for metric_id, observation_id in keys:
        definition = metric_contract.definition(metric_id)
        baseline_observation = baseline_scope.observations.get(
            (metric_id, observation_id)
        )
        candidate_observation = candidate_scope.observations.get(
            (metric_id, observation_id)
        )
        baseline_metric = (
            baseline_observation.metric if baseline_observation is not None else None
        )
        candidate_metric = (
            candidate_observation.metric if candidate_observation is not None else None
        )
        baseline_metric_contract_fingerprint = (
            baseline_metric.metric_contract_fingerprint
            if baseline_metric is not None
            else None
        )
        candidate_metric_contract_fingerprint = (
            candidate_metric.metric_contract_fingerprint
            if candidate_metric is not None
            else None
        )
        baseline_compatible = (
            baseline_observation is not None
            and baseline_metric_contract_fingerprint == expected_contract_fingerprint
        )
        candidate_compatible = (
            candidate_observation is not None
            and candidate_metric_contract_fingerprint == expected_contract_fingerprint
        )

        reason_set: set[ComparisonReason] = set()
        if baseline_observation is None:
            reason_set.add("missing_baseline")
        if candidate_observation is None:
            reason_set.add("missing_candidate")
        if (
            baseline_observation is not None
            and not baseline_compatible
            or candidate_observation is not None
            and not candidate_compatible
        ):
            reason_set.add("metric_contract_mismatch")
        if baseline_observation is not None and candidate_observation is not None:
            if (
                baseline_observation.partition_id != candidate_observation.partition_id
                or baseline_observation.partition_fingerprint
                != candidate_observation.partition_fingerprint
            ):
                reason_set.add("partition_mismatch")

        statuses = {
            status
            for status in (
                baseline_metric.status if baseline_metric is not None else None,
                candidate_metric.status if candidate_metric is not None else None,
            )
            if status is not None
        }
        if "unknown" in statuses:
            reason_set.add("unknown_value")
        if "not_applicable" in statuses:
            reason_set.add("not_applicable")

        incomplete_reasons = reason_set.intersection(
            {
                "missing_baseline",
                "missing_candidate",
                "metric_contract_mismatch",
                "partition_mismatch",
                "unknown_value",
            }
        )
        if incomplete_reasons:
            status: ComparisonStatus = "incomplete"
        elif "not_applicable" in reason_set:
            status = "not_applicable"
        else:
            status = "complete"

        absolute_delta: Decimal | None = None
        relative_delta: Decimal | None = None
        relative_delta_reason: RelativeDeltaReason | None = None
        directional_relative_delta: Decimal | None = None
        direction_result: DirectionResult | None = None

        if status == "complete":
            if (
                baseline_metric is None
                or candidate_metric is None
                or baseline_metric.status not in _NUMERIC_STATUSES
                or candidate_metric.status not in _NUMERIC_STATUSES
                or baseline_metric.value is None
                or candidate_metric.value is None
            ):
                raise GateContractError(
                    "complete comparison requires numeric metric values"
                )
            absolute_delta = candidate_metric.value - baseline_metric.value
            direction_result = _direction_result(definition.direction, absolute_delta)
            if baseline_metric.value == 0:
                relative_delta_reason = "baseline_zero"
            else:
                relative_delta = absolute_delta / abs(baseline_metric.value)
                if definition.direction == "maximize":
                    directional_relative_delta = relative_delta
                elif definition.direction == "minimize":
                    directional_relative_delta = -relative_delta

        reasons = tuple(reason for reason in _REASON_ORDER if reason in reason_set)
        comparisons.append(
            MetricComparison._create(
                metric_id=metric_id,
                direction=definition.direction,
                unit=definition.unit,
                required=definition.required,
                observation_id=observation_id,
                metric_contract_fingerprint=expected_contract_fingerprint,
                baseline_candidate_fingerprint=(
                    baseline_observation.candidate_fingerprint
                    if baseline_observation is not None
                    else None
                ),
                candidate_fingerprint=(
                    candidate_observation.candidate_fingerprint
                    if candidate_observation is not None
                    else None
                ),
                baseline_partition_id=(
                    baseline_observation.partition_id
                    if baseline_observation is not None
                    else None
                ),
                candidate_partition_id=(
                    candidate_observation.partition_id
                    if candidate_observation is not None
                    else None
                ),
                baseline_partition_fingerprint=(
                    baseline_observation.partition_fingerprint
                    if baseline_observation is not None
                    else None
                ),
                candidate_partition_fingerprint=(
                    candidate_observation.partition_fingerprint
                    if candidate_observation is not None
                    else None
                ),
                baseline_metric_contract_fingerprint=baseline_metric_contract_fingerprint,
                candidate_metric_contract_fingerprint=candidate_metric_contract_fingerprint,
                baseline_status=(
                    baseline_metric.status if baseline_metric is not None else None
                ),
                candidate_status=(
                    candidate_metric.status if candidate_metric is not None else None
                ),
                baseline_value=(
                    baseline_metric.value if baseline_metric is not None else None
                ),
                candidate_value=(
                    candidate_metric.value if candidate_metric is not None else None
                ),
                baseline_compatible=baseline_compatible,
                candidate_compatible=candidate_compatible,
                absolute_delta=absolute_delta,
                relative_delta=relative_delta,
                relative_delta_reason=relative_delta_reason,
                directional_relative_delta=directional_relative_delta,
                direction_result=direction_result,
                status=status,
                reasons=reasons,
            )
        )

    return tuple(comparisons)


GATE_DECISION_CONTRACT_VERSION = "arvp.gate-decision.v1"
GateVerdict = Literal["PASS", "FAIL", "HOLD"]
CriterionOutcome = Literal["pass", "fail", "hold", "not_applicable"]
CriterionReason = Literal[
    "missing_comparison",
    "missing_baseline",
    "missing_candidate",
    "unknown_value",
    "not_applicable",
    "incompatible_evidence",
    "relative_delta_unavailable",
]


@dataclass(frozen=True, slots=True, init=False)
class CriterionResult:
    criterion: GateCriterion
    outcome: CriterionOutcome
    actual: Decimal | None
    comparison_fingerprint: str | None
    reason: CriterionReason | None

    @classmethod
    def _create(
        cls,
        *,
        criterion: GateCriterion,
        outcome: CriterionOutcome,
        actual: Decimal | None,
        comparison_fingerprint: str | None,
        reason: CriterionReason | None,
    ) -> CriterionResult:
        instance = object.__new__(cls)
        object.__setattr__(instance, "criterion", criterion)
        object.__setattr__(instance, "outcome", outcome)
        object.__setattr__(instance, "actual", actual)
        object.__setattr__(instance, "comparison_fingerprint", comparison_fingerprint)
        object.__setattr__(instance, "reason", reason)
        return instance

    def to_dict(self) -> dict[str, Any]:
        return {
            "actual": self.actual,
            "comparison_fingerprint": self.comparison_fingerprint,
            "criterion": self.criterion.to_dict(),
            "outcome": self.outcome,
            "reason": self.reason,
        }

    def fingerprint(self) -> str:
        return canonical_hash(self.to_dict())


@dataclass(frozen=True, slots=True, init=False)
class GateDecision:
    policy_fingerprint: str
    metric_contract_fingerprint: str
    verdict: GateVerdict
    criteria: tuple[CriterionResult, ...]
    contract_version: str

    @classmethod
    def _create(
        cls,
        *,
        policy_fingerprint: str,
        metric_contract_fingerprint: str,
        verdict: GateVerdict,
        criteria: tuple[CriterionResult, ...],
    ) -> GateDecision:
        instance = object.__new__(cls)
        object.__setattr__(instance, "policy_fingerprint", policy_fingerprint)
        object.__setattr__(
            instance, "metric_contract_fingerprint", metric_contract_fingerprint
        )
        object.__setattr__(instance, "verdict", verdict)
        object.__setattr__(instance, "criteria", criteria)
        object.__setattr__(instance, "contract_version", GATE_DECISION_CONTRACT_VERSION)
        return instance

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "criteria": [result.to_dict() for result in self.criteria],
            "metric_contract_fingerprint": self.metric_contract_fingerprint,
            "policy_fingerprint": self.policy_fingerprint,
            "verdict": self.verdict,
        }

    def fingerprint(self) -> str:
        return canonical_hash(self.to_dict())


def _unavailable_result(
    *,
    criterion: GateCriterion,
    required: bool,
    comparison: MetricComparison | None,
    reason: CriterionReason,
) -> CriterionResult:
    return CriterionResult._create(
        criterion=criterion,
        outcome="hold" if required else "not_applicable",
        actual=None,
        comparison_fingerprint=(
            comparison.fingerprint() if comparison is not None else None
        ),
        reason=reason,
    )


def _absolute_result(
    criterion: AbsoluteThresholdCriterion,
    definition_required: bool,
    comparison: MetricComparison | None,
) -> CriterionResult:
    if comparison is None:
        return _unavailable_result(
            criterion=criterion,
            required=definition_required,
            comparison=None,
            reason="missing_comparison",
        )
    if comparison.candidate_fingerprint is None or comparison.candidate_status is None:
        return _unavailable_result(
            criterion=criterion,
            required=definition_required,
            comparison=comparison,
            reason="missing_candidate",
        )
    if not comparison.candidate_compatible:
        return _unavailable_result(
            criterion=criterion,
            required=definition_required,
            comparison=comparison,
            reason="incompatible_evidence",
        )
    if comparison.candidate_status == "unknown":
        return _unavailable_result(
            criterion=criterion,
            required=definition_required,
            comparison=comparison,
            reason="unknown_value",
        )
    if comparison.candidate_status == "not_applicable":
        return _unavailable_result(
            criterion=criterion,
            required=definition_required,
            comparison=comparison,
            reason="not_applicable",
        )
    if comparison.candidate_value is None:
        raise GateContractError("numeric candidate status requires candidate_value")
    actual = comparison.candidate_value
    passed = (
        actual >= criterion.threshold
        if criterion.operator == "gte"
        else actual <= criterion.threshold
    )
    return CriterionResult._create(
        criterion=criterion,
        outcome="pass" if passed else "fail",
        actual=actual,
        comparison_fingerprint=comparison.fingerprint(),
        reason=None,
    )


def _relative_unavailable_reason(comparison: MetricComparison) -> CriterionReason:
    if "missing_baseline" in comparison.reasons:
        return "missing_baseline"
    if "missing_candidate" in comparison.reasons:
        return "missing_candidate"
    if "unknown_value" in comparison.reasons:
        return "unknown_value"
    if "not_applicable" in comparison.reasons:
        return "not_applicable"
    if (
        "metric_contract_mismatch" in comparison.reasons
        or "partition_mismatch" in comparison.reasons
    ):
        return "incompatible_evidence"
    if comparison.relative_delta_reason == "baseline_zero":
        return "relative_delta_unavailable"
    return "incompatible_evidence"


def _relative_result(
    criterion: RelativeBaselineCriterion,
    definition_required: bool,
    comparison: MetricComparison | None,
) -> CriterionResult:
    if comparison is None:
        return _unavailable_result(
            criterion=criterion,
            required=definition_required,
            comparison=None,
            reason="missing_comparison",
        )
    if comparison.directional_relative_delta is None:
        return _unavailable_result(
            criterion=criterion,
            required=definition_required,
            comparison=comparison,
            reason=_relative_unavailable_reason(comparison),
        )
    actual = comparison.directional_relative_delta
    if criterion.mode == "no_regression_beyond":
        passed = actual >= -criterion.threshold
    else:
        passed = actual >= criterion.threshold
    return CriterionResult._create(
        criterion=criterion,
        outcome="pass" if passed else "fail",
        actual=actual,
        comparison_fingerprint=comparison.fingerprint(),
        reason=None,
    )


def evaluate_gate(
    *,
    policy: GatePolicy,
    comparisons: Sequence[MetricComparison],
    metric_contract: MetricContract,
) -> GateDecision:
    """Evaluate one explicit comparison scope without hidden aggregation."""
    if type(policy) is not GatePolicy:
        raise GateContractError("policy must be a GatePolicy")
    if type(metric_contract) is not MetricContract:
        raise GateContractError("metric_contract must be a MetricContract")
    expected_contract_fingerprint = metric_contract.fingerprint()
    if policy.metric_contract_fingerprint != expected_contract_fingerprint:
        raise GateContractError("metric contract fingerprint does not match GatePolicy")
    if isinstance(comparisons, (str, bytes)) or not isinstance(comparisons, Sequence):
        raise GateContractError("comparisons must be a sequence of MetricComparison")

    by_metric: dict[str, MetricComparison] = {}
    for comparison in comparisons:
        if type(comparison) is not MetricComparison:
            raise GateContractError(
                "comparisons must contain MetricComparison instances"
            )
        if comparison.metric_contract_fingerprint != expected_contract_fingerprint:
            raise GateContractError(
                "comparison metric contract fingerprint does not match supplied contract"
            )
        if comparison.metric_id in by_metric:
            raise GateContractError(
                f"multiple comparisons for metric: {comparison.metric_id}"
            )
        by_metric[comparison.metric_id] = comparison

    results: list[CriterionResult] = []
    for criterion in policy.criteria:
        definition = metric_contract.definition(criterion.metric_id)
        matched = by_metric.get(criterion.metric_id)
        if type(criterion) is AbsoluteThresholdCriterion:
            result = _absolute_result(criterion, definition.required, matched)
        elif type(criterion) is RelativeBaselineCriterion:
            result = _relative_result(criterion, definition.required, matched)
        else:
            raise GateContractError("unsupported criterion type")
        results.append(result)

    normalized = tuple(sorted(results, key=lambda item: item.criterion.criterion_id))
    outcomes = {result.outcome for result in normalized}
    if "fail" in outcomes:
        verdict: GateVerdict = "FAIL"
    elif "hold" in outcomes:
        verdict = "HOLD"
    else:
        verdict = "PASS"

    return GateDecision._create(
        policy_fingerprint=policy.fingerprint(),
        metric_contract_fingerprint=expected_contract_fingerprint,
        verdict=verdict,
        criteria=normalized,
    )
