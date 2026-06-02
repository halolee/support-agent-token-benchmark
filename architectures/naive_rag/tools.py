"""Naive RAG tool definitions.

Per METHODOLOGY's modularity constraint, the agent reaches the corpus
ONLY through Support Content's `vector_search` tool. This module:

  - defines `vector_search` (Support Content's interface for Naive RAG),
  - re-exports the booking tools (Booking Systems — identical across
    architectures) and `audit_log` (Compliance — identical across
    architectures).

The combined `TOOL_SCHEMAS` and `TOOL_DISPATCH` are what the agent loop
hands to the Anthropic API and uses to resolve tool_use blocks.

Lazy initialisation: the BGE-M3 embedder and ChromaDB collection are
loaded on first call to `vector_search`, not at import. Tests and the
chunker can import this module without paying the model-load cost.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from architectures._shared.audit import AUDIT_TOOL_SCHEMA, audit_log
from architectures._shared.booking_tools import (
    BOOKING_TOOL_DISPATCH,
    BOOKING_TOOL_SCHEMAS,
)

from .setup_vector_store import (
    COLLECTION_NAME,
    EMBEDDING_MODEL_NAME,
    VECTOR_STORE_DIR,
)


# ---------------------------------------------------------------------------
# Vector store handle (lazy init)
# ---------------------------------------------------------------------------


_embedding_model = None
_collection = None


def _get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer

        _embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _embedding_model


def _get_collection():
    global _collection
    if _collection is None:
        import chromadb

        if not VECTOR_STORE_DIR.exists():
            raise FileNotFoundError(
                f"Vector store not found at {VECTOR_STORE_DIR}. Run "
                f"`python -m architectures.naive_rag.setup_vector_store` first."
            )
        client = chromadb.PersistentClient(path=str(VECTOR_STORE_DIR))
        _collection = client.get_collection(name=COLLECTION_NAME)
    return _collection


def reset_lazy_state() -> None:
    """Test/debug hook — drops the cached model + collection handles."""
    global _embedding_model, _collection
    _embedding_model = None
    _collection = None


# ---------------------------------------------------------------------------
# Support Content interface: vector_search
# ---------------------------------------------------------------------------


# Default per architectures/naive_rag/README.md. Adversarial review
# (Phase 2 Step 10 Check 1) verifies this is tuned, not just defaulted.
DEFAULT_K = 4


def vector_search(query: str, k: int = DEFAULT_K) -> dict[str, Any]:
    """Support Content's retrieval interface for Naive RAG.

    Returns a dict containing the top-k chunks with section_id /
    section_title metadata for citation. The agent sees this serialised
    as JSON in the tool_result content.

    Bounds k to [1, 10] defensively — over-retrieval is a known waste
    pattern (per naive_rag/README.md), and an LLM-supplied k value
    shouldn't be able to blow up retrieved_context tokens.
    """
    bounded_k = max(1, min(int(k), 10))
    model = _get_embedding_model()
    collection = _get_collection()

    query_embedding = model.encode(
        [query], normalize_embeddings=True
    )[0].tolist()
    raw = collection.query(
        query_embeddings=[query_embedding],
        n_results=bounded_k,
    )

    chunks: list[dict[str, Any]] = []
    ids = raw.get("ids", [[]])[0]
    documents = raw.get("documents", [[]])[0]
    metadatas = raw.get("metadatas", [[]])[0]
    distances = raw.get("distances", [[]])[0] if raw.get("distances") else [None] * len(ids)

    for chunk_id, text, meta, dist in zip(ids, documents, metadatas, distances):
        chunks.append(
            {
                "chunk_id": chunk_id,
                "section_id": meta.get("section_id"),
                "section_title": meta.get("section_title"),
                "text": text,
                "distance": dist,
            }
        )
    return {"query": query, "k": bounded_k, "chunks": chunks}


VECTOR_SEARCH_SCHEMA: dict[str, Any] = {
    "name": "vector_search",
    "description": (
        "Search the Swiss Airlines FAQ corpus by semantic similarity. "
        "Returns the top-k most relevant chunks with their section "
        "citations. Use this for any policy or procedure question. "
        "Phrase the query as a natural-language search string, not a "
        "keyword list. Default k=4; raise it only if the first results "
        "don't cover the question."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural-language search query.",
            },
            "k": {
                "type": "integer",
                "description": "Number of chunks to retrieve (1-10, default 4).",
            },
        },
        "required": ["query"],
    },
}


# ---------------------------------------------------------------------------
# Combined registry exposed to the agent loop
# ---------------------------------------------------------------------------


TOOL_SCHEMAS: list[dict[str, Any]] = [
    VECTOR_SEARCH_SCHEMA,
    *BOOKING_TOOL_SCHEMAS,
    AUDIT_TOOL_SCHEMA,
]


def _dispatch_vector_search(query: str, k: int = DEFAULT_K) -> dict[str, Any]:
    # Wrapper so positional `query` calls work uniformly with the
    # kwargs-style booking-tool dispatch below.
    return vector_search(query=query, k=k)


TOOL_DISPATCH: dict[str, Any] = {
    "vector_search": _dispatch_vector_search,
    **BOOKING_TOOL_DISPATCH,
    "audit_log": audit_log,
}


# Tool names whose calls produce category-② "retrieved_context" tokens
# (used by the runner's decomposition logic if it ever wants to attribute
# tokens by source). audit_log is excluded per METHODOLOGY.
RETRIEVAL_TOOL_NAMES: set[str] = {"vector_search"}
AUDIT_TOOL_NAME = "audit_log"


def execute_tool(name: str, arguments: dict[str, Any]) -> Any:
    """Resolve a tool_use block. Unknown tools raise so the runner can
    surface the error rather than the model silently flailing.
    """
    if name not in TOOL_DISPATCH:
        raise KeyError(f"Unknown tool: {name!r}")
    fn = TOOL_DISPATCH[name]
    # audit_log + vector_search are kwarg-only; booking tools accept kwargs.
    return fn(**arguments)


def serialise_tool_result(result: Any) -> str:
    """Tool results travel back to the model as text. JSON is structured
    enough that the model can parse it without a free-text rendering pass.
    """
    return json.dumps(result, default=str, ensure_ascii=False)
