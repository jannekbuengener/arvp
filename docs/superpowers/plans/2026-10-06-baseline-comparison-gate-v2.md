# Baseline Comparison + Gate v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement deterministic candidate-vs-baseline comparison and versioned PASS/FAIL/HOLD gating for ARVP v0.2 without hidden aggregation or global scoring.

**Architecture:** Add a focused `arvp.gates` module that consumes #6/#7 `Observation` and `MetricContract` evidence, emits portable `MetricComparison` records, then evaluates a versioned `GatePolicy` into fingerprintable criterion results and a `GateDecision`. Existing boolean gate/ranking helpers remain legacy-only in `arvp.evaluation`; #9–#11 consume the new root-exported contracts.

**Tech Stack:** Python 3.11+, dataclasses, `Decimal`, Canonical v2 hashing, pytest, Ruff, mypy, stdlib JSON/hashlib golden oracle.

**Spec:** `docs/superpowers/specs/2026-10-06-baseline-comparison-gate-v2-design.md`

## Global Constraints

- No new runtime dependency.
- Comparison identity must bind existing candidate/partition/metric/observation evidence; do not create parallel identity models.
- `absolute_delta = candidate - baseline` whenever both compatible numeric values exist.
- `relative_delta = absolute_delta / abs(baseline)` when baseline is non-zero; baseline zero leaves relative delta undefined.
- Missing/unknown/incompatible required evidence yields HOLD unless another evaluable criterion already proves FAIL.
- Optional unavailable evidence yields NOT_APPLICABLE and does not block PASS.
- No hidden aggregation, weighted/global score, statistical-significance claim, or auto-promotion.
- Comparison, policy, criterion-result, and decision ordering must be deterministic and input-order independent.
- Legacy `arvp.evaluation` gate/ranking helpers remain importable but are not the v0.2 root API.

## Review Focus

1. Mixed/malformed observation scopes: reject mixed candidates, mixed partitions within one side, duplicate `(metric_id, observation_id)`, and mixed side metric-contract fingerprints rather than selecting one silently.
2. Incompatible but structurally valid evidence: preserve raw side values/statuses but never calculate deltas across partition/metric-contract mismatches.
3. Baseline zero and negative baseline: zero never divides; negative baseline uses `abs(baseline)` and preserves raw signed delta.
4. Gate ambiguity: multiple comparisons for one criterion metric must fail closed rather than aggregate or choose arbitrarily.
5. Verdict precedence: measured FAIL wins over simultaneous HOLD; otherwise HOLD wins over PASS; optional unavailable evidence remains NOT_APPLICABLE.

---

### Task 1: Portable comparison contracts and compatibility engine

**Files:**
- Create: `src/arvp/gates.py`
- Create: `tests/test_gates.py`

**Interfaces:**
- Consumes: `MetricContract`, `MetricDefinition`, `Observation`, `MetricValue` from `arvp.metrics`.
- Produces:
  - `METRIC_COMPARISON_CONTRACT_VERSION = "arvp.metric-comparison.v1"`
  - `ComparisonStatus = Literal["complete", "incomplete", "not_applicable"]`
  - `ComparisonReason = Literal["missing_baseline", "missing_candidate", "metric_contract_mismatch", "partition_mismatch", "unknown_value", "not_applicable"]`
  - `RelativeDeltaReason = Literal["baseline_zero"]`
  - `DirectionResult = Literal["improved", "regressed", "equal"]`
  - `GateContractError(ValueError)`
  - immutable `MetricComparison` with fields `metric_id`, `direction`, `unit`, `required`, `observation_id`, `metric_contract_fingerprint`, `baseline_candidate_fingerprint`, `candidate_fingerprint`, `baseline_partition_id`, `candidate_partition_id`, `baseline_partition_fingerprint`, `candidate_partition_fingerprint`, `baseline_metric_contract_fingerprint`, `candidate_metric_contract_fingerprint`, `baseline_status`, `candidate_status`, `baseline_value`, `candidate_value`, `baseline_compatible`, `candidate_compatible`, `absolute_delta`, `relative_delta`, `relative_delta_reason`, `directional_relative_delta`, `direction_result`, `status`, `reasons`, `contract_version`; plus `to_dict()` and `fingerprint()`
  - `compare_observation_scope(*, baseline: Sequence[Observation], candidate: Sequence[Observation], metric_contract: MetricContract) -> tuple[MetricComparison, ...]`

- [ ] **Step 1: Write RED comparison-contract tests**

