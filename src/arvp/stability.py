"""Explicit aggregation and paired deterministic stability resampling."""

from __future__ import annotations

import random
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

STABILITY_CONFIG_CONTRACT_VERSION = "arvp.stability-config.v1"
STABILITY_RESULT_CONTRACT_VERSION = "arvp.stability-result.v1"
Aggregation = Literal["mean", "sum"]
StabilityStatus = Literal["complete", "incomplete"]
_VALID_AGGREGATIONS = frozenset({"mean", "sum"})
_NUMERIC_STATUSES = frozenset({"measured", "derived"})


class StabilityError(ValueError):
    """Raised when paired stability inputs or configuration are invalid."""


@dataclass(frozen=True, slots=True)
class StabilityConfig:
    """Caller-visible resampling configuration; never inferred from metric names."""

    aggregation: Aggregation
    sample_count: int
    blocks_per_sample: int
    seed: int
    contract_version: str = STABILITY_CONFIG_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if (
            type(self.aggregation) is not str
            or self.aggregation not in _VALID_AGGREGATIONS
        ):
            raise StabilityError("aggregation must be mean or sum")
        for field in ("sample_count", "blocks_per_sample"):
            value = getattr(self, field)
            if isinstance(value, bool) or type(value) is not int or value < 1:
                raise StabilityError(f"{field} must be a positive integer")
        if isinstance(self.seed, bool) or type(self.seed) is not int or self.seed < 0:
            raise StabilityError("seed must be a non-negative integer")
        if self.contract_version != STABILITY_CONFIG_CONTRACT_VERSION:
            raise StabilityError(
                f"contract_version must be {STABILITY_CONFIG_CONTRACT_VERSION!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "aggregation": self.aggregation,
            "blocks_per_sample": self.blocks_per_sample,
            "contract_version": self.contract_version,
            "sample_count": self.sample_count,
            "seed": self.seed,
        }

    def fingerprint(self) -> str:
        return canonical_hash(self.to_dict())


@dataclass(frozen=True, slots=True)
class PairedStabilityResult:
    """Empirical paired stability evidence (not a statistical significance claim)."""

    request_fingerprint: str
    metric_id: str
    direction: MetricDirection
    aggregation: Aggregation
    status: StabilityStatus
    pair_count: int
    sample_count: int
    observed_delta: Decimal | None
    p05: Decimal | None
    p50: Decimal | None
    p95: Decimal | None
    favors_candidate: bool | None
    reasons: tuple[str, ...]
    contract_version: str = STABILITY_RESULT_CONTRACT_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "aggregation": self.aggregation,
            "contract_version": self.contract_version,
            "direction": self.direction,
            "favors_candidate": self.favors_candidate,
            "metric_id": self.metric_id,
            "observed_delta": self.observed_delta,
            "p05": self.p05,
            "p50": self.p50,
            "p95": self.p95,
            "pair_count": self.pair_count,
            "reasons": list(self.reasons),
            "request_fingerprint": self.request_fingerprint,
            "sample_count": self.sample_count,
            "status": self.status,
        }

    def fingerprint(self) -> str:
        return canonical_hash(self.to_dict())


def _aggregate(values: Sequence[Decimal], aggregation: Aggregation) -> Decimal:
    if not values:
        raise StabilityError("cannot aggregate empty values")
    total = sum(values, Decimal("0"))
    if aggregation == "sum":
        return total
    return total / Decimal(len(values))


def _quantile(ordered: Sequence[Decimal], percentile: int) -> Decimal:
    if not ordered:
        raise StabilityError("cannot compute quantile of empty samples")
    if percentile < 0 or percentile > 100:
        raise StabilityError("percentile must be in 0..100")
    index = ((len(ordered) - 1) * percentile) // 100
    return ordered[index]


def _require_numeric(observation: Observation) -> Decimal:
    status: MetricValueStatus = observation.metric.status
    if status not in _NUMERIC_STATUSES or observation.metric.value is None:
        raise StabilityError(
            f"observation {observation.observation_id!r} requires a finite numeric value"
        )
    value = observation.metric.value
    if not value.is_finite():
        raise StabilityError(
            f"observation {observation.observation_id!r} requires a finite numeric value"
        )
    return value


def _index_side(
    observations: Sequence[Observation],
    *,
    metric_id: str,
    metric_contract: MetricContract,
    side: str,
) -> dict[str, Observation]:
    if isinstance(observations, (str, bytes)) or not isinstance(observations, Sequence):
        raise StabilityError(f"{side} must be a sequence of Observation")
    expected_fp = metric_contract.fingerprint()
    indexed: dict[str, Observation] = {}
    partition_fp: str | None = None
    for observation in observations:
        if type(observation) is not Observation:
            raise StabilityError(f"{side} must contain Observation instances")
        if observation.metric.metric_id != metric_id:
            continue
        if observation.metric.metric_contract_fingerprint != expected_fp:
            raise StabilityError(
                f"{side} observation metric contract fingerprint mismatch"
            )
        if partition_fp is None:
            partition_fp = observation.partition_fingerprint
        elif observation.partition_fingerprint != partition_fp:
            raise StabilityError(f"{side} observations must share one partition")
        if observation.observation_id in indexed:
            raise StabilityError(
                f"duplicate {side} observation_id: {observation.observation_id}"
            )
        indexed[observation.observation_id] = observation
    return indexed


