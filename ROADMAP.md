# Roadmap

This document tracks scope decisions over time: what's in v1, what's deferred to v2, and what's noted for further consideration.

The principle: ship the load-bearing comparison first. Add scope when v1 results justify it, not when it would be "nice to have."

## v1 — Current scope

**Architectures measured:**
- Naive RAG
- Cached RAG (Naive RAG with prompt caching enabled)
- Grep search (keyword search)
- Hybrid RAG

**Architectures named but not measured:**
- Fine-tuned, Deterministic routing, No-LLM

**Constraints enforced:**
- Modularity / siloed-department constraint (see METHODOLOGY)
- Adversarial review required before any finding is published
- Single model (`claude-sonnet-4-6`) across all architectures
- Single domain (airline customer support, English only)
- Single-turn dialogue

**Deliverables:**
- Working measurement framework with reproducible runs
- Comparison report with confidence assessment
- HANDOVER document showing how each architecture respects the modularity constraint
- Companion LinkedIn article using the measurements as evidence

## v2 — Deferred

These are deliberately deferred from v1. Each has a specific trigger condition for being promoted to v2 scope.

### Quality re-measurement series (committed for v2 — no trigger condition required)

v1 ships with HIGH-confidence cost findings and LOW-confidence quality findings. The §10 adversarial review (see `measurement/results/comparison.md` §"Confidence and known biases" and `measurement/results/runs/2026-06-04-phase2-step8b/judgment_summary.md` §"Manual review findings") identified a methodology defect (Finding C3: the LLM-as-judge prompt embeds the architecture name, producing asymmetric scoring strictness) plus five open Hybrid RAG retrieval bugs. The cost numbers are independent of both; quality numbers are not.

This is a quality-focused v2 series, distinct from the cost-focused architectures-deferred items below.

- **Trigger to add:** committed. Not gated on v1 reception — the §10 review explicitly states quality numbers are preliminary until this series ships.
- **Required fixes before re-sweep:**
  - **C3 fix** — strip `architecture`, `run_index`, and `tools_called` from `_build_agent_suffix` in `measurement/judge.py:236-256`. One-line PR. Blinds the judge to architecture identity per LLM-as-judge best practice.
  - **Hybrid RAG bug fixes** — issues #29 (BM25 accent tokenizer), #30 (RRF tie-break vector-favored), #31 (reranker 512-token silent truncation), #32 (BM25 early-break on negative-IDF chunks). Issue #35 is preventive only (no current code path triggers it) and can be deferred.
- **Required protocol:** re-sweep all three architectures in a single alternating run per METHODOLOGY §"Run protocol" — a hybrid-alone rerun against the v1 naive/grep numbers would break the time-of-day control and is explicitly NOT recommended (see `judgment_summary.md` §"Implications for §10").
- **Re-judge:** the full 153 dispatches with the blinded judge prompt. Plus a fresh 10% manual review sample to verify the C3 fix landed cleanly.
- **Estimated additional work:** ~0.5 day for the fixes (one-line judge PR + per-bug Hybrid RAG fix); ~1 day for the re-sweep + re-judge + `comparison.md` quality-section update + LinkedIn-article amendment.
- **Estimated paid cost:** ~$13 (re-sweep ~$6.50, re-judge ~$6.50 — same magnitude as the Phase 2 sweep).
- **Deliverables:**
  - Updated `comparison.md` with blinded-judge quality numbers replacing the LOW-confidence cells.
  - Companion LinkedIn-article follow-up "Quality, properly measured" using the same data with the methodology fix as the narrative hook.
  - `judgment_summary.md` for the v2 sweep showing whether the C3 finding closes (pass rate spread tightens) and whether the hybrid bug fixes show up as quality lift.
- **Article framing:** v2 becomes a content series — v1's headline is "we measured cost cleanly and found Naive cheapest"; v2's headline is "we measured the judge, found a leak, fixed it, and re-measured quality." This is a methodology contribution, not a retraction. Most LLM-as-judge writeups don't surface this kind of self-criticism.

### Bounded tools

- **Trigger to add:** Reviewers or readers argue thatBounded tools and Hybrid RAGare meaningfully different in cost or success rate, and the comparison would benefit from distinguishing them.
- **Estimated additional work:** ~1 day (implementation + adversarial review + report update)

