"""Typed, domain-neutral metric and paired observation contracts."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from arvp.canonical import (
    CanonicalizationError,
    FingerprintFormatError,
    canonical_hash,
    canonical_json_dumps,
    validate_fingerprint,
)
from arvp.identities import CandidateSpec, EvaluationPartition

METRIC_DEFINITION_CONTRACT_VERSION = "arvp.metric-definition.v1"
METRIC_CONTRACT_VERSION = "arvp.metric-contract.v1"
METRIC_VALUE_CONTRACT_VERSION = "arvp.metric-value.v1"
OBSERVATION_CONTRACT_VERSION = "arvp.observation.v1"

MetricDirection = Literal["maximize", "minimize", "neutral"]
MetricValueStatus = Literal["measured", "derived", "unknown", "not_applicable"]

_METRIC_ID_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_OBSERVATION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_VALID_DIRECTIONS = frozenset({"maximize", "minimize", "neutral"})
_VALID_STATUSES = frozenset({"measured", "derived", "unknown", "not_applicable"})
_VALUE_STATUSES = frozenset({"measured", "derived"})


class MetricContractError(ValueError):
    """Raised when a metric or observation contract is malformed."""


def _require_metric_id(value: object) -> str:
    if type(value) is not str or _METRIC_ID_RE.fullmatch(value) is None:
        raise MetricContractError("metric_id must match ^[a-z][a-z0-9_.-]{0,63}$")
    return value


def _require_unit(value: object) -> str:
    if type(value) is not str or not value.strip():
        raise MetricContractError("unit must be a non-empty string")
    try:
        canonical_json_dumps({"unit": value})
    except CanonicalizationError as exc:
        raise MetricContractError(f"unit must be portable text: {exc}") from exc
    return value


def _require_observation_id(value: object) -> str:
    if type(value) is not str or _OBSERVATION_ID_RE.fullmatch(value) is None:
        raise MetricContractError(
            "observation_id must match ^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
        )
    return value


def _finite_decimal(value: object) -> Decimal:
    if type(value) is int:
        result = Decimal(value)
    elif type(value) is float:
        if not math.isfinite(value):
            raise MetricContractError(
                "measured/derived metrics require a finite numeric value"
            )
        result = Decimal(str(value))
    elif type(value) is Decimal:
        result = value
    else:
        raise MetricContractError(
            "measured/derived metrics require a finite numeric value"
        )
    if not result.is_finite():
        raise MetricContractError(
            "measured/derived metrics require a finite numeric value"
        )
    return result


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    metric_id: str
    direction: MetricDirection
    unit: str
    required: bool
    contract_version: str = METRIC_DEFINITION_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_metric_id(self.metric_id)
        if type(self.direction) is not str or self.direction not in _VALID_DIRECTIONS:
            raise MetricContractError(
                "direction must be maximize, minimize, or neutral"
            )
        _require_unit(self.unit)
        if type(self.required) is not bool:
            raise MetricContractError("required must be bool")
        if self.contract_version != METRIC_DEFINITION_CONTRACT_VERSION:
            raise MetricContractError(
                f"contract_version must be {METRIC_DEFINITION_CONTRACT_VERSION!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "direction": self.direction,
            "metric_id": self.metric_id,
            "required": self.required,
            "unit": self.unit,
        }

    def fingerprint(self) -> str:
        return canonical_hash(self.to_dict())


@dataclass(frozen=True, slots=True, init=False)
class MetricValue:
    metric_id: str
    status: MetricValueStatus
    value: Decimal | None
    metric_contract_fingerprint: str
    contract_version: str

    @classmethod
    def _from_contract(
        cls,
        *,
        metric_id: str,
        status: MetricValueStatus,
        value: Decimal | None,
        metric_contract_fingerprint: str,
    ) -> MetricValue:
        instance = object.__new__(cls)
        object.__setattr__(instance, "metric_id", metric_id)
        object.__setattr__(instance, "status", status)
        object.__setattr__(instance, "value", value)
        object.__setattr__(
            instance, "metric_contract_fingerprint", metric_contract_fingerprint
        )
        object.__setattr__(instance, "contract_version", METRIC_VALUE_CONTRACT_VERSION)
        return instance

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "contract_version": self.contract_version,
            "metric_contract_fingerprint": self.metric_contract_fingerprint,
            "metric_id": self.metric_id,
            "status": self.status,
        }
        if self.value is not None:
            payload["value"] = self.value
        return payload

    def fingerprint(self) -> str:
        return canonical_hash(self.to_dict())


@dataclass(frozen=True, slots=True)
class MetricContract:
    definitions: tuple[MetricDefinition, ...]
    contract_version: str = METRIC_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if type(self.definitions) is not tuple or not self.definitions:
            raise MetricContractError("definitions must be a non-empty tuple")
        if self.contract_version != METRIC_CONTRACT_VERSION:
            raise MetricContractError(
                f"contract_version must be {METRIC_CONTRACT_VERSION!r}"
            )
        seen: set[str] = set()
        normalized: list[MetricDefinition] = []
        for definition in self.definitions:
            if type(definition) is not MetricDefinition:
                raise MetricContractError(
                    "definitions must contain MetricDefinition instances"
                )
            if definition.metric_id in seen:
                raise MetricContractError(
                    f"duplicate metric_id: {definition.metric_id}"
                )
            seen.add(definition.metric_id)
            normalized.append(definition)
        object.__setattr__(
            self,
            "definitions",
            tuple(sorted(normalized, key=lambda item: item.metric_id)),
        )

    def definition(self, metric_id: str) -> MetricDefinition:
        _require_metric_id(metric_id)
        for definition in self.definitions:
            if definition.metric_id == metric_id:
                return definition
        raise MetricContractError(f"unknown metric_id: {metric_id}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "definitions": [definition.to_dict() for definition in self.definitions],
        }

    def fingerprint(self) -> str:
        return canonical_hash(self.to_dict())

    def value(
        self,
        metric_id: str,
        status: MetricValueStatus,
        value: int | float | Decimal | None = None,
    ) -> MetricValue:
        self.definition(metric_id)
        if type(status) is not str or status not in _VALID_STATUSES:
            raise MetricContractError(
                "status must be measured, derived, unknown, or not_applicable"
            )
        if status in _VALUE_STATUSES:
            normalized_value = _finite_decimal(value)
        else:
            if value is not None:
                raise MetricContractError(
                    "unknown/not_applicable metrics must not carry a numeric value"
                )
            normalized_value = None
        return MetricValue._from_contract(
            metric_id=metric_id,
            status=status,
            value=normalized_value,
            metric_contract_fingerprint=self.fingerprint(),
        )

    def validate_values(self, values: Sequence[MetricValue]) -> tuple[MetricValue, ...]:
        if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
            raise MetricContractError(
                "values must be a sequence of MetricValue instances"
            )
        expected_fingerprint = self.fingerprint()
        seen: set[str] = set()
        normalized: list[MetricValue] = []
        for value in values:
            if type(value) is not MetricValue:
                raise MetricContractError("values must contain MetricValue instances")
            self.definition(value.metric_id)
            if value.metric_contract_fingerprint != expected_fingerprint:
                raise MetricContractError(
                    "metric contract fingerprint does not match MetricContract"
                )
            if value.metric_id in seen:
                raise MetricContractError(f"duplicate metric_id: {value.metric_id}")
            seen.add(value.metric_id)
            normalized.append(value)
        return tuple(sorted(normalized, key=lambda item: item.metric_id))


@dataclass(frozen=True, slots=True, init=False)
class Observation:
    observation_id: str
    candidate_fingerprint: str
    partition_id: str
    partition_fingerprint: str
    metric: MetricValue
    contract_version: str

    def __init__(
        self,
        *,
        observation_id: str,
        candidate: CandidateSpec,
        partition: EvaluationPartition,
        metric_contract: MetricContract,
        metric: MetricValue,
    ) -> None:
        _require_observation_id(observation_id)
        if type(candidate) is not CandidateSpec:
            raise MetricContractError("candidate must be a CandidateSpec")
        if type(partition) is not EvaluationPartition:
            raise MetricContractError("partition must be an EvaluationPartition")
        if type(metric_contract) is not MetricContract:
            raise MetricContractError("metric_contract must be a MetricContract")
        validated = metric_contract.validate_values((metric,))
        object.__setattr__(self, "observation_id", observation_id)
        object.__setattr__(self, "candidate_fingerprint", candidate.fingerprint())
        object.__setattr__(self, "partition_id", partition.partition_id)
        object.__setattr__(self, "partition_fingerprint", partition.fingerprint())
        object.__setattr__(self, "metric", validated[0])
        object.__setattr__(self, "contract_version", OBSERVATION_CONTRACT_VERSION)

    def pairing_key(self) -> tuple[str, str, str, str]:
        return (
            self.partition_fingerprint,
            self.metric.metric_contract_fingerprint,
            self.metric.metric_id,
            self.observation_id,
        )

    def scope_key(self) -> tuple[str, str, str, str, str]:
        return (self.candidate_fingerprint, *self.pairing_key())

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_fingerprint": self.candidate_fingerprint,
            "contract_version": self.contract_version,
            "metric": self.metric.to_dict(),
            "observation_id": self.observation_id,
            "partition_fingerprint": self.partition_fingerprint,
            "partition_id": self.partition_id,
        }

    def fingerprint(self) -> str:
        return canonical_hash(self.to_dict())

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any], *, metric_contract: MetricContract
    ) -> Observation:
        """Revive a portable observation mapping without consumer runtime objects."""
        if not isinstance(payload, Mapping):
            raise MetricContractError("observation payload must be a mapping")
        if type(metric_contract) is not MetricContract:
            raise MetricContractError("metric_contract must be a MetricContract")
        contract_version = payload.get("contract_version", OBSERVATION_CONTRACT_VERSION)
        if contract_version != OBSERVATION_CONTRACT_VERSION:
            raise MetricContractError(
                f"contract_version must be {OBSERVATION_CONTRACT_VERSION!r}"
            )
        observation_id = _require_observation_id(payload.get("observation_id"))
        try:
            candidate_fingerprint = validate_fingerprint(
                payload.get("candidate_fingerprint"), "candidate_fingerprint"
            )
            partition_fingerprint = validate_fingerprint(
                payload.get("partition_fingerprint"), "partition_fingerprint"
            )
        except FingerprintFormatError as exc:
            raise MetricContractError(str(exc)) from exc
        partition_id = payload.get("partition_id")
        if type(partition_id) is not str or not partition_id.strip():
            raise MetricContractError("partition_id must be a non-empty string")
        metric_payload = payload.get("metric")
        if not isinstance(metric_payload, Mapping):
            raise MetricContractError("metric must be a mapping")
        metric_id = metric_payload.get("metric_id")
        status = metric_payload.get("status")
        if type(metric_id) is not str:
            raise MetricContractError("metric.metric_id must be a string")
        if type(status) is not str or status not in _VALID_STATUSES:
            raise MetricContractError(
                "status must be measured, derived, unknown, or not_applicable"
            )
        typed_status: MetricValueStatus = status  # type: ignore[assignment]
        if "value" in metric_payload:
            metric = metric_contract.value(
                metric_id, typed_status, metric_payload["value"]
            )
        else:
            metric = metric_contract.value(metric_id, typed_status)
        expected_fp = metric_contract.fingerprint()
        declared_fp = metric_payload.get("metric_contract_fingerprint")
        if declared_fp is not None and declared_fp != expected_fp:
            raise MetricContractError(
                "metric contract fingerprint does not match MetricContract"
            )
        if metric.metric_contract_fingerprint != expected_fp:
            raise MetricContractError(
                "metric contract fingerprint does not match MetricContract"
            )
        instance = object.__new__(cls)
        object.__setattr__(instance, "observation_id", observation_id)
        object.__setattr__(instance, "candidate_fingerprint", candidate_fingerprint)
        object.__setattr__(instance, "partition_id", partition_id.strip())
        object.__setattr__(instance, "partition_fingerprint", partition_fingerprint)
        object.__setattr__(instance, "metric", metric)
        object.__setattr__(instance, "contract_version", OBSERVATION_CONTRACT_VERSION)
        return instance


def validate_observations(
    observations: Sequence[Observation],
) -> tuple[Observation, ...]:
    if isinstance(observations, (str, bytes)) or not isinstance(observations, Sequence):
        raise MetricContractError(
            "observations must be a sequence of Observation instances"
        )
    seen: set[tuple[str, str, str, str, str]] = set()
    normalized: list[Observation] = []
    for observation in observations:
        if type(observation) is not Observation:
            raise MetricContractError("observations must contain Observation instances")
        key = observation.scope_key()
        if key in seen:
            raise MetricContractError("duplicate observation scope")
        seen.add(key)
        normalized.append(observation)
    return tuple(sorted(normalized, key=lambda item: item.scope_key()))
