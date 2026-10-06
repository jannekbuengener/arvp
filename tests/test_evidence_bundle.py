from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from arvp.bundle import (
    EVIDENCE_BUNDLE_CONTRACT_VERSION,
    EvidenceBundle,
    EvidenceBundleError,
    compute_evidence_fingerprint,
    read_evidence_bundle,
    write_evidence_bundle,
)
from arvp.canonical import canonical_json_dumps
from arvp.datasets import identify_content
from arvp.evidence import FailureEvidence
from arvp.gates import (
    AbsoluteThresholdCriterion,
    GatePolicy,
    compare_observation_scope,
    evaluate_gate,
)
from arvp.identities import CandidateSpec, EvaluationPartition
from arvp.metrics import MetricContract, MetricDefinition, Observation
from arvp.provenance import RunProvenance
from arvp.schemas import SCHEMA_ASSET_NAMES, load_schema
from arvp.suite import EvaluationSuite


def _metric_contract() -> MetricContract:
    return MetricContract((MetricDefinition("quality.score", "maximize", "1", True),))


def _partition() -> EvaluationPartition:
    content = identify_content([{"id": "a"}], fields=("id",), ordering="ordered")
    return EvaluationPartition("validation", "validation", content)


def _candidate(candidate_id: str = "cand") -> CandidateSpec:
    return CandidateSpec(candidate_id, "impl.eval", "r1", {"depth": 2})


def _suite() -> tuple[EvaluationSuite, GatePolicy, MetricContract]:
    contract = _metric_contract()
    policy = GatePolicy(
        "release.default",
        contract,
        (
            AbsoluteThresholdCriterion(
                "quality.floor", "quality.score", "gte", Decimal("0.5")
            ),
        ),
    )
    content = identify_content([{"id": "root"}], fields=("id",), ordering="ordered")
    suite = EvaluationSuite(
        "release.default",
        content,
        (_partition(),),
        contract,
        policy,
        _candidate("baseline"),
    )
    return suite, policy, contract


def _observation(
    *,
    candidate: CandidateSpec,
    partition: EvaluationPartition,
    contract: MetricContract,
    value: Decimal,
    observation_id: str = "obs-1",
) -> Observation:
    return Observation(
        observation_id=observation_id,
        candidate=candidate,
        partition=partition,
        metric_contract=contract,
        metric=contract.value("quality.score", "measured", value),
    )


def _bundle(
    *,
    generated_at: str = "2026-10-06T12:00:00Z",
    candidate_id: str = "cand",
    value: Decimal = Decimal("0.9"),
) -> EvidenceBundle:
    suite, policy, contract = _suite()
    baseline = _candidate("baseline")
    candidate = _candidate(candidate_id)
    partition = suite.partition("validation")
    baseline_obs = _observation(
        candidate=baseline,
        partition=partition,
        contract=contract,
        value=Decimal("0.8"),
    )
    candidate_obs = _observation(
        candidate=candidate,
        partition=partition,
        contract=contract,
        value=value,
    )
    comparisons = compare_observation_scope(
        baseline=(baseline_obs,),
        candidate=(candidate_obs,),
        metric_contract=contract,
    )
    decision = evaluate_gate(
        policy=policy,
        comparisons=comparisons,
        metric_contract=contract,
    )
    provenance = RunProvenance.bind(
        candidate_fingerprint=candidate.fingerprint(),
        suite=suite,
        partition_id="validation",
        code_revision="deadbeef",
        configuration={"seed": 7},
        arvp_version="0.1.0-test",
    )
    return EvidenceBundle.build(
        suite=suite,
        partition_id="validation",
        candidate_fingerprint=candidate.fingerprint(),
        run_provenance=provenance,
        gate_decision=decision,
        observations=(candidate_obs,),
        comparisons=comparisons,
        failures=(),
        generated_at=generated_at,
    )


def test_bundle_contract_version() -> None:
    assert EVIDENCE_BUNDLE_CONTRACT_VERSION == "arvp.evidence.v1"
    assert _bundle().contract_version == EVIDENCE_BUNDLE_CONTRACT_VERSION


