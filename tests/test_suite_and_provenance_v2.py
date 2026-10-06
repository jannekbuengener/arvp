from __future__ import annotations

from decimal import Decimal

import pytest

from arvp.datasets import identify_content
from arvp.gates import AbsoluteThresholdCriterion, GatePolicy
from arvp.identities import CandidateSpec, EvaluationPartition
from arvp.metrics import MetricContract, MetricDefinition
from arvp.provenance import (
    MAX_ATTEMPT,
    RUN_PROVENANCE_CONTRACT_VERSION,
    RUN_RECORD_SCHEMA_VERSION,
    JsonlRunRegistry,
    ProvenanceError,
    RunProvenance,
    RunRecord,
    canonicalize_utc,
)
from arvp.suite import (
    EVALUATION_SUITE_CONTRACT_VERSION,
    EvaluationSuite,
    SuiteContractError,
)


def _metric_contract() -> MetricContract:
    return MetricContract(
        (
            MetricDefinition("quality.score", "maximize", "1", True),
            MetricDefinition("error.rate", "minimize", "1", True),
        )
    )


def _partition(
    seed: str = "a", partition_id: str = "validation"
) -> EvaluationPartition:
    content = identify_content([{"id": seed}], fields=("id",), ordering="ordered")
    return EvaluationPartition(partition_id, "validation", content)


def _candidate(candidate_id: str = "baseline") -> CandidateSpec:
    return CandidateSpec(candidate_id, "impl.eval", "r1", {"depth": 2})


def _suite(
    *,
    suite_id: str = "release.default",
    partitions: tuple[EvaluationPartition, ...] | None = None,
    baseline: CandidateSpec | None = None,
    threshold: Decimal = Decimal("0.5"),
) -> EvaluationSuite:
    contract = _metric_contract()
    policy = GatePolicy(
        "release.default",
        contract,
        (
            AbsoluteThresholdCriterion(
                "quality.floor", "quality.score", "gte", threshold
            ),
        ),
    )
    content = identify_content([{"id": "root"}], fields=("id",), ordering="ordered")
    return EvaluationSuite(
        suite_id,
        content,
        partitions if partitions is not None else (_partition(),),
        contract,
        policy,
        baseline if baseline is not None else _candidate(),
    )


def test_suite_fingerprint_stable_across_partition_insertion_order() -> None:
    p_a = _partition("a", "alpha")
    p_b = _partition("b", "beta")
    left = _suite(partitions=(p_a, p_b))
    right = _suite(partitions=(p_b, p_a))
    assert left.fingerprint() == right.fingerprint()
    assert [p.partition_id for p in left.partitions] == ["alpha", "beta"]


def test_suite_fingerprint_changes_on_partition_metric_gate_or_baseline() -> None:
    base = _suite()
    other_partition = _suite(partitions=(_partition("z", "validation"),))
    other_gate = _suite(threshold=Decimal("0.9"))
    other_baseline = _suite(baseline=_candidate("other-baseline"))
    assert base.fingerprint() != other_partition.fingerprint()
    assert base.fingerprint() != other_gate.fingerprint()
    assert base.fingerprint() != other_baseline.fingerprint()


def test_suite_rejects_gate_policy_from_foreign_metric_contract() -> None:
    contract = _metric_contract()
    foreign = MetricContract((MetricDefinition("other.metric", "maximize", "1", True),))
    policy = GatePolicy(
        "release.default",
        foreign,
        (
            AbsoluteThresholdCriterion(
                "other.floor", "other.metric", "gte", Decimal("1")
            ),
        ),
    )
    content = identify_content([{"id": "root"}], fields=("id",), ordering="ordered")
    with pytest.raises(SuiteContractError, match="gate_policy metric contract"):
        EvaluationSuite(
            "release.default",
            content,
            (_partition(),),
            contract,
            policy,
            _candidate(),
        )


