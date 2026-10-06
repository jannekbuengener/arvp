"""Sample Brain FSLD key/tempo artifact integration tests (#14)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from arvp.canonical import canonical_json_dumps
from arvp.schemas import load_schema
from examples.sample_brain_fsld_key_tempo import (
    FIXTURE_ROOT,
    FsldAdapterError,
    assert_no_private_leakage,
    build_run,
    load_json,
    ma_key_root_exact_rate_from_bundle,
    validate_fsld_report,
)

ROOT = Path(__file__).resolve().parents[1]


def test_pass_improved_candidate_via_serialized_evaluation_input() -> None:
    first, serialized, status = build_run(candidate_key="improved")
    second, _, _ = build_run(candidate_key="improved")
    assert status == "compatible"
    assert first.gate_decision["verdict"] == "PASS"
    assert first.evidence_fingerprint == second.evidence_fingerprint
    assert ma_key_root_exact_rate_from_bundle(first) == pytest.approx(1.0)
    portable = json.loads(serialized)
    assert portable["baseline_observations"]
    assert portable["candidate_observations"]
    assert portable["contract_version"] == "arvp.evaluation-input.v1"
    dumped = canonical_json_dumps(first.to_dict())
    assert_no_private_leakage(dumped)
    assert str(ROOT).replace("\\", "/") not in dumped.replace("\\", "/")


def test_fail_regression_candidate() -> None:
    bundle, _, status = build_run(
        candidate_key="regression",
        candidate_report_name="candidate_regression.json",
    )
    assert status == "compatible"
    assert bundle.gate_decision["verdict"] == "FAIL"
    assert ma_key_root_exact_rate_from_bundle(bundle) == pytest.approx(0.0)


def test_hold_when_public_audio_unavailable() -> None:
    bundle, serialized, status = build_run(
        candidate_key="improved",
        candidate_report_name="public_audio_unavailable.json",
    )
    assert status == "blocked_unavailable"
    assert bundle.gate_decision["verdict"] == "HOLD"
    payload = json.loads(serialized)
    assert payload["candidate_observations"] == []
    # Must not invent a measured 0% candidate quality signal.
    assert ma_key_root_exact_rate_from_bundle(bundle) is None
    assert any(
        failure.get("code") == "input_unavailable" for failure in payload["failures"]
    )
    assert_no_private_leakage(payload)


def test_hold_when_candidate_observations_missing() -> None:
    bundle, serialized, status = build_run(
        candidate_key="improved",
        include_candidate_observations=False,
    )
    assert status == "compatible"
    assert bundle.gate_decision["verdict"] == "HOLD"
    payload = json.loads(serialized)
    assert payload["baseline_observations"]
    assert payload["candidate_observations"] == []


def test_hold_on_manifest_mismatch() -> None:
    bundle, serialized, status = build_run(
        candidate_key="improved",
        candidate_report_name="mismatched_manifest.json",
    )
    assert status == "manifest_mismatch"
    assert bundle.gate_decision["verdict"] == "HOLD"
    payload = json.loads(serialized)
    assert payload["baseline_observations"]
    assert payload["candidate_observations"] == []
    assert ma_key_root_exact_rate_from_bundle(bundle) is None
    assert any(
        failure.get("metadata", {}).get("reason") == "manifest_mismatch"
        for failure in payload["failures"]
    )


def test_hold_on_split_mismatch() -> None:
    bundle, serialized, status = build_run(
        candidate_key="improved",
        candidate_report_name="mismatched_split.json",
    )
    assert status == "split_mismatch"
    assert bundle.gate_decision["verdict"] == "HOLD"
    payload = json.loads(serialized)
    assert payload["baseline_observations"]
    assert payload["candidate_observations"] == []
    assert ma_key_root_exact_rate_from_bundle(bundle) is None


def test_malformed_report_raises_structured_failure() -> None:
    with pytest.raises(FsldAdapterError, match="split must be"):
        validate_fsld_report(load_json(FIXTURE_ROOT / "malformed_missing_fields.json"))


def test_schema_validates_evaluation_input_and_evidence_bundle() -> None:
    try:
        import jsonschema
    except ImportError:
        pytest.skip("jsonschema unavailable on this host")

    bundle, serialized, _ = build_run(candidate_key="improved")
    Draft = jsonschema.Draft202012Validator
    Draft(load_schema("evaluation_input_v1.json")).validate(json.loads(serialized))
    Draft(load_schema("evidence_bundle_v1.json")).validate(
        json.loads(canonical_json_dumps(bundle.to_dict()))
    )


def test_stability_evidence_present_for_paired_key_metric() -> None:
    bundle, _, _ = build_run(candidate_key="improved")
    assert bundle.stability
    paired = [
        item for item in bundle.stability if item.get("metric_id") == "key.root.correct"
    ]
    assert paired
    assert paired[0]["status"] == "complete"
    assert paired[0]["pair_count"] == 4


def test_fixtures_are_sanitized_and_repository_owned() -> None:
    for name in (
        "baseline_evaluated.json",
        "candidate_improved.json",
        "candidate_regression.json",
        "public_audio_unavailable.json",
        "mismatched_manifest.json",
        "mismatched_split.json",
        "candidates.json",
    ):
        path = FIXTURE_ROOT / name
        assert path.is_file(), name
        assert_no_private_leakage(path.read_text(encoding="utf-8"))

    assert (FIXTURE_ROOT / "PROVENANCE.md").is_file()

    unavailable = load_json(FIXTURE_ROOT / "public_audio_unavailable.json")
    assert unavailable["run_status"] == "PUBLIC_AUDIO_NOT_AVAILABLE_LOCALLY"
    assert unavailable["metrics"] is None

    baseline = validate_fsld_report(load_json(FIXTURE_ROOT / "baseline_evaluated.json"))
    assert baseline["run_status"] == "EVALUATED"
    assert baseline["metrics"]["ma"]["key_root"]["exact_rate"] == 0.5
