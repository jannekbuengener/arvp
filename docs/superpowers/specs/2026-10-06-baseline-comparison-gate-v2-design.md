# ARVP v0.2 Baseline Comparison + Gate v2 Design

Issue: #8 — Baseline comparison engine and PASS/FAIL/HOLD Gate v2

## Intent

Replace the bootstrap's boolean gate and one-number ranking path with explicit, portable candidate-vs-baseline evidence plus deterministic PASS / FAIL / HOLD decisions.

The design consumes the contracts already frozen by #6/#7. It does not recreate candidate, partition, metric, or observation identity. It must remain usable by #9 EvaluationSuite, #10 paired stability, #11 Evidence Bundle, and #14 Sample Brain FSLD compatibility checks.

## Selected architecture

Add a new `arvp.gates` module. Keep the existing bootstrap helpers in `arvp.evaluation` only as documented legacy compatibility surface.

`arvp.gates` owns four things:

1. portable candidate-vs-baseline comparison records;
2. deterministic observation-scope comparison;
3. versioned/fingerprinted gate policy contracts;
4. deterministic criterion results and PASS / FAIL / HOLD decisions.

The module remains pure and dependency-light. It performs no persistence, mutation, aggregation, resampling, promotion, or domain-specific scoring.

## Why observation-first

`MetricValue` alone does not prove dataset/partition/scope compatibility. `Observation` already binds the metric value to candidate fingerprint, partition ID/fingerprint, metric-contract fingerprint, and consumer-supplied observation ID.

Therefore the comparison engine consumes `Observation` sets plus the expected `MetricContract`. A matching metric ID string alone is never enough to calculate a numeric delta.

A comparison call represents one explicit observation scope. Each side must contain observations from one candidate and one partition only. Duplicate `(metric_id, observation_id)` entries on either side are rejected rather than silently merged.

## Public contract versions

- `METRIC_COMPARISON_CONTRACT_VERSION = "arvp.metric-comparison.v1"`
- `GATE_POLICY_CONTRACT_VERSION = "arvp.gate-policy.v1"`
- `GATE_DECISION_CONTRACT_VERSION = "arvp.gate-decision.v1"`

All portable objects use Canonical v2 hashing. Contract versions enter their fingerprints.

## MetricComparison

`MetricComparison` is immutable and produced by the comparison engine rather than freely constructed.

It records at least:

- metric ID;
- metric direction, unit, and required flag from the expected `MetricContract`;
- observation ID;
- expected metric-contract fingerprint;
- baseline and candidate candidate-fingerprints;
- baseline and candidate partition IDs/fingerprints;
- baseline and candidate metric-contract fingerprints;
- baseline and candidate value statuses;
- baseline and candidate raw values;
- raw signed absolute delta (`candidate - baseline`) when defined;
- raw signed relative delta when defined;
- direction-aware relative delta when defined;
- whether the raw delta favors the candidate when direction permits interpretation;
- comparison status;
- deterministic `reasons` tuple when comparison is incomplete/not-applicable; relative-delta unavailability is reported separately.

`ComparisonStatus = Literal["complete", "incomplete", "not_applicable"]`.

## Delta semantics

For comparable numeric values:

`absolute_delta = candidate - baseline`

If `baseline != 0`:

`relative_delta = absolute_delta / abs(baseline)`

If `baseline == 0`, relative delta is undefined (`None`) and an explicit `baseline_zero` reason is exposed. No infinity, fake zero percent, or division-by-zero fallback is allowed.

Direction-aware relative change is:

- maximize: `relative_delta`;
- minimize: `-relative_delta`;
- neutral: undefined.

Thus a positive direction-aware change always means improvement and a negative value always means regression. Raw signed deltas remain visible regardless of interpretation.

## Comparison compatibility and status

The engine matches baseline/candidate observations by `(metric_id, observation_id)` and then validates compatibility before computing deltas.

Compatibility requires:

- both observations belong to one declared side candidate;
- metric ID is defined by the expected `MetricContract`;
- both metric values bind the expected metric-contract fingerprint;
- partition IDs and partition fingerprints match;
- observation IDs match;
- the expected metric definition supplies the unit/direction/required semantics.

A differing partition or metric-contract fingerprint produces explicit `incomplete` evidence. No numeric delta is produced from incompatible evidence.

Status rules:

