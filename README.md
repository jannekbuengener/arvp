# ARVP

ARVP is a domain-neutral Python framework for deterministic validation,
evaluation, and experiments. Version **0.2.0** freezes the portable contract
surface: identities, typed metrics, baseline comparison, PASS/FAIL/HOLD gates,
paired stability, Evidence Bundle v1, and an artifact-first consumer boundary.

The core has no trading, live-execution, exchange, database, Docker, credential,
market-data, audio, or Sample Brain runtime dependency. Domain adapters live
outside `src/arvp`.

## Model

```text
DATASET -> CANDIDATE -> RUN -> METRICS -> COMPARE -> GATE -> EVIDENCE
```

Consumer boundary:

```text
portable EvaluationInput (baseline_observations / candidate_observations)
  -> ARVP evaluation
  -> Evidence Bundle v1
```

## Public modules

- `arvp.canonical` — canonical JSON and SHA-256 hashing
- `arvp.datasets` — safe request and ordered/unordered content identities
- `arvp.identities` — domain-neutral candidate and evaluation-partition identities
- `arvp.metrics` / `arvp.gates` — typed metrics, baseline comparison, PASS/FAIL/HOLD
- `arvp.suite` — versioned `EvaluationSuite`
- `arvp.stability` — explicit aggregation and paired deterministic resampling
- `arvp.provenance` — RunProvenance v2 and JSONL registry integrity
- `arvp.bundle` — Evidence Bundle v1 with semantic fingerprint and atomic writer
- `arvp.schemas` — packaged JSON Schema assets
- `arvp.adapters` — EvaluationInput envelope and in-process Protocol
- `arvp.scenarios` — Scenario Harness v2
- `arvp.evaluation` — legacy window helpers (prefer v0.2 modules above)
- `arvp.evidence` — structured failure evidence and portable metadata safety

## Reference proofs (outside core)

- `examples/integer_threshold_classification` — synthetic second-domain E2E (#13)
- `examples/sample_brain_fsld_key_tempo` — Sample Brain FSLD key/tempo (#14)

## Development

Requires Python 3.11 or later.

```powershell
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m mypy src/arvp
```

## Documentation

- [`docs/architecture-v0.2.md`](docs/architecture-v0.2.md)
- [`docs/compatibility-policy-v0.2.md`](docs/compatibility-policy-v0.2.md)
- [`docs/CHANGELOG-v0.2.md`](docs/CHANGELOG-v0.2.md) / [`CHANGELOG.md`](CHANGELOG.md)
- [`docs/governance-ruleset-proposal-v0.2.md`](docs/governance-ruleset-proposal-v0.2.md)
  (proposal only; application requires Owner GO)
- Contract docs: canonical, identity, metric, gate, provenance, stability,
  evidence-bundle, adapter/scenario harness

## Release status

Package version: **0.2.0**. Optional git tag `v0.2.0` and GitHub `main` ruleset
application remain Owner-GO gated and are not implied by this package bump.
