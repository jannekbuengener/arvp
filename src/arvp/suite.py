"""Versioned EvaluationSuite binding identities, metrics, and gate policy."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from arvp.canonical import canonical_hash
from arvp.datasets import DatasetContentIdentity
from arvp.gates import GatePolicy
from arvp.identities import CandidateSpec, EvaluationPartition
from arvp.metrics import MetricContract

EVALUATION_SUITE_CONTRACT_VERSION = "arvp.evaluation-suite.v1"
_STABLE_ID_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")


class SuiteContractError(ValueError):
    """Raised when an EvaluationSuite contract is malformed."""


def _require_stable_id(value: object, field: str) -> str:
    if type(value) is not str or _STABLE_ID_RE.fullmatch(value) is None:
        raise SuiteContractError(f"{field} must match ^[a-z][a-z0-9_.-]{{0,63}}$")
    return value


@dataclass(frozen=True, slots=True, init=False)
class EvaluationSuite:
    """Decision-relevant evaluation binding with a stable suite fingerprint.

    The suite fingerprint changes when content identity, partitions, metric
    contract, gate policy, or baseline candidate identity changes. Partition
    insertion order does not affect the fingerprint.
    """

    suite_id: str
    content_identity: DatasetContentIdentity
    partitions: tuple[EvaluationPartition, ...]
    metric_contract_fingerprint: str
    gate_policy_fingerprint: str
    baseline_candidate_fingerprint: str
    contract_version: str

    def __init__(
        self,
        suite_id: str,
        content_identity: DatasetContentIdentity,
        partitions: Sequence[EvaluationPartition],
        metric_contract: MetricContract,
        gate_policy: GatePolicy,
        baseline_candidate: CandidateSpec,
    ) -> None:
        suite_id = _require_stable_id(suite_id, "suite_id")
        if type(content_identity) is not DatasetContentIdentity:
            raise SuiteContractError(
                "content_identity must be a DatasetContentIdentity"
            )
        if type(metric_contract) is not MetricContract:
            raise SuiteContractError("metric_contract must be a MetricContract")
        if type(gate_policy) is not GatePolicy:
            raise SuiteContractError("gate_policy must be a GatePolicy")
        if type(baseline_candidate) is not CandidateSpec:
            raise SuiteContractError("baseline_candidate must be a CandidateSpec")
        if (
            isinstance(partitions, (str, bytes))
            or not isinstance(partitions, Sequence)
            or not partitions
        ):
            raise SuiteContractError("partitions must be a non-empty sequence")

        metric_fp = metric_contract.fingerprint()
        if gate_policy.metric_contract_fingerprint != metric_fp:
            raise SuiteContractError(
                "gate_policy metric contract fingerprint does not match metric_contract"
            )

        normalized: list[EvaluationPartition] = []
        seen: set[str] = set()
        for partition in partitions:
            if type(partition) is not EvaluationPartition:
                raise SuiteContractError(
                    "partitions must contain EvaluationPartition instances"
                )
            if partition.partition_id in seen:
                raise SuiteContractError(
                    f"duplicate partition_id: {partition.partition_id}"
                )
            seen.add(partition.partition_id)
            normalized.append(partition)

        object.__setattr__(self, "suite_id", suite_id)
        object.__setattr__(self, "content_identity", content_identity)
        object.__setattr__(
            self,
            "partitions",
            tuple(sorted(normalized, key=lambda item: item.partition_id)),
        )
        object.__setattr__(self, "metric_contract_fingerprint", metric_fp)
        object.__setattr__(self, "gate_policy_fingerprint", gate_policy.fingerprint())
        object.__setattr__(
            self,
            "baseline_candidate_fingerprint",
            baseline_candidate.fingerprint(),
        )
        object.__setattr__(self, "contract_version", EVALUATION_SUITE_CONTRACT_VERSION)

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline_candidate_fingerprint": self.baseline_candidate_fingerprint,
            "content_identity": self.content_identity.to_dict(),
            "contract_version": self.contract_version,
            "gate_policy_fingerprint": self.gate_policy_fingerprint,
            "metric_contract_fingerprint": self.metric_contract_fingerprint,
            "partitions": [partition.to_dict() for partition in self.partitions],
            "suite_id": self.suite_id,
        }

    def fingerprint(self) -> str:
        return canonical_hash(self.to_dict())

    def partition(self, partition_id: str) -> EvaluationPartition:
        for partition in self.partitions:
            if partition.partition_id == partition_id:
                return partition
        raise SuiteContractError(f"unknown partition_id: {partition_id}")
