"""Domain-neutral candidate and evaluation partition identities."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from arvp.canonical import canonical_hash
from arvp.datasets import DatasetContentIdentity
from arvp.evidence import PortableEvidenceError, validate_portable_metadata

CANDIDATE_CONTRACT_VERSION = "arvp.candidate.v1"
EVALUATION_PARTITION_CONTRACT_VERSION = "arvp.evaluation-partition.v1"

PartitionRole = Literal[
    "development",
    "calibration",
    "validation",
    "test",
    "external_check",
]
_VALID_PARTITION_ROLES = frozenset(
    {"development", "calibration", "validation", "test", "external_check"}
)


class IdentityContractError(ValueError):
    """Raised when a portable identity contract is malformed or unsafe."""


def _require_text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise IdentityContractError(f"{field} must be a non-empty string")
    return value.strip()


def _portable_configuration(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise IdentityContractError("configuration must be a mapping")
    try:
        return validate_portable_metadata(dict(value), field="configuration")
    except PortableEvidenceError as exc:
        raise IdentityContractError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class CandidateSpec:
    """Portable semantic identity of one candidate implementation/configuration."""

    candidate_id: str
    implementation_id: str
    revision: str
    configuration: Mapping[str, Any]
    contract_version: str = CANDIDATE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_text(self.candidate_id, "candidate_id")
        _require_text(self.implementation_id, "implementation_id")
        _require_text(self.revision, "revision")
        if self.contract_version != CANDIDATE_CONTRACT_VERSION:
            raise IdentityContractError(
                f"contract_version must be {CANDIDATE_CONTRACT_VERSION!r}"
            )
        object.__setattr__(
            self, "configuration", _portable_configuration(self.configuration)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "configuration": _portable_configuration(self.configuration),
            "contract_version": self.contract_version,
            "implementation_id": self.implementation_id,
            "revision": self.revision,
        }

    def fingerprint(self) -> str:
        return canonical_hash(self.to_dict())


@dataclass(frozen=True, slots=True)
class EvaluationPartition:
    """Domain-neutral evaluation role bound to exact dataset membership."""

    partition_id: str
    role: PartitionRole
    content_identity: DatasetContentIdentity
    contract_version: str = EVALUATION_PARTITION_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_text(self.partition_id, "partition_id")
        if type(self.role) is not str or self.role not in _VALID_PARTITION_ROLES:
            raise IdentityContractError(
                "role must be development, calibration, validation, test, or external_check"
            )
        if type(self.content_identity) is not DatasetContentIdentity:
            raise IdentityContractError(
                "content_identity must be a DatasetContentIdentity"
            )
        if self.contract_version != EVALUATION_PARTITION_CONTRACT_VERSION:
            raise IdentityContractError(
                f"contract_version must be {EVALUATION_PARTITION_CONTRACT_VERSION!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_identity": self.content_identity.to_dict(),
            "contract_version": self.contract_version,
            "partition_id": self.partition_id,
            "role": self.role,
        }

    def fingerprint(self) -> str:
        return canonical_hash(self.to_dict())
