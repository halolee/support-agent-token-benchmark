"""Naive RAG architecture.

The canonical tutorial pattern: chunk corpus → embed → vector store →
top-K retrieval → LLM agent loop. The popular default and the source of
most "RAG" misconceptions; included as the baseline every other
architecture is compared against.

Per `architectures/naive_rag/README.md` for design choices.
"""
