"""Architecture implementations.

Each subpackage is one retrieval architecture under test. Per
METHODOLOGY's modularity constraint, the only cross-team data flow is
through tool calls — agents never read the corpus or database directly.

The `_shared` subpackage holds tool implementations that are uniform
across architectures (Booking Systems' transactional tools, Compliance's
audit log, the corpus chunker reused by Naive RAG and Hybrid RAG).
"""
