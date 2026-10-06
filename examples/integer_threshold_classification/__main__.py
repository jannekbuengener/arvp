"""CLI entry for the integer-threshold second-domain proof."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running as ``python -m examples.integer_threshold_classification``
# or ``python examples/integer_threshold_classification/__main__.py``.
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from examples.integer_threshold_classification import (  # noqa: E402
    accuracy_from_bundle,
    build_run,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="ARVP integer-threshold classification second-domain proof"
    )
    parser.add_argument(
        "--candidate",
        choices=("improved", "regression", "baseline"),
        default="improved",
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
    bundle, serialized = build_run(
        candidate_key=args.candidate,
        include_candidate_observations=not args.hold,
    )
    if args.write_input is not None:
        args.write_input.write_text(serialized, encoding="utf-8")
    print(
        json.dumps(
            {
                "verdict": bundle.gate_decision["verdict"],
                "evidence_fingerprint": bundle.evidence_fingerprint,
                "candidate_accuracy": (
                    None
                    if accuracy_from_bundle(bundle) is None
                    else str(accuracy_from_bundle(bundle))
                ),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
