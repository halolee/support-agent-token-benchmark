"""Shared infrastructure across architectures.

Per CLAUDE.md and METHODOLOGY:
- Booking Systems' transactional tools are IDENTICAL across architectures.
- Compliance's audit_log payload is uniform.
- The corpus chunker is reused by Naive RAG and Hybrid RAG (both need the
  same chunk boundaries so vector retrieval comparisons aren't confounded
  by chunking differences).

Living under `_shared/` so accidental edits stay visible — if you change a
booking tool here, you change it for every architecture in the comparison.
"""
