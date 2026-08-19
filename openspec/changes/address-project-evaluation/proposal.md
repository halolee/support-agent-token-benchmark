# Change: Address project evaluation findings

## Why

The v1 repository provides a credible, transparent cost case study, but its comparative quality evidence is not publication-grade. The judge sees architecture identity, Hybrid RAG has known retrieval defects, and Cached RAG quality was inherited rather than measured. Reproducibility and documentation gaps also make a clean handoff harder than necessary.

The full verdict and evidence boundaries are recorded in `PROJECT_EVALUATION.md`.

## What changes

- Blind and recalibrate quality measurement before publishing architecture-quality comparisons.
- Fix known Hybrid RAG retrieval defects and rerun architectures under the documented alternating protocol.
- Add sensitivity runs that distinguish retrieval architecture from retrieval payload allowance.
- Make test and report workflows safe on a clean checkout.
- Reconcile stale documentation and missing release artifacts.

## Scope and sequencing

The tasks are split by repository ownership so workers can take one reviewable workstream at a time. Measurement validity is P0. Reproducibility and documentation are P1. Broader multi-domain or multi-model expansion remains future scope and should not block correction of v1.

No frozen v1 task IDs or historical result files should be mutated. New sweeps must use a new dated result directory and manifest.

## Acceptance

- Comparative quality numbers come from a blinded, full alternating sweep after retrieval fixes.
- Operational-default results are accompanied by context-budget sensitivity results.
- A fresh supported environment can run the offline suite in CI.
- Report generation cannot overwrite the curated publication artifact by default.
- Root guidance accurately describes the current implementation and license.
