# ARVP EvaluationSuite and RunProvenance v2

This document freezes the v0.2 suite-binding and registry-integrity surface introduced by Issue #9.

## Contract versions

- `EVALUATION_SUITE_CONTRACT_VERSION = "arvp.evaluation-suite.v1"`
- `RUN_PROVENANCE_CONTRACT_VERSION = "arvp.run-provenance.v2"`
- `RUN_RECORD_SCHEMA_VERSION = "arvp.run-record.v2"`

## EvaluationSuite

`EvaluationSuite` binds:

- `suite_id`
- dataset/content identity (`DatasetContentIdentity`)
- declared `EvaluationPartition` values (fingerprint-stable, sorted by `partition_id`)
- metric-contract fingerprint
- gate-policy fingerprint
- baseline candidate fingerprint
- suite contract version

The suite fingerprint changes when any decision-relevant binding changes. Partition insertion order does not.

## RunProvenance v2

Provenance binds full semantic identity, not display IDs alone:

- candidate fingerprint
- suite fingerprint
- partition ID + partition fingerprint
- consumer `code_revision`
- optional consumer `configuration`
- `arvp_version` (package/contract identifier)
- contract version `arvp.run-provenance.v2`

Attempt identity is explicit via `run_id(attempt)` / registry records and is **not** part of the provenance fingerprint.

## Run ID / attempt bounds

Display form: `run-<12 hex of provenance fingerprint>-<4 digit attempt>`.

- attempt is an integer in `1..MAX_ATTEMPT` (`MAX_ATTEMPT = 9999`)
- overflow fails closed
- the 12-hex prefix is a display aid only

`JsonlRunRegistry.next_attempt()` selects attempts by the **full** provenance fingerprint so shortened-ID collisions cannot mix attempts.

## Registry lifecycle

Records carry `schema_version = arvp.run-record.v2`. Missing/foreign schema versions fail closed.

Allowed transitions for one `run_id`:

1. first record must be `running`
2. `running` → `completed` or `failed`
3. terminal states reject further appends (including duplicate terminals)
4. duplicate `running` is rejected

Timestamps are canonicalized to UTC `Z` form (`canonicalize_utc`).

Malformed JSONL lines fail closed.

## Source-of-truth boundary

The JSONL registry is a local convenience/history index, not the canonical portable evidence artifact. Evidence Bundle v1 (Issue #11) is the portable output.

## Single-writer limit

v0.2 remains **single-writer**. Concurrent writers to one registry path are unsupported. No cross-platform locking dependency is added merely to claim concurrency support.

## Successor handoff

Issue #11 consumes suite + provenance fingerprints when building Evidence Bundle v1.
