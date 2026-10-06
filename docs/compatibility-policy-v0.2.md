# Pre-1.0 compatibility policy

ARVP is pre-1.0. Contract and fingerprint stability matters for auditability,
but breaking changes remain allowed when necessary to fix correctness or safety.

## What is versioned

- Contract version strings (for example `arvp.evidence.v1`,
  `arvp.evaluation-input.v1`)
- Packaged JSON Schema asset names under `arvp.schemas`
- Semantic fingerprint inputs documented per contract

## Fingerprint rules

- Semantic fingerprints hash decision-relevant fields only.
- Volatile presentation/transport fields (for example `generated_at`) must not
  change semantic identity.
- A fingerprint field must never be part of its own hash input.
- Byte integrity, when needed, uses a separate artifact hash.

## Breaking-change expectations before 1.0

A change is breaking when it alters:

- a public type/function signature required by consumers;
- a contract version string or schema asset required shape;
- semantic fingerprint inputs for an existing contract version.

Breaking changes require:

1. an explicit contract version bump or documented deprecation note;
2. changelog entry under the release that introduces the change;
3. no silent reinterpretation of existing semantic fingerprints.

Non-breaking changes include docs, tests, reference examples outside
`src/arvp`, and additive optional fields that existing validators reject only
when unknown fields are explicitly forbidden (those remain fail-closed).

## Schema compatibility

Evidence Bundle / Evaluation Input / suite / observation schemas use closed
top-level shapes (`additionalProperties: false` where frozen). Unknown
top-level keys are rejected. Nested openness, when present, is documented in
the owning contract doc.
