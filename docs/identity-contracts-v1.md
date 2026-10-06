# ARVP Identity Contracts v1

This document freezes the v0.2 domain-neutral identity surface introduced by Issue #6.

## Dataset content identity

`CONTENT_IDENTITY_SCHEMA_VERSION = "arvp.dataset-content.v2"`

`DatasetContentIdentity` fields:
- `schema_version`
- `ordering`: `"ordered" | "unordered"`
- `record_count`: non-negative integer
- `fingerprint`: strict lowercase SHA-256 fingerprint

`identify_content(records, *, fields, ordering)` requires callers to select semantic fields explicitly. ARVP does not coerce or guess domain equivalence.

`ordered` preserves input record order. `unordered` sorts selected records by Canonical-v2 JSON before hashing. Duplicate records are preserved; no deduplication occurs. Empty datasets are valid when the selected field contract is explicit.

The dataset fingerprint preimage includes `schema_version`, `ordering`, the selected field names, and all selected records. Request identity (`DatasetRequest`) remains separate from loaded-content identity.

## Candidate identity

`CANDIDATE_CONTRACT_VERSION = "arvp.candidate.v1"`

`CandidateSpec` fields:
- `candidate_id`
- `implementation_id`
- `revision`
- `configuration`
- `contract_version`

All fields above enter the deterministic candidate fingerprint. Configuration must satisfy the shared portable-evidence boundary and is defensively copied. Mapping insertion order does not affect identity; semantic value/type changes do.

## Evaluation partition identity

`EVALUATION_PARTITION_CONTRACT_VERSION = "arvp.evaluation-partition.v1"`

`EvaluationPartition` fields:
- `partition_id`
- `role`
- `content_identity`: partition-specific `DatasetContentIdentity`
- `contract_version`

Well-known v0.2 roles:
- `development`
- `calibration`
- `validation`
- `test`
- `external_check`

Partition membership is bound by the partition-specific content identity. Changing any selected record changes the partition identity. A role never implies training, mutation, or promotion behavior.

## Portable boundary

Consumers own domain normalization. ARVP will not treat values such as `1`, `1.0`, `"1"`, and `Decimal("1")` as equivalent unless Canonical v2 itself defines them as equivalent.

No candidate/dataset/partition contract requires a local path, filename, database identifier, credential, runtime object, or raw domain payload.

## Legacy evaluation windows

`EvaluationWindow`, `EvaluationPlan`, `WindowResult`, and `run_evaluation_plan()` remain temporarily available from `arvp.evaluation` as bootstrap compatibility APIs. They are not the v0.2 identity architecture and are intentionally not exported from the package root.

Successor slices must use `EvaluationPartition` rather than defining new split/window identity semantics. Scenario Harness v2 owns the later runner migration.

## Successor handoff

Issue #7 must reference partition identity from this contract for per-observation evidence. Issue #9 must compose these dataset, candidate, and partition identities into `EvaluationSuite` and RunProvenance v2.

Golden identity fixtures live at `tests/fixtures/identity_contracts_v1_golden.json` and are exercised by unit tests plus the cross-platform installed-wheel smoke probe.
