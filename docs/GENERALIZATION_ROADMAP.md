# Generalization roadmap

## Current boundary

The bootstrap deliberately validates only the following neutral flow:

```text
DATASET -> CANDIDATE -> RUN -> METRICS -> COMPARE -> GATE -> EVIDENCE
```

Each arrow is represented by a small contract. No domain adapter is included
yet; adapters belong at the boundary and must provide selected dataset fields,
candidates, metrics, and evidence explicitly.

## Later domains

| Domain | Dataset | Candidate | Typical metrics | Deferred adapter work |
| --- | --- | --- | --- | --- |
| Music/audio analysis | labeled clips/features | extractor or matcher | precision, latency, agreement | audio loader and feature schema |
| ML/model evaluation | labeled train/validation corpus | model/configuration | accuracy, calibration, drift | model runner and prediction schema |
| Search/ranking evaluation | judged query/document sets | ranker/configuration | NDCG, recall, diversity | judgment and ranking adapters |
| Strategy/research validation | historical research windows | research hypothesis | stability, coverage, drawdown | domain-owned market-data adapter |
| Generic algorithm benchmarking | versioned input corpus | implementation/configuration | runtime, quality, memory | benchmark runner and resource metrics |

## Sequencing

1. Keep the bootstrap contracts stable through real users in at least two
   non-trading domains.
2. Define typed metric and evidence envelopes from observed shared needs.
3. Add optional adapters as separate packages; keep `arvp` free of runtimes,
   credentials, databases, and domain data clients.
4. Generalize report rendering and gate policy only after comparable evidence
   contracts exist.
5. Version each public contract before migration tooling or remote registries.

## Non-goals for the next slice

- No global plugin system, workflow engine, web service, database, or UI.
- No automatic data discovery, secret handling, or opaque model execution.
- No attempt to transpose Claire de Binare live-readiness or trading governance
  into a generic framework.