- `complete`: both sides are compatible and both values are `measured` or `derived`;
- `not_applicable`: either side explicitly reports `not_applicable`;
- `incomplete`: required pairing/compatibility is absent, or either side is `unknown`.

Missing baseline/candidate observations are represented as `incomplete` comparison records where the existing side's raw evidence is still preserved.

The comparison result separately exposes side compatibility so an absolute candidate-only criterion can still be evaluated when the only missing evidence is the baseline. Relative criteria always require a complete comparable pair.

## Gate criteria

Gate policy uses two explicit criterion types. No metric-name heuristics exist.

### AbsoluteThresholdCriterion

Fields:

- `criterion_id`;
- `metric_id`;
- `operator`: `gte | lte`;
- finite Decimal `threshold`.

It evaluates the compatible candidate value only. Baseline evidence is not required for a pure absolute threshold.

### RelativeBaselineCriterion

Fields:

- `criterion_id`;
- `metric_id`;
- `mode`: `no_regression_beyond | minimum_improvement`;
- non-negative finite Decimal `threshold` interpreted as a fraction.

It consumes the direction-aware relative delta. Thresholds are fractions (`0.05` means 5%).

- `no_regression_beyond(t)` passes when directional relative delta is `>= -t`;
- `minimum_improvement(t)` passes when directional relative delta is `>= t`.

Relative criteria are invalid for `neutral` metrics because neutral direction intentionally carries no better/worse interpretation. Callers must use an absolute threshold for neutral metrics.

## Required evidence

`MetricDefinition.required` remains the single authority for whether missing/unavailable evidence blocks the decision. Gate policy does not duplicate or override metric requiredness.

For a required metric:

- unknown/missing/incompatible evidence needed by a criterion -> criterion `HOLD`;
- `not_applicable` evidence needed by a criterion -> criterion `HOLD`;
- relative criterion with baseline zero -> criterion `HOLD`.

For an optional metric, the same unavailable conditions produce criterion `NOT_APPLICABLE` and do not block PASS.

This prevents a second, contradictory requiredness contract from emerging inside GatePolicy.

## GatePolicy

`GatePolicy` contains:

- `policy_id` using the same lowercase stable-identifier style as metric IDs;
- exact `metric_contract_fingerprint`;
- non-empty tuple of unique criteria;
- contract version.

At construction it validates that every criterion references a known metric. Relative criteria against neutral metrics are rejected. Criteria are normalized by `criterion_id`, making policy identity independent of caller input order.

The policy fingerprint covers the policy ID, metric-contract fingerprint, complete normalized criterion definitions, and contract version. Changing threshold, operator, mode, metric target, criterion ID, or bound metric contract changes the fingerprint.

## Gate decision

`GateVerdict = Literal["PASS", "FAIL", "HOLD"]`.

Each criterion emits a portable `CriterionResult` with:

- criterion ID/type;
- metric ID;
- outcome: `pass | fail | hold | not_applicable`;
- actual value used when evaluable;
- threshold/operator/mode semantics;
- comparison fingerprint/reference where present;
- explicit reason when not evaluable.

Exact verdict precedence:

1. if any evaluable criterion is `fail` -> `FAIL`;
2. otherwise if any criterion result is `hold` -> `HOLD`;
3. otherwise -> `PASS`.

A proven measured failure therefore remains FAIL even if some other required evidence is missing. Missing evidence cannot erase a measured regression, and missing evidence can never become a numeric zero.

`GateDecision` binds the gate-policy fingerprint, metric-contract fingerprint, ordered criterion results, verdict, and contract version. It is fingerprintable and contains no promotion/mutation behavior.

## Evaluation scope and no hidden aggregation

Gate evaluation accepts one explicit comparison scope. For any metric referenced by a criterion there must be at most one `MetricComparison` in the supplied scope.

If multiple comparison records for the same metric are supplied, evaluation rejects the input as ambiguous rather than silently aggregating or choosing one. Callers may use an explicitly aggregated observation such as an `aggregate` observation ID. Issue #10 owns mean/sum aggregation and paired resampling.

This preserves the v0.2 rule that core decision logic never invents hidden aggregation.

## Legacy compatibility

The current `arvp.evaluation.GateCriterion`, boolean `GateDecision`, `evaluate_gate()`, `CandidateScore`, and `rank_candidates()` remain temporarily importable from `arvp.evaluation` for bootstrap compatibility.