def test_round_trip_write_read(tmp_path: Path) -> None:
    bundle = _bundle()
    path = tmp_path / "evidence.json"
    sealed = write_evidence_bundle(path, bundle)
    loaded = read_evidence_bundle(path)
    assert loaded.evidence_fingerprint == sealed.evidence_fingerprint
    assert loaded.artifact_hash == sealed.artifact_hash
    assert canonical_json_dumps(loaded.to_dict()) == canonical_json_dumps(
        sealed.to_dict()
    )


def test_fingerprint_stable_when_only_generated_at_changes() -> None:
    left = _bundle(generated_at="2026-10-06T12:00:00Z")
    right = _bundle(generated_at="2026-10-06T18:30:00.123456Z")
    assert left.evidence_fingerprint == right.evidence_fingerprint
    assert left.generated_at != right.generated_at


def test_fingerprint_changes_with_candidate_metric_or_gate_semantics() -> None:
    base = _bundle(candidate_id="cand-a", value=Decimal("0.9"))
    other_candidate = _bundle(candidate_id="cand-b", value=Decimal("0.9"))
    other_metric = _bundle(candidate_id="cand-a", value=Decimal("0.1"))
    assert base.evidence_fingerprint != other_candidate.evidence_fingerprint
    assert base.evidence_fingerprint != other_metric.evidence_fingerprint


def test_fingerprint_field_excluded_from_hash_input() -> None:
    bundle = _bundle()
    payload = bundle.to_dict()
    assert "evidence_fingerprint" in payload
    recomputed = compute_evidence_fingerprint(payload)
    assert recomputed == bundle.evidence_fingerprint
    mutated = dict(payload)
    mutated["evidence_fingerprint"] = "0" * 64
    assert compute_evidence_fingerprint(mutated) == bundle.evidence_fingerprint


def test_unknown_top_level_fields_rejected() -> None:
    payload = _bundle().to_dict()
    payload["extra_field"] = "nope"
    with pytest.raises(EvidenceBundleError, match="unknown Evidence Bundle fields"):
        EvidenceBundle.from_dict(payload)


def test_unsafe_failure_metadata_rejected() -> None:
    with pytest.raises(Exception, match="forbidden key"):
        FailureEvidence.invalid_input(metadata={"path": "/secret"})


def test_atomic_writer_leaves_no_partial_file_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = _bundle()
    path = tmp_path / "evidence.json"

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr("arvp.bundle.os.replace", boom)
    with pytest.raises(OSError, match="simulated replace failure"):
        write_evidence_bundle(path, bundle)
    assert not path.exists()
    leftovers = list(tmp_path.glob(".evidence.json.*.tmp"))
    assert leftovers == []


def test_golden_fixture_round_trip() -> None:
    fixture_path = (
        Path(__file__).resolve().parent / "fixtures" / "evidence_bundle_v1_golden.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    loaded = EvidenceBundle.from_dict(fixture["bundle"])
    assert loaded.evidence_fingerprint == fixture["bundle"]["evidence_fingerprint"]
    assert loaded.artifact_hash == fixture["bundle"]["artifact_hash"]


def test_schema_assets_validate_with_jsonschema(tmp_path: Path) -> None:
    try:
        import jsonschema
    except ImportError:
        pytest.skip("jsonschema unavailable on this host")

    Draft202012Validator = jsonschema.Draft202012Validator

    assert SCHEMA_ASSET_NAMES == (
        "evidence_bundle_v1.json",
        "evaluation_input_v1.json",
        "evaluation_suite_v1.json",
        "metric_observation_v1.json",
    )
    bundle = write_evidence_bundle(tmp_path / "live.json", _bundle())
    portable = json.loads(canonical_json_dumps(bundle.to_dict()))
    Draft202012Validator(load_schema("evidence_bundle_v1.json")).validate(portable)
    Draft202012Validator(load_schema("evaluation_suite_v1.json")).validate(
        portable["suite"]
    )
    for observation in portable["observations"]:
        Draft202012Validator(load_schema("metric_observation_v1.json")).validate(
            observation
        )

    fixture_path = (
        Path(__file__).resolve().parent / "fixtures" / "evidence_bundle_v1_golden.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    Draft202012Validator(load_schema("evidence_bundle_v1.json")).validate(
        fixture["bundle"]
    )


def test_schema_assets_importable_from_package() -> None:
    from importlib import resources

    root = resources.files("arvp.schemas")
    for name in SCHEMA_ASSET_NAMES:
        assert root.joinpath(name).is_file()