### Stuffed corpus

- **Trigger to add:** v1 results suggest Naive RAG and Hybrid RAG are paying significant cost for retrieval that the corpus size doesn't justify. If retrieval overhead is dominating cost on a small corpus, the SolDevelo finding becomes worth re-validating directly.
- **Estimated additional work:** ~0.5 day (simplest of the deferred architectures)

### Prompt caching variants for other architectures

v1 measures Naive RAG and Cached RAG. Future work: measure Hybrid RAG with caching, Grep search with caching, etc.

- **Trigger to add:** If Cached RAG shows dramatic cost collapse, the question "does caching collapse cost for non-A architectures too" becomes important.
- **Estimated additional work:** ~0.5 day per architecture

### Multi-turn dialogue measurement

All v1 tasks are single-turn. Multi-turn would compound the architectural cost differences in ways v1 can't see.

- **Trigger to add:** v1 publishes, audience asks about multi-turn.
- **Estimated additional work:** ~2 days (need to design realistic dialogue task set, handle conversation history token accumulation)

### Cheaper model comparison

v1 uses Sonnet 4.6. Smaller/cheaper models (Haiku 4.5, GPT-4o-mini) may interact differently with the architectures.

- **Trigger to add:** Question arises whether the architectural advantage holds at lower price points.
- **Estimated additional work:** ~1 day (re-run existing task set on additional models, extend comparison report)

### Larger task set

v1 has ~17 tasks. 50–100 tasks would tighten statistical confidence.

- **Trigger to add:** Headline differences are small enough that variance matters more than mean.
- **Estimated additional work:** ~1 day to write tasks, ~1 day to re-run

## Beyond v2 — Noted for future consideration

### Fine-tuned

Requires training infrastructure not present in this project. If commissioned as a v3, would need:
- Training data preparation pipeline
- Compute budget for training runs
- Model hosting infrastructure for inference
- Methodology adjustment to handle amortized training cost

### Deterministic routing

Requires building a router (classifier or rule system). If commissioned as v3:
- Router design and training
- Routing accuracy measurement (separate from retrieval cost)
- More complex success criteria (right answer + right path)

### Different domain

Airline customer support has particular properties (finite policy taxonomy, structured booking data). Domains with open-ended policy spaces or unstructured data may shift the comparison.

- Healthcare triage
- Legal document research
- Internal IT helpdesk
- Developer documentation Q&A

Each domain would be its own v-N.

### Corpus and data evolution as an experimental axis

Run the same task set against a "before" corpus/DB and an "after" corpus/DB to measure how each architecture absorbs change. Adaptation cost becomes a comparison dimension alongside per-task token cost.

The shape: v1 measures cost and success on a static dataset. It doesn't measure what it takes to *update* each architecture when policy text changes or new policy classes are added. That's a real architectural trade-off:

