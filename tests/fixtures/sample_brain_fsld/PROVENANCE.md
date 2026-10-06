# Sample Brain FSLD fixtures — provenance / sanitization

## Purpose

Repository-owned **synthetic** FSLD key/tempo evaluation reports for ARVP #14.
They mirror the live Sample Brain document type
`sample_brain.fsld_current_analyzer_eval` schema `1.0.0` without importing
Sample Brain runtime modules and without any local audio root.

## Source contract anchor

- Sample Brain module (read-only reference): `src/fsld_current_analyzer_eval.py`
- Schema identity: `document_type=sample_brain.fsld_current_analyzer_eval`,
  `schema_version=1.0.0`
- Schema-introducing commit (Sample Brain): `eff14d25`
- Cross-repo bridge contract (Sample Brain #956): `sample-brain.analysis-eval.v1`
  — #14 adapts the legacy FSLD report at the ARVP consumer boundary rather than
  requiring FSLD fields inside `src/arvp`.

## Sanitization rules

Fixtures contain only:

- synthetic decimal `public_sample_id` values (`90001`–`90004`);
- portable scalar ground truth / predictions / aggregate metrics;
- fixed fake `manifest_sha256` hex strings (not real FSL10K bytes).

Fixtures must never contain:

- absolute paths, usernames, hostnames;
- audio filenames, audio bytes, or file hashes of audio;
- private Traktor / library identifiers;
- Sample Brain DB rows or credential material.

## HOLD matrix (expected adapter outcomes)

| Scenario | Expected |
|---|---|
| baseline evaluated + compatible improved candidate | `PASS` |
| baseline evaluated + compatible regression candidate | `FAIL` |
| `PUBLIC_AUDIO_NOT_AVAILABLE_LOCALLY` / `metrics=null` | `HOLD` (never measured 0%) |
| missing required evaluated evidence | `HOLD` |
| manifest or split / membership mismatch | `HOLD` (fail closed) |
| malformed report | structured adapter failure (no Evidence Bundle) |

## Candidate revision gap

FSLD reports do not carry a git/code revision. External candidate descriptors
live in `candidates.json` and are required by the reference adapter alongside
each report.

## Regeneration

```powershell
python tests/fixtures/sample_brain_fsld/_generate.py
```
