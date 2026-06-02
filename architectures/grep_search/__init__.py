"""Grep search architecture.

Keyword search over the SWISS FAQ corpus exposed as a structured tool
(`grep_corpus`). The agent picks search terms; the tool returns matching
lines with surrounding context and a section citation.

Per `architectures/grep_search/README.md` for design choices. The
implementation reuses `_shared/booking_tools.py` and `_shared/audit.py`
verbatim — the only difference from Naive RAG is the retrieval tool.
"""
