# Proposed `main` repository ruleset (NOT APPLIED)

Prepared for Issue #15. **Do not apply without explicit Owner GO.**

## Target

Repository: `jannekbuengener/arvp`  
Branch: `main`

## Exact minimal enforcement

1. Restrict creations/updates to pull requests only (no direct push to `main`).
2. Require status checks to pass before merge on the **latest push / final head**:
   - `lint`
   - `typecheck`
   - `package`
   - `unit / py3.11`
   - `unit / py3.12`
   - `unit / py3.13`
   - `unit / py3.14`
   - `platform-smoke / ubuntu`
   - `platform-smoke / windows`
3. Block force pushes to `main`.
4. Block deletion of `main`.
5. Do **not** enable admin/bypass as a normal delivery path.

## Out of scope for this proposal

- CODEOWNERS / review-count requirements (can be added later)
- Tag protection for `v0.2.0` (separate Owner decision)
- Rules outside `main`

## Application status

**Pending Owner GO.** Preparing this proposal is in scope for #15; mutating
GitHub rulesets/branch protection is not.
