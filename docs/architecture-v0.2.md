# ARVP v0.2 architecture

ARVP is a domain-neutral Python validation/evaluation framework. Consumers own
domain data loading, model/algorithm execution, and promotion decisions. ARVP
owns portable identities, typed metrics, comparison/gates, stability analysis,
and Evidence Bundles.

## Canonical flow

```text
DATASET -> CANDIDATE -> RUN -> METRICS -> COMPARE -> GATE -> EVIDENCE
```

Primary consumer boundary:

```text
consumer domain
  -> portable EvaluationInput (baseline_observations / candidate_observations)
  -> ARVP contracts (suite / metrics / gates / stability / provenance)
  -> Evidence Bundle v1
```

## Public surface (`src/arvp`)

| Module | Role |
|--------|------|
| `canonical` | Canonical JSON + SHA-256 fingerprints |
| `datasets` | Dataset request + content identity (`identify_content`) |
| `identities` | `CandidateSpec`, `EvaluationPartition` |
| `metrics` | `MetricDefinition` / `MetricContract` / `Observation` |
| `gates` | Baseline comparison + PASS/FAIL/HOLD |
| `suite` | Versioned `EvaluationSuite` |
| `stability` | Explicit aggregation + paired deterministic resampling |
| `provenance` | `RunProvenance` v2 + optional JSONL registry |
| `bundle` | Evidence Bundle v1 (semantic fingerprint + atomic writer) |
| `schemas` | Packaged JSON Schema assets |
| `adapters` | Artifact-first `EvaluationInput` + in-process Protocol |
| `scenarios` | Scenario Harness v2 (decision-relevant identity) |
| `evaluation` | Legacy window helpers (compat; prefer v0.2 modules) |
| `evidence` | Structured `FailureEvidence` + portable metadata safety |

## Reference proofs (outside core)

- `examples/integer_threshold_classification` — synthetic non-audio/non-trading E2E (#13)
- `examples/sample_brain_fsld_key_tempo` — Sample Brain FSLD key/tempo artifact adapter (#14)

These packages must not be imported by `src/arvp`. Core must not gain
domain-specific required fields to support them.

## Non-goals (v0.2)

No workflow engine, plugin discovery, remote execution, DB-as-source-of-truth,
dashboard, package-registry publication, or automatic tuning/promotion.
