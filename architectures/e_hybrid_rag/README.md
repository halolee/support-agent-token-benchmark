# Architecture E — Hybrid RAG

Vector search + BM25 keyword search combined, with a reranking pass on merged results. The production-standard pattern mature teams converge on.

## Why this architecture is in the comparison

See `ARCHITECTURE_RATIONALE.md`. Brief: Without E, the comparison is against a strawman. Naive RAG (A) is not what production teams actually run after iterating past v1. Hybrid RAG with reranking is. Any alternative that beats A but loses to E is not actually a win — it's just better than the tutorial pattern.

E is the real benchmark.

## Files

| File           | Purpose                                                  |
|----------------|----------------------------------------------------------|
| `agent.py`     | Main agent loop                                          |
| `tools.py`     | Tool definitions including the hybrid search tool        |
| `prompts.py`   | System prompt                                            |
| `setup_indices.py` | One-time script to build vector store AND BM25 index |

## Modularity constraint compliance

- **Support Content's interface:** `hybrid_search(query: str, k: int = 6) -> list[Chunk]`. Internally combines vector retrieval and BM25 retrieval, deduplicates, and applies reranking. AI Engineering's agent sees only the final ranked list.
- **Booking Systems' interface:** Identical to all other architectures
- **Compliance interface:** Identical

Support Content's operational burden is highest with E — they maintain both indices, the reranking model, and the combination logic. This is part of E's cost story even though it's not reflected in per-call tokens.

## Design choices

### Retrieval

- **Vector component:** Same as Architecture A (`text-embedding-3-small`, top-K from vector store)
- **Keyword component:** BM25 (via `rank_bm25` library) over the same chunked corpus
- **Combination:** Reciprocal Rank Fusion (RRF) to merge vector and BM25 results
- **Reranking:** Cross-encoder (`cross-encoder/ms-marco-MiniLM-L-6-v2` or similar lightweight model) over merged candidates
- **K_initial:** 10 (5 from each component, combined and deduplicated)
- **K_final:** 6 (after reranking)

### Tuning targets

- Vector vs. BM25 weight in RRF (start with equal weighting, tune in adversarial review)
- Reranking model choice (lightweight by default to keep latency reasonable)
- K_initial and K_final balance (more initial candidates → better reranking quality but higher reranking cost)

### Tools

- `hybrid_search(query: str, k: int = 6)` — Support Content's retrieval interface
- All Booking Systems tools (identical to A)
- `audit_log` (identical to A)

### Prompts

System prompt similar to A's (~500 tokens). The agent doesn't need to know about the hybrid retrieval internals — it just calls the search tool. The agent-facing API is the same as A; only Support Content's implementation differs.

## What "done" looks like

- Successfully answers at least 2 of 3 pure-policy tasks
- Successfully answers at least 2 of 3 pure-transactional tasks
- Token measurements logged to `measurement/results/architecture_e.json`
- Decomposition sums correctly

## Known limitations

- Embedding API calls (vector component) and reranking inference excluded from per-task cost
- BM25 index rebuilt on fresh clone (alongside vector store)
- Reranking model loaded into memory; cold-start cost not measured
- Tuning is ongoing in production — v1 measures a single tuning configuration

## What this architecture demonstrates

If E is the cheapest, the answer is "use mature RAG, not tutorial RAG." If A+G (cached A) matches E on cost while losing slightly on quality, the answer is "cache before complicating." If C matches E on cost AND quality, the answer is "you may not need the complexity at all." E provides the floor for "what production-grade RAG actually costs," which is the load-bearing comparison the article needs.
