# Roadmap

This document tracks scope decisions over time: what's in v1, what's deferred to v2, and what's noted for further consideration.

The principle: ship the load-bearing comparison first. Add scope when v1 results justify it, not when it would be "nice to have."

## v1 — Current scope

**Architectures measured:**
- A — Naive RAG
- A+G — A with prompt caching enabled
- C — Grep / keyword search
- E — Hybrid RAG

**Architectures named but not measured:**
- F (fine-tuning), H (deterministic routing), I (no LLM)

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

### Architecture B — Bounded structured tools

- **Trigger to add:** Reviewers or readers argue that B and E are meaningfully different in cost or success rate, and the comparison would benefit from distinguishing them.
- **Estimated additional work:** ~1 day (implementation + adversarial review + report update)

### Architecture D — Full corpus stuffed

- **Trigger to add:** v1 results suggest A and E are paying significant cost for retrieval that the corpus size doesn't justify. If retrieval overhead is dominating cost on a small corpus, the SolDevelo finding becomes worth re-validating directly.
- **Estimated additional work:** ~0.5 day (simplest of the deferred architectures)

### Prompt caching variants for other architectures

v1 measures A and A+G. Future work: measure E with caching, C with caching, etc.

- **Trigger to add:** If A+G shows dramatic cost collapse, the question "does caching collapse cost for non-A architectures too" becomes important.
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

### Architecture F — Fine-tuned model

Requires training infrastructure not present in this project. If commissioned as a v3, would need:
- Training data preparation pipeline
- Compute budget for training runs
- Model hosting infrastructure for inference
- Methodology adjustment to handle amortized training cost

### Architecture H — Deterministic routing + LLM at edges

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

- Architecture A / E need re-indexing (Support Content's operational burden)
- Architecture A+G needs cache invalidation + re-indexing
- Architecture C needs no code change if the corpus just grows; needs code change only if the policy taxonomy changes the *kind* of question to ask

**Trigger condition:** if v1 results show C competitive on cost/success against A and E on the static dataset, the natural follow-up question is whether C's adaptation story holds when the corpus changes. Without this axis, v1 understates C's case if C is genuinely cheaper to evolve, and overstates C's case if C silently misses new policy categories.

**Estimated effort:** significant. Requires (a) a second corpus reflecting realistic policy expansion, (b) re-running the full task set, (c) potentially new tasks specifically targeting the new policy classes, (d) re-indexing/adaptation-cost instrumentation.

**Origin:** surfaced during Phase 1 Step 0 corpus inventory. The bucket's `travel.sqlite` (Apr 23 2024, aviation-only) → `travel2.sqlite` (Apr 30 2024, multi-domain) evolution suggested the experimental design, though those two files aren't directly usable as a before/after pair (different schemas, not a migration test).

**Good fit for an open-source contributor.** Independent of the other Beyond-v2 items; doesn't require training infrastructure (unlike F) or a new component to build (unlike H). The instrumentation hook is the existing `setup_*` script in each architecture; the rest is task-set construction and a second measurement pass.

## Decision log

Significant scope decisions and their rationale:

| Date | Decision | Rationale |
|------|----------|-----------|
| Design phase | Cut from 6 architectures to 4 in v1 | "Cumulative scope creep" — each addition was individually justified but together tripled scope. Cutting B and D ships the load-bearing comparison first. Demonstrates prioritization. |
| Design phase | Added Architecture E (hybrid RAG) | Without it, comparing against naive RAG (A) is a strawman in 2026. Production RAG is hybrid. |
| Design phase | Added A+G (caching variant) | Without it, the comparison overstates RAG's real production cost. Most teams running A in production have caching enabled. |
| Design phase | Enforced modularity constraint across all architectures | Simulates enterprise org-chart reality. Without it, the experiment measures startup-context architectures, not enterprise ones. |
| Design phase | Phased build (foundation → core → variant → optional) | Allows shipping a working artifact at each phase. Supports parallel execution with job hunt. |
| 2026-05-25 | Added "corpus/data evolution axis" to Beyond v2 | Surfaced during Phase 1 Step 0 corpus inventory. The bucket's travel→travel2 evolution suggested an adaptation-cost experimental axis distinct from per-call token cost. Flagged as a good contributor fit for the open-source v2+. |

## How this document gets updated

Add a row to the decision log whenever scope changes. Move items between sections (v1 / v2 / future) when triggers fire. Don't delete deferred items — keeping them visible shows what was considered.
