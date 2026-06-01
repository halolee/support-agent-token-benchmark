# Budget

Three-tier budget for v1, with a hard cap that forces a pause-and-decide rather than drift.

## Why tiers

The work this project does splits cleanly along *what's being verified*:

- **Implementation correctness** (does the code work?) → verifiable in session compute, no API spend.
- **Measurement infrastructure correctness** (do our token counts match the API?) → only verifiable via real API responses. The measurement is the thing being measured.
- **The measurement itself** (what do the architectures actually cost per task?) → real API runs across the full task set.

The tiers below mirror that split. Tier 2 is the smallest tier but is not optional — it's the only place where the *measurement infrastructure* can be verified before we trust Tier 3's numbers.

---

## Tier 1 — Implementation (Claude Code max-5 plan, $0 marginal)

All design, debugging, iteration, code-writing, mocked unit tests, and manual task walkthrough. Covered by the existing Claude Code subscription; no API spend per session.

**Examples:**
- Writing `measurement/tokens.py` and its 12 mocked unit tests (already done — $0)
- Designing the agent loops for each architecture
- Local pytest runs against cassettes
- Inspecting tool outputs while debugging an integration

**Edge cases discovered during Tier 2 or Tier 3 work get debugged in Tier 1.** Cycle back here whenever a failure surfaces; don't try to debug while burning API budget.

---

## Tier 2 — Validation runs (direct API, ~$1–3 total)

Small real-API runs on 2–3 task subsets per architecture to confirm the measurement infrastructure works correctly **before** committing to full Tier 3 measurement.

**What's verified in Tier 2:**
- Token decomposition sum matches API-reported `input_tokens` within 5% (METHODOLOGY's methodology gate)
- Agent loop completes end-to-end with the real model
- `record_run` output is well-formed against real `Usage` objects
- Tool-call cycle correctly accumulates `retrieved_context` tokens across turns

**Cassettes from Tier 2 become methodology-gate fixtures** used by all subsequent session-based verification (see `tests/cassette.py`). Record once, replay forever — the only ongoing cost is when fixtures need to be re-recorded (model version change, decomposition logic change).

Tier 2 cost is small because each validation hits at most a few API calls per architecture, on 2-3 short tasks. Total across Naive RAG, Grep search, Hybrid RAG: well under $3.

---

## Tier 3 — Recorded measurements (direct API, ~$35–60 honest budget)

Full Phase 2 runs in incremental pattern:

1. **Naive RAG** — full task set × 3 runs. Inspect results.
2. **Grep search** — same pattern. Inspect.
3. **Hybrid RAG** — same pattern. Inspect.
4. **Phase 3: Cached RAG** — caching variant on top of Naive RAG.
5. **Judge scoring** — Claude Opus 4.7 against the per-task rubric.
6. **Adversarial-review re-runs** if Check 1/2/3 (METHODOLOGY) reveals tuning asymmetry, task-set bias, or counterfactual gaps.

**Estimate range explanation:**
- Low end (~$35): tasks complete in 2–3 model calls each, no re-runs needed
- High end (~$60): tasks take 4+ turns each, adversarial review triggers a re-run of one architecture, judge re-scoring after rubric tweak

The high end deliberately exceeds the hard cap. That's by design — it forces an explicit pause-and-decide rather than letting cost drift into recovery territory.

---

## Hard cap: $50 for Tier 2 + Tier 3 combined

```
                 Tier 1            Tier 2            Tier 3
  Estimate:      $0 marginal       $1–3              $35–60
  Cap:           uncapped          (no separate)     ────────── $50 ──────────
                                                     combined T2 + T3
```

If actual cumulative spend approaches $50, **stop and decide**. Options at that point:

1. **Drop a low-priority architecture** (defer E to v2 if A and C are landed)
2. **Reduce runs per task** (3 → 1, accepting less variance information)
3. **Reduce task set** (skip the edge cases, keep policy + transactional + mixed)
4. **Accept the cap-breach** with explicit reasoning ("the result is publishable as-is")

Each option has a real cost — drift is what we're avoiding, not breach itself.

---

## Dry-run discipline

Before any Tier 3 expenditure on a given architecture, that architecture's Tier 2 validation must have passed. Specifically:

- Methodology gate (5% sum) verified via cassette replay (zero ongoing cost) OR via fresh live run (~$0.01)
- A smoke run completes end-to-end on 1-2 tasks with the real API
- `record_run` output is inspected for shape correctness

Catching a decomposition bug in $1 of Tier 2 spend is roughly 30× cheaper than catching it after a full Tier 3 run. The asymmetry justifies the discipline.

---

## Cost log

Update this table after each phase. Estimates and actuals together — large gaps are a signal to re-estimate.

| Date | Phase / Tier | Architecture | Estimated | Actual | Cumulative T2+T3 | Notes |
|------|--------------|--------------|-----------|--------|------------------|-------|
| — | Tier 2 validation | Naive RAG | $0.50 | _TBD_ | _TBD_ | First Tier 2 run; records methodology gate cassette |
| — | Tier 2 validation | Grep search | $0.50 | _TBD_ | _TBD_ | |
| — | Tier 2 validation | Hybrid RAG | $0.50 | _TBD_ | _TBD_ | |
| — | Tier 3 measurement | Naive RAG | $10 | _TBD_ | _TBD_ | Full task set × 3 runs |
| — | Tier 3 measurement | Grep search | $6 | _TBD_ | _TBD_ | Lower input tokens expected |
| — | Tier 3 measurement | Hybrid RAG | $12 | _TBD_ | _TBD_ | Highest input tokens expected (reranker overhead is local, not API) |
| — | Tier 3 Cached RAG | Cached RAG | $2 | _TBD_ | _TBD_ | Caching discount expected to bring this down sharply |
| — | Tier 3 judge | (all) | $5 | _TBD_ | _TBD_ | Opus 4.7 scoring |
| — | Tier 3 re-runs | _TBD_ | $0–10 | _TBD_ | _TBD_ | Triggered by adversarial review only |

If the **cumulative** column exceeds $50 at any row, halt and invoke the pause-and-decide protocol above.

---

## Out of scope (deliberately not in this budget)

- **Embedding compute** — BGE-M3 is self-hosted; $0.
- **Vector store hosting** — local ChromaDB; $0.
- **Reranker inference** — local cross-encoder; $0.
- **Developer time** — measured implicitly through phase pacing, not as dollars.
- **v2 work** — corpus-evolution axis, .NET reference implementation, etc., per `ROADMAP.md`.

Anthropic also exposes a hard usage limit per API key. **Set this to $50** as a belt-and-suspenders enforcement of the cap above.
