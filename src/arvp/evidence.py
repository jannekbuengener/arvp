"""Portable failure evidence and metadata safety boundary.

This module defines the canonical failure evidence contract and the shared
metadata validation used by all portable ARVP surfaces (scenarios, evaluation,
provenance, datasets). It replaces the ad-hoc error handling and denylist
approach with a positive, portable contract.

Key design principles:
- No free-form error text in portable results
- Exception type name only (no message, no traceback)
- Expected failures are explicit evidence; unexpected exceptions fail-fast by default
- Metadata is caller-projected and validated against Canonical v2 + danger keys
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, get_args

from arvp.canonical import (
    CanonicalizationError,
    canonical_json_dumps,
)

FAILURE_EVIDENCE_VERSION = "arvp.failure-evidence.v1"

FailureCode = Literal[
    "expected_domain_failure",
    "input_unavailable",
    "invalid_input",
    "unexpected_exception",
    "insufficient_evidence",
]

_FAILURE_CODES = frozenset(get_args(FailureCode))
_EXCEPTION_TYPE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_STAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")


class PortableEvidenceError(ValueError):
    """Raised when portable evidence contract is violated."""


@dataclass(frozen=True, slots=True)
class FailureEvidence:
    """Structured, portable failure evidence.

    Replaces free-form failure_reason strings. No diagnostic text, no paths,
    no secrets. Only stable classification and caller-projected metadata.
    """

    code: FailureCode
    exception_type: str | None = None
    stage: str | None = None
    metadata: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or self.code not in _FAILURE_CODES:
            raise PortableEvidenceError(f"invalid failure code: {self.code!r}")
        if self.exception_type is not None:
            if not isinstance(
                self.exception_type, str
            ) or not _EXCEPTION_TYPE_RE.fullmatch(self.exception_type):
                raise PortableEvidenceError(
                    "exception_type must be a simple class name token or None"
                )
        if self.stage is not None:
            if not isinstance(self.stage, str) or not _STAGE_RE.fullmatch(self.stage):
                raise PortableEvidenceError(
                    "stage must be a non-empty string using 1-64 portable token characters or None"
                )
        if self.metadata is not None:
            if not isinstance(self.metadata, Mapping):
                raise PortableEvidenceError("metadata must be a mapping or None")
            object.__setattr__(
                self,
                "metadata",
                validate_portable_metadata(self.metadata, field="failure.metadata"),
            )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code}
        if self.exception_type is not None:
            payload["exception_type"] = self.exception_type
        if self.stage is not None:
            payload["stage"] = self.stage
        if self.metadata is not None:
            payload["metadata"] = copy.deepcopy(dict(self.metadata))
        return payload

    @classmethod
    def from_unexpected_exception(
        cls,
        exc: BaseException,
        *,
        stage: str | None = None,
    ) -> "FailureEvidence":
        """Create failure evidence from an unexpected exception.

        Only the exception class name is captured. Message, traceback,
        and any path/secret data in the exception are deliberately excluded.
        """
        return cls(
            code="unexpected_exception",
            exception_type=type(exc).__name__,
            stage=stage,
            metadata=None,
        )

    @classmethod
    def expected_domain_failure(
        cls,
        *,
        stage: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "FailureEvidence":
        """Create evidence for an expected domain failure (e.g., input unavailable)."""
        return cls(
            code="expected_domain_failure",
            exception_type=None,
            stage=stage,
            metadata=metadata,
        )

    @classmethod
    def input_unavailable(
        cls,
        *,
        stage: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "FailureEvidence":
        """Create evidence for unavailable input (runner-level)."""
        return cls(
            code="input_unavailable",
            exception_type=None,
            stage=stage,
            metadata=metadata,
        )

    @classmethod
    def invalid_input(
        cls,
        *,
        stage: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "FailureEvidence":
        """Create evidence for invalid input detected before runner."""
        return cls(
            code="invalid_input",
            exception_type=None,
            stage=stage,
            metadata=metadata,
        )

    @classmethod
    def insufficient_evidence(
        cls,
        *,
        stage: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "FailureEvidence":
        """Create evidence for insufficient evidence to produce a result."""
        return cls(
            code="insufficient_evidence",
            exception_type=None,
            stage=stage,
            metadata=metadata,
        )


_DANGER_KEYS = frozenset(
    {
        "api_key",
        "api_secret",
        "authorization",
        "connection_string",
        "database_url",
        "dsn",
        "file_path",
        "password",
        "path",
        "secret",
        "token",
    }
)


def validate_portable_metadata(
    value: Mapping[str, Any],
    *,
    field: str = "metadata",
) -> dict[str, Any]:
    """Validate metadata for portable evidence projection.

    Two-layer validation:
    1. Canonical v2: the entire value must be canonicalizable (no non-portable types)
    2. Danger keys: recursive denylist for known sensitive key names (defense in depth)

    Returns a deep copy of the validated mapping.
    """
    if not isinstance(value, Mapping):
        raise PortableEvidenceError(f"{field}: must be a mapping")

    copied = dict(value)

    # Layer 1: Canonical v2 validation
    try:
        canonical_json_dumps(copied)
    except CanonicalizationError as exc:
        raise PortableEvidenceError(f"{field}: not canonicalizable: {exc}") from exc

    # Layer 2: Danger keys (case-insensitive)
    def walk(node: Any, path: str = "") -> None:
        if isinstance(node, Mapping):
            for key, item in node.items():
                key_text = str(key)
                if key_text.casefold() in _DANGER_KEYS:
                    raise PortableEvidenceError(
                        f"{field}: forbidden key '{key_text}' at {path or 'root'}"
                    )
                walk(item, f"{path}.{key_text}" if path else key_text)
        elif isinstance(node, (list, tuple)):
            for i, item in enumerate(node):
                walk(item, f"{path}[{i}]")

    walk(copied)

    return copy.deepcopy(copied)
