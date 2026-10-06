# ARVP Comparison and Gate Contracts v1

This document freezes the v0.2 baseline-comparison and PASS/FAIL/HOLD surface introduced by Issue #8.

## Contract versions

- `METRIC_COMPARISON_CONTRACT_VERSION = "arvp.metric-comparison.v1"`
- `GATE_POLICY_CONTRACT_VERSION = "arvp.gate-policy.v1"`
- `GATE_DECISION_CONTRACT_VERSION = "arvp.gate-decision.v1"`

## Comparison authority

`compare_observation_scope(...)` consumes baseline and candidate `Observation` sequences plus the expected `MetricContract`.

A metric ID string alone never proves comparability. Numeric deltas require compatible metric-contract identity and matching partition identity. Each side must contain observations from exactly one candidate, one partition, and one metric contract; duplicate `(metric_id, observation_id)` keys are rejected.

Comparison output is deterministic by `(metric_id, observation_id)` and preserves the raw candidate/baseline statuses and values even when the evidence is incomplete.

`ComparisonStatus` values are `complete`, `incomplete`, and `not_applicable`.

## Delta semantics

For compatible numeric values:

- `absolute_delta = candidate - baseline`
- when baseline is non-zero: `relative_delta = absolute_delta / abs(baseline)`
- when baseline is zero: relative delta is undefined and `relative_delta_reason = "baseline_zero"`

No infinity, fake zero percent, or implicit fallback is created.

Direction-aware relative delta keeps the raw delta visible while normalizing interpretation:

- maximize: same sign as `relative_delta`
- minimize: sign inverted
- neutral: undefined

Positive direction-aware change means improvement, negative means regression. Neutral metrics make no automatic better/worse claim.

## Gate criteria

`AbsoluteThresholdCriterion(criterion_id, metric_id, operator, threshold)` supports `gte` and `lte`. It evaluates compatible candidate evidence and does not require a baseline merely to apply an absolute threshold.

`RelativeBaselineCriterion(criterion_id, metric_id, mode, threshold)` supports:

- `no_regression_beyond`
- `minimum_improvement`

Relative thresholds are non-negative fractions; `0.05` means 5%. Relative criteria are invalid for neutral metrics.

## Required evidence

`MetricDefinition.required` is the single requiredness authority. GatePolicy does not duplicate it.

If evidence needed by a criterion is unavailable:

- required metric -> criterion outcome `hold`
- optional metric -> criterion outcome `not_applicable`

Missing/unknown/incompatible evidence never becomes numeric zero. Optional `not_applicable` evidence does not block PASS.

## GatePolicy

`GatePolicy(policy_id, metric_contract, criteria)` stores the exact metric-contract fingerprint and a deterministic criterion tuple sorted by `criterion_id`.

Policy identity changes when the policy ID, metric-contract fingerprint, criterion target, operator/mode, threshold, criterion ID, or contract version changes.

Unknown metric IDs, duplicate criterion IDs, empty policy criteria, invalid IDs, non-finite thresholds, and relative criteria on neutral metrics fail closed.

## Verdict

`GateVerdict` is exactly `PASS | FAIL | HOLD`.

Criterion outcomes are `pass | fail | hold | not_applicable`.

Verdict precedence is exact:

1. any evaluable `fail` -> `FAIL`
2. otherwise any `hold` -> `HOLD`
3. otherwise -> `PASS`

A measured failure therefore remains FAIL even when unrelated required evidence is missing. Missing evidence cannot erase a proven regression.

Gate evaluation accepts one explicit comparison scope. More than one comparison for a criterion metric is rejected rather than silently aggregated. Issue #10 owns aggregation and paired resampling.

## Legacy boundary

The bootstrap `arvp.evaluation.GateCriterion`, boolean `GateDecision`, `evaluate_gate()`, `CandidateScore`, and `rank_candidates()` remain module-level compatibility APIs. They are not exported from the package root as the v0.2 decision path.

No runtime deprecation warning is emitted in v0.2 Slice #8.

## Successor handoff

- #9 binds `GatePolicy.fingerprint()` into `EvaluationSuite`.
- #10 reuses observation pairing/raw delta semantics and owns explicit aggregation/resampling.
- #11 embeds comparisons, policy, criterion results, and GateDecision into Evidence Bundle v1.
- #14 relies on comparison compatibility to prevent mismatched Sample Brain dataset/partition/metric evidence from becoming numeric deltas.

No global weighted score, automatic promotion, hidden aggregation, domain-specific threshold catalog, or statistical-significance claim is defined here.
