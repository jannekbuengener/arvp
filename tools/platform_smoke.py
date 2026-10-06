"""Cross-platform smoke probe for ARVP portable identity contracts."""

from __future__ import annotations

import json
from pathlib import Path

from arvp.canonical import CanonicalizationError, canonical_hash, canonical_json_dumps
from arvp.datasets import DatasetContentIdentity, identify_content
from arvp.identities import CandidateSpec, EvaluationPartition

try:
    from canonical_v2_golden import load_golden_vectors, reconstruct_source
except ImportError:
    from tools.canonical_v2_golden import load_golden_vectors, reconstruct_source


_IDENTITY_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "fixtures"
    / "identity_contracts_v1_golden.json"
)


def probe_golden_vectors() -> None:
    """Verify all canonical-v2 golden vectors."""
    for vec in load_golden_vectors():
        source = reconstruct_source(vec)
        if "expect_error" in vec:
            try:
                canonical_json_dumps(source)
            except CanonicalizationError:
                pass
            else:
                raise AssertionError(
                    f"Vector {vec['name']}: expected {vec['expect_error']}, but succeeded"
                )
        else:
            actual_json = canonical_json_dumps(source)
            assert actual_json == vec["expected_json"], (
                f"Vector {vec['name']}: canonical JSON mismatch\n"
                f"  expected: {vec['expected_json']}\n"
                f"  actual:   {actual_json}"
            )
            actual_fp = canonical_hash(source)
            assert actual_fp == vec["expected_fingerprint"], (
                f"Vector {vec['name']}: fingerprint mismatch\n"
                f"  expected: {vec['expected_fingerprint']}\n"
                f"  actual:   {actual_fp}"
            )


def probe_identity_contracts() -> None:
    """Verify dataset, candidate, and partition golden identities."""
    fixture = json.loads(_IDENTITY_FIXTURE.read_text(encoding="utf-8"))
    for vector in fixture["vectors"]:
        kind = vector["kind"]
        if kind == "dataset":
            identity = identify_content(
                vector["records"],
                fields=tuple(vector["fields"]),
                ordering=vector["ordering"],
            )
            actual_fingerprint = identity.fingerprint
        elif kind == "candidate":
            candidate = CandidateSpec(
                vector["candidate_id"],
                vector["implementation_id"],
                vector["revision"],
                vector["configuration"],
            )
            actual_fingerprint = candidate.fingerprint()
        elif kind == "partition":
            raw = vector["content_identity"]
            content = DatasetContentIdentity(
                schema_version=raw["schema_version"],
                ordering=raw["ordering"],
                record_count=raw["record_count"],
                fingerprint=raw["fingerprint"],
            )
            partition = EvaluationPartition(
                vector["partition_id"], vector["role"], content
            )
            actual_fingerprint = partition.fingerprint()
        else:
            raise AssertionError(f"unknown identity golden kind: {kind}")
        assert actual_fingerprint == vector["expected_fingerprint"], vector["name"]


def probe_platform_repeatability() -> None:
    """Additional repeatability checks for cross-platform validation."""
    payload = {
        "z": 26,
        "a": 1,
        "nested": {"gamma": [3, 2, 1], "alpha": None},
        "decimal": "1.234",
        "negative_zero": -0.0,
    }
    first = canonical_json_dumps(payload)
    second = canonical_json_dumps(dict(reversed(list(payload.items()))))
    assert first == canonical_json_dumps(payload), "canonical_json_dumps not repeatable"
    assert first == second, "canonical_json_dumps depends on mapping order"
    assert isinstance(first, str)

    payload2 = {
        "rows": [{"id": 3, "score": "1.5"}, {"id": 1, "score": "0.5"}],
        "count": 2,
    }
    first_hash = canonical_hash(payload2)
    second_hash = canonical_hash(payload2)
    assert first_hash == second_hash, "canonical_hash not repeatable"
    assert len(first_hash) == 64, f"expected 64 hex characters, got {len(first_hash)}"


def main() -> int:
    probe_golden_vectors()
    probe_identity_contracts()
    probe_platform_repeatability()
    print("platform smoke ok: canonical v2 and identity goldens verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
