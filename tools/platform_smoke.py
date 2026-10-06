"""Platform smoke probe for ARVP Issue #4.

Runs the canonical v2 golden vectors on every platform so that CI proves the
core contracts execute and repeat identically inside one environment.

This probe validates the frozen canonical v2 contract via golden fixture.
"""

from __future__ import annotations

from arvp.canonical import CanonicalizationError, canonical_hash, canonical_json_dumps

try:
    # When run from tools/ directory (package smoke test)
    from canonical_v2_golden import load_golden_vectors, reconstruct_source
except ImportError:
    # When run from repo root (unit tests)
    from tools.canonical_v2_golden import load_golden_vectors, reconstruct_source


def probe_golden_vectors() -> None:
    """Verify all golden vectors match expected canonical JSON and fingerprints."""
    for vec in load_golden_vectors():
        source = reconstruct_source(vec)
        if "expect_error" in vec:
            # Negative test: verify error is raised
            try:
                canonical_json_dumps(source)
            except CanonicalizationError:
                pass
            else:
                raise AssertionError(
                    f"Vector {vec['name']}: expected {vec['expect_error']}, but succeeded"
                )
        else:
            # Positive test: verify exact canonical JSON and fingerprint
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


def probe_platform_repeatability() -> None:
    """Additional repeatability checks for cross-platform validation."""
    # Canonical JSON dumps repeatability
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

    # Canonical hash repeatability
    payload2 = {
        "rows": [{"id": 3, "score": "1.5"}, {"id": 1, "score": "0.5"}],
        "count": 2,
    }

    first = canonical_hash(payload2)
    second = canonical_hash(payload2)

    assert first == second, "canonical_hash not repeatable"
    assert len(first) == 64, f"expected 64 hex characters, got {len(first)}"


def main() -> int:
    probe_golden_vectors()
    probe_platform_repeatability()
    print("platform smoke ok: canonical v2 golden vectors verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
