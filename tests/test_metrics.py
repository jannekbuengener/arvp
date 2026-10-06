from __future__ import annotations

from decimal import Decimal

import pytest

from arvp.datasets import identify_content
from arvp.identities import CandidateSpec, EvaluationPartition
from arvp.metrics import (
    METRIC_CONTRACT_VERSION,
    METRIC_DEFINITION_CONTRACT_VERSION,
    METRIC_VALUE_CONTRACT_VERSION,
    OBSERVATION_CONTRACT_VERSION,
    MetricContract,
    MetricContractError,
    MetricDefinition,
    MetricValue,
    Observation,
    validate_observations,
)


def _definitions() -> tuple[MetricDefinition, ...]:
    return (
        MetricDefinition("tempo.abs_error", "minimize", "bpm", True),
        MetricDefinition("search.relevance", "maximize", "1", True),
        MetricDefinition("runtime.ms", "neutral", "ms", False),
    )


def _contract() -> MetricContract:
    return MetricContract(_definitions())


def _partition() -> EvaluationPartition:
    content = identify_content(
        [{"id": "a"}, {"id": "b"}], fields=("id",), ordering="ordered"
    )
    return EvaluationPartition("validation", "validation", content)


def _candidate(candidate_id: str, revision: str = "r1") -> CandidateSpec:
    return CandidateSpec(candidate_id, "impl.search", revision, {"depth": 2})


def test_metric_definition_contract_and_fingerprint_are_deterministic() -> None:
    definition = MetricDefinition("tempo.abs_error", "minimize", "bpm", True)
    assert definition.contract_version == METRIC_DEFINITION_CONTRACT_VERSION
    assert definition.to_dict() == {
        "contract_version": METRIC_DEFINITION_CONTRACT_VERSION,
        "direction": "minimize",
        "metric_id": "tempo.abs_error",
        "required": True,
        "unit": "bpm",
    }
    assert len(definition.fingerprint()) == 64
    assert definition.fingerprint() == definition.fingerprint()


@pytest.mark.parametrize(
    "metric_id", ["Score", "_score", "score/mean", "score mean", "", "a" * 65]
)
def test_metric_definition_rejects_invalid_metric_ids(metric_id: str) -> None:
    with pytest.raises(MetricContractError, match="metric_id"):
        MetricDefinition(metric_id, "maximize", "1", True)


@pytest.mark.parametrize("direction", ["up", "down", "MAXIMIZE", 1])
def test_metric_definition_rejects_invalid_direction(direction: object) -> None:
    with pytest.raises(MetricContractError, match="direction"):
        MetricDefinition("score", direction, "1", True)  # type: ignore[arg-type]


def test_metric_definition_requires_non_empty_unit_and_exact_bool_required() -> None:
    with pytest.raises(MetricContractError, match="unit"):
        MetricDefinition("score", "maximize", "", True)
    with pytest.raises(MetricContractError, match="required"):
        MetricDefinition("score", "maximize", "1", 1)  # type: ignore[arg-type]


def test_metric_definition_accepts_dimensionless_unit_one() -> None:
    definition = MetricDefinition("search.relevance", "maximize", "1", True)
    assert definition.unit == "1"


def test_metric_contract_sorts_definitions_and_hashes_independent_of_input_order() -> (
    None
):
    definitions = _definitions()
    first = MetricContract(definitions)
    second = MetricContract(tuple(reversed(definitions)))
    assert first.contract_version == METRIC_CONTRACT_VERSION
    assert [item.metric_id for item in first.definitions] == [
        "runtime.ms",
        "search.relevance",
        "tempo.abs_error",
    ]
    assert first.to_dict() == second.to_dict()
    assert first.fingerprint() == second.fingerprint()


def test_metric_contract_rejects_empty_and_duplicate_definitions() -> None:
    with pytest.raises(MetricContractError, match="non-empty"):
        MetricContract(())
    duplicate = MetricDefinition("score", "maximize", "1", True)
    with pytest.raises(MetricContractError, match="duplicate metric_id"):
        MetricContract((duplicate, duplicate))


def test_metric_contract_definition_lookup_rejects_unknown_metric() -> None:
    with pytest.raises(MetricContractError, match="unknown metric_id"):
        _contract().definition("missing.metric")


@pytest.mark.parametrize("status", ["measured", "derived"])
def test_metric_value_measured_and_derived_require_finite_numeric_value(
    status: str,
) -> None:
    contract = _contract()
    value = contract.value("tempo.abs_error", status, 1.25)  # type: ignore[arg-type]
    assert value.contract_version == METRIC_VALUE_CONTRACT_VERSION
    assert value.metric_id == "tempo.abs_error"
    assert value.status == status
    assert value.value == Decimal("1.25")
    assert value.metric_contract_fingerprint == contract.fingerprint()
    assert len(value.fingerprint()) == 64


@pytest.mark.parametrize("bad", [None, True, "1.0", float("nan"), float("inf")])
def test_metric_value_rejects_missing_non_numeric_and_non_finite_measured_values(
    bad: object,
) -> None:
    with pytest.raises(MetricContractError, match="finite numeric value"):
        _contract().value("tempo.abs_error", "measured", bad)  # type: ignore[arg-type]


@pytest.mark.parametrize("status", ["unknown", "not_applicable"])
def test_metric_value_missing_statuses_require_no_numeric_value(status: str) -> None:
    contract = _contract()
    value = contract.value("runtime.ms", status)  # type: ignore[arg-type]
    assert value.status == status
    assert value.value is None
    assert "value" not in value.to_dict()
    with pytest.raises(MetricContractError, match="must not carry a numeric value"):
        contract.value("runtime.ms", status, 0)  # type: ignore[arg-type]


