# External References — ARVP

This repo-local index records external technical references that are materially relevant to ARVP. It follows the Agent Workforce external-reference contract: <https://github.com/jannekbuengener/agent-workforce/blob/main/contracts/EXTERNAL_REFERENCE_CONTRACT.md>.

ARVP remains domain-neutral. External references do not add trading, Sample Brain, database, Docker, live-execution or deployment scope to the core.

## Priority and authority

- `P0` — active/core reference backed by a current repo signal.
- `P1` — active secondary reference backed by a current repo signal.
- `P2` — parked/reference-only; not evidence of active scope.

External source authority is independent from priority: `OFFICIAL_SPEC` > `OFFICIAL_DOCS` > `UPSTREAM_PROJECT_DOCS` > `UPSTREAM_ISSUES_RELEASES` > `ESTABLISHED_TECHNICAL_KNOWLEDGE` > `COMMUNITY` > `EXAMPLE_DISCOVERY`.

## Active references

| Category | Name | Priority | Source type | Authority | Purpose | Repo signal | When to use | Canonical URL / identity |
|---|---|---|---|---|---|---|---|---|
| Runtime | Python | `P0` | `official_docs` | `OFFICIAL_DOCS` | Runtime, stdlib and language semantics. | `pyproject.toml` requires Python `>=3.11`. | Runtime/typing/stdlib/compatibility work. | https://docs.python.org/3/ |
| Packaging | Setuptools | `P0` | `official_docs` | `OFFICIAL_DOCS` | Build backend and src-layout packaging. | `pyproject.toml` uses `setuptools.build_meta` and package discovery from `src`. | Packaging/build/layout changes. | https://setuptools.pypa.io/en/latest/ |
| Testing | pytest | `P0` | `official_docs` | `OFFICIAL_DOCS` | Deterministic test and validation behavior. | `pyproject.toml` dev dependency and pytest config; README development gate. | Tests, fixtures, parametrization, collection. | https://docs.pytest.org/en/stable/ |
| Schemas | JSON Schema | `P0` | `official_spec` | `OFFICIAL_SPEC` | Schema semantics for packaged `arvp.schemas` assets and evidence contracts. | `src/arvp/schemas/` is packaged; `jsonschema>=4.23` is a dev dependency. | Schema authoring/validation or compatibility work. | https://json-schema.org/ |
| Static analysis | Ruff | `P1` | `official_docs` | `OFFICIAL_DOCS` | Lint/format behavior. | `pyproject.toml` dev dependency/config; README runs `ruff check` and `ruff format --check`. | Ruff configuration or formatting/lint changes. | https://docs.astral.sh/ruff/ |
| Type checking | mypy | `P1` | `official_docs` | `OFFICIAL_DOCS` | Static typing behavior. | `pyproject.toml` dev dependency/config; README runs `mypy src/arvp`. | Type-checking/API annotation work. | https://mypy.readthedocs.io/en/stable/ |
| Packaging | PyPA build | `P1` | `official_docs` | `OFFICIAL_DOCS` | Standards-based package build tooling. | `pyproject.toml` dev dependency `build>=1.2`; v0.2 release-readiness docs/package flow. | Distribution build/release checks. | https://build.pypa.io/en/stable/ |
| Packaging | Twine | `P1` | `official_docs` | `OFFICIAL_DOCS` | Distribution metadata/upload validation tooling. | `pyproject.toml` dev dependency `twine>=6.1`; release-readiness tooling. | Distribution metadata/check/release work only. | https://twine.readthedocs.io/en/stable/ |
| Repository CI | GitHub Actions | `P1` | `official_docs` | `OFFICIAL_DOCS` | Workflow/check semantics for repository validation. | `.github/workflows/` and repository release/governance surfaces. | CI/check/workflow changes. | https://docs.github.com/en/actions |

## Parked references

No domain technology is parked merely because an example adapter mentions a consumer. Add `P2` only when an ARVP-owned issue/canon path gives the reference a concrete future purpose.

## Maintenance rules

- Every `P0`/`P1` row must retain a current repo signal.
- Example adapters never promote consumer technologies into ARVP core dependencies.
- Community/example sources may aid discovery but never override official/upstream or live repository evidence.
- Do not commit machine-local absolute paths, credentials, private endpoints or transient installation state.