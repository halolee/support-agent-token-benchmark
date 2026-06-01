# Implement Naive RAG

## Why

Naive RAG is the v1 reference for the canonical tutorial RAG pattern most teams ship as their first deployment. Per `ARCHITECTURE_RATIONALE.md`, it serves as the baseline every other architecture in the comparison must beat to claim a win — the "popular default" the article compares the rest against.

Without A landed and measured, no other architecture's headline number is interpretable.

## What changes

- Set up vector store: chunk `corpus/swiss_faq.md` per the chunking strategy in `architectures/naive_rag/README.md`, embed with BGE-M3 (self-hosted), persist locally
- Implement Support Content's `vector_search(query, k)` tool — the inter-team interface
- Reuse Booking Systems' transactional tools (`get_booking_status`, `search_flights`, `search_hotels`, `search_cars`) and Compliance's `audit_log` (uniform payload)
- Implement agent loop in `architectures/naive_rag/agent.py` — receive message → call model with system prompt + tools → execute tool calls → feed results back → loop until no-tool-call response
- Instrument token counting at every model call (not just the final one)
- Smoke-test with 2-3 hand-written queries before full measurement

## Impact

- **New code:** `architectures/naive_rag/agent.py`, `tools.py`, `prompts.py`, `setup_vector_store.py`
- **New persisted artifact:** `architectures/naive_rag/vector_store/` (gitignored)
- **Modifies:** nothing existing
- **Depends on:** `measurement/tokens.py` (Phase 1 deliverable) and `corpus/swiss_faq.md` (Phase 1 Step 0) being in place first
- **Blocks:** Grep search and E can proceed in parallel, but `measurement/runner.py`'s full multi-architecture run depends on at least one architecture being complete

## Modularity constraint compliance

This is the one rule most likely to be accidentally violated. The agent code in this change must NOT read `corpus/swiss_faq.md` directly. Access goes through `vector_search()` only. See `METHODOLOGY.md` §"Modularity constraint" for the full spec; per-architecture compliance is documented in the architecture README.

## Adversarial review hooks

Per METHODOLOGY's Check 1 (equal tuning effort), this change must produce a tuned configuration, not a default one. Specifically: top-K, chunk size, and the chunking-overflow strategy should each be a deliberate choice with rationale documented in the change's design notes or the architecture README, not left at library defaults.