Add focused tests for complete maximize/minimize/neutral comparisons, negative baseline relative delta, baseline zero, unknown/not-applicable statuses, missing side, partition mismatch, metric-contract mismatch, deterministic output order, and malformed/mixed side scopes.

Key assertions:

```python
assert comparison.absolute_delta == Decimal("10")
assert comparison.relative_delta == Decimal("0.1")
assert comparison.directional_relative_delta == Decimal("0.1")
assert comparison.direction_result == "improved"
```

For baseline `Decimal("-100")` and candidate `Decimal("-90")`:

```python
assert comparison.absolute_delta == Decimal("10")
assert comparison.relative_delta == Decimal("0.1")
```

For baseline zero:

```python
assert comparison.relative_delta is None
assert comparison.relative_delta_reason == "baseline_zero"
```

For incompatible partitions/contracts:

```python
assert comparison.status == "incomplete"
assert comparison.absolute_delta is None
assert "partition_mismatch" in comparison.reasons
```

- [ ] **Step 2: Run comparison tests and verify RED**

Run: `py -3.12 -m pytest tests/test_gates.py -q -k comparison`
Expected: collection/import failures because `arvp.gates`/comparison contracts do not exist.

- [ ] **Step 3: Implement comparison contracts and `compare_observation_scope`**

Use exact built-in type validation consistent with current contracts. Normalize one side at a time; require one candidate fingerprint, one partition identity, and one side metric-contract fingerprint, while allowing baseline and candidate sides to disagree with each other so the disagreement can become explicit incomplete evidence.

Match records by `(metric_id, observation_id)`. Preserve missing-side evidence with `None` fields. Sort final records by `(metric_id, observation_id)`.

- [ ] **Step 4: Run comparison tests and verify GREEN**

Run: `py -3.12 -m pytest tests/test_gates.py -q -k comparison`
Expected: PASS.

- [ ] **Step 5: Commit Task 1**

```bash
git add src/arvp/gates.py tests/test_gates.py
git commit -m "feat(gates): add compatible baseline comparison evidence"
```

### Task 2: Versioned gate criteria and policy identity

**Files:**
- Modify: `src/arvp/gates.py`
- Modify: `tests/test_gates.py`

**Interfaces:**
- Consumes: Task 1 `GateContractError`; `MetricContract` direction/required semantics.
- Produces:
  - `GATE_POLICY_CONTRACT_VERSION = "arvp.gate-policy.v1"`
  - `GateOperator = Literal["gte", "lte"]`
  - `RelativeMode = Literal["no_regression_beyond", "minimum_improvement"]`
  - frozen `AbsoluteThresholdCriterion(criterion_id, metric_id, operator, threshold)`
  - frozen `RelativeBaselineCriterion(criterion_id, metric_id, mode, threshold)`
  - `GateCriterion = AbsoluteThresholdCriterion | RelativeBaselineCriterion`
  - custom-init frozen `GatePolicy(policy_id: str, metric_contract: MetricContract, criteria: Sequence[GateCriterion])`
  - `GatePolicy.to_dict()` and `.fingerprint()`

- [ ] **Step 1: Write RED policy tests**

Test stable ID validation, finite numeric thresholds, non-negative relative thresholds, duplicate criterion IDs, unknown metric IDs, relative criteria on neutral metrics, empty policy criteria, foreign/wrong contract versions, and input-order-independent policy fingerprints.

Key assertions:

```python
assert first.fingerprint() == second.fingerprint()
assert [c.criterion_id for c in first.criteria] == ["quality", "runtime"]
```

- [ ] **Step 2: Run policy tests and verify RED**

Run: `py -3.12 -m pytest tests/test_gates.py -q -k policy`
Expected: FAIL because policy contracts are absent.

- [ ] **Step 3: Implement criterion and policy contracts**

Use `^[a-z][a-z0-9_.-]{0,63}$` for `criterion_id` and `policy_id`. Threshold inputs accept exact `int`, `float`, or `Decimal`, reject bool/string/non-finite, and normalize to finite `Decimal`. Relative thresholds are fractions and must be `>= 0`.

`GatePolicy` stores only the exact metric-contract fingerprint, normalized criteria, policy ID, and contract version; the `MetricContract` argument is used for construction-time validation and is not embedded as a runtime object in portable output.

- [ ] **Step 4: Run policy tests and verify GREEN**

Run: `py -3.12 -m pytest tests/test_gates.py -q -k policy`
Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```bash
git add src/arvp/gates.py tests/test_gates.py
git commit -m "feat(gates): add fingerprinted gate policy"
```

### Task 3: Criterion results and PASS / FAIL / HOLD evaluation

