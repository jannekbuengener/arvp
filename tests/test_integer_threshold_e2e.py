"""End-to-end second-domain proof for integer-threshold classification (#13)."""

from __future__ import annotations

import json
import subprocess
import sys
import venv
from pathlib import Path

import pytest

from arvp.schemas import load_schema
from examples.integer_threshold_classification import (
    GENERATED_AT,
    accuracy_from_bundle,
    build_run,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "integer_threshold" / "cases.json"


def test_pass_improved_candidate_via_serialized_evaluation_input() -> None:
    from arvp.canonical import canonical_json_dumps

    first, serialized = build_run(candidate_key="improved")
    second, _ = build_run(candidate_key="improved")
    assert first.gate_decision["verdict"] == "PASS"
    assert first.evidence_fingerprint == second.evidence_fingerprint
    assert accuracy_from_bundle(first) == pytest.approx(1.0)
    portable = json.loads(serialized)
    assert portable["baseline_observations"]
    assert portable["candidate_observations"]
    assert portable["contract_version"] == "arvp.evaluation-input.v1"
    # No private/local path leakage in portable evidence.
    dumped = canonical_json_dumps(first.to_dict())
    assert "D:\\" not in dumped
    assert "/Users/" not in dumped
    assert str(ROOT).replace("\\", "/") not in dumped.replace("\\", "/")


def test_fail_regression_candidate() -> None:
    bundle, _ = build_run(candidate_key="regression")
    assert bundle.gate_decision["verdict"] == "FAIL"
    assert accuracy_from_bundle(bundle) == pytest.approx(0.75)


def test_hold_when_candidate_observations_missing() -> None:
    bundle, serialized = build_run(
        candidate_key="improved", include_candidate_observations=False
    )
    assert bundle.gate_decision["verdict"] == "HOLD"
    payload = json.loads(serialized)
    assert payload["baseline_observations"]
    assert payload["candidate_observations"] == []


def test_schema_validates_evaluation_input_and_evidence_bundle() -> None:
    try:
        import jsonschema
    except ImportError:
        pytest.skip("jsonschema unavailable on this host")

    from arvp.canonical import canonical_json_dumps

    bundle, serialized = build_run(candidate_key="improved")
    Draft = jsonschema.Draft202012Validator
    Draft(load_schema("evaluation_input_v1.json")).validate(json.loads(serialized))
    Draft(load_schema("evidence_bundle_v1.json")).validate(
        json.loads(canonical_json_dumps(bundle.to_dict()))
    )


def test_stability_evidence_present_for_paired_correct_metric() -> None:
    bundle, _ = build_run(candidate_key="improved")
    assert bundle.stability
    correct = [item for item in bundle.stability if item.get("metric_id") == "correct"]
    assert correct
    assert correct[0]["status"] == "complete"
    assert correct[0]["pair_count"] == 8


def test_fixture_is_repository_owned_and_boring() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert fixture["ground_truth_rule"].startswith("label = 1 if x >= 10")
    assert [case["id"] for case in fixture["cases"]] == [
        f"case-{index:03d}" for index in range(1, 9)
    ]


def test_installed_wheel_evaluates_serialized_envelope(tmp_path: Path) -> None:
    """Prove the installed package (not source-tree import) can evaluate the envelope."""
    _, serialized = build_run(candidate_key="improved")
    envelope = tmp_path / "evaluation-input.json"
    envelope.write_text(serialized, encoding="utf-8")

    dist_dir = tmp_path / "dist"
    venv_dir = tmp_path / "wheel-venv"
    outside = tmp_path / "outside-repo"
    outside.mkdir()
    builder = venv.EnvBuilder(with_pip=True)
    builder.create(venv_dir)
    if sys.platform == "win32":
        python = venv_dir / "Scripts" / "python.exe"
    else:
        python = venv_dir / "bin" / "python"

    subprocess.run(
        [str(python), "-m", "pip", "install", "--upgrade", "pip", "build"],
        check=True,
        cwd=ROOT,
    )
    subprocess.run(
        [str(python), "-m", "build", "--wheel", "--outdir", str(dist_dir)],
        check=True,
        cwd=ROOT,
    )
    wheels = list(dist_dir.glob("arvp-*.whl"))
    assert wheels
    subprocess.run(
        [str(python), "-m", "pip", "install", str(wheels[0])],
        check=True,
        cwd=outside,
    )
    probe = outside / "probe.py"
    probe.write_text(
        "\n".join(
            [
                "from pathlib import Path",
                "import arvp",
                "from arvp import evaluate_evaluation_input",
                f"envelope = Path({str(envelope)!r})",
                "bundle = evaluate_evaluation_input(",
                f"    envelope, generated_at={GENERATED_AT!r}",
                ")",
                "assert 'site-packages' in Path(arvp.__file__).resolve().parts",
                "assert bundle.gate_decision['verdict'] == 'PASS'",
                "print(bundle.evidence_fingerprint)",
            ]
        ),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [str(python), str(probe)],
        check=True,
        cwd=outside,
        capture_output=True,
        text=True,
    )
    assert completed.stdout.strip()
