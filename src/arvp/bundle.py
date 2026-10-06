"""Evidence Bundle v1: portable, versioned evaluation evidence artifact.

The Evidence Bundle is the canonical portable source of truth for what was
tested, against what, what was measured, and why the gate said PASS/FAIL/HOLD.

Fingerprint semantics:
- ``evidence_fingerprint`` hashes only decision-relevant semantic fields.
- Volatile presentation/transport fields (``generated_at``) are excluded.
- ``artifact_hash`` is a separate byte-integrity digest and is excluded from
  the semantic fingerprint.
- The fingerprint field itself is never part of its own hash input.

Compatibility rule for unknown fields: reject. Bundles and schema assets use
``additionalProperties: false`` / explicit required key sets so consumers never
silently accept unrecognized top-level evidence keys.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arvp.canonical import (
    CanonicalizationError,
    FingerprintFormatError,
    canonical_hash,
    canonical_json_dumps,
    revive_canonical,
    validate_fingerprint,
)
from arvp.evidence import (
    FailureEvidence,
    PortableEvidenceError,
    validate_portable_metadata,
)
from arvp.gates import GateDecision, MetricComparison
from arvp.metrics import Observation
from arvp.provenance import ProvenanceError, RunProvenance, canonicalize_utc
from arvp.stability import PairedStabilityResult
from arvp.suite import EvaluationSuite

EVIDENCE_BUNDLE_CONTRACT_VERSION = "arvp.evidence.v1"

_TOP_LEVEL_KEYS = frozenset(
    {
        "artifact_hash",
        "baseline_candidate_fingerprint",
        "candidate_fingerprint",
        "comparisons",
        "contract_version",
        "evidence_fingerprint",
        "failures",
        "gate_decision",
        "gate_policy_fingerprint",
        "generated_at",
        "observations",
        "partition_fingerprint",
        "partition_id",
        "run_provenance",
        "stability",
        "suite",
    }
)
_SEMANTIC_EXCLUDED_KEYS = frozenset(
    {
        "artifact_hash",
        "evidence_fingerprint",
        "generated_at",
    }
)


class EvidenceBundleError(ValueError):
    """Raised when an Evidence Bundle contract or write path is invalid."""


def _require_fingerprint(value: object, field: str) -> str:
    try:
        return validate_fingerprint(value, field)
    except FingerprintFormatError as exc:
        raise EvidenceBundleError(str(exc)) from exc


def _require_mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise EvidenceBundleError(f"{field} must be a mapping")
    try:
        validate_portable_metadata(value, field=field)
    except PortableEvidenceError as exc:
        raise EvidenceBundleError(str(exc)) from exc
    return dict(value)


def _require_mapping_sequence(value: object, field: str) -> tuple[dict[str, Any], ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise EvidenceBundleError(f"{field} must be a sequence of mappings")
    items: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        items.append(_require_mapping(item, f"{field}[{index}]"))
    return tuple(items)


def semantic_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return the decision-relevant subset used for ``evidence_fingerprint``."""
    if not isinstance(payload, Mapping):
        raise EvidenceBundleError("payload must be a mapping")
    return {
        key: payload[key]
        for key in sorted(payload)
        if key not in _SEMANTIC_EXCLUDED_KEYS
    }


def compute_evidence_fingerprint(payload: Mapping[str, Any]) -> str:
    """Hash semantic evidence only; never includes the fingerprint field itself."""
    return canonical_hash(semantic_payload(payload))


def compute_artifact_hash(payload: Mapping[str, Any]) -> str:
    """Hash the portable artifact bytes excluding ``artifact_hash`` itself."""
    body = {key: value for key, value in payload.items() if key != "artifact_hash"}
    return canonical_hash(body)


