"""Deterministic run provenance and an append-only JSONL registry."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
import json
from pathlib import Path
import re
from typing import Any

from arvp.canonical import canonical_hash, canonical_json_dumps
from arvp.datasets import assert_evidence_safe


_FINGERPRINT_RE = re.compile(r"^[a-f0-9]{64}$")
_RUN_ID_RE = re.compile(r"^run-[a-f0-9]{12}-\d{4}$")
_VALID_STATUSES = frozenset({"running", "completed", "failed"})


class ProvenanceError(ValueError):
    """Raised when portable provenance or a registry record is invalid."""


def _require_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProvenanceError(f"{field} must be a non-empty string")
    return value.strip()


def _require_fingerprint(value: object, field: str) -> str:
    if not isinstance(value, str) or not _FINGERPRINT_RE.fullmatch(value):
        raise ProvenanceError(
            f"{field} must be a 64-character lowercase SHA-256 hash"
        )
    return value


def _parse_utc(value: object, field: str) -> str:
    text = _require_text(value, field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProvenanceError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ProvenanceError(f"{field} must carry an explicit UTC offset")
    return text


@dataclass(frozen=True, slots=True)
class RunProvenance:
    """Inputs that determine a reproducible run independently of its attempt."""

    candidate_id: str
    dataset_fingerprint: str
    code_revision: str
    configuration: Mapping[str, Any]
    contract_version: str = "arvp.run-provenance.v1"

    def __post_init__(self) -> None:
        _require_text(self.candidate_id, "candidate_id")
        _require_fingerprint(self.dataset_fingerprint, "dataset_fingerprint")
        _require_text(self.code_revision, "code_revision")
        _require_text(self.contract_version, "contract_version")
        if not isinstance(self.configuration, Mapping):
            raise ProvenanceError("configuration must be a mapping")
        copied = dict(self.configuration)
        try:
            assert_evidence_safe(copied)
        except ValueError as exc:
            raise ProvenanceError(str(exc)) from exc
        object.__setattr__(self, "configuration", copied)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "code_revision": self.code_revision,
            "configuration": dict(self.configuration),
            "contract_version": self.contract_version,
            "dataset_fingerprint": self.dataset_fingerprint,
        }

    def fingerprint(self) -> str:
        return canonical_hash(self.to_dict())

    def run_id(self, attempt: int) -> str:
        if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
            raise ProvenanceError("attempt must be a positive integer")
        return f"run-{self.fingerprint()[:12]}-{attempt:04d}"


@dataclass(frozen=True, slots=True)
class RunRecord:
    """One lifecycle observation in the JSONL registry."""

    run_id: str
    provenance_fingerprint: str
    status: str
    started_at_utc: str
    finished_at_utc: str | None = None
    failure_reason: str | None = None
    result: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, str) or not _RUN_ID_RE.fullmatch(self.run_id):
            raise ProvenanceError(
                "run_id must match run-<12 hex>-<4 digit attempt>"
            )
        _require_fingerprint(self.provenance_fingerprint, "provenance_fingerprint")
        if self.status not in _VALID_STATUSES:
            raise ProvenanceError(f"status must be one of {sorted(_VALID_STATUSES)}")
        started = _parse_utc(self.started_at_utc, "started_at_utc")
        finished: str | None = None
        if self.finished_at_utc is not None:
            finished = _parse_utc(self.finished_at_utc, "finished_at_utc")
            if datetime.fromisoformat(finished.replace("Z", "+00:00")) < datetime.fromisoformat(started.replace("Z", "+00:00")):
                raise ProvenanceError("finished_at_utc must be >= started_at_utc")
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
            _require_text(self.failure_reason, "failure_reason")
        if self.result is not None:
            if not isinstance(self.result, Mapping):
                raise ProvenanceError("result must be a mapping")
            copied = dict(self.result)
            try:
                assert_evidence_safe(copied)
            except ValueError as exc:
                raise ProvenanceError(str(exc)) from exc
            object.__setattr__(self, "result", copied)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "provenance_fingerprint": self.provenance_fingerprint,
            "run_id": self.run_id,
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
    def from_dict(cls, payload: Mapping[str, Any]) -> "RunRecord":
        expected = {
            "run_id",
            "provenance_fingerprint",
            "status",
            "started_at_utc",
            "finished_at_utc",
            "failure_reason",
            "result",
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
            )
        except KeyError as exc:
            raise ProvenanceError(
                f"missing required run record field: {exc.args[0]}"
            ) from exc


class JsonlRunRegistry:
    """Small, append-only local registry with strict read validation."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def append(self, record: RunRecord) -> None:
        if not isinstance(record, RunRecord):
            raise ProvenanceError("record must be a RunRecord")
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
                records.append(RunRecord.from_dict(payload))
            except ProvenanceError as exc:
                raise ProvenanceError(
                    f"invalid registry line {number}: {exc}"
                ) from exc
        return records

    def next_attempt(self, provenance: RunProvenance) -> int:
        if not isinstance(provenance, RunProvenance):
            raise ProvenanceError("provenance must be a RunProvenance")
        prefix = f"run-{provenance.fingerprint()[:12]}-"
        attempts = [
            int(record.run_id.rsplit("-", 1)[1])
            for record in self.load_all()
            if record.run_id.startswith(prefix)
        ]
        return max(attempts, default=0) + 1