def test_run_provenance_v2_binds_full_candidate_suite_partition_identity() -> None:
    suite = _suite(
        partitions=(_partition("a", "validation"), _partition("b", "holdout"))
    )
    candidate = _candidate("cand-1")
    provenance = RunProvenance.bind(
        candidate_fingerprint=candidate.fingerprint(),
        suite=suite,
        partition_id="validation",
        code_revision="deadbeef",
        configuration={"seed": 7},
        arvp_version="0.1.0-test",
    )
    assert provenance.contract_version == RUN_PROVENANCE_CONTRACT_VERSION
    assert provenance.suite_fingerprint == suite.fingerprint()
    assert (
        provenance.partition_fingerprint == suite.partition("validation").fingerprint()
    )
    assert provenance.candidate_fingerprint == candidate.fingerprint()
    assert "deadbeef" in provenance.to_dict()["code_revision"]
    assert (
        provenance.fingerprint()
        == RunProvenance(
            candidate_fingerprint=candidate.fingerprint(),
            suite_fingerprint=suite.fingerprint(),
            partition_id="validation",
            partition_fingerprint=suite.partition("validation").fingerprint(),
            code_revision="deadbeef",
            configuration={"seed": 7},
            arvp_version="0.1.0-test",
        ).fingerprint()
    )


def test_registry_round_trip_uses_full_fingerprint_for_attempts(tmp_path) -> None:
    suite = _suite()
    provenance = RunProvenance.bind(
        candidate_fingerprint=_candidate("cand").fingerprint(),
        suite=suite,
        partition_id="validation",
        code_revision="rev",
        arvp_version="0.1.0",
    )
    registry = JsonlRunRegistry(tmp_path / "registry.jsonl")
    running = RunRecord(
        run_id=provenance.run_id(1),
        provenance_fingerprint=provenance.fingerprint(),
        status="running",
        started_at_utc="2026-10-05T12:00:00+00:00",
    )
    done = RunRecord(
        run_id=provenance.run_id(1),
        provenance_fingerprint=provenance.fingerprint(),
        status="completed",
        started_at_utc="2026-10-05T12:00:00Z",
        finished_at_utc="2026-10-05T12:00:01+00:00",
        result={"accuracy": 0.9},
    )
    registry.append(running)
    registry.append(done)
    loaded = registry.load_all()
    assert loaded[0].started_at_utc == "2026-10-05T12:00:00Z"
    assert loaded[1].finished_at_utc == "2026-10-05T12:00:01Z"
    assert loaded[1].schema_version == RUN_RECORD_SCHEMA_VERSION
    assert registry.next_attempt(provenance) == 2


def test_prefix_collision_does_not_mix_attempts(tmp_path) -> None:
    """Same 12-hex run-id prefix must not share attempt counters across fingerprints."""
    suite = _suite()
    real = RunProvenance.bind(
        candidate_fingerprint=_candidate("real").fingerprint(),
        suite=suite,
        partition_id="validation",
        code_revision="rev-a",
        arvp_version="0.1.0",
    )
    prefix = real.fingerprint()[:12]
    foreign_fp = prefix + ("f" if real.fingerprint()[12] != "f" else "e") * 52
    assert foreign_fp != real.fingerprint()
    foreign = RunRecord(
        run_id=f"run-{prefix}-0099",
        provenance_fingerprint=foreign_fp,
        status="running",
        started_at_utc="2026-10-05T12:00:00Z",
    )
    registry = JsonlRunRegistry(tmp_path / "registry.jsonl")
    registry.append(foreign)
    assert registry.next_attempt(real) == 1


def test_run_record_requires_prefix_coherence_and_nonzero_attempt() -> None:
    with pytest.raises(ProvenanceError, match="prefix must match"):
        RunRecord(
            run_id="run-aaaaaaaaaaaa-0001",
            provenance_fingerprint="b" * 64,
            status="running",
            started_at_utc="2026-10-05T12:00:00Z",
        )
    with pytest.raises(ProvenanceError, match="positive integer"):
        RunRecord(
            run_id="run-" + ("a" * 12) + "-0000",
            provenance_fingerprint="a" * 64,
            status="running",
            started_at_utc="2026-10-05T12:00:00Z",
        )


