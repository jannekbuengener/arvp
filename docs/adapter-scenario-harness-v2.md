# ARVP Adapter Boundary and Scenario Harness v2

This document freezes the artifact-first integration surface and Scenario
Harness v2 introduced by Issue #12.

## Evaluation Input contract

- `EVALUATION_INPUT_CONTRACT_VERSION = "arvp.evaluation-input.v1"`
- Schema asset: `evaluation_input_v1.json`

Primary integration is artifact/contract first:

```text
consumer domain -> portable EvaluationInput (baseline + candidate sides)
                -> ARVP evaluation -> Evidence Bundle
```

ARVP does not discover, import, or own consumer runtimes, loaders, databases,
model servers, DAWs, exchanges, or application state. There is no plugin
registry, hidden filesystem scan, or cloud callback.

### Explicit baseline / candidate evidence sides

`EvaluationInput` carries separated:

- `baseline_observations`
- `candidate_observations`

These map 1:1 into `compare_observation_scope(baseline=..., candidate=...)`
and `paired_resample_stability`. Suite `baseline_candidate_fingerprint` binds
baseline **identity** only; it is never treated as baseline evidence.

Empty or missing sides remain expressible so gates can surface
`missing_baseline` / `missing_candidate` / HOLD without collapsing both sides
into a single observation list.

### In-process surface

`ObservationProducer` is an explicit callable/protocol. Callers that already
live in-process may implement it and invoke `produce_observations(...)`.
`evaluate_artifacts(...)` evaluates already-produced observation sides.

### Portable surface

Serialize with `dumps_evaluation_input(...)` / `EvaluationInput.to_dict()`,
then call `evaluate_evaluation_input(...)` without importing the consumer.

## Scenario Harness v2

- `SCENARIO_CONTRACT_VERSION = "arvp.scenario.v2"`
- `SCENARIO_MANIFEST_CONTRACT_VERSION = "arvp.scenario-manifest.v2"`

Scenario fingerprints bind:

- scenario id + parameters
- candidate fingerprint
- suite fingerprint
- partition fingerprint
- execution mode + configuration

Group fingerprints bind request fingerprints plus safe result semantics
(exit codes, metrics, structured failures). Wall-clock timestamps are recorded
on the manifest for presentation only and do not enter semantic identity.

Unexpected runner exceptions raise by default. Explicit
`unexpected_exceptions="capture"` emits only safe structured
`FailureEvidence` (exception type name, never message/traceback).

## Non-goals

- no entry-point/plugin discovery
- no workflow engine/scheduler
- no subprocess manager
- no consumer-specific adapters inside `src/arvp`
- no remote execution
