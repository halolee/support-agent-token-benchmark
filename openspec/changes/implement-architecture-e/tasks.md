# Tasks for implement-architecture-e

## 1. Indices setup

- [ ] 1.1 Reuse Naive RAG's chunking strategy on `corpus/swiss_faq.md`. If Naive RAG's chunking lives in a non-shared script, extract to a shared helper to ensure parity.
- [ ] 1.2 Build vector store with BGE-M3 embeddings (same model as Naive RAG) in `architectures/hybrid_rag/vector_store/`
- [ ] 1.3 Build BM25 index via `rank_bm25` over the same chunked corpus; persist alongside vector store
- [ ] 1.4 Verify both indices return sensible results for a few test queries before integrating

## 2. Inter-team `hybrid_search` tool (modularity constraint)

- [ ] 2.1 Implement `hybrid_search(query: str, k: int = 6)` in `tools.py` as Support Content's interface
- [ ] 2.2 Internally: vector retrieval (K=5) + BM25 retrieval (K=5), combine via Reciprocal Rank Fusion (RRF), deduplicate by chunk ID
- [ ] 2.3 Apply cross-encoder reranking (`cross-encoder/ms-marco-MiniLM-L-6-v2`, loaded via `sentence-transformers`) over the merged candidates
- [ ] 2.4 Return top-K_final (default 6) reranked chunks
- [ ] 2.5 Agent code sees only the final ranked list — no vector/BM25/rerank internals exposed; no separate sub-tools
- [ ] 2.6 All SQL queries (Booking Systems tools) use parameterized statements; no string concatenation of user-derived input. Code-quality requirement per architecture README.

## 3. Reuse shared tools

- [ ] 3.1 Wire in Booking Systems tools (identical to Naive RAG and Grep search)
- [ ] 3.2 Wire in Compliance's `audit_log` per the uniform payload spec

## 4. Agent loop

- [ ] 4.1 Write system prompt in `prompts.py` targeting ~500 tokens (similar to Naive RAG — the agent doesn't need to know about hybrid internals; it just calls one search tool)
- [ ] 4.2 Implement agent loop — same shape as Naive RAG and Grep search
- [ ] 4.3 Instrument token counting at every model call

## 5. Tuning targets (for adversarial review)

- [ ] 5.1 Document the chosen RRF weighting (default: equal weight to vector and BM25; tune in adversarial review if smoke test surfaces obvious mismatch)
- [ ] 5.2 Document the reranker choice; verify model loads on CPU within reasonable time
- [ ] 5.3 Document K_initial and K_final values; tune in adversarial review if needed

## 6. Smoke test

- [ ] 6.1 Run agent on 2-3 hand-written tasks; verify completion
- [ ] 6.2 Verify token decomposition sums within 5% tolerance
- [ ] 6.3 Output to `measurement/results/architecture_hybrid_rag.json` is well-formed JSON

## 7. "Done" criteria from architecture README

- [ ] 7.1 Successfully answers ≥2 of 3 pure-policy tasks
- [ ] 7.2 Successfully answers ≥2 of 3 pure-transactional tasks
- [ ] 7.3 Token decomposition is correct (5% tolerance) on all full-run tasks
