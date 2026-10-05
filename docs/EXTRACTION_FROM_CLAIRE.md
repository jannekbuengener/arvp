# Extraction from Claire de Binare

## Source

- Source repository: `jannekbuengener/Claire_de_Binare`
- Source commit: `56928a4b78f1f89a42b0366b89c28725b42f22b5`
- Extraction date: 2026-10-05
- Target repository: `jannekbuengener/arvp`

This bootstrap adapts generic validation patterns. It is not a history rewrite,
package move, or compatibility promise with the source repository.

## Extracted modules

| ARVP module | Source module or pattern | Adaptation |
| --- | --- | --- |
| `arvp.canonical` | `core/replay/canonical_json.py` | Canonical serialization and SHA-256 contracts, documented as a standalone utility. |
| `arvp.datasets` | `core/replay/dataset_identity.py` | Explicit semantic field selection replaces CDB candle, provider, and `DatasetSpec` contracts. |
| `arvp.provenance` | `core/replay/run_registry.py` | Generic candidate/run provenance and a JSONL registry replace replay, scheduler, and artifact-root fields. |
| `arvp.scenarios` | `core/replay/scenario_harness.py` | Generic scenario parameters/results replace replay variants and CDB clock integration. |
| `arvp.evaluation` | `core/replay/walk_forward.py`, `core/replay/resampling.py`, `services/validation/gate_evaluator.py` | Window split, resampling, gate, and candidate-ranking primitives replace strategy KPIs, environment thresholds, and execution terms. |

## Deliberately excluded

- Trading runtime, exchange adapters, MEXC/Binance integrations, orders, fills,
  portfolio, risk, capital, and live-trading governance.
- Docker, databases, Redis, migrations, service topology, scheduled workers,
  and runtime artifacts.
- Strategy-specific backtest runners, market symbols/timeframes, price data,
  proprietary datasets, calibration results, and evidence packets.
- Claire-specific credentials, environment configuration, local paths, and
  source artifact locations.

## Claire-specific dependencies not carried forward

The source modules depend on CDB scheduler profiles, clock and seed utilities,
dataset providers/specifications, ARVP evidence naming, and strategy metrics.
ARVP deliberately defines small local contracts instead of importing or
emulating these dependencies with stubs.

## Generalization candidates

The bootstrap keeps the following candidates for later, evidence-driven work:

- pluggable data adapters and typed metric schemas;
- richer evidence bundles and artifact writers;
- configurable quantiles and resampling modes;
- structured gates, scorecards, and report renderers;
- domain extensions listed in the generalization roadmap.
