# Implement Hybrid RAG

## Why

Hybrid RAG is the production-standard pattern mature teams converge on — vector + BM25 + reranking. Per `ARCHITECTURE_RATIONALE.md`, without Hybrid RAG in the comparison the article is vulnerable to "you compared against a tutorial-grade strawman" pushback.

Hybrid RAG is the real benchmark every alternative must beat, not Naive RAG. An alternative that beats Naive RAG but loses to Hybrid RAG is not actually a win — it's just better than the tutorial pattern.

## What changes

- Build BOTH a vector store (BGE-M3 embeddings, same as Naive RAG) and a BM25 index over the same chunked corpus
- Implement Support Content's `hybrid_search(query, k)` tool — internally combines vector + BM25 via Reciprocal Rank Fusion, applies cross-encoder reranking (`cross-encoder/ms-marco-MiniLM-L-6-v2`, self-hosted), returns top-K reranked chunks
- Reuse Booking Systems' transactional tools and Compliance's `audit_log` (identical across architectures)
- Implement agent loop in `architectures/hybrid_rag/agent.py`
- Smoke-test with 2-3 hand-written queries

## Impact

- **New code:** `architectures/hybrid_rag/agent.py`, `tools.py`, `prompts.py`, `setup_indices.py`
- **New persisted artifacts:** vector store + BM25 index under `architectures/hybrid_rag/vector_store/` (gitignored)
- **Reranker model** (`cross-encoder/ms-marco-MiniLM-L-6-v2`) downloaded on first run; cached locally thereafter
- **Modifies:** nothing existing
- **Depends on:** `measurement/tokens.py`, `corpus/swiss_faq.md`, ideally Naive RAG done first so chunking/embedding pipeline is validated before adding BM25 and reranker on top

## Modularity constraint compliance

The vector store, BM25 index, reranker model, and combination logic all live inside Support Content's owned perimeter. The agent only calls `hybrid_search()` and sees the final ranked list — it never sees the vector/BM25/rerank internals or the merge strategy. The tool's input/output contract is the entire inter-team interface.

## Adversarial review hooks

Per METHODOLOGY's Check 1 (equal tuning effort), Hybrid RAG has the most tuning surface of any v1 architecture:

- Vector vs BM25 weighting in Reciprocal Rank Fusion (default: equal)
- Reranker model choice (`cross-encoder/ms-marco-MiniLM-L-6-v2` chosen for being lightweight and CPU-friendly)
- K_initial vs K_final balance (more initial candidates → better reranking but higher cost)

All three must be deliberate choices with rationale documented, not library defaults. This is the architecture most likely to look artificially weak if any one of these is wrong.
