"""Sample Brain FSLD key/tempo reference adapter (outside ARVP core).

Primary path:

    sanitized FSLD JSON artifact
      -> domain mapping (this module)
      -> portable EvaluationInput (baseline/candidate sides)
      -> ARVP evaluate_evaluation_input
      -> Evidence Bundle v1

No Sample Brain runtime import. No audio fields in ARVP core. Private library
material is rejected at the fixture/adapter boundary.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from arvp.adapters import (
    build_evaluation_input,
    dumps_evaluation_input,
    evaluate_evaluation_input,
)
from arvp.bundle import EvidenceBundle
from arvp.datasets import identify_content
from arvp.evidence import FailureEvidence
from arvp.gates import AbsoluteThresholdCriterion, GatePolicy, RelativeBaselineCriterion
from arvp.identities import CandidateSpec, EvaluationPartition, PartitionRole
from arvp.metrics import MetricContract, MetricDefinition, Observation
from arvp.provenance import RunProvenance
from arvp.stability import StabilityConfig
from arvp.suite import EvaluationSuite

DOCUMENT_TYPE = "sample_brain.fsld_current_analyzer_eval"
SCHEMA_VERSION = "1.0.0"
PUBLIC_AUDIO_NOT_AVAILABLE_LOCALLY = "PUBLIC_AUDIO_NOT_AVAILABLE_LOCALLY"
EVALUATED_RUN_STATUS = "EVALUATED"
GENERATED_AT = "2026-10-06T20:00:00Z"

KEY_ROOT_CORRECT_METRIC_ID = "key.root.correct"
MA_KEY_ROOT_EXACT_RATE_METRIC_ID = "ma.key.root.exact.rate"
BPM_ABS_ERROR_METRIC_ID = "bpm.abs.error"

FIXTURE_ROOT = (
    Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "sample_brain_fsld"
)

CompatibilityStatus = Literal[
    "compatible",
    "blocked_unavailable",
    "manifest_mismatch",
    "split_mismatch",
    "membership_mismatch",
]

_SPLIT_TO_ROLE: dict[str, PartitionRole] = {
    "CALIBRATION": "calibration",
    "TEST": "test",
}


class FsldAdapterError(ValueError):
    """Structured failure when an FSLD artifact cannot be mapped safely."""


def load_json(path: Path | str) -> dict[str, Any]:
    destination = Path(path)
    try:
        payload = json.loads(destination.read_text(encoding="utf-8"))
    except OSError as exc:
        raise FsldAdapterError(f"could not read fixture: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise FsldAdapterError(f"fixture is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise FsldAdapterError("fixture root must be an object")
    return payload


def load_candidate_descriptor(
    key: str, *, candidates_path: Path | None = None
) -> CandidateSpec:
    path = (
        FIXTURE_ROOT / "candidates.json"
        if candidates_path is None
        else Path(candidates_path)
    )
    payload = load_json(path)
    candidates = payload.get("candidates")
    if not isinstance(candidates, Mapping) or key not in candidates:
        raise FsldAdapterError(f"unknown candidate descriptor key: {key!r}")
    raw = candidates[key]
    if not isinstance(raw, Mapping):
        raise FsldAdapterError(f"candidate descriptor {key!r} must be an object")
    try:
        return CandidateSpec(
            str(raw["candidate_id"]),
            str(raw["implementation_id"]),
            str(raw["revision"]),
            dict(raw.get("configuration") or {}),
        )
    except Exception as exc:  # noqa: BLE001 - surface as adapter failure
        raise FsldAdapterError(f"invalid candidate descriptor {key!r}: {exc}") from exc


def validate_fsld_report(report: Mapping[str, Any]) -> dict[str, Any]:
    """Fail closed on malformed FSLD reports before any ARVP mapping."""
    if not isinstance(report, Mapping):
        raise FsldAdapterError("report must be a mapping")
    if report.get("document_type") != DOCUMENT_TYPE:
        raise FsldAdapterError("document_type is not the FSLD current-analyzer eval")
    if report.get("schema_version") != SCHEMA_VERSION:
        raise FsldAdapterError("unsupported FSLD schema_version")
    split = report.get("split")
    if split not in _SPLIT_TO_ROLE:
        raise FsldAdapterError("split must be CALIBRATION or TEST")
    run_status = report.get("run_status")
    if run_status not in {EVALUATED_RUN_STATUS, PUBLIC_AUDIO_NOT_AVAILABLE_LOCALLY}:
        raise FsldAdapterError("run_status is unsupported")
    manifest = report.get("manifest_sha256")
    if type(manifest) is not str or len(manifest) != 64:
        raise FsldAdapterError("manifest_sha256 must be a 64-char hex digest")
    if any(ch not in "0123456789abcdef" for ch in manifest.lower()):
        raise FsldAdapterError("manifest_sha256 must be hexadecimal")
    records = report.get("records")
    if not isinstance(records, list) or not records:
        raise FsldAdapterError("records must be a non-empty list")
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            raise FsldAdapterError(f"records[{index}] must be an object")
        sample_id = record.get("public_sample_id")
        if type(sample_id) is not str or not sample_id.isdecimal():
            raise FsldAdapterError(
                f"records[{index}].public_sample_id must be a decimal string"
            )
        if record.get("split") != split:
            raise FsldAdapterError(f"records[{index}].split must match top-level split")
        if record.get("annotation_tier") not in {"ma", "sa"}:
            raise FsldAdapterError(f"records[{index}].annotation_tier must be ma or sa")
        ground = record.get("ground_truth")
        if not isinstance(ground, Mapping):
            raise FsldAdapterError(f"records[{index}].ground_truth must be an object")
        # Privacy: refuse path-like leakage in portable scalar fields.
        encoded = json.dumps(record, sort_keys=True)
        for needle in ("\\\\", "/Users/", "/home/", "C:\\\\", ".wav", "Traktor"):
            if needle in encoded:
                raise FsldAdapterError(
                    "record contains forbidden path/audio/private material"
                )
    metrics = report.get("metrics")
    if run_status == PUBLIC_AUDIO_NOT_AVAILABLE_LOCALLY:
        if metrics is not None:
            raise FsldAdapterError(
                "PUBLIC_AUDIO_NOT_AVAILABLE_LOCALLY requires metrics=null"
            )
    elif metrics is None:
        raise FsldAdapterError("EVALUATED reports require metrics")
    elif not isinstance(metrics, Mapping):
        raise FsldAdapterError("metrics must be an object when present")
    return dict(report)


def is_blocked_unavailable(report: Mapping[str, Any]) -> bool:
    return (
        report.get("run_status") == PUBLIC_AUDIO_NOT_AVAILABLE_LOCALLY
        or report.get("metrics") is None
    )


def membership_records(report: Mapping[str, Any]) -> list[dict[str, str]]:
    """Safe split membership used to bind ARVP partition content identity."""
    validated = validate_fsld_report(report)
    rows = [
        {
            "public_sample_id": str(record["public_sample_id"]),
            "annotation_tier": str(record["annotation_tier"]),
            "split": str(validated["split"]),
            "manifest_sha256": str(validated["manifest_sha256"]),
        }
        for record in validated["records"]
    ]
    rows.sort(key=lambda item: int(item["public_sample_id"]))
    return rows


def content_identity_from_report(report: Mapping[str, Any]):
    rows = membership_records(report)
    return identify_content(
        rows,
        fields=("public_sample_id", "annotation_tier", "split", "manifest_sha256"),
        ordering="ordered",
    )


def partition_from_report(report: Mapping[str, Any]) -> EvaluationPartition:
    validated = validate_fsld_report(report)
    split = str(validated["split"])
    role = _SPLIT_TO_ROLE[split]
    content = content_identity_from_report(validated)
    return EvaluationPartition(split.lower(), role, content)


def metric_contract() -> MetricContract:
    return MetricContract(
        (
            MetricDefinition(KEY_ROOT_CORRECT_METRIC_ID, "maximize", "1", True),
            MetricDefinition(BPM_ABS_ERROR_METRIC_ID, "minimize", "bpm", True),
            MetricDefinition(MA_KEY_ROOT_EXACT_RATE_METRIC_ID, "maximize", "1", True),
        )
    )


def gate_policy(contract: MetricContract) -> GatePolicy:
    return GatePolicy(
        "sample-brain.fsld.keytempo.release",
        contract,
        (
            AbsoluteThresholdCriterion(
                "ma.key.root.floor",
                MA_KEY_ROOT_EXACT_RATE_METRIC_ID,
                "gte",
                Decimal("0.25"),
            ),
            RelativeBaselineCriterion(
                "ma.key.root.improve",
                MA_KEY_ROOT_EXACT_RATE_METRIC_ID,
                "minimum_improvement",
                Decimal("0.2"),
            ),
        ),
    )


def _key_root_eligible(ground: Mapping[str, Any]) -> bool:
    return ground.get("tonality") == "tonal" and ground.get("root_evidence") == "known"


def _bpm_eligible(ground: Mapping[str, Any]) -> bool:
    bpm = ground.get("bpm")
    return (
        ground.get("bpm_evidence") == "known"
        and isinstance(bpm, (int, float))
        and float(bpm) > 0
    )


def observations_from_report(
    report: Mapping[str, Any],
    *,
    candidate: CandidateSpec,
    partition: EvaluationPartition,
    contract: MetricContract,
) -> tuple[Observation, ...]:
    """Map one evaluated FSLD report into ARVP observations.

    Blocked/unavailable reports must not be passed here; they produce empty
    observations plus FailureEvidence instead of a fabricated 0% baseline.
    """
    validated = validate_fsld_report(report)
    if is_blocked_unavailable(validated):
        raise FsldAdapterError(
            "blocked/unavailable reports must not emit measured observations"
        )
    metrics = validated["metrics"]
    assert isinstance(metrics, Mapping)
    ma = metrics.get("ma")
    if not isinstance(ma, Mapping):
        raise FsldAdapterError("metrics.ma missing")
    key_root = ma.get("key_root")
    if not isinstance(key_root, Mapping) or "exact_rate" not in key_root:
        raise FsldAdapterError("metrics.ma.key_root.exact_rate missing")
    exact_rate = key_root["exact_rate"]
    if exact_rate is None:
        raise FsldAdapterError("ma.key_root.exact_rate is null")
    if not isinstance(exact_rate, (int, float)) or isinstance(exact_rate, bool):
        raise FsldAdapterError("ma.key_root.exact_rate must be numeric")

    observations: list[Observation] = []
    for record in sorted(
        validated["records"], key=lambda item: int(str(item["public_sample_id"]))
    ):
        if record.get("status") != "ok":
            continue
        sample_id = str(record["public_sample_id"])
        ground = record["ground_truth"]
        assert isinstance(ground, Mapping)
        if _key_root_eligible(ground):
            predicted = record.get("predicted_key_root")
            correct = (
                1
                if type(predicted) is str and predicted == ground.get("key_root")
                else 0
            )
            observations.append(
                Observation(
                    observation_id=f"{sample_id}.key.root.correct",
                    candidate=candidate,
                    partition=partition,
                    metric_contract=contract,
                    metric=contract.value(
                        KEY_ROOT_CORRECT_METRIC_ID,
                        "measured",
                        Decimal(correct),
                    ),
                )
            )
        if _bpm_eligible(ground):
            predicted_bpm = record.get("predicted_bpm")
            label_bpm = float(ground["bpm"])  # type: ignore[arg-type]
            if (
                isinstance(predicted_bpm, (int, float))
                and not isinstance(predicted_bpm, bool)
                and float(predicted_bpm) > 0
            ):
                abs_error = abs(float(predicted_bpm) - label_bpm)
                observations.append(
                    Observation(
                        observation_id=f"{sample_id}.bpm.abs.error",
                        candidate=candidate,
                        partition=partition,
                        metric_contract=contract,
                        metric=contract.value(
                            BPM_ABS_ERROR_METRIC_ID,
                            "measured",
                            Decimal(str(abs_error)),
                        ),
                    )
                )

    observations.append(
        Observation(
            observation_id="aggregate.ma.key.root.exact.rate",
            candidate=candidate,
            partition=partition,
            metric_contract=contract,
            metric=contract.value(
                MA_KEY_ROOT_EXACT_RATE_METRIC_ID,
                "measured",
                Decimal(str(exact_rate)),
            ),
        )
    )
    return tuple(observations)


def compatibility_status(
    baseline_report: Mapping[str, Any],
    candidate_report: Mapping[str, Any],
) -> CompatibilityStatus:
    baseline = validate_fsld_report(baseline_report)
    candidate = validate_fsld_report(candidate_report)
    if is_blocked_unavailable(baseline) or is_blocked_unavailable(candidate):
        return "blocked_unavailable"
    if baseline["manifest_sha256"] != candidate["manifest_sha256"]:
        return "manifest_mismatch"
    if baseline["split"] != candidate["split"]:
        return "split_mismatch"
    baseline_ids = [
        (row["public_sample_id"], row["annotation_tier"])
        for row in membership_records(baseline)
    ]
    candidate_ids = [
        (row["public_sample_id"], row["annotation_tier"])
        for row in membership_records(candidate)
    ]
    if baseline_ids != candidate_ids:
        return "membership_mismatch"
    return "compatible"


def build_suite(
    report: Mapping[str, Any],
    *,
    baseline: CandidateSpec,
    contract: MetricContract,
    policy: GatePolicy,
) -> EvaluationSuite:
    partition = partition_from_report(report)
    content = partition.content_identity
    return EvaluationSuite(
        "sample-brain.fsld.keytempo.v1",
        content,
        (partition,),
        contract,
        policy,
        baseline,
    )


def _failure_for_status(status: CompatibilityStatus) -> FailureEvidence:
    if status == "blocked_unavailable":
        return FailureEvidence.input_unavailable(
            stage="fsld.adapter",
            metadata={"reason": PUBLIC_AUDIO_NOT_AVAILABLE_LOCALLY},
        )
    if status in {"manifest_mismatch", "split_mismatch", "membership_mismatch"}:
        return FailureEvidence.insufficient_evidence(
            stage="fsld.adapter",
            metadata={"reason": status},
        )
    return FailureEvidence.insufficient_evidence(
        stage="fsld.adapter",
        metadata={"reason": "unknown"},
    )


def build_run(
    *,
    baseline_key: str = "baseline",
    candidate_key: str = "improved",
    baseline_report_name: str = "baseline_evaluated.json",
    candidate_report_name: str = "candidate_improved.json",
    fixture_root: Path | None = None,
    include_candidate_observations: bool = True,
) -> tuple[EvidenceBundle, str, CompatibilityStatus]:
    """Map fixtures into EvaluationInput, evaluate, return bundle + status."""
    root = FIXTURE_ROOT if fixture_root is None else Path(fixture_root)
    baseline_report = validate_fsld_report(load_json(root / baseline_report_name))
    candidate_report = validate_fsld_report(load_json(root / candidate_report_name))
    baseline = load_candidate_descriptor(
        baseline_key, candidates_path=root / "candidates.json"
    )
    candidate = load_candidate_descriptor(
        candidate_key, candidates_path=root / "candidates.json"
    )

    status = compatibility_status(baseline_report, candidate_report)
    contract = metric_contract()
    policy = gate_policy(contract)

    # Suite/partition always bind to the baseline artifact membership when the
    # baseline itself is evaluable; otherwise bind to the candidate membership
    # solely to keep Evidence Bundle construction possible under HOLD.
    suite_report = (
        baseline_report
        if not is_blocked_unavailable(baseline_report)
        else candidate_report
    )
    if is_blocked_unavailable(suite_report):
        # Both sides blocked: still need a partition identity from membership.
        suite_report = baseline_report

    suite = build_suite(
        suite_report, baseline=baseline, contract=contract, policy=policy
    )
    partition = suite.partition(suite.partitions[0].partition_id)

    failures: list[FailureEvidence] = []
    baseline_obs: tuple[Observation, ...] = ()
    candidate_obs: tuple[Observation, ...] = ()

    if status == "compatible" and include_candidate_observations:
        baseline_obs = observations_from_report(
            baseline_report,
            candidate=baseline,
            partition=partition,
            contract=contract,
        )
        candidate_obs = observations_from_report(
            candidate_report,
            candidate=candidate,
            partition=partition,
            contract=contract,
        )
    else:
        failures.append(_failure_for_status(status))
        # Compatible but caller omitted candidate evidence still HOLDs.
        if status == "compatible" and not include_candidate_observations:
            baseline_obs = observations_from_report(
                baseline_report,
                candidate=baseline,
                partition=partition,
                contract=contract,
            )
            failures[:] = [
                FailureEvidence.insufficient_evidence(
                    stage="fsld.adapter",
                    metadata={"reason": "missing_candidate_observations"},
                )
            ]
        elif status == "blocked_unavailable":
            # Never emit measured 0% from unavailable evidence. Keep measured
            # baseline only when the baseline itself is evaluated and identity
            # would match except for availability.
            if (
                not is_blocked_unavailable(baseline_report)
                and baseline_report["manifest_sha256"]
                == candidate_report["manifest_sha256"]
                and baseline_report["split"] == candidate_report["split"]
                and [
                    (row["public_sample_id"], row["annotation_tier"])
                    for row in membership_records(baseline_report)
                ]
                == [
                    (row["public_sample_id"], row["annotation_tier"])
                    for row in membership_records(candidate_report)
                ]
            ):
                baseline_obs = observations_from_report(
                    baseline_report,
                    candidate=baseline,
                    partition=partition,
                    contract=contract,
                )
            # candidate_obs stays empty -> HOLD
        else:
            # Manifest/split/membership mismatch: fail closed with HOLD.
            # Keep measured baseline identity context when available, but never
            # attach candidate observations across incompatible artifacts.
            failures[:] = [_failure_for_status(status)]
            if not is_blocked_unavailable(baseline_report):
                baseline_obs = observations_from_report(
                    baseline_report,
                    candidate=baseline,
                    partition=partition,
                    contract=contract,
                )
            candidate_obs = ()

    provenance = RunProvenance.bind(
        candidate_fingerprint=candidate.fingerprint(),
        suite=suite,
        partition_id=partition.partition_id,
        code_revision=str(candidate.revision),
        configuration={
            "domain": "sample_brain_fsld_key_tempo",
            "baseline_report": baseline_report_name,
            "candidate_report": candidate_report_name,
            "compatibility": status,
            "manifest_sha256": str(suite_report["manifest_sha256"]),
            "split": str(suite_report["split"]),
        },
        arvp_version="0.1.0-test",
    )
    # Paired stability requires at least one observation side; HOLD paths that
    # intentionally omit both sides skip stability rather than inventing pairs.
    stability: StabilityConfig | None = None
    if baseline_obs or candidate_obs:
        stability = StabilityConfig(
            aggregation="mean",
            sample_count=16,
            blocks_per_sample=1,
            seed=14,
        )
    evaluation_input = build_evaluation_input(
        suite=suite,
        metric_contract=contract,
        gate_policy=policy,
        baseline_candidate=baseline,
        candidate_fingerprint=candidate.fingerprint(),
        partition_id=partition.partition_id,
        run_provenance=provenance,
        baseline_observations=baseline_obs,
        candidate_observations=candidate_obs,
        failures=failures,
        stability_config=stability,
        configuration={"proof": "issue-14", "compatibility": status},
    )
    serialized = dumps_evaluation_input(evaluation_input)
    bundle = evaluate_evaluation_input(
        json.loads(serialized), generated_at=GENERATED_AT
    )
    return bundle, serialized, status


def ma_key_root_exact_rate_from_bundle(bundle: EvidenceBundle) -> Decimal | None:
    candidate_fp = bundle.candidate_fingerprint
    for observation in bundle.observations:
        if observation.get("candidate_fingerprint") != candidate_fp:
            continue
        metric = observation.get("metric", {})
        if metric.get("metric_id") != MA_KEY_ROOT_EXACT_RATE_METRIC_ID:
            continue
        if metric.get("status") != "measured":
            continue
        value = metric.get("value")
        if value is None:
            return None
        return Decimal(str(value))
    return None


def assert_no_private_leakage(payload: Mapping[str, Any] | Sequence[Any] | str) -> None:
    """Privacy scan used by tests against fixtures and Evidence Bundles."""
    if isinstance(payload, str):
        text = payload
    else:
        text = json.dumps(payload, sort_keys=True)
    lowered = text.casefold()
    forbidden = (
        "d:\\",
        "c:\\",
        "/users/",
        "/home/",
        ".wav",
        "traktor",
        "private_sample",
        "audio-root",
        "audio_root",
    )
    for needle in forbidden:
        if needle in lowered:
            raise AssertionError(f"forbidden material present: {needle}")
