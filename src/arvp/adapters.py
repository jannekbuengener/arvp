"""Artifact-first adapter boundary for in-process and portable consumers.

Primary integration path:

    consumer domain -> portable EvaluationInput (baseline/candidate sides)
                    -> ARVP evaluation -> Evidence Bundle

ARVP never discovers, imports, or owns consumer runtimes, data loaders,
databases, model servers, DAWs, exchanges, or application state. There is no
plugin registry, filesystem scan, or cloud callback.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from arvp.bundle import EvidenceBundle, EvidenceBundleError
from arvp.canonical import (
    CanonicalizationError,
    FingerprintFormatError,
    canonical_hash,
    canonical_json_dumps,
    revive_canonical,
    validate_fingerprint,
)
from arvp.datasets import DatasetContentIdentity
from arvp.evidence import (
    FailureEvidence,
    PortableEvidenceError,
    validate_portable_metadata,
)
from arvp.gates import (
    AbsoluteThresholdCriterion,
    GateContractError,
    GatePolicy,
    RelativeBaselineCriterion,
    compare_observation_scope,
    evaluate_gate,
)
from arvp.identities import (
    CANDIDATE_CONTRACT_VERSION,
    EVALUATION_PARTITION_CONTRACT_VERSION,
    CandidateSpec,
    EvaluationPartition,
)
from arvp.metrics import (
    METRIC_CONTRACT_VERSION,
    METRIC_DEFINITION_CONTRACT_VERSION,
    MetricContract,
    MetricContractError,
    MetricDefinition,
    Observation,
)
from arvp.provenance import (
    RUN_PROVENANCE_CONTRACT_VERSION,
    ProvenanceError,
    RunProvenance,
)
from arvp.stability import (
    STABILITY_CONFIG_CONTRACT_VERSION,
    PairedStabilityResult,
    StabilityConfig,
    StabilityError,
    paired_resample_stability,
)
from arvp.suite import EvaluationSuite, SuiteContractError

EVALUATION_INPUT_CONTRACT_VERSION = "arvp.evaluation-input.v1"


class AdapterError(ValueError):
    """Raised when portable adapter inputs violate the artifact boundary."""


def _require_fingerprint(value: object, field: str) -> str:
    try:
        return validate_fingerprint(value, field)
    except FingerprintFormatError as exc:
        raise AdapterError(str(exc)) from exc


def _require_mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise AdapterError(f"{field} must be a mapping")
    try:
        validate_portable_metadata(value, field=field)
    except PortableEvidenceError as exc:
        raise AdapterError(str(exc)) from exc
    return copy.deepcopy(dict(value))


def _require_mapping_sequence(value: object, field: str) -> tuple[dict[str, Any], ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise AdapterError(f"{field} must be a sequence of mappings")
    return tuple(
        _require_mapping(item, f"{field}[{index}]") for index, item in enumerate(value)
    )


def _contains_arvp(value: Any) -> bool:
    if isinstance(value, Mapping):
        if "$arvp" in value:
            return True
        return any(_contains_arvp(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_arvp(item) for item in value)
    return False


def _materialise_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise AdapterError("payload must be a mapping")
    materialised: Mapping[str, Any] = payload
    if _contains_arvp(payload):
        try:
            revived = revive_canonical(dict(payload))
        except CanonicalizationError as exc:
            raise AdapterError(f"payload is not canonical: {exc}") from exc
        if not isinstance(revived, dict):
            raise AdapterError("payload must be a mapping")
        materialised = revived
    return dict(materialised)


def _metric_definition_from_dict(payload: Mapping[str, Any]) -> MetricDefinition:
    if not isinstance(payload, Mapping):
        raise AdapterError("metric definition must be a mapping")
    try:
        return MetricDefinition(
            payload["metric_id"],
            payload["direction"],
            payload["unit"],
            payload["required"],
            contract_version=payload.get(
                "contract_version", METRIC_DEFINITION_CONTRACT_VERSION
            ),
        )
    except (KeyError, TypeError, MetricContractError) as exc:
        raise AdapterError(f"metric definition invalid: {exc}") from exc


def _metric_contract_from_dict(payload: Mapping[str, Any]) -> MetricContract:
    if not isinstance(payload, Mapping):
        raise AdapterError("metric_contract must be a mapping")
    definitions = payload.get("definitions")
    if isinstance(definitions, (str, bytes)) or not isinstance(definitions, Sequence):
        raise AdapterError("metric_contract.definitions must be a sequence")
    try:
        return MetricContract(
            tuple(_metric_definition_from_dict(item) for item in definitions),
            contract_version=payload.get("contract_version", METRIC_CONTRACT_VERSION),
        )
    except (TypeError, MetricContractError) as exc:
        raise AdapterError(f"metric_contract invalid: {exc}") from exc


def _criterion_from_dict(
    payload: Mapping[str, Any],
) -> AbsoluteThresholdCriterion | RelativeBaselineCriterion:
    if not isinstance(payload, Mapping):
        raise AdapterError("criterion must be a mapping")
    criterion_type = payload.get("criterion_type")
    try:
        if criterion_type == "absolute_threshold":
            return AbsoluteThresholdCriterion(
                payload["criterion_id"],
                payload["metric_id"],
                payload["operator"],
                payload["threshold"],
            )
        if criterion_type == "relative_baseline":
            return RelativeBaselineCriterion(
                payload["criterion_id"],
                payload["metric_id"],
                payload["mode"],
                payload["threshold"],
            )
    except (KeyError, TypeError, GateContractError) as exc:
        raise AdapterError(f"gate criterion invalid: {exc}") from exc
    raise AdapterError(f"unsupported criterion_type: {criterion_type!r}")


def _gate_policy_from_dict(
    payload: Mapping[str, Any], *, metric_contract: MetricContract
) -> GatePolicy:
    if not isinstance(payload, Mapping):
        raise AdapterError("gate_policy must be a mapping")
    criteria = payload.get("criteria")
    if isinstance(criteria, (str, bytes)) or not isinstance(criteria, Sequence):
        raise AdapterError("gate_policy.criteria must be a sequence")
    try:
        policy = GatePolicy(
            payload["policy_id"],
            metric_contract,
            tuple(_criterion_from_dict(item) for item in criteria),
        )
    except (KeyError, TypeError, GateContractError) as exc:
        raise AdapterError(f"gate_policy invalid: {exc}") from exc
    declared = payload.get("metric_contract_fingerprint")
    if declared is not None and declared != policy.metric_contract_fingerprint:
        raise AdapterError("gate_policy metric contract fingerprint mismatch")
    return policy


def _content_identity_from_dict(payload: Mapping[str, Any]) -> DatasetContentIdentity:
    if not isinstance(payload, Mapping):
        raise AdapterError("content_identity must be a mapping")
    try:
        return DatasetContentIdentity(
            schema_version=payload["schema_version"],
            ordering=payload["ordering"],
            record_count=payload["record_count"],
            fingerprint=payload["fingerprint"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AdapterError(f"content_identity invalid: {exc}") from exc


def _partition_from_dict(payload: Mapping[str, Any]) -> EvaluationPartition:
    if not isinstance(payload, Mapping):
        raise AdapterError("partition must be a mapping")
    try:
        return EvaluationPartition(
            payload["partition_id"],
            payload["role"],
            _content_identity_from_dict(payload["content_identity"]),
            contract_version=payload.get(
                "contract_version", EVALUATION_PARTITION_CONTRACT_VERSION
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AdapterError(f"partition invalid: {exc}") from exc


def _candidate_from_dict(payload: Mapping[str, Any]) -> CandidateSpec:
    if not isinstance(payload, Mapping):
        raise AdapterError("baseline_candidate must be a mapping")
    try:
        return CandidateSpec(
            payload["candidate_id"],
            payload["implementation_id"],
            payload["revision"],
            payload.get("configuration", {}),
            contract_version=payload.get(
                "contract_version", CANDIDATE_CONTRACT_VERSION
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AdapterError(f"baseline_candidate invalid: {exc}") from exc


def _suite_from_parts(
    *,
    suite_payload: Mapping[str, Any],
    metric_contract: MetricContract,
    gate_policy: GatePolicy,
    baseline_candidate: CandidateSpec,
) -> EvaluationSuite:
    if not isinstance(suite_payload, Mapping):
        raise AdapterError("suite must be a mapping")
    partitions = suite_payload.get("partitions")
    if isinstance(partitions, (str, bytes)) or not isinstance(partitions, Sequence):
        raise AdapterError("suite.partitions must be a sequence")
    try:
        suite = EvaluationSuite(
            suite_payload["suite_id"],
            _content_identity_from_dict(suite_payload["content_identity"]),
            tuple(_partition_from_dict(item) for item in partitions),
            metric_contract,
            gate_policy,
            baseline_candidate,
        )
    except (KeyError, TypeError, SuiteContractError) as exc:
        raise AdapterError(f"suite invalid: {exc}") from exc
    declared_baseline = suite_payload.get("baseline_candidate_fingerprint")
    if (
        declared_baseline is not None
        and declared_baseline != suite.baseline_candidate_fingerprint
    ):
        raise AdapterError("suite baseline_candidate fingerprint mismatch")
    declared_metric = suite_payload.get("metric_contract_fingerprint")
    if (
        declared_metric is not None
        and declared_metric != suite.metric_contract_fingerprint
    ):
        raise AdapterError("suite metric_contract fingerprint mismatch")
    declared_gate = suite_payload.get("gate_policy_fingerprint")
    if declared_gate is not None and declared_gate != suite.gate_policy_fingerprint:
        raise AdapterError("suite gate_policy fingerprint mismatch")
    return suite


def _run_provenance_from_dict(payload: Mapping[str, Any]) -> RunProvenance:
    if not isinstance(payload, Mapping):
        raise AdapterError("run_provenance must be a mapping")
    try:
        return RunProvenance(
            candidate_fingerprint=payload["candidate_fingerprint"],
            suite_fingerprint=payload["suite_fingerprint"],
            partition_id=payload["partition_id"],
            partition_fingerprint=payload["partition_fingerprint"],
            code_revision=payload["code_revision"],
            configuration=payload.get("configuration", {}),
            arvp_version=payload["arvp_version"],
            contract_version=payload.get(
                "contract_version", RUN_PROVENANCE_CONTRACT_VERSION
            ),
        )
    except (KeyError, TypeError, ProvenanceError) as exc:
        raise AdapterError(f"run_provenance invalid: {exc}") from exc


def _stability_config_from_dict(payload: Mapping[str, Any]) -> StabilityConfig:
    if not isinstance(payload, Mapping):
        raise AdapterError("stability_config must be a mapping")
    try:
        return StabilityConfig(
            aggregation=payload["aggregation"],
            sample_count=payload["sample_count"],
            blocks_per_sample=payload["blocks_per_sample"],
            seed=payload["seed"],
            contract_version=payload.get(
                "contract_version", STABILITY_CONFIG_CONTRACT_VERSION
            ),
        )
    except (KeyError, TypeError, StabilityError) as exc:
        raise AdapterError(f"stability_config invalid: {exc}") from exc


def _observations_from_dicts(
    payloads: Sequence[Mapping[str, Any]],
    *,
    metric_contract: MetricContract,
    field: str,
) -> tuple[Observation, ...]:
    observations: list[Observation] = []
    for index, payload in enumerate(payloads):
        try:
            observations.append(
                Observation.from_dict(payload, metric_contract=metric_contract)
            )
        except MetricContractError as exc:
            raise AdapterError(f"{field}[{index}] invalid: {exc}") from exc
    return tuple(observations)


def _failure_from_dict(payload: Mapping[str, Any]) -> FailureEvidence:
    if not isinstance(payload, Mapping):
        raise AdapterError("failure must be a mapping")
    try:
        return FailureEvidence(
            code=payload["code"],
            stage=payload.get("stage"),
            exception_type=payload.get("exception_type"),
            metadata=payload.get("metadata"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AdapterError(f"failure invalid: {exc}") from exc


@runtime_checkable
class ObservationProducer(Protocol):
    """In-process callable/protocol: consumer produces portable observations."""

    def produce(
        self,
        *,
        candidate: CandidateSpec,
        partition: EvaluationPartition,
        metric_contract: MetricContract,
    ) -> Sequence[Observation]:
        """Return validated observations for one candidate/partition scope."""


@runtime_checkable
class ArtifactEvaluationBoundary(Protocol):
    """Thin in-process Protocol for artifact-first evaluation."""

    def evaluate_artifacts(
        self,
        *,
        suite: EvaluationSuite,
        metric_contract: MetricContract,
        gate_policy: GatePolicy,
        partition_id: str,
        candidate_fingerprint: str,
        baseline_observations: Sequence[Observation],
        candidate_observations: Sequence[Observation],
        run_provenance: RunProvenance,
        generated_at: str,
        failures: Sequence[FailureEvidence] = (),
        stability_config: StabilityConfig | None = None,
    ) -> EvidenceBundle:
        """Evaluate already-produced portable observations."""


@dataclass(frozen=True, slots=True)
class EvaluationInput:
    """Versioned serialized evaluation-input envelope (arvp.evaluation-input.v1).

    ``baseline_observations`` and ``candidate_observations`` are explicit
    evidence sides that map 1:1 into ``compare_observation_scope`` /
    ``paired_resample_stability``. Suite baseline identity alone is never
    treated as baseline evidence.
    """

    suite: Mapping[str, Any]
    metric_contract: Mapping[str, Any]
    gate_policy: Mapping[str, Any]
    baseline_candidate: Mapping[str, Any]
    candidate_fingerprint: str
    partition_id: str
    run_provenance: Mapping[str, Any]
    baseline_observations: Sequence[Mapping[str, Any]]
    candidate_observations: Sequence[Mapping[str, Any]]
    failures: Sequence[Mapping[str, Any]] = ()
    stability_config: Mapping[str, Any] | None = None
    configuration: Mapping[str, Any] | None = None
    contract_version: str = EVALUATION_INPUT_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != EVALUATION_INPUT_CONTRACT_VERSION:
            raise AdapterError(
                f"contract_version must be {EVALUATION_INPUT_CONTRACT_VERSION!r}"
            )
        object.__setattr__(self, "suite", _require_mapping(self.suite, "suite"))
        object.__setattr__(
            self,
            "metric_contract",
            _require_mapping(self.metric_contract, "metric_contract"),
        )
        object.__setattr__(
            self, "gate_policy", _require_mapping(self.gate_policy, "gate_policy")
        )
        object.__setattr__(
            self,
            "baseline_candidate",
            _require_mapping(self.baseline_candidate, "baseline_candidate"),
        )
        object.__setattr__(
            self,
            "candidate_fingerprint",
            _require_fingerprint(self.candidate_fingerprint, "candidate_fingerprint"),
        )
        if type(self.partition_id) is not str or not self.partition_id.strip():
            raise AdapterError("partition_id must be a non-empty string")
        object.__setattr__(self, "partition_id", self.partition_id.strip())
        object.__setattr__(
            self,
            "run_provenance",
            _require_mapping(self.run_provenance, "run_provenance"),
        )
        object.__setattr__(
            self,
            "baseline_observations",
            _require_mapping_sequence(
                self.baseline_observations, "baseline_observations"
            ),
        )
        object.__setattr__(
            self,
            "candidate_observations",
            _require_mapping_sequence(
                self.candidate_observations, "candidate_observations"
            ),
        )
        object.__setattr__(
            self, "failures", _require_mapping_sequence(self.failures, "failures")
        )
        if self.stability_config is None:
            stability = None
        else:
            stability = _require_mapping(self.stability_config, "stability_config")
        object.__setattr__(self, "stability_config", stability)
        if self.configuration is None:
            configuration: dict[str, Any] = {}
        else:
            configuration = _require_mapping(self.configuration, "configuration")
            try:
                canonical_json_dumps(configuration)
            except CanonicalizationError as exc:
                raise AdapterError(f"configuration not canonicalizable: {exc}") from exc
        object.__setattr__(self, "configuration", configuration)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "baseline_candidate": dict(self.baseline_candidate),
            "baseline_observations": [
                dict(item) for item in self.baseline_observations
            ],
            "candidate_fingerprint": self.candidate_fingerprint,
            "candidate_observations": [
                dict(item) for item in self.candidate_observations
            ],
            "configuration": dict(self.configuration or {}),
            "contract_version": self.contract_version,
            "failures": [dict(item) for item in self.failures],
            "gate_policy": dict(self.gate_policy),
            "metric_contract": dict(self.metric_contract),
            "partition_id": self.partition_id,
            "run_provenance": dict(self.run_provenance),
            "suite": dict(self.suite),
        }
        if self.stability_config is not None:
            payload["stability_config"] = dict(self.stability_config)
        return payload

    def fingerprint(self) -> str:
        return canonical_hash(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> EvaluationInput:
        materialised = _materialise_payload(payload)
        return cls(
            suite=materialised["suite"],
            metric_contract=materialised["metric_contract"],
            gate_policy=materialised["gate_policy"],
            baseline_candidate=materialised["baseline_candidate"],
            candidate_fingerprint=materialised["candidate_fingerprint"],
            partition_id=materialised["partition_id"],
            run_provenance=materialised["run_provenance"],
            baseline_observations=materialised.get("baseline_observations", ()),
            candidate_observations=materialised.get("candidate_observations", ()),
            failures=materialised.get("failures", ()),
            stability_config=materialised.get("stability_config"),
            configuration=materialised.get("configuration"),
            contract_version=materialised.get(
                "contract_version", EVALUATION_INPUT_CONTRACT_VERSION
            ),
        )

    @classmethod
    def from_path(cls, path: Path | str) -> EvaluationInput:
        destination = Path(path)
        try:
            raw = json.loads(destination.read_text(encoding="utf-8"))
        except OSError as exc:
            raise AdapterError(f"could not read evaluation input: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise AdapterError(f"evaluation input is not valid JSON: {exc}") from exc
        if not isinstance(raw, Mapping):
            raise AdapterError("evaluation input root must be a mapping")
        return cls.from_dict(raw)


def build_evaluation_input(
    *,
    suite: EvaluationSuite,
    metric_contract: MetricContract,
    gate_policy: GatePolicy,
    baseline_candidate: CandidateSpec,
    candidate_fingerprint: str,
    partition_id: str,
    run_provenance: RunProvenance,
    baseline_observations: Sequence[Observation] = (),
    candidate_observations: Sequence[Observation] = (),
    failures: Sequence[FailureEvidence] = (),
    stability_config: StabilityConfig | None = None,
    configuration: Mapping[str, Any] | None = None,
) -> EvaluationInput:
    """Assemble a portable EvaluationInput from live in-process contract objects."""
    if type(suite) is not EvaluationSuite:
        raise AdapterError("suite must be an EvaluationSuite")
    if type(metric_contract) is not MetricContract:
        raise AdapterError("metric_contract must be a MetricContract")
    if type(gate_policy) is not GatePolicy:
        raise AdapterError("gate_policy must be a GatePolicy")
    if type(baseline_candidate) is not CandidateSpec:
        raise AdapterError("baseline_candidate must be a CandidateSpec")
    if type(run_provenance) is not RunProvenance:
        raise AdapterError("run_provenance must be a RunProvenance")
    suite.partition(partition_id)
    return EvaluationInput(
        suite=suite.to_dict(),
        metric_contract=metric_contract.to_dict(),
        gate_policy=gate_policy.to_dict(),
        baseline_candidate=baseline_candidate.to_dict(),
        candidate_fingerprint=candidate_fingerprint,
        partition_id=partition_id,
        run_provenance=run_provenance.to_dict(),
        baseline_observations=[item.to_dict() for item in baseline_observations],
        candidate_observations=[item.to_dict() for item in candidate_observations],
        failures=[item.to_dict() for item in failures],
        stability_config=(
            None if stability_config is None else stability_config.to_dict()
        ),
        configuration=configuration,
    )


def dumps_evaluation_input(evaluation_input: EvaluationInput) -> str:
    """Serialize EvaluationInput as canonical JSON for cross-package exchange."""
    if type(evaluation_input) is not EvaluationInput:
        raise AdapterError("evaluation_input must be an EvaluationInput")
    try:
        return canonical_json_dumps(evaluation_input.to_dict())
    except CanonicalizationError as exc:
        raise AdapterError(f"evaluation input not canonicalizable: {exc}") from exc


def produce_observations(
    producer: ObservationProducer,
    *,
    candidate: CandidateSpec,
    partition: EvaluationPartition,
    metric_contract: MetricContract,
) -> tuple[Observation, ...]:
    """Invoke an explicit in-process producer; no discovery or registry."""
    if not isinstance(producer, ObservationProducer):
        raise AdapterError("producer must implement ObservationProducer")
    raw = producer.produce(
        candidate=candidate,
        partition=partition,
        metric_contract=metric_contract,
    )
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        raise AdapterError("producer must return a sequence of Observation")
    observations: list[Observation] = []
    for index, item in enumerate(raw):
        if type(item) is not Observation:
            raise AdapterError(f"producer[{index}] must be an Observation")
        observations.append(item)
    return tuple(observations)


def evaluate_artifacts(
    *,
    suite: EvaluationSuite,
    metric_contract: MetricContract,
    gate_policy: GatePolicy,
    partition_id: str,
    candidate_fingerprint: str,
    baseline_observations: Sequence[Observation],
    candidate_observations: Sequence[Observation],
    run_provenance: RunProvenance,
    generated_at: str,
    failures: Sequence[FailureEvidence] = (),
    stability_config: StabilityConfig | None = None,
) -> EvidenceBundle:
    """Evaluate already-produced observation sides without consumer imports.

    Unexpected programmer/runtime exceptions raise by default (fail-fast).
    Expected domain failures belong in ``failures`` as structured evidence.
    """
    if type(suite) is not EvaluationSuite:
        raise AdapterError("suite must be an EvaluationSuite")
    if type(metric_contract) is not MetricContract:
        raise AdapterError("metric_contract must be a MetricContract")
    if type(gate_policy) is not GatePolicy:
        raise AdapterError("gate_policy must be a GatePolicy")
    if type(run_provenance) is not RunProvenance:
        raise AdapterError("run_provenance must be a RunProvenance")
    _require_fingerprint(candidate_fingerprint, "candidate_fingerprint")
    suite.partition(partition_id)

    try:
        comparisons = compare_observation_scope(
            baseline=baseline_observations,
            candidate=candidate_observations,
            metric_contract=metric_contract,
        )
        gate_decision = evaluate_gate(
            policy=gate_policy,
            comparisons=comparisons,
            metric_contract=metric_contract,
        )
        stability_results: tuple[PairedStabilityResult, ...] = ()
        if stability_config is not None:
            if type(stability_config) is not StabilityConfig:
                raise AdapterError("stability_config must be a StabilityConfig")
            observation_metric_ids = {
                observation.metric.metric_id
                for observation in (*baseline_observations, *candidate_observations)
            }
            gate_metric_ids = {
                criterion.metric_id for criterion in gate_policy.criteria
            }
            # Prefer metrics present on the observation sides (paired evidence);
            # fall back to gate metrics when sides are empty.
            metric_ids = sorted(observation_metric_ids or gate_metric_ids)
            stability_results = tuple(
                paired_resample_stability(
                    baseline=baseline_observations,
                    candidate=candidate_observations,
                    metric_contract=metric_contract,
                    metric_id=metric_id,
                    config=stability_config,
                )
                for metric_id in metric_ids
            )
        combined = tuple(baseline_observations) + tuple(candidate_observations)
        return EvidenceBundle.build(
            suite=suite,
            partition_id=partition_id,
            candidate_fingerprint=candidate_fingerprint,
            run_provenance=run_provenance,
            gate_decision=gate_decision,
            observations=combined,
            comparisons=comparisons,
            stability=stability_results,
            failures=failures,
            generated_at=generated_at,
        )
    except (AdapterError, GateContractError, StabilityError, EvidenceBundleError):
        raise
    except Exception as exc:
        # Never silently convert unexpected exceptions into a successful path.
        # Callers that want structured capture use Scenario Harness capture mode.
        _ = FailureEvidence.from_unexpected_exception(exc, stage="adapter")
        raise


def evaluate_evaluation_input(
    payload: Mapping[str, Any] | EvaluationInput | Path | str,
    *,
    generated_at: str,
) -> EvidenceBundle:
    """Deserialize EvaluationInput (if needed), validate, evaluate, return bundle."""
    try:
        if isinstance(payload, EvaluationInput):
            evaluation_input = payload
        elif isinstance(payload, Path) or (
            isinstance(payload, str) and Path(payload).is_file()
        ):
            evaluation_input = EvaluationInput.from_path(payload)
        elif isinstance(payload, Mapping):
            evaluation_input = EvaluationInput.from_dict(payload)
        else:
            raise AdapterError(
                "payload must be EvaluationInput, a mapping, or an existing file path"
            )

        metric_contract = _metric_contract_from_dict(evaluation_input.metric_contract)
        gate_policy = _gate_policy_from_dict(
            evaluation_input.gate_policy, metric_contract=metric_contract
        )
        baseline_candidate = _candidate_from_dict(evaluation_input.baseline_candidate)
        suite = _suite_from_parts(
            suite_payload=evaluation_input.suite,
            metric_contract=metric_contract,
            gate_policy=gate_policy,
            baseline_candidate=baseline_candidate,
        )
        run_provenance = _run_provenance_from_dict(evaluation_input.run_provenance)
        baseline_observations = _observations_from_dicts(
            evaluation_input.baseline_observations,
            metric_contract=metric_contract,
            field="baseline_observations",
        )
        candidate_observations = _observations_from_dicts(
            evaluation_input.candidate_observations,
            metric_contract=metric_contract,
            field="candidate_observations",
        )
        failures = tuple(_failure_from_dict(item) for item in evaluation_input.failures)
        stability_config = (
            None
            if evaluation_input.stability_config is None
            else _stability_config_from_dict(evaluation_input.stability_config)
        )
        return evaluate_artifacts(
            suite=suite,
            metric_contract=metric_contract,
            gate_policy=gate_policy,
            partition_id=evaluation_input.partition_id,
            candidate_fingerprint=evaluation_input.candidate_fingerprint,
            baseline_observations=baseline_observations,
            candidate_observations=candidate_observations,
            run_provenance=run_provenance,
            generated_at=generated_at,
            failures=failures,
            stability_config=stability_config,
        )
    except EvidenceBundleError as exc:
        raise AdapterError(str(exc)) from exc
