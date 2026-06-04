"""Cached RAG architecture.

Naive RAG plus Anthropic prompt caching on the system prompt and the
tool-definitions block. The retrieval mechanism (chunk corpus → embed →
vector store → top-K) is identical to Naive RAG; only the wire-format
`cache_control` markers and per-architecture cost decomposition differ.

The "have you tried the obvious optimization first" baseline for
production teams running Naive RAG; quantifies the cost-shape shift
caching produces on a representative agent workload.

Per `architectures/cached_rag/README.md` for design choices.
"""