**Files:**
- Modify: `src/arvp/gates.py`
- Modify: `tests/test_gates.py`

**Interfaces:**
- Consumes: Task 1 `MetricComparison`; Task 2 `GatePolicy` and criterion types.
- Produces:
  - `GATE_DECISION_CONTRACT_VERSION = "arvp.gate-decision.v1"`
  - `GateVerdict = Literal["PASS", "FAIL", "HOLD"]`
  - `CriterionOutcome = Literal["pass", "fail", "hold", "not_applicable"]`
  - frozen internal-construction `CriterionResult` with fields `criterion`, `outcome`, `actual`, `comparison_fingerprint`, `reason`; plus `to_dict()` and `fingerprint()`
  - frozen internal-construction `GateDecision` with fields `policy_fingerprint`, `metric_contract_fingerprint`, `verdict`, `criteria`, `contract_version`; plus `to_dict()` and `fingerprint()`
  - `evaluate_gate(*, policy: GatePolicy, comparisons: Sequence[MetricComparison], metric_contract: MetricContract) -> GateDecision`

- [ ] **Step 1: Write RED verdict tests**

Cover exact threshold boundaries, maximize/minimize relative regression tolerance, minimum improvement, missing required comparison, unknown required value, optional not-applicable evidence, baseline-zero relative criterion, measured regression, all-pass, deterministic criterion order, wrong policy/metric contract binding, ambiguous multiple comparisons per metric, and FAIL-over-HOLD precedence.

Required verdict cases:

```python
assert evaluate_gate(...all_satisfied...).verdict == "PASS"
assert evaluate_gate(...measured_regression...).verdict == "FAIL"
assert evaluate_gate(...required_unknown...).verdict == "HOLD"
```

Simultaneous measured failure + unrelated required missing evidence:

```python
assert decision.verdict == "FAIL"
```

Optional `not_applicable` criterion:

```python
assert result.outcome == "not_applicable"
assert decision.verdict == "PASS"
```

- [ ] **Step 2: Run verdict tests and verify RED**

Run: `py -3.12 -m pytest tests/test_gates.py -q -k 'decision or verdict or criterion_result'`
Expected: FAIL because decision contracts/evaluator are absent.

- [ ] **Step 3: Implement criterion evaluation and verdict precedence**

Absolute criteria may evaluate when candidate evidence is compatible and numeric even if baseline is missing. Relative criteria require a complete comparable pair and non-`None` direction-aware relative delta.

Unavailable evidence uses `MetricDefinition.required` from the supplied `MetricContract`: required -> `hold`; optional -> `not_applicable`.

Verdict reduction is exact: any `fail` -> FAIL; else any `hold` -> HOLD; else PASS.

Reject more than one `MetricComparison` for a criterion metric instead of aggregating. Validate policy and supplied metric-contract fingerprints match before evaluation.

- [ ] **Step 4: Run verdict tests and verify GREEN**

Run: `py -3.12 -m pytest tests/test_gates.py -q -k 'decision or verdict or criterion_result'`
Expected: PASS.

- [ ] **Step 5: Run all gate tests**

Run: `py -3.12 -m pytest tests/test_gates.py -q`
Expected: PASS.

- [ ] **Step 6: Commit Task 3**

```bash
git add src/arvp/gates.py tests/test_gates.py
git commit -m "feat(gates): add deterministic pass fail hold decisions"
```

### Task 4: Public API and explicit legacy boundary

