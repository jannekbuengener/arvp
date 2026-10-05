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

The package currently exposes five focused modules:

- `arvp.canonical` — canonical JSON and SHA-256 hashing
- `arvp.datasets` — safe request and content identities
- `arvp.provenance` — deterministic run identities and append-only JSONL records
- `arvp.scenarios` — explicit, fail-closed scenario orchestration
- `arvp.evaluation` — walk-forward plans, resampling, comparison, and gates

## Development

Requires Python 3.11 or later.

```powershell
python -m pytest
```

For extraction lineage, scope boundaries, and deferred work, see
[`docs/EXTRACTION_FROM_CLAIRE.md`](docs/EXTRACTION_FROM_CLAIRE.md) and
[`docs/GENERALIZATION_ROADMAP.md`](docs/GENERALIZATION_ROADMAP.md).
