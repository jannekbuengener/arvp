# ARVP

ARVP is a domain-independent Python framework for deterministic validation,
evaluation, and experiments. Its initial core was extracted from reusable ARVP
patterns in [Claire de Binare](https://github.com/jannekbuengener/Claire_de_Binare).

This repository is deliberately a bootstrap, not a completed generalization.
It establishes a small, runnable core for deterministic serialization, dataset
identity, provenance, scenario execution, evaluation splits, stability analysis,
candidate comparison, and explicit gates.

The core has no trading, live-execution, exchange, database, Docker, credential,
or market-data dependency. It does not contain strategy logic or proprietary
datasets.

## Model

```text
DATASET -> CANDIDATE -> RUN -> METRICS -> COMPARE -> GATE -> EVIDENCE
```

The package currently exposes focused modules:

- `arvp.canonical` — canonical JSON and SHA-256 hashing
- `arvp.datasets` — safe request and explicit ordered/unordered content identities
- `arvp.identities` — domain-neutral candidate and evaluation-partition identities
- `arvp.metrics` / `arvp.gates` — typed metrics, baseline comparison, PASS/FAIL/HOLD
- `arvp.suite` — versioned `EvaluationSuite` binding content, partitions, metrics, gates
- `arvp.stability` — explicit mean/sum aggregation and paired deterministic resampling
- `arvp.provenance` — RunProvenance v2 and single-writer JSONL registry integrity
- `arvp.bundle` — versioned Evidence Bundle v1 with semantic fingerprint and atomic writer
- `arvp.schemas` — packaged JSON Schema assets for portable contracts
- `arvp.adapters` — artifact-first EvaluationInput envelope and in-process producer protocol
- `arvp.scenarios` — Scenario Harness v2 with decision-relevant request/result identity
- `arvp.evaluation` — legacy window execution plus resampling, comparison, and gate helpers

## Development

Requires Python 3.11 or later.

```powershell
python -m pytest
```

For extraction lineage, scope boundaries, and deferred work, see
[`docs/EXTRACTION_FROM_CLAIRE.md`](docs/EXTRACTION_FROM_CLAIRE.md) and
[`docs/GENERALIZATION_ROADMAP.md`](docs/GENERALIZATION_ROADMAP.md),
[`docs/identity-contracts-v1.md`](docs/identity-contracts-v1.md),
[`docs/metric-contracts-v1.md`](docs/metric-contracts-v1.md),
[`docs/gate-contracts-v1.md`](docs/gate-contracts-v1.md),
[`docs/provenance-contracts-v2.md`](docs/provenance-contracts-v2.md),
[`docs/stability-contracts-v1.md`](docs/stability-contracts-v1.md),
[`docs/evidence-bundle-v1.md`](docs/evidence-bundle-v1.md), and
[`docs/adapter-scenario-harness-v2.md`](docs/adapter-scenario-harness-v2.md).
