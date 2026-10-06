from __future__ import annotations

from pathlib import Path

import pytest

from arvp.datasets import identify_content
from arvp.identities import (
    CANDIDATE_CONTRACT_VERSION,
    EVALUATION_PARTITION_CONTRACT_VERSION,
    CandidateSpec,
    EvaluationPartition,
    IdentityContractError,
)


def test_candidate_fingerprint_is_deterministic_and_mapping_order_independent() -> None:
    first = CandidateSpec(
        candidate_id="candidate-a",
        implementation_id="search.algorithm",
        revision="r1",
        configuration={"alpha": 1, "beta": {"x": 2}},
    )
    second = CandidateSpec(
        candidate_id="candidate-a",
        implementation_id="search.algorithm",
        revision="r1",
        configuration={"beta": {"x": 2}, "alpha": 1},
    )

    assert first.contract_version == CANDIDATE_CONTRACT_VERSION
    assert first.fingerprint() == second.fingerprint()


def test_candidate_fingerprint_changes_with_identity_inputs() -> None:
    base = CandidateSpec("candidate-a", "impl-a", "r1", {"threshold": 1})
    changed_revision = CandidateSpec("candidate-a", "impl-a", "r2", {"threshold": 1})
    changed_implementation = CandidateSpec(
        "candidate-a", "impl-b", "r1", {"threshold": 1}
    )
    changed_configuration = CandidateSpec(
        "candidate-a", "impl-a", "r1", {"threshold": 2}
    )

    fingerprints = {
        base.fingerprint(),
        changed_revision.fingerprint(),
        changed_implementation.fingerprint(),
        changed_configuration.fingerprint(),
    }
    assert len(fingerprints) == 4


def test_candidate_configuration_is_defensively_owned() -> None:
    source = {"nested": {"weights": [1, 2]}}
    candidate = CandidateSpec("candidate-a", "impl-a", "r1", source)
    before = candidate.fingerprint()

    source["nested"]["weights"].append(3)  # type: ignore[index]

    assert candidate.configuration == {"nested": {"weights": [1, 2]}}
    assert candidate.fingerprint() == before


def test_candidate_rejects_unsafe_or_nonportable_configuration() -> None:
    with pytest.raises(IdentityContractError, match="forbidden"):
        CandidateSpec("candidate-a", "impl-a", "r1", {"path": "private.wav"})
    with pytest.raises(IdentityContractError, match="canonical"):
        CandidateSpec("candidate-a", "impl-a", "r1", {"value": Path("private.wav")})


def test_candidate_contract_version_is_exact() -> None:
    with pytest.raises(IdentityContractError, match="contract_version"):
        CandidateSpec(
            "candidate-a",
            "impl-a",
            "r1",
            {},
            contract_version="arvp.candidate.v0",
        )


def test_partition_accepts_only_well_known_roles() -> None:
    content = identify_content([{"id": "a"}], fields=("id",), ordering="ordered")
    roles = ("development", "calibration", "validation", "test", "external_check")

    for role in roles:
        partition = EvaluationPartition("split-a", role, content)  # type: ignore[arg-type]
        assert partition.role == role
        assert partition.contract_version == EVALUATION_PARTITION_CONTRACT_VERSION
        assert len(partition.fingerprint()) == 64

    with pytest.raises(IdentityContractError, match="role"):
        EvaluationPartition("split-a", "train", content)  # type: ignore[arg-type]


def test_partition_fingerprint_binds_id_role_and_exact_membership() -> None:
    content_a = identify_content([{"id": "a"}], fields=("id",), ordering="ordered")
    content_b = identify_content([{"id": "b"}], fields=("id",), ordering="ordered")

    base = EvaluationPartition("split-a", "calibration", content_a)
    changed_membership = EvaluationPartition("split-a", "calibration", content_b)
    changed_role = EvaluationPartition("split-a", "test", content_a)
    changed_id = EvaluationPartition("split-b", "calibration", content_a)

    assert (
        len(
            {
                base.fingerprint(),
                changed_membership.fingerprint(),
                changed_role.fingerprint(),
                changed_id.fingerprint(),
            }
        )
        == 4
    )


def test_partition_requires_dataset_content_identity_and_has_no_window_fields() -> None:
    content = identify_content([], fields=("id",), ordering="unordered")
    partition = EvaluationPartition("empty-test", "test", content)

    assert set(partition.to_dict()) == {
        "content_identity",
        "contract_version",
        "partition_id",
        "role",
    }
    assert "start" not in partition.to_dict()
    assert "end" not in partition.to_dict()

    with pytest.raises(IdentityContractError, match="content_identity"):
        EvaluationPartition("bad", "test", "not-an-identity")  # type: ignore[arg-type]


def test_identity_contracts_are_exported_from_package_root() -> None:
    import arvp

    assert arvp.CONTENT_IDENTITY_SCHEMA_VERSION == "arvp.dataset-content.v2"
    assert arvp.CANDIDATE_CONTRACT_VERSION == "arvp.candidate.v1"
    assert arvp.EVALUATION_PARTITION_CONTRACT_VERSION == "arvp.evaluation-partition.v1"
    assert arvp.DatasetOrdering is not None
    assert arvp.CandidateSpec is CandidateSpec
    assert arvp.EvaluationPartition is EvaluationPartition
    assert arvp.IdentityContractError is IdentityContractError
