# Note to the Implementation Agent

This document is the framing context for the implementation work. Read this **first**, then the README, then the other docs in the order suggested below.

## What this project is

A measurement framework comparing **four retrieval architectures** for LLM-based customer support agents:

- **A** — Naive RAG (vector top-K)
- **A+G** — A with prompt caching enabled
- **C** — Grep / keyword search
- **E** — Hybrid RAG (vector + BM25 + reranking)

The goal is to map the spectrum of common retrieval patterns, measure their cost and success characteristics, and produce defensible evidence for a companion LinkedIn article on AI architecture trade-offs.

This is **not**:
- A "RAG vs. MCP" comparison (MCP is a transport protocol, not an alternative to retrieval)
- A "RAG vs. CLI/grep" hot-take where grep is expected to win
- An advocacy project — the article's argument is that the right architecture depends on factors most teams don't measure, which works regardless of which architecture wins

## What changed from the previous version

Earlier iterations of this project had two architectures (A and B). You correctly flagged that this didn't match the article framing. We expanded to four (A, A+G, C, E), deferred B and D to v2, and added several other corrections you caught:

- **Modularity constraint enforced** across all architectures (every cross-team data flow via explicit tool call, owned by the data-owning team) — this simulates enterprise org-chart conditions
- **Model IDs fixed:** agent = `claude-sonnet-4-6`, judge = `claude-opus-4-7`
- **Tokenizer corrected:** drop `tiktoken` (OpenAI), use Anthropic's `client.beta.messages.count_tokens()`
- **Latency clarified:** single-request wall clock, not under load
- **Class distribution corrected:** 3/3/8/3 (mixed-heavy, reflecting realistic traffic)
- **Schema example rewritten:** the previous canonical example violated METHODOLOGY Check 2 by mapping task phrasing too cleanly to tool category names
- **Phased build:** 4 phases, each independently shippable, supporting parallel execution with other work
- **Adversarial review** is non-negotiable before any finding is published

## How to read the docs

Suggested order:

1. **`AGENT_HANDOVER_NOTE.md`** — this file (the framing)
2. **`README.md`** — project overview
3. **`ARCHITECTURE_RATIONALE.md`** — why these four architectures and not others
4. **`ROADMAP.md`** — what's in v1, what's deferred, what's beyond
5. **`METHODOLOGY.md`** — how measurements are taken; pay special attention to the modularity constraint and the adversarial review sections
6. **`HANDOVER.md`** — the cross-department artifact; shows how each architecture respects the modularity constraint
7. **`BUILD_PLAN.md`** — phased execution plan; **Step 0 is required first action**
8. **`architectures/*/README.md`** — per-architecture specifications
9. **`measurement/tasks.md`** — task set specification; **read Check 2 rule carefully**
10. **`measurement/results/comparison.md`** — output template

## What you should do first

**Phase 1, Step 0 in BUILD_PLAN:** explore the LangGraph customer support tutorial. Read what's actually there before designing anything. The corpus (`swiss_faq.md`) and database (`travel.sqlite`) need to be downloaded from there. Inventory what they contain — this affects implementation choices for A, C, and E.

After Step 0, proceed through BUILD_PLAN phases sequentially. Each phase is independently shippable.

## What to push back on if you see it

If during implementation you notice:

1. **A misalignment between the docs and the article's framing** — flag it. The previous version had exactly this problem; catching it early is high value.
2. **A measurement choice that would bias the comparison** — flag it. The adversarial review discipline depends on catching these before publication.
3. **A scope addition that wasn't in v1 plan** — push back. "Cumulative scope creep" already happened once with this project; we shipped a tighter v1 specifically to demonstrate prioritization. Don't add B, D, F, H, I to v1 unless we explicitly discuss it.
4. **A task phrasing that violates Check 2** — fix it. Tasks that map cleanly to category names (or to keyword-friendly vocabulary for grep) are the most common source of accidentally biased measurements.

## What success looks like

For each phase:

- **Phase 1 deliverable:** repo runs end-to-end with smoke test passing; token decomposition is correct
- **Phase 2 deliverable:** three architectures measured (A, C, E), adversarial review complete, comparison report has real numbers
- **Phase 3 deliverable:** A+G added, comparison report shows caching effect quantified
- **Phase 4:** deferred (B, D) unless explicitly added

The project ships as a portfolio artifact when Phases 1-2 complete with adversarial review done. Phase 3 strengthens it. Phase 4 is opt-in.

## Questions to ask before starting

If anything in the docs is unclear, ambiguous, or seems wrong, ask before implementing. The cost of asking is one message exchange; the cost of building on a misunderstanding is rework.

Specifically worth asking if:
- The modularity constraint feels artificial or hard to implement for a specific architecture
- The task set distribution feels wrong for the corpus you actually find in `swiss_faq.md`
- The architecture choices feel incomplete (we may have deferred the wrong things)
- The adversarial review feels excessive or feels insufficient

The disposition: this is collaborative work. Pushback is welcome.
