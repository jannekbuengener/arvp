"""One-shot generator for sanitized FSLD fixtures (not imported by tests)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent

MANIFEST_A = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
MANIFEST_B = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
LIBS = {"librosa": "0.10.2", "numpy": "2.1.0", "soundfile": "0.12.1"}


def gt(
    root: str | None,
    mode: str | None,
    bpm: float | None,
    *,
    tonality: str = "tonal",
    root_ev: str = "known",
    mode_ev: str = "known",
    bpm_ev: str = "known",
) -> dict[str, object]:
    return {
        "tonality": tonality,
        "key_root": root,
        "root_evidence": root_ev,
        "key_mode": mode,
        "mode_evidence": mode_ev,
        "bpm": bpm,
        "bpm_evidence": bpm_ev,
    }


def rec(
    sid: str,
    split: str,
    tier: str,
    ground: dict[str, object],
    *,
    pred_root: str | None,
    pred_mode: str | None,
    pred_key: str | None,
    pred_bpm: float | None,
    status: str = "ok",
    exclusion: str | None = None,
) -> dict[str, object]:
    return {
        "public_sample_id": sid,
        "split": split,
        "annotation_tier": tier,
        "ground_truth": ground,
        "analyzer_id": "sample_brain.analyze.extract_features",
        "key_analysis_contract_version": "1.0.0",
        "mode_contrast_min": 0.15,
        "bpm_normalization": "none",
        "runtime_libraries": dict(LIBS),
        "predicted_key_root": pred_root,
        "predicted_key_mode": pred_mode,
        "predicted_key": pred_key,
        "predicted_bpm": pred_bpm,
        "native_evidence": {
            "key_conf": 0.55 if status == "ok" else None,
            "key_mode_evidence": (
                {"kind": "third_contrast", "contrast": 0.42} if status == "ok" else None
            ),
            "quality_note": None,
        },
        "runtime_ms": 11.0 if status == "ok" else None,
        "status": status,
        "exclusion_reason": exclusion,
    }


BASE_GT: list[tuple[str, str, dict[str, object]]] = [
    ("90001", "ma", gt("C", "maj", 120.0)),
    ("90002", "ma", gt("D", "min", 100.0)),
    ("90003", "sa", gt("G", "maj", 128.0)),
    ("90004", "sa", gt("A", "min", 90.0)),
]


def predictions(
    kind: str,
) -> list[tuple[str | None, str | None, str | None, float | None]]:
    if kind == "baseline":
        return [
            ("C", "maj", "Cmaj", 120.0),
            ("E", "min", "Emin", 100.0),
            ("G", "maj", "Gmaj", 128.0),
            ("B", "min", "Bmin", 90.0),
        ]
    if kind == "improved":
        return [
            ("C", "maj", "Cmaj", 120.0),
            ("D", "min", "Dmin", 100.0),
            ("G", "maj", "Gmaj", 128.0),
            ("A", "min", "Amin", 90.0),
        ]
    if kind == "regression":
        return [
            ("F", "maj", "Fmaj", 60.0),
            ("E", "min", "Emin", 50.0),
            ("C", "maj", "Cmaj", 64.0),
            ("B", "min", "Bmin", 45.0),
        ]
    raise ValueError(kind)


def metrics_for(kind: str) -> dict[str, object]:
    if kind == "baseline":
        ma_exact, sa_exact = 1, 1
        ma_tempo_correct, sa_tempo_correct = 2, 2
        err = 0.0
    elif kind == "improved":
        ma_exact, sa_exact = 2, 2
        ma_tempo_correct, sa_tempo_correct = 2, 2
        err = 0.0
    else:
        ma_exact, sa_exact = 0, 0
        ma_tempo_correct, sa_tempo_correct = 0, 0
        err = 40.0

    def tier(exact: int, tempo_correct: int) -> dict[str, object]:
        return {
            "key_root": {
                "eligible": 2,
                "predicted": 2,
                "exact": exact,
                "exact_rate": exact / 2,
            },
            "full_key": {
                "eligible": 2,
                "predicted": 2,
                "exact": exact,
                "exact_rate": exact / 2,
            },
            "tempo": {
                "eligible": 2,
                "predicted": 2,
                "absolute_bpm_error": {
                    "count": 2,
                    "mean": err,
                    "median": err,
                    "p95": err,
                },
                "relative_bpm_error": {
                    "count": 2,
                    "mean": 0.0 if tempo_correct == 2 else 0.5,
                    "median": 0.0 if tempo_correct == 2 else 0.5,
                    "p95": 0.0 if tempo_correct == 2 else 0.5,
                },
                "relation_counts": {
                    "correct": tempo_correct,
                    "half": 2 - tempo_correct,
                    "double": 0,
                    "ambiguous": 0,
                    "outlier": 0,
                },
                "relation_rates": {
                    "correct": tempo_correct / 2,
                    "half": (2 - tempo_correct) / 2,
                    "double": 0.0,
                    "ambiguous": 0.0,
                    "outlier": 0.0,
                },
            },
        }

    return {
        "ma": tier(ma_exact, ma_tempo_correct),
        "sa": tier(sa_exact, sa_tempo_correct),
    }


def report(
    kind: str,
    *,
    split: str = "TEST",
    manifest: str = MANIFEST_A,
    run_status: str = "EVALUATED",
) -> dict[str, object]:
    preds = predictions(kind)
    records: list[dict[str, object]] = []
    for (sid, tier, ground), pred in zip(BASE_GT, preds, strict=True):
        records.append(
            rec(
                sid,
                split,
                tier,
                ground,
                pred_root=pred[0],
                pred_mode=pred[1],
                pred_key=pred[2],
                pred_bpm=pred[3],
            )
        )
    return {
        "document_type": "sample_brain.fsld_current_analyzer_eval",
        "schema_version": "1.0.0",
        "split": split,
        "run_status": run_status,
        "manifest_sha256": manifest,
        "records": records,
        "metrics": metrics_for(kind) if run_status == "EVALUATED" else None,
    }


def unavailable() -> dict[str, object]:
    records = [
        rec(
            sid,
            "TEST",
            tier,
            ground,
            pred_root=None,
            pred_mode=None,
            pred_key=None,
            pred_bpm=None,
            status="missing_audio",
            exclusion="audio_missing",
        )
        for sid, tier, ground in BASE_GT
    ]
    return {
        "document_type": "sample_brain.fsld_current_analyzer_eval",
        "schema_version": "1.0.0",
        "split": "TEST",
        "run_status": "PUBLIC_AUDIO_NOT_AVAILABLE_LOCALLY",
        "manifest_sha256": MANIFEST_A,
        "records": records,
        "metrics": None,
    }


def write(name: str, obj: object) -> None:
    path = ROOT / name
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("wrote", path.name)


def main() -> None:
    write("baseline_evaluated.json", report("baseline"))
    write("candidate_improved.json", report("improved"))
    write("candidate_regression.json", report("regression"))
    write("public_audio_unavailable.json", unavailable())
    write("mismatched_manifest.json", report("improved", manifest=MANIFEST_B))
    write("mismatched_split.json", report("improved", split="CALIBRATION"))
    write(
        "malformed_missing_fields.json",
        {
            "document_type": "sample_brain.fsld_current_analyzer_eval",
            "schema_version": "1.0.0",
        },
    )
    write(
        "candidates.json",
        {
            "source_schema": "sample_brain.fsld_current_analyzer_eval@1.0.0",
            "source_sample_brain_commit": "eff14d25",
            "note": (
                "Explicit external candidate descriptors; FSLD reports do not "
                "carry a git/code revision. Synthetic public_sample_id values "
                "only; no audio, paths, or private identifiers."
            ),
            "candidates": {
                "baseline": {
                    "candidate_id": "fsld.keytempo.baseline",
                    "implementation_id": "sample_brain.analyze.extract_features",
                    "revision": "fixture-baseline-r1",
                    "configuration": {
                        "bpm_normalization": "none",
                        "key_analysis_contract_version": "1.0.0",
                        "profile": "baseline",
                    },
                },
                "improved": {
                    "candidate_id": "fsld.keytempo.improved",
                    "implementation_id": "sample_brain.analyze.extract_features",
                    "revision": "fixture-improved-r1",
                    "configuration": {
                        "bpm_normalization": "none",
                        "key_analysis_contract_version": "1.0.0",
                        "profile": "improved",
                    },
                },
                "regression": {
                    "candidate_id": "fsld.keytempo.regression",
                    "implementation_id": "sample_brain.analyze.extract_features",
                    "revision": "fixture-regression-r1",
                    "configuration": {
                        "bpm_normalization": "none",
                        "key_analysis_contract_version": "1.0.0",
                        "profile": "regression",
                    },
                },
            },
        },
    )


if __name__ == "__main__":
    main()
