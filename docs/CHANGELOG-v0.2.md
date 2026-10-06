# Changelog

## 0.2.0 — 2026-10-06

Domain-neutral validation/evaluation framework freeze for the v0.2 contract
surface.

### Added

- Canonical portable values and fingerprint hardening
- Portable failure evidence / structured failure semantics
- Domain-neutral dataset, candidate, and partition identities
- Typed metrics and observation contracts
- Baseline comparison with PASS/FAIL/HOLD Gate v2
- EvaluationSuite + RunProvenance v2 registry integrity
- Explicit aggregation and paired deterministic stability resampling
- Evidence Bundle v1 + packaged JSON schemas
- Artifact-first EvaluationInput envelope and Scenario Harness v2
- Synthetic integer-threshold second-domain E2E proof
- Sample Brain FSLD key/tempo reference adapter (outside `src/arvp`)
- Reproducible CI (Python 3.11–3.14), packaging, and platform smoke

### Packaging

- Package version set to `0.2.0`
- License metadata migrated off deprecated setuptools table-form field

### Documentation

- Architecture overview (`docs/architecture-v0.2.md`)
- Pre-1.0 compatibility / fingerprint policy
- Proposed (unapplied) `main` ruleset text

### Explicitly deferred

- SQLite / Metabase projection
- Remote artifact store / package registry publication
- Plugin discovery/marketplace
- Streaming / huge-dataset identity
- Harmonic-match evaluation
- Automatic candidate generation / tuning
- Optional `v0.2.0` git tag and GitHub ruleset application (Owner-GO gated)