**Files:**
- Modify: `src/arvp/__init__.py`
- Modify: `src/arvp/evaluation.py`
- Modify: `tests/test_evaluation.py`
- Modify: `tests/test_gates.py`
- Create: `docs/gate-contracts-v1.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: Tasks 1–3 final `arvp.gates` API.
- Produces: package-root exports for the v0.2 comparison/gate surface while leaving bootstrap gate/ranking helpers module-local legacy compatibility.

- [ ] **Step 1: Write RED root-export and legacy-boundary tests**

Assert every successor-facing gate contract/function is present in `arvp.__all__`, and assert `CandidateScore`, `rank_candidates`, old `GateCriterion`, old boolean `GateDecision`, and old `evaluate_gate` are not root-exported while remaining importable from `arvp.evaluation`.

- [ ] **Step 2: Run export tests and verify RED**

Run: `py -3.12 -m pytest tests/test_gates.py tests/test_evaluation.py -q -k 'export or legacy'`
Expected: FAIL until root exports/docs are updated.

- [ ] **Step 3: Export new API and mark legacy helpers explicitly**

Add root imports/`__all__` entries for the new constants, types, criteria, policy, comparison/evaluation functions, and error. Do not root-export legacy evaluation gate/ranking classes/functions.

Update legacy docstrings/comments in `src/arvp/evaluation.py`; do not emit runtime deprecation warnings.

- [ ] **Step 4: Document exact v1 contracts**

`docs/gate-contracts-v1.md` must freeze comparison matching/compatibility, delta semantics, relative-baseline rule, requiredness authority, criterion semantics, verdict precedence, deterministic ordering, and successor handoffs. README adds `arvp.gates` and labels `arvp.evaluation` gate/ranking helpers legacy.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run: `py -3.12 -m pytest tests/test_gates.py tests/test_evaluation.py -q`
Expected: PASS.

- [ ] **Step 6: Commit Task 4**

```bash
git add src/arvp/__init__.py src/arvp/evaluation.py tests/test_evaluation.py tests/test_gates.py docs/gate-contracts-v1.md README.md
git commit -m "docs(gates): expose v2 gate surface and legacy boundary"
```

### Task 5: Golden verdict evidence, platform smoke, and delivery gates

**Files:**
- Create: `tests/fixtures/gate_contracts_v1_golden.json`
- Create: `tests/test_gate_goldens.py`
- Modify: `tools/platform_smoke.py`

**Interfaces:**
- Consumes: final public Task 1–4 contracts.
- Produces: frozen cross-platform comparison/policy/decision evidence for #9–#11 consumers.

- [ ] **Step 1: Write RED golden/platform tests**

`tests/test_gate_goldens.py` reconstructs frozen comparison/policy/decision cases and asserts both canonical JSON and fingerprints. It must include PASS, FAIL, HOLD, negative baseline, zero baseline, optional N/A, contract mismatch, partition mismatch, and FAIL-over-HOLD vectors.

Add a platform-smoke test that imports and runs `probe_gate_contracts()`.

- [ ] **Step 2: Run golden tests and verify RED**

Run: `py -3.12 -m pytest tests/test_gate_goldens.py -q`
Expected: FAIL because fixture/probe are missing.

- [ ] **Step 3: Author golden fixture with an independent oracle**

Generate expected canonical JSON/fingerprints with a one-off stdlib-only authoring script using `json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=False)` and SHA-256 over `b"arvp.canonical.v2\x00" + canonical_bytes`. Do not call production `canonical_hash()` to author expected hashes.

Commit only the frozen fixture unless a reusable checked oracle is genuinely required by the tests.

- [ ] **Step 4: Extend `tools/platform_smoke.py`**

Add `probe_gate_contracts()` that reconstructs the fixture through installed public APIs and verifies canonical JSON/fingerprints. Call it from `main()` alongside canonical/identity/metric probes.

- [ ] **Step 5: Run golden/platform tests and verify GREEN**

Run: `py -3.12 -m pytest tests/test_gate_goldens.py -q`
Expected: PASS.

- [ ] **Step 6: Run the full fresh source gate chain**

Run in order:

```powershell
py -3.12 -m pytest -q
py -3.12 -m ruff check .
py -3.12 -m ruff format --check .
py -3.12 -m mypy src\arvp
git diff --check
```

Expected: all PASS, zero failures.

- [ ] **Step 7: Build/package/fresh-wheel smoke**

Build wheel + sdist into a fresh temp directory, run `twine check`, execute source-tree platform smoke with explicit worktree source path, install the wheel into a fresh venv outside the repo, prove `arvp.__file__` resolves from venv `site-packages`, run installed-wheel platform smoke, and run `pip check`.

Expected: all PASS. The existing setuptools table-form `project.license` deprecation warning may remain unchanged/out-of-scope.

- [ ] **Step 8: Commit Task 5**

```bash
git add tests/fixtures/gate_contracts_v1_golden.json tests/test_gate_goldens.py tools/platform_smoke.py
git commit -m "test(gates): freeze comparison and verdict goldens"
```

- [ ] **Step 9: Final branch review and PR packaging**

Verify `origin/main` is still the intended base, inspect `git diff origin/main...HEAD`, ensure no private paths/data/build artifacts are tracked, push `feat/8-baseline-gates`, and open a PR with `Closes #8` plus exact public types, HOLD/FAIL precedence, delta semantics, legacy `CandidateScore` status, local validation, and successor handoff.

- [ ] **Step 10: CI/review gate**

Wait for final-head CI. Inspect reviews/threads. Fix Critical/Important findings within #8 scope and re-run impacted gates. Stop at READY_FOR_MERGE unless explicit merge authorization is given.