They are documented as legacy/deprecated and are not exported as the v0.2 root API. The new `arvp.gates.GateDecision` is the canonical v0.2 decision contract.

No runtime deprecation warning is emitted in #8 to avoid introducing warning-driven behavior changes into existing callers. Successor slices must use the new gate API.

## Error handling

Malformed contract construction raises a gate-domain error (`GateContractError`). Examples include invalid IDs, non-finite thresholds, duplicate criteria, unknown metric IDs, relative criteria on neutral metrics, and wrong contract versions.

Comparison input that is structurally ambiguous (mixed candidates/partitions within one side, duplicate observation keys, wrong object types) raises `GateContractError`.

Semantically unavailable but structurally valid evaluation evidence does not raise merely because it cannot prove a decision. It becomes explicit incomplete/not-applicable comparison evidence and ultimately HOLD/NOT_APPLICABLE according to requiredness.

This is the fail-closed boundary: malformed inputs are errors; valid-but-insufficient evidence is portable HOLD-compatible evidence.

## Deterministic ordering

- comparison records: `(metric_id, observation_id)`;
- gate policy criteria: `criterion_id`;
- criterion results: `criterion_id`.

Input mapping/sequence order must not affect fingerprints or verdict output.

## Public root surface

Export the successor-facing v0.2 contracts from `arvp.__init__`:

- comparison/gate contract-version constants;
- `ComparisonStatus`, `GateVerdict`;
- `MetricComparison`;
- `AbsoluteThresholdCriterion`;
- `RelativeBaselineCriterion`;
- `GatePolicy`;
- `CriterionResult`;
- new `GateDecision`;
- comparison and gate evaluation functions;
- `GateContractError`.

Do not root-export the legacy `arvp.evaluation` gate/ranking types.

## Golden evidence

Freeze repository-owned golden cases for:

- maximize improvement;
- minimize improvement;
- neutral raw delta with no direction inference;
- negative baseline relative delta using `abs(baseline)`;
- zero baseline with undefined relative delta;
- missing required candidate -> HOLD;
- unknown required candidate -> HOLD;
- optional not-applicable -> non-blocking;
- metric-contract mismatch -> HOLD-compatible incomplete comparison;
- partition mismatch -> HOLD-compatible incomplete comparison;
- measured absolute/relative regression -> FAIL;
- all criteria satisfied -> PASS;
- FAIL precedence over simultaneous HOLD;
- deterministic order independent of input order.

Golden expected fingerprints must be independently authored with stdlib JSON/hashlib using the Canonical-v2 domain separator, not generated by calling production `canonical_hash()` as the oracle.

Cross-platform platform smoke must exercise the new golden comparisons/policies/decisions from source and installed wheel.

## Test strategy

TDD order:

1. comparison compatibility and delta semantics;
2. criterion/policy validation and fingerprints;
3. PASS/FAIL/HOLD evaluation precedence;
4. legacy-boundary/root-export tests;
5. independent golden vectors and platform smoke;
6. full regression + lint + formatting + mypy + build + Twine + fresh-wheel smoke.

Tests must explicitly prove that missing evidence never becomes zero, relative division by zero never occurs, policy/input ordering is deterministic, and no global scalar score is introduced.

## Successor contracts

#9 receives the stable `GatePolicy.fingerprint()` for `EvaluationSuite` identity.

#10 reuses raw comparison semantics and observation pairing; it owns aggregation/resampling and must keep raw signed deltas.

#11 embeds `MetricComparison`, `GatePolicy`, criterion results, and `GateDecision` as portable Evidence Bundle evidence.

#14 relies on comparison compatibility to prevent mismatched dataset/partition/metric-contract evidence from producing numeric FSLD deltas.

## Non-goals

- no EvaluationSuite (#9);
- no aggregation or resampling (#10);
- no Evidence Bundle/schema work (#11);
- no Scenario Harness v2 (#12);
- no Sample Brain adapter (#14);
- no auto-promotion or mutation;
- no weighted/global score;
- no statistical-significance claim;
- no domain-specific thresholds.

## Acceptance

The same valid inputs always produce the same comparison fingerprints, criterion results, and verdict. Required missing/incompatible evidence yields HOLD unless a measured failure already proves FAIL. Optional unavailable evidence does not block. Relative gates work for positive and negative baselines, never divide by zero, and preserve raw deltas. The new policy fingerprint changes whenever decision semantics change.
