"""Hybrid RAG architecture.

Vector search + BM25 keyword search combined via Reciprocal Rank Fusion,
with a cross-encoder reranking pass on the merged candidates. The
production-standard pattern mature teams converge on after iterating
past tutorial RAG.

Per `architectures/hybrid_rag/README.md` for design choices. The
agent-facing API is identical to Naive RAG (one search tool returning
ranked chunks with citation metadata); only Support Content's
implementation differs — that's the whole point of the modularity
constraint.
"""