def test_metric_value_unknown_metric_is_rejected() -> None:
    with pytest.raises(MetricContractError, match="unknown metric_id"):
        _contract().value("missing.metric", "measured", 1)


def test_metric_value_cannot_be_constructed_directly() -> None:
    with pytest.raises(TypeError):
        MetricValue(
            "score", "measured", Decimal("1"), "a" * 64, METRIC_VALUE_CONTRACT_VERSION
        )  # type: ignore[call-arg]


def test_validate_values_rejects_duplicates_and_foreign_contract_values() -> None:
    contract = _contract()
    value = contract.value("search.relevance", "measured", Decimal("0.8"))
    with pytest.raises(MetricContractError, match="duplicate metric_id"):
        contract.validate_values((value, value))
    foreign_contract = MetricContract(
        (MetricDefinition("search.relevance", "maximize", "percent", True),)
    )
    foreign = foreign_contract.value("search.relevance", "measured", Decimal("0.8"))
    with pytest.raises(MetricContractError, match="metric contract fingerprint"):
        contract.validate_values((foreign,))


def test_validate_values_returns_deterministic_metric_id_order() -> None:
    contract = _contract()
    values = (
        contract.value("tempo.abs_error", "measured", 2),
        contract.value("runtime.ms", "unknown"),
        contract.value("search.relevance", "derived", Decimal("0.9")),
    )
    validated = contract.validate_values(tuple(reversed(values)))
    assert [item.metric_id for item in validated] == [
        "runtime.ms",
        "search.relevance",
        "tempo.abs_error",
    ]


@pytest.mark.parametrize(
    "observation_id",
    ["", "has space", "folder/file", "folder\\file", ".starts-with-dot", "x" * 129],
)
def test_observation_rejects_invalid_opaque_ids(observation_id: str) -> None:
    contract = _contract()
    value = contract.value("search.relevance", "measured", 1)
    with pytest.raises(MetricContractError, match="observation_id"):
        Observation(
            observation_id=observation_id,
            candidate=_candidate("candidate-a"),
            partition=_partition(),
            metric_contract=contract,
            metric=value,
        )


def test_observation_binds_candidate_partition_metric_contract_and_metric() -> None:
    contract = _contract()
    candidate = _candidate("candidate-a")
    partition = _partition()
    value = contract.value("search.relevance", "measured", Decimal("0.75"))
    observation = Observation(
        observation_id="item:001",
        candidate=candidate,
        partition=partition,
        metric_contract=contract,
        metric=value,
    )
    assert observation.contract_version == OBSERVATION_CONTRACT_VERSION
    assert observation.candidate_fingerprint == candidate.fingerprint()
    assert observation.partition_id == partition.partition_id
    assert observation.partition_fingerprint == partition.fingerprint()
    assert observation.metric == value
    assert observation.to_dict()["metric"] == value.to_dict()
    assert len(observation.fingerprint()) == 64


def test_paired_observations_share_pairing_key_but_not_scope_or_fingerprint() -> None:
    contract = _contract()
    partition = _partition()
    baseline = Observation(
        observation_id="item:001",
        candidate=_candidate("baseline"),
        partition=partition,
        metric_contract=contract,
        metric=contract.value("search.relevance", "measured", Decimal("0.70")),
    )
    candidate = Observation(
        observation_id="item:001",
        candidate=_candidate("candidate"),
        partition=partition,
        metric_contract=contract,
        metric=contract.value("search.relevance", "measured", Decimal("0.82")),
    )
    assert baseline.pairing_key() == candidate.pairing_key()
    assert baseline.scope_key() != candidate.scope_key()
    assert baseline.fingerprint() != candidate.fingerprint()


def test_observation_rejects_metric_from_different_contract() -> None:
    contract = _contract()
    foreign_contract = MetricContract(
        (MetricDefinition("search.relevance", "maximize", "percent", True),)
    )
    foreign_value = foreign_contract.value("search.relevance", "measured", 1)
    with pytest.raises(MetricContractError, match="metric contract fingerprint"):
        Observation(
            observation_id="item:001",
            candidate=_candidate("candidate-a"),
            partition=_partition(),
            metric_contract=contract,
            metric=foreign_value,
        )


def test_validate_observations_rejects_duplicate_scope_and_sorts_deterministically() -> (
    None
):
    contract = _contract()
    partition = _partition()
    candidate = _candidate("candidate-a")
    first = Observation(
        observation_id="item:002",
        candidate=candidate,
        partition=partition,
        metric_contract=contract,
        metric=contract.value("search.relevance", "measured", 1),
    )
    second = Observation(
        observation_id="item:001",
        candidate=candidate,
        partition=partition,
        metric_contract=contract,
        metric=contract.value("tempo.abs_error", "measured", 2),
    )
    validated = validate_observations((first, second))
    assert validated == tuple(
        sorted((first, second), key=lambda item: item.scope_key())
    )
    with pytest.raises(MetricContractError, match="duplicate observation scope"):
        validate_observations((first, first))


def test_public_metric_contracts_are_exported_from_package_root() -> None:
    import arvp

    expected = {
        "METRIC_DEFINITION_CONTRACT_VERSION",
        "METRIC_CONTRACT_VERSION",
        "METRIC_VALUE_CONTRACT_VERSION",
        "OBSERVATION_CONTRACT_VERSION",
        "MetricDirection",
        "MetricValueStatus",
        "MetricContractError",
        "MetricDefinition",
        "MetricContract",
        "MetricValue",
        "Observation",
        "validate_observations",
    }
    assert expected.issubset(set(arvp.__all__))
    for name in expected:
        assert hasattr(arvp, name)
