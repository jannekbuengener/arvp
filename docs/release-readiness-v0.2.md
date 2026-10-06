# v0.2 release readiness checklist (#15)

Live base at preparation: `origin/main` @ `09df83a` (#14 merged).

## Prerequisite slices

- [x] #3–#14 merged/closed (live GitHub)
- [x] No open implementation PRs at start of #15 branch

## Package / docs

- [x] Version `0.2.0` in `pyproject.toml`
- [x] License metadata migrated to `LicenseRef-Proprietary` + `LICENSE`
- [x] Architecture, compatibility, changelog, ruleset *proposal* docs
- [x] README reflects shipped v0.2 surface (not bootstrap-only)

## Explicitly not done in this PR (Owner-GO)

- [ ] Apply GitHub ruleset / branch protection
- [ ] Create `v0.2.0` git tag
- [ ] Package registry publication (out of scope)

## Validation to run on the release PR head

- pytest (including second-domain + FSLD e2e)
- ruff check + format check
- mypy `src/arvp`
- `python -m build` + `twine check`
- clean wheel install smoke (CI package job)
- platform smoke ubuntu/windows (CI)
