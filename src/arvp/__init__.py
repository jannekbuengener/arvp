"""ARVP: deterministic validation, evaluation, and experiment primitives."""

from arvp.canonical import (
    CANONICAL_CONTRACT_VERSION,
    CanonicalizationError,
    FingerprintFormatError,
    canonical_hash,
    canonical_json_dumps,
    validate_fingerprint,
)
from arvp.datasets import DatasetContentIdentity, DatasetRequest
from arvp.evidence import (
    FAILURE_EVIDENCE_VERSION,
    FailureCode,
    FailureEvidence,
    PortableEvidenceError,
    validate_portable_metadata,
)
from arvp.provenance import RunProvenance, RunRecord

__all__ = [
    "DatasetContentIdentity",
    "DatasetRequest",
    "RunProvenance",
    "RunRecord",
    "CANONICAL_CONTRACT_VERSION",
    "canonical_hash",
    "canonical_json_dumps",
    "validate_fingerprint",
    "CanonicalizationError",
    "FingerprintFormatError",
    "FAILURE_EVIDENCE_VERSION",
    "FailureCode",
    "FailureEvidence",
    "PortableEvidenceError",
    "validate_portable_metadata",
]
