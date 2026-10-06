# ARVP Paired Stability Contracts v1

This document freezes the v0.2 explicit aggregation and paired resampling surface introduced by Issue #10.

## Contract versions

- `STABILITY_CONFIG_CONTRACT_VERSION = "arvp.stability-config.v1"`
- `STABILITY_RESULT_CONTRACT_VERSION = "arvp.stability-result.v1"`

## Aggregation

Callers must choose an explicit aggregation:

- `mean`
- `sum`

No aggregation is inferred from a metric name. For `sum`, `blocks_per_sample` must equal the paired observation count so resampled bands stay on the same scale as the observed aggregate.

## Paired resampling

`paired_resample_stability(...)` consumes baseline and candidate `Observation` sequences, a `MetricContract`, `metric_id`, and `StabilityConfig`.

Requirements:

- numeric observations only (`measured` / `derived` with finite values)
- one shared partition identity per side
- matching metric-contract fingerprint
- pairs aligned by `observation_id` (order-independent)
- missing pairs yield `status=incomplete` with explicit reasons; pairs are never silently dropped
- deterministic RNG seed in the config

## Output

Complete results include:

- `observed_delta` using the configured aggregation over all pairs
- empirical `p05` / `p50` / `p95` of the resampled candidate-baseline delta distribution
- raw signed delta retained
- optional `favors_candidate` interpretation from `MetricDefinition.direction`

These percentiles are empirical resampling summaries, not statistical significance or confidence intervals.

## Fingerprinting

The stability request fingerprint covers baseline/candidate observation payloads, metric identity, metric-contract fingerprint, and the full config (including aggregation and seed).

## Legacy note

`arvp.evaluation.resample_stability` remains as bootstrap compatibility only. New code must use `arvp.stability.paired_resample_stability`.