- Naive RAG / E need re-indexing (Support Content's operational burden)
- Cached RAG needs cache invalidation + re-indexing
- Grep search needs no code change if the corpus just grows; needs code change only if the policy taxonomy changes the *kind* of question to ask

**Trigger condition:** if v1 results show C competitive on cost/success against Naive RAG and Hybrid RAG on the static dataset, the natural follow-up question is whether Grep search's adaptation story holds when the corpus changes. Without this axis, v1 understates Grep search's case if Grep search is genuinely cheaper to evolve, and overstates Grep search's case if Grep search silently misses new policy categories.

**Estimated effort:** significant. Requires (a) a second corpus reflecting realistic policy expansion, (b) re-running the full task set, (c) potentially new tasks specifically targeting the new policy classes, (d) re-indexing/adaptation-cost instrumentation.

**Origin:** surfaced during Phase 1 Step 0 corpus inventory. The bucket's `travel.sqlite` (Apr 23 2024, aviation-only) → `travel2.sqlite` (Apr 30 2024, multi-domain) evolution suggested the experimental design, though those two files aren't directly usable as a before/after pair (different schemas, not a migration test).

**Good fit for an open-source contributor.** Independent of the other Beyond-v2 items; doesn't require training infrastructure (unlike F) or a new component to build (unlike H). The instrumentation hook is the existing `setup_*` script in each architecture; the rest is task-set construction and a second measurement pass.

### .NET reference implementation

A C#/.NET port of the architectures as a reference implementation. v1 is Python because the AI tooling ecosystem is Python-dominant — even Microsoft pushes Python for Azure AI Foundry and Semantic Kernel's Python flavor. A .NET port serves enterprise .NET-shaped readers who'd prefer to evaluate the architectures against their actual stack. Component mapping: Azure AI Search or Qdrant.NET for vector retrieval, ONNX Runtime for BGE-M3, Semantic Kernel for agent orchestration, inter-service contracts model the modularity constraint cleanly. Methodology is language-invariant; the architectural trade-offs hold whichever language. Good open-source contributor fit for someone .NET-fluent.

## Decision log

Significant scope decisions and their rationale:

| Date | Decision | Rationale |
|------|----------|-----------|
| Design phase | Cut from 6 architectures to 4 in v1 | "Cumulative scope creep" — each addition was individually justified but together tripled scope. Cutting Bounded tools and Stuffed corpus ships the load-bearing comparison first. Demonstrates prioritization. |
| Design phase | Added Hybrid RAG (hybrid RAG) | Without it, comparing against Naive RAG is a strawman in 2026. Production RAG is hybrid. |
| Design phase | Added Cached RAG (caching variant) | Without it, the comparison overstates RAG's real production cost. Most teams running Naive RAG in production have caching enabled. |
| Design phase | Enforced modularity constraint across all architectures | Simulates enterprise org-chart reality. Without it, the experiment measures startup-context architectures, not enterprise ones. |
| Design phase | Phased build (foundation → core → variant → optional) | Allows shipping a working artifact at each phase. Supports parallel execution with job hunt. |
| 2026-05-25 | Added "corpus/data evolution axis" to Beyond v2 | Surfaced during Phase 1 Step 0 corpus inventory. The bucket's travel→travel2 evolution suggested an adaptation-cost experimental axis distinct from per-call token cost. Flagged as a good contributor fit for the open-source v2+. |
| 2026-05-25 | Stay Python for v1; .NET reference implementation noted as Beyond-v2 candidate | Solo-founder runway considerations favor the language ecosystem with mature AI tooling — even Microsoft pushes Python for Azure AI Foundry and Semantic Kernel's Python flavor. The methodology is language-invariant, so .NET-shaped enterprise readers can map architectures to their stack via the component mapping in the Beyond-v2 entry. The article will include a "mapping to .NET ecosystem" paragraph for that audience. |
| 2026-06-02 | Froze benchmark task set at 17/17 (3 POL, 3 TXN, 8 MIX, 3 EDGE) | Merge of [#16](https://github.com/halolee/support-agent-token-benchmark/pull/16) (commit `e5f8c43`); also tagged `tasks-frozen-v1`. All measured architectures run against this set. Anchor for reproducibility — the published numbers in `comparison.md` are tied to this task set. Edits create new IDs and deprecate old ones per CLAUDE.md invariants. |
| 2026-06-04 | Ship v1 §10 with cost-confident / quality-preliminary framing; queue v2 quality re-measurement series | Phase 2 §10 adversarial review surfaced Finding C3 (judge prompt embeds architecture name, contaminating quality scoring) plus a stability test confirming asymmetric judge strictness across architectures. Cost numbers are HIGH-confidence (mechanical at API level, robust to bug status and filtering); quality numbers are LOW-confidence and contaminated by C3. Decision: ship v1 with HIGH-confidence cost findings as the headline and LOW-confidence quality findings front-loaded with the C3 caveat. v2 series (blinded judge + Hybrid RAG bug fixes + full re-sweep + re-judge, ~$13) committed above the v2 trigger-condition items. Article framing becomes a "cost + methodology" v1 headline and "quality, properly measured" v2 follow-up. Reasoning fully documented in `comparison.md` §"Confidence and known biases" and `runs/2026-06-04-phase2-step8b/judgment_summary.md`. |

## How this document gets updated

Add a row to the decision log whenever scope changes. Move items between sections (v1 / v2 / future) when triggers fire. Don't delete deferred items — keeping them visible shows what was considered.
