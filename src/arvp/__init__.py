"""ARVP: deterministic validation, evaluation, and experiment primitives."""

from arvp.canonical import (
    CANONICAL_CONTRACT_VERSION,
    CanonicalizationError,
    FingerprintFormatError,
    canonical_hash,
    canonical_json_dumps,
    validate_fingerprint,
)
from arvp.datasets import (
    CONTENT_IDENTITY_SCHEMA_VERSION,
    DatasetContentIdentity,
    DatasetOrdering,
    DatasetRequest,
)
from arvp.evidence import (
    FAILURE_EVIDENCE_VERSION,
    FailureCode,
    FailureEvidence,
    PortableEvidenceError,
    validate_portable_metadata,
)
from arvp.identities import (
    CANDIDATE_CONTRACT_VERSION,
    EVALUATION_PARTITION_CONTRACT_VERSION,
    CandidateSpec,
    EvaluationPartition,
    IdentityContractError,
    PartitionRole,
)
from arvp.provenance import RunProvenance, RunRecord

__all__ = [
    "CANONICAL_CONTRACT_VERSION",
    "CANDIDATE_CONTRACT_VERSION",
    "CONTENT_IDENTITY_SCHEMA_VERSION",
    "EVALUATION_PARTITION_CONTRACT_VERSION",
    "FAILURE_EVIDENCE_VERSION",
    "CandidateSpec",
    "CanonicalizationError",
    "DatasetContentIdentity",
    "DatasetOrdering",
    "DatasetRequest",
    "EvaluationPartition",
    "FailureCode",
    "FailureEvidence",
    "FingerprintFormatError",
    "IdentityContractError",
    "PartitionRole",
    "PortableEvidenceError",
    "RunProvenance",
    "RunRecord",
    "canonical_hash",
    "canonical_json_dumps",
    "validate_fingerprint",
    "validate_portable_metadata",
]
