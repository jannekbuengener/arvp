# ARVP Metric and Observation Contracts v1

This document freezes the v0.2 metric and paired-observation surface introduced by Issue #7.

## Contract versions

- `METRIC_DEFINITION_CONTRACT_VERSION = "arvp.metric-definition.v1"`
- `METRIC_CONTRACT_VERSION = "arvp.metric-contract.v1"`
- `METRIC_VALUE_CONTRACT_VERSION = "arvp.metric-value.v1"`
- `OBSERVATION_CONTRACT_VERSION = "arvp.observation.v1"`

## MetricDefinition

`MetricDefinition(metric_id, direction, unit, required)` is domain-neutral and fingerprinted.

`metric_id` must match `^[a-z][a-z0-9_.-]{0,63}$`. `direction` is exactly `maximize`, `minimize`, or `neutral`. `unit` is consumer-owned non-empty portable text; ARVP does not interpret or normalize units. Dimensionless metrics use the explicit unit `"1"`. `required` must be an actual boolean.

ARVP does not ship a domain metric catalog. Consumers define metric IDs, directions, units, and requiredness.

## MetricContract

`MetricContract(definitions)` is the authority for one evaluation metric set. It requires a non-empty tuple of unique `MetricDefinition` objects, sorts them deterministically by `metric_id`, and exposes a stable fingerprint independent of caller insertion order.

Successor contracts use this fingerprint as `metric_contract_fingerprint`. Gate, suite, stability, and evidence code must not invent parallel metric-set identity.

## MetricValue

Metric values are created through `MetricContract.value(...)`; direct public construction is intentionally unavailable.

Statuses are `measured`, `derived`, `unknown`, and `not_applicable`.

`measured` and `derived` require a finite exact `int`, `float`, or `Decimal` input and are stored as finite `Decimal`. `bool`, strings, missing values, NaN, and infinity are rejected. `unknown` and `not_applicable` must carry no numeric value; missing evidence is never represented as zero.

Each `MetricValue` binds its `metric_id` and the exact `MetricContract` fingerprint. `MetricContract.validate_values()` rejects unknown metrics, foreign metric contracts, and duplicate metric IDs, then returns deterministic `metric_id` order.

## Observation

`Observation` binds one metric value to one consumer-supplied observation ID, candidate identity, and evaluation partition identity.

`observation_id` must match `^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$`. It is opaque and supplied by the consumer. ARVP does not derive observation IDs from filenames, paths, private inputs, or file hashes.

Portable observation evidence contains the observation ID, candidate fingerprint, partition ID and fingerprint, typed `MetricValue` including the metric-contract fingerprint, and the observation contract version.

`pairing_key()` deliberately excludes candidate identity and contains partition fingerprint, metric-contract fingerprint, metric ID, and observation ID. Baseline and candidate observations can therefore share a pairing key while retaining different candidate scopes and fingerprints. `scope_key()` adds the candidate fingerprint and is used for duplicate rejection.

`validate_observations()` rejects duplicate full scopes and returns deterministic scope order. It does not aggregate, compare, rank, or gate observations.

## Legacy result migration

`ScenarioResult.metrics` and `WindowResult.metrics` are now `tuple[MetricValue, ...] | None`. When metrics are present, the result must also receive the owning `MetricContract`; construction delegates to `MetricContract.validate_values()`.

`ScenarioResult.to_dict()` serializes typed metric values plus the metric-contract fingerprint. The legacy evaluation-window execution model remains a compatibility surface; Issue #12 owns Scenario Harness v2.

## Successor handoff

- Issue #8 consumes `MetricDefinition`, `MetricContract`, and `MetricValue` for baseline comparison and PASS/FAIL/HOLD gates.
- Issue #9 binds `MetricContract.fingerprint()` into `EvaluationSuite`.
- Issue #10 pairs observations by `Observation.pairing_key()` and must declare aggregation explicitly.
- Issue #11 embeds these portable contracts into Evidence Bundle v1.

No aggregation policy, weighted quality score, statistical-significance claim, comparison verdict, or domain-specific metric is defined here.

Frozen golden vectors live in `tests/fixtures/metric_contracts_v1_golden.json` and are exercised by unit tests plus the installed-wheel cross-platform smoke probe.
