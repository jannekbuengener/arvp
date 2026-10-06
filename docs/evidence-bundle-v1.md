# ARVP Evidence Bundle v1

This document freezes the portable Evidence Bundle introduced by Issue #11.

## Contract version

- `EVIDENCE_BUNDLE_CONTRACT_VERSION = "arvp.evidence.v1"`

## Role

The Evidence Bundle JSON is the portable source of truth for a completed
evaluation decision. Future SQLite/Metabase projections are disposable and must
be rebuildable from these bundles.

A bundle explains:

- which suite/content/partition/candidate identities were evaluated;
- which run provenance identity produced the measurements;
- metric observations and candidate-vs-baseline comparisons;
- gate policy identity plus PASS/FAIL/HOLD decision;
- optional paired stability summaries;
- structured failure/blocking evidence;
- a semantic evidence fingerprint.

## Fingerprint semantics

`evidence_fingerprint` hashes only decision-relevant semantic fields.

Excluded from the semantic fingerprint:

- `generated_at` (volatile presentation/transport timestamp)
- `evidence_fingerprint` (never hashed into itself)
- `artifact_hash` (separate byte-integrity digest)

Changing candidate, metric, comparison, gate, stability, failure, suite, or
provenance semantics must change the fingerprint. Changing only `generated_at`
must not.

`artifact_hash` covers the portable artifact payload excluding itself. It is
optional until write time; `write_evidence_bundle` seals it.

## JSON schemas

Packaged assets under `arvp.schemas`:

- `evidence_bundle_v1.json`
- `evaluation_suite_v1.json`
- `metric_observation_v1.json`

Runtime remains dependency-light. JSON Schema validation uses the optional
`jsonschema` package in development/tests.

Compatibility rule: unknown top-level Evidence Bundle fields are rejected.
Schema documents set `additionalProperties: false` for the frozen public
shapes.

## Artifact writing

`write_evidence_bundle(path, bundle)` serializes canonical JSON and writes via
a temporary sibling file then `os.replace`, so a crash cannot leave a partially
written canonical bundle masquerading as valid.

Callers choose the output path. Bundles must not embed repository-local or
absolute source paths; portable metadata still runs through the shared danger-key
validation from Issue #5.

Written JSON uses Canonical v2, including `$arvp` decimal extensions.
`read_evidence_bundle` / `EvidenceBundle.from_dict` revive those extensions back
to `Decimal` before fingerprint checks so semantic identity survives round-trip.

## Non-goals

- no SQLite persistence
- no dashboard
- no remote artifact service
- no binary/raw dataset embedding
- no automatic production promotion