@dataclass(frozen=True, slots=True, init=False)
class EvidenceBundle:
    """Self-contained portable evaluation evidence artifact."""

    contract_version: str
    suite: dict[str, Any]
    partition_id: str
    partition_fingerprint: str
    candidate_fingerprint: str
    baseline_candidate_fingerprint: str | None
    run_provenance: dict[str, Any]
    observations: tuple[dict[str, Any], ...]
    comparisons: tuple[dict[str, Any], ...]
    gate_policy_fingerprint: str
    gate_decision: dict[str, Any]
    stability: tuple[dict[str, Any], ...]
    failures: tuple[dict[str, Any], ...]
    generated_at: str
    evidence_fingerprint: str
    artifact_hash: str | None

    def __init__(
        self,
        *,
        suite: Mapping[str, Any],
        partition_id: str,
        partition_fingerprint: str,
        candidate_fingerprint: str,
        baseline_candidate_fingerprint: str | None,
        run_provenance: Mapping[str, Any],
        observations: Sequence[Mapping[str, Any]],
        comparisons: Sequence[Mapping[str, Any]],
        gate_policy_fingerprint: str,
        gate_decision: Mapping[str, Any],
        stability: Sequence[Mapping[str, Any]] = (),
        failures: Sequence[Mapping[str, Any]] = (),
        generated_at: str,
        artifact_hash: str | None = None,
        contract_version: str = EVIDENCE_BUNDLE_CONTRACT_VERSION,
        evidence_fingerprint: str | None = None,
    ) -> None:
        if contract_version != EVIDENCE_BUNDLE_CONTRACT_VERSION:
            raise EvidenceBundleError(
                f"contract_version must be {EVIDENCE_BUNDLE_CONTRACT_VERSION!r}"
            )
        if type(partition_id) is not str or not partition_id.strip():
            raise EvidenceBundleError("partition_id must be a non-empty string")

        suite_payload = _require_mapping(suite, "suite")
        provenance_payload = _require_mapping(run_provenance, "run_provenance")
        decision_payload = _require_mapping(gate_decision, "gate_decision")
        observation_payloads = _require_mapping_sequence(observations, "observations")
        comparison_payloads = _require_mapping_sequence(comparisons, "comparisons")
        stability_payloads = _require_mapping_sequence(stability, "stability")
        failure_payloads = _require_mapping_sequence(failures, "failures")

        partition_fp = _require_fingerprint(
            partition_fingerprint, "partition_fingerprint"
        )
        candidate_fp = _require_fingerprint(
            candidate_fingerprint, "candidate_fingerprint"
        )
        gate_policy_fp = _require_fingerprint(
            gate_policy_fingerprint, "gate_policy_fingerprint"
        )
        baseline_fp: str | None
        if baseline_candidate_fingerprint is None:
            baseline_fp = None
        else:
            baseline_fp = _require_fingerprint(
                baseline_candidate_fingerprint, "baseline_candidate_fingerprint"
            )
        if artifact_hash is not None:
            artifact_hash = _require_fingerprint(artifact_hash, "artifact_hash")

        try:
            generated = canonicalize_utc(generated_at, "generated_at")
        except ProvenanceError as exc:
            raise EvidenceBundleError(str(exc)) from exc

        object.__setattr__(self, "contract_version", contract_version)
        object.__setattr__(self, "suite", suite_payload)
        object.__setattr__(self, "partition_id", partition_id.strip())
        object.__setattr__(self, "partition_fingerprint", partition_fp)
        object.__setattr__(self, "candidate_fingerprint", candidate_fp)
        object.__setattr__(self, "baseline_candidate_fingerprint", baseline_fp)
        object.__setattr__(self, "run_provenance", provenance_payload)
        object.__setattr__(self, "observations", observation_payloads)
        object.__setattr__(self, "comparisons", comparison_payloads)
        object.__setattr__(self, "gate_policy_fingerprint", gate_policy_fp)
        object.__setattr__(self, "gate_decision", decision_payload)
        object.__setattr__(self, "stability", stability_payloads)
        object.__setattr__(self, "failures", failure_payloads)
        object.__setattr__(self, "generated_at", generated)
        object.__setattr__(self, "artifact_hash", artifact_hash)

        draft = self._payload(include_fingerprint=False, include_artifact_hash=False)
        computed = compute_evidence_fingerprint(draft)
        if evidence_fingerprint is None:
            evidence_fingerprint = computed
        else:
            evidence_fingerprint = _require_fingerprint(
                evidence_fingerprint, "evidence_fingerprint"
            )
            if evidence_fingerprint != computed:
                raise EvidenceBundleError(
                    "evidence_fingerprint does not match semantic payload"
                )
        object.__setattr__(self, "evidence_fingerprint", evidence_fingerprint)

    @classmethod
    def build(
        cls,
        *,
        suite: EvaluationSuite,
        partition_id: str,
        candidate_fingerprint: str,
        run_provenance: RunProvenance,
        gate_decision: GateDecision,
        observations: Sequence[Observation] = (),
        comparisons: Sequence[MetricComparison] = (),
        stability: Sequence[PairedStabilityResult] = (),
        failures: Sequence[FailureEvidence] = (),
        generated_at: str,
    ) -> EvidenceBundle:
        """Assemble a bundle from live contract objects."""
        if type(suite) is not EvaluationSuite:
            raise EvidenceBundleError("suite must be an EvaluationSuite")
        if type(run_provenance) is not RunProvenance:
            raise EvidenceBundleError("run_provenance must be a RunProvenance")
        if type(gate_decision) is not GateDecision:
            raise EvidenceBundleError("gate_decision must be a GateDecision")
        partition = suite.partition(partition_id)
        if run_provenance.suite_fingerprint != suite.fingerprint():
            raise EvidenceBundleError("run_provenance suite fingerprint mismatch")
        if run_provenance.partition_id != partition.partition_id:
            raise EvidenceBundleError("run_provenance partition_id mismatch")
        if run_provenance.partition_fingerprint != partition.fingerprint():
            raise EvidenceBundleError("run_provenance partition fingerprint mismatch")
        if run_provenance.candidate_fingerprint != candidate_fingerprint:
            raise EvidenceBundleError("run_provenance candidate fingerprint mismatch")
        if gate_decision.policy_fingerprint != suite.gate_policy_fingerprint:
            raise EvidenceBundleError("gate_decision policy fingerprint mismatch")

        for index, observation in enumerate(observations):
            if type(observation) is not Observation:
                raise EvidenceBundleError(
                    f"observations[{index}] must be an Observation"
                )
        for index, comparison in enumerate(comparisons):
            if type(comparison) is not MetricComparison:
                raise EvidenceBundleError(
                    f"comparisons[{index}] must be a MetricComparison"
                )
        for index, item in enumerate(stability):
            if type(item) is not PairedStabilityResult:
                raise EvidenceBundleError(
                    f"stability[{index}] must be a PairedStabilityResult"
                )
        for index, failure in enumerate(failures):
            if type(failure) is not FailureEvidence:
                raise EvidenceBundleError(
                    f"failures[{index}] must be a FailureEvidence"
                )

        return cls(
            suite=suite.to_dict(),
            partition_id=partition.partition_id,
            partition_fingerprint=partition.fingerprint(),
            candidate_fingerprint=candidate_fingerprint,
            baseline_candidate_fingerprint=suite.baseline_candidate_fingerprint,
            run_provenance=run_provenance.to_dict(),
            observations=[item.to_dict() for item in observations],
            comparisons=[item.to_dict() for item in comparisons],
            gate_policy_fingerprint=suite.gate_policy_fingerprint,
            gate_decision=gate_decision.to_dict(),
            stability=[item.to_dict() for item in stability],
            failures=[item.to_dict() for item in failures],
            generated_at=generated_at,
        )

    def _payload(
        self,
        *,
        include_fingerprint: bool,
        include_artifact_hash: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "baseline_candidate_fingerprint": self.baseline_candidate_fingerprint,
            "candidate_fingerprint": self.candidate_fingerprint,
            "comparisons": [dict(item) for item in self.comparisons],
            "contract_version": self.contract_version,
            "failures": [dict(item) for item in self.failures],
            "gate_decision": dict(self.gate_decision),
            "gate_policy_fingerprint": self.gate_policy_fingerprint,
            "generated_at": self.generated_at,
            "observations": [dict(item) for item in self.observations],
            "partition_fingerprint": self.partition_fingerprint,
            "partition_id": self.partition_id,
            "run_provenance": dict(self.run_provenance),
            "stability": [dict(item) for item in self.stability],
            "suite": dict(self.suite),
        }
        if include_fingerprint:
            payload["evidence_fingerprint"] = self.evidence_fingerprint
        if include_artifact_hash:
            payload["artifact_hash"] = self.artifact_hash
        return payload

    def to_dict(self) -> dict[str, Any]:
        return self._payload(include_fingerprint=True, include_artifact_hash=True)

    def with_artifact_hash(self) -> EvidenceBundle:
        """Return a copy whose ``artifact_hash`` matches the portable bytes."""
        payload = self.to_dict()
        digest = compute_artifact_hash(payload)
        return EvidenceBundle(
            suite=self.suite,
            partition_id=self.partition_id,
            partition_fingerprint=self.partition_fingerprint,
            candidate_fingerprint=self.candidate_fingerprint,
            baseline_candidate_fingerprint=self.baseline_candidate_fingerprint,
            run_provenance=self.run_provenance,
            observations=self.observations,
            comparisons=self.comparisons,
            gate_policy_fingerprint=self.gate_policy_fingerprint,
            gate_decision=self.gate_decision,
            stability=self.stability,
            failures=self.failures,
            generated_at=self.generated_at,
            artifact_hash=digest,
            evidence_fingerprint=self.evidence_fingerprint,
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> EvidenceBundle:
        """Parse a portable mapping; unknown top-level keys are rejected.

        Accepts either live Python payloads (``Decimal`` values) or canonical
        JSON objects that still contain ``$arvp`` decimal extensions.
        """
        if not isinstance(payload, Mapping):
            raise EvidenceBundleError("payload must be a mapping")
        materialised: Mapping[str, Any] = payload
        if _contains_arvp(payload):
            try:
                revived = revive_canonical(dict(payload))
            except CanonicalizationError as exc:
                raise EvidenceBundleError(
                    f"evidence bundle is not canonical: {exc}"
                ) from exc
            if not isinstance(revived, dict):
                raise EvidenceBundleError("evidence bundle must be a mapping")
            materialised = revived
        unknown = sorted(set(materialised) - _TOP_LEVEL_KEYS)
        if unknown:
            raise EvidenceBundleError(
                f"unknown Evidence Bundle fields: {', '.join(unknown)}"
            )
        missing = sorted(_TOP_LEVEL_KEYS - set(materialised))
        if missing:
            raise EvidenceBundleError(
                f"missing Evidence Bundle fields: {', '.join(missing)}"
            )
        return cls(
            suite=materialised["suite"],
            partition_id=materialised["partition_id"],
            partition_fingerprint=materialised["partition_fingerprint"],
            candidate_fingerprint=materialised["candidate_fingerprint"],
            baseline_candidate_fingerprint=materialised[
                "baseline_candidate_fingerprint"
            ],
            run_provenance=materialised["run_provenance"],
            observations=materialised["observations"],
            comparisons=materialised["comparisons"],
            gate_policy_fingerprint=materialised["gate_policy_fingerprint"],
            gate_decision=materialised["gate_decision"],
            stability=materialised["stability"],
            failures=materialised["failures"],
            generated_at=materialised["generated_at"],
            artifact_hash=materialised["artifact_hash"],
            contract_version=materialised["contract_version"],
            evidence_fingerprint=materialised["evidence_fingerprint"],
        )


def _contains_arvp(value: Any) -> bool:
    if isinstance(value, Mapping):
        if "$arvp" in value:
            return True
        return any(_contains_arvp(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_arvp(item) for item in value)
    return False


def write_evidence_bundle(path: str | Path, bundle: EvidenceBundle) -> EvidenceBundle:
    """Atomically write a bundle as canonical JSON.

    Writes a temporary sibling file then replaces the destination so a crash
    cannot leave a partially written canonical evidence file. Returns the
    bundle including a filled ``artifact_hash``.
    """
    destination = Path(path)
    if destination.exists() and destination.is_dir():
        raise EvidenceBundleError("evidence bundle path must be a file path")
    sealed = bundle.with_artifact_hash()
    text = canonical_json_dumps(sealed.to_dict())
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=str(destination.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, destination)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return sealed


def read_evidence_bundle(path: str | Path) -> EvidenceBundle:
    """Load and validate a previously written Evidence Bundle."""
    import json

    text = Path(path).read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise EvidenceBundleError("evidence bundle is not valid JSON") from exc
    try:
        revived = revive_canonical(payload)
    except CanonicalizationError as exc:
        raise EvidenceBundleError(f"evidence bundle is not canonical: {exc}") from exc
    if not isinstance(revived, dict):
        raise EvidenceBundleError("evidence bundle must be a JSON object")
    bundle = EvidenceBundle.from_dict(revived)
    expected = compute_artifact_hash(bundle.to_dict())
    if bundle.artifact_hash != expected:
        raise EvidenceBundleError("artifact_hash does not match bundle bytes payload")
    return bundle
