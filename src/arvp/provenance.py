"""RunProvenance v2 and an append-only, single-writer JSONL registry.

The JSONL registry is a local convenience/history index, not the canonical
portable evidence artifact (see Evidence Bundle v1 / Issue #11).

v0.2 is explicitly **single-writer**: concurrent writers are unsupported.
Callers must serialize appends to one registry path. The implementation fails
closed on malformed/corrupted lines and invalid lifecycle transitions; it does
not add a cross-platform lock dependency.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Literal

from arvp.canonical import (
    CanonicalizationError,
    FingerprintFormatError,
    canonical_hash,
    canonical_json_dumps,
    validate_fingerprint,
)
from arvp.evidence import (
    PortableEvidenceError,
    validate_portable_metadata,
)
from arvp.suite import EvaluationSuite

RUN_PROVENANCE_CONTRACT_VERSION = "arvp.run-provenance.v2"
RUN_RECORD_SCHEMA_VERSION = "arvp.run-record.v2"
MAX_ATTEMPT = 9999
_RUN_ID_RE = re.compile(r"^run-[a-f0-9]{12}-\d{4}$")
RunStatus = Literal["running", "completed", "failed"]
_VALID_STATUSES = frozenset({"running", "completed", "failed"})
_TERMINAL_STATUSES = frozenset({"completed", "failed"})


class ProvenanceError(ValueError):
    """Raised when portable provenance or a registry record is invalid."""


def default_arvp_version() -> str:
    """Installed package version, or an explicit unknown marker."""
    try:
        return version("arvp")
    except PackageNotFoundError:
        return "0.0.0+unknown"


def _require_text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise ProvenanceError(f"{field} must be a non-empty string")
    return value.strip()


def _require_fingerprint(value: object, field: str) -> str:
    try:
        return validate_fingerprint(value, field)
    except FingerprintFormatError as exc:
        raise ProvenanceError(str(exc)) from exc


def canonicalize_utc(value: object, field: str) -> str:
    """Parse an aware UTC timestamp and return canonical ``...Z`` form."""
    text = _require_text(value, field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProvenanceError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ProvenanceError(f"{field} must carry an explicit UTC offset")
    utc = parsed.astimezone(timezone.utc)
    if utc.microsecond:
        return utc.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
    return utc.strftime("%Y-%m-%dT%H:%M:%S") + "Z"


def _assert_evidence_safe(value: Any) -> None:
    try:
        validate_portable_metadata(value)
    except PortableEvidenceError as exc:
        raise ProvenanceError(str(exc)) from exc


def _require_attempt(attempt: object) -> int:
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise ProvenanceError("attempt must be a positive integer")
    if attempt > MAX_ATTEMPT:
        raise ProvenanceError(f"attempt must be <= {MAX_ATTEMPT}")
    return attempt


@dataclass(frozen=True, slots=True)
class RunProvenance:
    """Inputs that determine a reproducible run independently of its attempt.

    Attempt identity is carried only by ``run_id(attempt)`` / registry records,
    never by the provenance fingerprint itself.
    """

    candidate_fingerprint: str
    suite_fingerprint: str
    partition_id: str
    partition_fingerprint: str
    code_revision: str
    configuration: Mapping[str, Any]
    arvp_version: str
    contract_version: str = RUN_PROVENANCE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_fingerprint",
            _require_fingerprint(self.candidate_fingerprint, "candidate_fingerprint"),
        )
        object.__setattr__(
            self,
            "suite_fingerprint",
            _require_fingerprint(self.suite_fingerprint, "suite_fingerprint"),
        )
        object.__setattr__(
            self, "partition_id", _require_text(self.partition_id, "partition_id")
        )
        object.__setattr__(
            self,
            "partition_fingerprint",
            _require_fingerprint(self.partition_fingerprint, "partition_fingerprint"),
        )
        object.__setattr__(
            self, "code_revision", _require_text(self.code_revision, "code_revision")
        )
        object.__setattr__(
            self, "arvp_version", _require_text(self.arvp_version, "arvp_version")
        )
        if self.contract_version != RUN_PROVENANCE_CONTRACT_VERSION:
            raise ProvenanceError(
                f"contract_version must be {RUN_PROVENANCE_CONTRACT_VERSION!r}"
            )
        if not isinstance(self.configuration, Mapping):
            raise ProvenanceError("configuration must be a mapping")
        copied = dict(self.configuration)
        _assert_evidence_safe(copied)
        try:
            canonical_json_dumps(copied)
        except CanonicalizationError as exc:
            raise ProvenanceError(f"configuration not canonicalizable: {exc}") from exc
        object.__setattr__(self, "configuration", copied)

    @classmethod
    def bind(
        cls,
        *,
        candidate_fingerprint: str,
        suite: EvaluationSuite,
        partition_id: str,
        code_revision: str,
        configuration: Mapping[str, Any] | None = None,
        arvp_version: str | None = None,
    ) -> RunProvenance:
        """Bind a suite partition plus candidate/code identity into provenance v2."""
        if type(suite) is not EvaluationSuite:
            raise ProvenanceError("suite must be an EvaluationSuite")
        partition = suite.partition(partition_id)
        return cls(
            candidate_fingerprint=candidate_fingerprint,
            suite_fingerprint=suite.fingerprint(),
            partition_id=partition.partition_id,
            partition_fingerprint=partition.fingerprint(),
            code_revision=code_revision,
            configuration={} if configuration is None else configuration,
            arvp_version=default_arvp_version()
            if arvp_version is None
            else arvp_version,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "arvp_version": self.arvp_version,
            "candidate_fingerprint": self.candidate_fingerprint,
            "code_revision": self.code_revision,
            "configuration": dict(self.configuration),
            "contract_version": self.contract_version,
            "partition_fingerprint": self.partition_fingerprint,
            "partition_id": self.partition_id,
            "suite_fingerprint": self.suite_fingerprint,
        }

    def fingerprint(self) -> str:
        return canonical_hash(self.to_dict())

    def run_id(self, attempt: int) -> str:
        """Display/run identity: ``run-<12 hex of provenance fp>-<4 digit attempt>``.

        Semantic attempt lookup must use the full provenance fingerprint; the
        12-hex prefix is a display aid only (max attempt ``MAX_ATTEMPT``).
        """
        attempt = _require_attempt(attempt)
        return f"run-{self.fingerprint()[:12]}-{attempt:04d}"


@dataclass(frozen=True, slots=True)
class RunRecord:
    """One lifecycle observation in the JSONL registry.

    Note: RunRecord is local operational state, not portable evidence.
    failure_reason remains a free-form string for local diagnostics.
    """

    run_id: str
    provenance_fingerprint: str
    status: RunStatus
    started_at_utc: str
    finished_at_utc: str | None = None
    failure_reason: str | None = None
    result: Mapping[str, Any] | None = None
    schema_version: str = RUN_RECORD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, str) or not _RUN_ID_RE.fullmatch(self.run_id):
            raise ProvenanceError(
                "run_id must match run-<12 hex>-<4 digit attempt> "
                f"(attempt 0001..{MAX_ATTEMPT:04d})"
            )
        object.__setattr__(
            self,
            "provenance_fingerprint",
            _require_fingerprint(self.provenance_fingerprint, "provenance_fingerprint"),
        )
        prefix, attempt_text = self.run_id.removeprefix("run-").rsplit("-", 1)
        if prefix != self.provenance_fingerprint[:12]:
            raise ProvenanceError(
                "run_id prefix must match provenance_fingerprint[:12]"
            )
        _require_attempt(int(attempt_text))
        if self.schema_version != RUN_RECORD_SCHEMA_VERSION:
            raise ProvenanceError(
                f"schema_version must be {RUN_RECORD_SCHEMA_VERSION!r}"
            )
        if self.status not in _VALID_STATUSES:
            raise ProvenanceError(f"status must be one of {sorted(_VALID_STATUSES)}")
        started = canonicalize_utc(self.started_at_utc, "started_at_utc")
        object.__setattr__(self, "started_at_utc", started)
        finished: str | None = None
        if self.finished_at_utc is not None:
            finished = canonicalize_utc(self.finished_at_utc, "finished_at_utc")
            if datetime.fromisoformat(
                finished.replace("Z", "+00:00")
            ) < datetime.fromisoformat(started.replace("Z", "+00:00")):
                raise ProvenanceError("finished_at_utc must be >= started_at_utc")
            object.__setattr__(self, "finished_at_utc", finished)
        if self.status == "running" and (
            finished is not None or self.failure_reason is not None
        ):
            raise ProvenanceError("running records cannot have completion data")
        if self.status == "completed" and (
            finished is None or self.failure_reason is not None
        ):
            raise ProvenanceError(
                "completed records require finished_at_utc and no failure_reason"
            )
        if self.status == "failed" and (
            finished is None or self.failure_reason is None
        ):
            raise ProvenanceError(
                "failed records require finished_at_utc and failure_reason"
            )
        if self.failure_reason is not None:
            object.__setattr__(
                self,
                "failure_reason",
                _require_text(self.failure_reason, "failure_reason"),
            )
        if self.result is not None:
            if not isinstance(self.result, Mapping):
                raise ProvenanceError("result must be a mapping")
            copied = dict(self.result)
            _assert_evidence_safe(copied)
            try:
                canonical_json_dumps(copied)
            except CanonicalizationError as exc:
                raise ProvenanceError(f"result not canonicalizable: {exc}") from exc
            object.__setattr__(self, "result", copied)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "provenance_fingerprint": self.provenance_fingerprint,
            "run_id": self.run_id,
            "schema_version": self.schema_version,
            "started_at_utc": self.started_at_utc,
            "status": self.status,
        }
        if self.finished_at_utc is not None:
            payload["finished_at_utc"] = self.finished_at_utc
        if self.failure_reason is not None:
            payload["failure_reason"] = self.failure_reason
        if self.result is not None:
            payload["result"] = dict(self.result)
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> RunRecord:
        expected = {
            "run_id",
            "provenance_fingerprint",
            "status",
            "started_at_utc",
            "finished_at_utc",
            "failure_reason",
            "result",
            "schema_version",
        }
        unknown = set(payload).difference(expected)
        if unknown:
            raise ProvenanceError(
                "unknown run record field(s): " + ", ".join(sorted(unknown))
            )
        try:
            return cls(
                run_id=payload["run_id"],
                provenance_fingerprint=payload["provenance_fingerprint"],
                status=payload["status"],
                started_at_utc=payload["started_at_utc"],
                finished_at_utc=payload.get("finished_at_utc"),
                failure_reason=payload.get("failure_reason"),
                result=payload.get("result"),
                schema_version=payload["schema_version"],
            )
        except KeyError as exc:
            raise ProvenanceError(
                f"missing required run record field: {exc.args[0]}"
            ) from exc


def _attempt_from_run_id(run_id: str) -> int:
    return int(run_id.rsplit("-", 1)[1])


def _validate_lifecycle_append(
    existing: Sequence[RunRecord], incoming: RunRecord
) -> None:
    """Enforce allowed transitions for one run_id under single-writer append."""
    same = [record for record in existing if record.run_id == incoming.run_id]
    if not same:
        if incoming.status != "running":
            raise ProvenanceError("first record for a run_id must have status running")
        return

    for record in same:
        if record.provenance_fingerprint != incoming.provenance_fingerprint:
            raise ProvenanceError(
                "run_id already bound to a different provenance fingerprint"
            )

    last = same[-1]
    if last.status in _TERMINAL_STATUSES:
        raise ProvenanceError(
            f"run_id {incoming.run_id} already terminal ({last.status})"
        )
    if last.status == "running":
        if incoming.status == "running":
            raise ProvenanceError("duplicate running record for run_id")
        if incoming.status not in _TERMINAL_STATUSES:
            raise ProvenanceError(
                "running records may only transition to completed or failed"
            )
        return
    raise ProvenanceError(f"illegal lifecycle state: {last.status}")


class JsonlRunRegistry:
    """Append-only local registry with strict read and lifecycle validation.

    Single-writer only. Concurrent appends to the same path are unsupported.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def append(self, record: RunRecord) -> None:
        if not isinstance(record, RunRecord):
            raise ProvenanceError("record must be a RunRecord")
        existing = self.load_all()
        _validate_lifecycle_append(existing, record)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(canonical_json_dumps(record.to_dict()) + "\n")
        except OSError as exc:
            raise ProvenanceError(f"could not append registry record: {exc}") from exc

    def load_all(self) -> list[RunRecord]:
        if not self.path.exists():
            return []
        records: list[RunRecord] = []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise ProvenanceError(f"could not read registry: {exc}") from exc
        for number, line in enumerate(lines, start=1):
            if not line.strip():
                raise ProvenanceError(f"blank registry line at {number}")
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ProvenanceError(
                    f"malformed JSON at registry line {number}"
                ) from exc
            if not isinstance(payload, Mapping):
                raise ProvenanceError(f"registry line {number} must be an object")
            try:
                record = RunRecord.from_dict(payload)
                _validate_lifecycle_append(records, record)
                records.append(record)
            except ProvenanceError as exc:
                raise ProvenanceError(f"invalid registry line {number}: {exc}") from exc
        return records

    def next_attempt(self, provenance: RunProvenance) -> int:
        """Next attempt for this full provenance fingerprint (not the 12-hex prefix)."""
        if not isinstance(provenance, RunProvenance):
            raise ProvenanceError("provenance must be a RunProvenance")
        fingerprint = provenance.fingerprint()
        attempts = [
            _attempt_from_run_id(record.run_id)
            for record in self.load_all()
            if record.provenance_fingerprint == fingerprint
        ]
        nxt = max(attempts, default=0) + 1
        if nxt > MAX_ATTEMPT:
            raise ProvenanceError(f"attempt must be <= {MAX_ATTEMPT}")
        return nxt
