"""CLI entry for Sample Brain FSLD key/tempo reference integration."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from examples.sample_brain_fsld_key_tempo import (  # noqa: E402
    build_run,
    ma_key_root_exact_rate_from_bundle,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="ARVP Sample Brain FSLD key/tempo reference integration (#14)"
    )
    parser.add_argument(
        "--candidate",
        choices=("improved", "regression", "baseline"),
        default="improved",
    )
    parser.add_argument(
        "--candidate-report",
        default=None,
        help="Override candidate fixture filename under tests/fixtures/sample_brain_fsld",
    )
    parser.add_argument(
        "--hold",
        action="store_true",
        help="Omit candidate observations to force HOLD via missing evidence",
    )
    parser.add_argument(
        "--write-input",
        type=Path,
        default=None,
        help="Optional path to write the serialized EvaluationInput JSON",
    )
    args = parser.parse_args(argv)
    report_name = args.candidate_report
    if report_name is None:
        report_name = {
            "improved": "candidate_improved.json",
            "regression": "candidate_regression.json",
            "baseline": "baseline_evaluated.json",
        }[args.candidate]
    bundle, serialized, status = build_run(
        candidate_key=args.candidate,
        candidate_report_name=report_name,
        include_candidate_observations=not args.hold,
    )
    if args.write_input is not None:
        args.write_input.write_text(serialized, encoding="utf-8")
    rate = ma_key_root_exact_rate_from_bundle(bundle)
    print(
        json.dumps(
            {
                "verdict": bundle.gate_decision["verdict"],
                "compatibility": status,
                "evidence_fingerprint": bundle.evidence_fingerprint,
                "candidate_ma_key_root_exact_rate": None if rate is None else str(rate),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