def test_load_all_revalidates_lifecycle_history(tmp_path) -> None:
    path = tmp_path / "registry.jsonl"
    fp = "a" * 64
    # Terminal-first history must fail closed on load.
    payload = {
        "run_id": "run-" + ("a" * 12) + "-0001",
        "provenance_fingerprint": fp,
        "schema_version": RUN_RECORD_SCHEMA_VERSION,
        "started_at_utc": "2026-10-05T12:00:00Z",
        "finished_at_utc": "2026-10-05T12:00:01Z",
        "status": "completed",
    }
    path.write_text(
        __import__("json").dumps(payload, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ProvenanceError, match="must have status running"):
        JsonlRunRegistry(path).load_all()


def test_canonical_utc_normalizes_equivalent_forms() -> None:
    assert canonicalize_utc("2026-10-05T12:00:00+00:00", "t") == "2026-10-05T12:00:00Z"
    assert canonicalize_utc("2026-10-05T12:00:00Z", "t") == "2026-10-05T12:00:00Z"
    with pytest.raises(ProvenanceError, match="UTC"):
        canonicalize_utc("2026-10-05T12:00:00", "t")


def test_lifecycle_transitions_and_duplicate_terminal_rejection(tmp_path) -> None:
    suite = _suite()
    provenance = RunProvenance.bind(
        candidate_fingerprint=_candidate("cand").fingerprint(),
        suite=suite,
        partition_id="validation",
        code_revision="rev",
        arvp_version="0.1.0",
    )
    registry = JsonlRunRegistry(tmp_path / "registry.jsonl")
    run_id = provenance.run_id(1)
    fp = provenance.fingerprint()
    registry.append(
        RunRecord(
            run_id=run_id,
            provenance_fingerprint=fp,
            status="running",
            started_at_utc="2026-10-05T12:00:00Z",
        )
    )
    with pytest.raises(ProvenanceError, match="duplicate running"):
        registry.append(
            RunRecord(
                run_id=run_id,
                provenance_fingerprint=fp,
                status="running",
                started_at_utc="2026-10-05T12:00:00Z",
            )
        )
    registry.append(
        RunRecord(
            run_id=run_id,
            provenance_fingerprint=fp,
            status="failed",
            started_at_utc="2026-10-05T12:00:00Z",
            finished_at_utc="2026-10-05T12:00:02Z",
            failure_reason="boom",
        )
    )
    with pytest.raises(ProvenanceError, match="already terminal"):
        registry.append(
            RunRecord(
                run_id=run_id,
                provenance_fingerprint=fp,
                status="completed",
                started_at_utc="2026-10-05T12:00:00Z",
                finished_at_utc="2026-10-05T12:00:03Z",
            )
        )


def test_malformed_registry_line_fails_closed(tmp_path) -> None:
    path = tmp_path / "registry.jsonl"
    path.write_text("{not json\n", encoding="utf-8")
    with pytest.raises(ProvenanceError, match="malformed JSON"):
        JsonlRunRegistry(path).load_all()


def test_attempt_boundary_rejects_overflow() -> None:
    suite = _suite()
    provenance = RunProvenance.bind(
        candidate_fingerprint=_candidate("cand").fingerprint(),
        suite=suite,
        partition_id="validation",
        code_revision="rev",
        arvp_version="0.1.0",
    )
    with pytest.raises(ProvenanceError, match=str(MAX_ATTEMPT)):
        provenance.run_id(MAX_ATTEMPT + 1)


def test_missing_schema_version_fails_closed() -> None:
    with pytest.raises(ProvenanceError, match="schema_version"):
        RunRecord.from_dict(
            {
                "run_id": "run-0123456789ab-0001",
                "provenance_fingerprint": "a" * 64,
                "status": "running",
                "started_at_utc": "2026-10-05T12:00:00Z",
            }
        )


def test_first_record_must_be_running(tmp_path) -> None:
    registry = JsonlRunRegistry(tmp_path / "registry.jsonl")
    with pytest.raises(ProvenanceError, match="must have status running"):
        registry.append(
            RunRecord(
                run_id="run-" + ("a" * 12) + "-0001",
                provenance_fingerprint="a" * 64,
                status="completed",
                started_at_utc="2026-10-05T12:00:00Z",
                finished_at_utc="2026-10-05T12:00:01Z",
            )
        )


def test_suite_contract_version_constant() -> None:
    assert EVALUATION_SUITE_CONTRACT_VERSION == "arvp.evaluation-suite.v1"
    assert _suite().contract_version == EVALUATION_SUITE_CONTRACT_VERSION