def _favors_candidate(delta: Decimal, direction: MetricDirection) -> bool | None:
    if direction == "maximize":
        return delta > 0
    if direction == "minimize":
        return delta < 0
    return None


def paired_resample_stability(
    *,
    baseline: Sequence[Observation],
    candidate: Sequence[Observation],
    metric_contract: MetricContract,
    metric_id: str,
    config: StabilityConfig,
) -> PairedStabilityResult:
    """Paired baseline/candidate stability with explicit aggregation and seed.

    Empirical p05/p50/p95 describe the resampled candidate-baseline delta
    distribution. They are not statistical significance or confidence intervals.
    """
    if type(metric_contract) is not MetricContract:
        raise StabilityError("metric_contract must be a MetricContract")
    if type(config) is not StabilityConfig:
        raise StabilityError("config must be a StabilityConfig")
    try:
        definition = metric_contract.definition(metric_id)
    except MetricContractError as exc:
        raise StabilityError(str(exc)) from exc

    baseline_index = _index_side(
        baseline,
        metric_id=metric_id,
        metric_contract=metric_contract,
        side="baseline",
    )
    candidate_index = _index_side(
        candidate,
        metric_id=metric_id,
        metric_contract=metric_contract,
        side="candidate",
    )
    if not baseline_index and not candidate_index:
        raise StabilityError("no observations for metric_id")

    baseline_ids = set(baseline_index)
    candidate_ids = set(candidate_index)
    missing_baseline = sorted(candidate_ids - baseline_ids)
    missing_candidate = sorted(baseline_ids - candidate_ids)
    if missing_baseline or missing_candidate:
        reasons: list[str] = []
        if missing_baseline:
            reasons.append("missing_baseline_pairs")
        if missing_candidate:
            reasons.append("missing_candidate_pairs")
        request_fingerprint = canonical_hash(
            {
                "baseline": [baseline_index[i].to_dict() for i in sorted(baseline_ids)],
                "candidate": [
                    candidate_index[i].to_dict() for i in sorted(candidate_ids)
                ],
                "config": config.to_dict(),
                "metric_contract_fingerprint": metric_contract.fingerprint(),
                "metric_id": metric_id,
            }
        )
        return PairedStabilityResult(
            request_fingerprint=request_fingerprint,
            metric_id=metric_id,
            direction=definition.direction,
            aggregation=config.aggregation,
            status="incomplete",
            pair_count=0,
            sample_count=config.sample_count,
            observed_delta=None,
            p05=None,
            p50=None,
            p95=None,
            favors_candidate=None,
            reasons=tuple(reasons),
        )

    pair_ids = tuple(sorted(baseline_ids))
    pairs: list[tuple[Decimal, Decimal]] = []
    for observation_id in pair_ids:
        baseline_value = _require_numeric(baseline_index[observation_id])
        candidate_value = _require_numeric(candidate_index[observation_id])
        pairs.append((baseline_value, candidate_value))

    if config.aggregation == "sum" and config.blocks_per_sample != len(pairs):
        raise StabilityError(
            "sum aggregation requires blocks_per_sample == pair_count "
            "to avoid silent scale mismatch"
        )
    if config.blocks_per_sample > len(pairs):
        raise StabilityError("blocks_per_sample cannot exceed pair_count")

    baseline_values = [item[0] for item in pairs]
    candidate_values = [item[1] for item in pairs]
    observed_delta = _aggregate(candidate_values, config.aggregation) - _aggregate(
        baseline_values, config.aggregation
    )

    rng = random.Random(config.seed)
    sample_deltas: list[Decimal] = []
    for _ in range(config.sample_count):
        sampled = [rng.choice(pairs) for _ in range(config.blocks_per_sample)]
        sample_baseline = [item[0] for item in sampled]
        sample_candidate = [item[1] for item in sampled]
        sample_deltas.append(
            _aggregate(sample_candidate, config.aggregation)
            - _aggregate(sample_baseline, config.aggregation)
        )
    ordered = sorted(sample_deltas)
    p05 = _quantile(ordered, 5)
    p50 = _quantile(ordered, 50)
    p95 = _quantile(ordered, 95)
    if not (p05 <= p50 <= p95):
        raise StabilityError("internal quantile ordering invariant violated")

    request_fingerprint = canonical_hash(
        {
            "baseline": [baseline_index[i].to_dict() for i in pair_ids],
            "candidate": [candidate_index[i].to_dict() for i in pair_ids],
            "config": config.to_dict(),
            "metric_contract_fingerprint": metric_contract.fingerprint(),
            "metric_id": metric_id,
        }
    )
    return PairedStabilityResult(
        request_fingerprint=request_fingerprint,
        metric_id=metric_id,
        direction=definition.direction,
        aggregation=config.aggregation,
        status="complete",
        pair_count=len(pairs),
        sample_count=config.sample_count,
        observed_delta=observed_delta,
        p05=p05,
        p50=p50,
        p95=p95,
        favors_candidate=_favors_candidate(observed_delta, definition.direction),
        reasons=(),
    )
