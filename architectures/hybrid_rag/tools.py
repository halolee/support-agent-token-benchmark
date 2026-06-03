"""Hybrid RAG tool definitions.

Per METHODOLOGY's modularity constraint, the agent reaches the corpus
ONLY through Support Content's `hybrid_search` tool. The tool's
internals — vector retrieval + BM25 + RRF fusion + cross-encoder
reranking — are all owned by Support Content. The agent sees only the
final ranked list of chunks, with the same shape as Naive RAG's
`vector_search` result so citation handling is uniform.

  - `hybrid_search(query, k)` is the Support Content interface for
    Hybrid RAG.
  - The booking tools (Booking Systems) and `audit_log` (Compliance)
    are re-exported from `_shared/` verbatim — identical across
    architectures.

Lazy initialisation: the BGE-M3 embedder, ChromaDB collection, BM25
sidecar, and cross-encoder reranker are all loaded on first call to
`hybrid_search`, not at import. Tests and the runner registry can
import this module without paying the model-load cost.
"""
from __future__ import annotations

import json
import math
import pickle
from pathlib import Path
from typing import Any

from architectures._shared.audit import AUDIT_TOOL_SCHEMA, audit_log
from architectures._shared.booking_tools import (
    BOOKING_TOOL_DISPATCH,
    BOOKING_TOOL_SCHEMAS,
)

from .setup_indices import (
    BM25_INDEX_PATH,
    BM25_INDEX_VERSION,
    COLLECTION_NAME,
    EMBEDDING_MODEL_NAME,
    RERANKER_MODEL_NAME,
    VECTOR_STORE_DIR,
    tokenize_for_bm25,
)


# ---------------------------------------------------------------------------
# Tuning knobs — per architectures/hybrid_rag/README.md
# ---------------------------------------------------------------------------

# Per-component top-K before RRF fusion. README spec: 5 from each side,
# combined and deduplicated → up to 10 unique candidates fed to the
# reranker. Raising these widens the reranker's input but doesn't change
# the agent-facing K_final.
VECTOR_TOP_K = 5
BM25_TOP_K = 5

# Default K_final returned to the agent (after reranking).
DEFAULT_K = 6

# Defensive ceiling on the agent-supplied k — mirrors vector_search /
# grep_corpus bounds. An LLM passing k=10000 shouldn't be able to blow up
# retrieved_context tokens. Capped at the K_initial pool size since RRF
# cannot fabricate candidates beyond what the components returned.
_K_CEILING = VECTOR_TOP_K + BM25_TOP_K

# Reciprocal Rank Fusion constant. 60 is the canonical default from
# Cormack et al. (2009) — robust across IR tasks, no per-domain tuning
# needed at this scale.
RRF_K = 60


# ---------------------------------------------------------------------------
# Lazy state
# ---------------------------------------------------------------------------


_embedding_model = None
_collection = None
_bm25 = None
_bm25_payload: dict[str, Any] | None = None
_reranker = None


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
                f"`python -m architectures.hybrid_rag.setup_indices` first."
            )
        client = chromadb.PersistentClient(path=str(VECTOR_STORE_DIR))
        _collection = client.get_collection(name=COLLECTION_NAME)
    return _collection


def _get_bm25():
    """Returns (BM25Okapi, payload) where payload carries chunk_ids,
    chunk_texts, section_ids, section_titles in the same order as the
    BM25Okapi corpus.
    """
    global _bm25, _bm25_payload
    if _bm25 is None:
        from rank_bm25 import BM25Okapi

        if not BM25_INDEX_PATH.exists():
            raise FileNotFoundError(
                f"BM25 index not found at {BM25_INDEX_PATH}. Run "
                f"`python -m architectures.hybrid_rag.setup_indices` first."
            )
        with open(BM25_INDEX_PATH, "rb") as f:
            payload = pickle.load(f)
        version = payload.get("version") if isinstance(payload, dict) else None
        if version != BM25_INDEX_VERSION:
            raise ValueError(
                f"BM25 index version mismatch at {BM25_INDEX_PATH}: "
                f"pickle has version={version!r}, code expects "
                f"{BM25_INDEX_VERSION}. Rebuild with "
                f"`python -m architectures.hybrid_rag.setup_indices`."
            )
        # Build BM25Okapi BEFORE mutating module globals — if construction
        # raises (corrupt corpus, missing key), we don't leave the partial
        # payload visible to subsequent callers.
        bm25_instance = BM25Okapi(payload["tokenised_corpus"])
        _bm25_payload = payload
        _bm25 = bm25_instance
    return _bm25, _bm25_payload


def _get_reranker():
    global _reranker
    if _reranker is None:
        from sentence_transformers import CrossEncoder

        _reranker = CrossEncoder(RERANKER_MODEL_NAME)
    return _reranker


def reset_lazy_state() -> None:
    """Test/debug hook — drops all cached model + index handles."""
    global _embedding_model, _collection, _bm25, _bm25_payload, _reranker
    _embedding_model = None
    _collection = None
    _bm25 = None
    _bm25_payload = None
    _reranker = None


# ---------------------------------------------------------------------------
# Retrieval components
# ---------------------------------------------------------------------------


def _vector_topk(query: str, k: int) -> list[dict[str, Any]]:
    """Top-k vector hits. Returns chunk dicts in rank order (best first)."""
    model = _get_embedding_model()
    collection = _get_collection()
    query_embedding = model.encode([query], normalize_embeddings=True)[0].tolist()
    raw = collection.query(query_embeddings=[query_embedding], n_results=k)

    ids = raw.get("ids", [[]])[0]
    documents = raw.get("documents", [[]])[0]
    metadatas = raw.get("metadatas", [[]])[0]
    out: list[dict[str, Any]] = []
    for chunk_id, text, meta in zip(ids, documents, metadatas):
        out.append(
            {
                "chunk_id": chunk_id,
                "section_id": meta.get("section_id"),
                "section_title": meta.get("section_title"),
                "text": text,
            }
        )
    return out


def _bm25_topk(query: str, k: int) -> list[dict[str, Any]]:
    """Top-k BM25 hits over the same chunks as the vector index. Returns
    chunk dicts in rank order (best first).
    """
    bm25, payload = _get_bm25()
    tokens = tokenize_for_bm25(query)
    if not tokens:
        return []
    scores = bm25.get_scores(tokens)
    # Argsort descending; numpy avoided to keep dependencies thin (rank_bm25
    # already uses numpy internally, but indexing back into plain lists is
    # cleanest with the score→idx zip pattern).
    ranked = sorted(
        range(len(scores)),
        key=lambda i: scores[i],
        reverse=True,
    )[:k]
    out: list[dict[str, Any]] = []
    for idx in ranked:
        # Score of 0 means the query had no shared terms with the chunk —
        # surfacing such "matches" only pollutes the RRF pool. Skip.
        if scores[idx] <= 0:
            break
        out.append(
            {
                "chunk_id": payload["chunk_ids"][idx],
                "section_id": payload["section_ids"][idx],
                "section_title": payload["section_titles"][idx],
                "text": payload["chunk_texts"][idx],
            }
        )
    return out


def _rrf_fuse(
    vector_hits: list[dict[str, Any]],
    bm25_hits: list[dict[str, Any]],
    *,
    rrf_k: int = RRF_K,
) -> list[dict[str, Any]]:
    """Reciprocal Rank Fusion: score(d) = sum_i 1 / (rrf_k + rank_i(d)).

    Equal weighting per README — tuning the weights is a Phase 2 Step 10
    adversarial-review knob, not a v1 default. Returns chunks ordered by
    fused score (highest first), deduplicated by chunk_id.
    """
    fused: dict[str, dict[str, Any]] = {}
    fused_scores: dict[str, float] = {}

    for rank, hit in enumerate(vector_hits, start=1):
        cid = hit["chunk_id"]
        fused.setdefault(cid, hit)
        fused_scores[cid] = fused_scores.get(cid, 0.0) + 1.0 / (rrf_k + rank)

    for rank, hit in enumerate(bm25_hits, start=1):
        cid = hit["chunk_id"]
        fused.setdefault(cid, hit)
        fused_scores[cid] = fused_scores.get(cid, 0.0) + 1.0 / (rrf_k + rank)

    # Stable order: descending fused score, ties broken by first-seen order.
    seen_order = list(fused.keys())
    ranked_ids = sorted(
        seen_order,
        key=lambda cid: (-fused_scores[cid], seen_order.index(cid)),
    )
    return [fused[cid] for cid in ranked_ids]


def _safe_rerank_score(raw: Any) -> float:
    """Coerce a reranker score to float; map NaN to -inf so the sort
    places degenerate scores last DETERMINISTICALLY. Python's sorted()
    has undefined behaviour with NaN keys — a single NaN can shuffle
    results across runs and break METHODOLOGY's median-of-three
    reproducibility contract.
    """
    v = float(raw)
    return float("-inf") if math.isnan(v) else v


def _rerank(query: str, candidates: list[dict[str, Any]], k: int) -> list[dict[str, Any]]:
    """Cross-encoder rerank. Returns top-k candidates in reranked order,
    each annotated with a `score` field (None if rerank was skipped).

    Skipped if candidates are empty or only one (nothing to reorder).
    """
    if len(candidates) <= 1:
        for c in candidates:
            c.setdefault("score", None)
        return candidates[:k]
    reranker = _get_reranker()
    pairs = [(query, c["text"]) for c in candidates]
    scores = reranker.predict(pairs)
    ranked = sorted(
        zip(candidates, scores),
        key=lambda pair: _safe_rerank_score(pair[1]),
        reverse=True,
    )
    out: list[dict[str, Any]] = []
    for c, s in ranked[:k]:
        v = float(s)
        c["score"] = None if math.isnan(v) else v
        out.append(c)
    return out


# ---------------------------------------------------------------------------
# Support Content interface: hybrid_search
# ---------------------------------------------------------------------------


def hybrid_search(query: str, k: int = DEFAULT_K) -> dict[str, Any]:
    """Support Content's retrieval interface for Hybrid RAG.

    Pipeline: vector top-K + BM25 top-K → RRF fusion (deduplicated) →
    cross-encoder rerank → top-k. Returns a dict containing the top-k
    chunks with section_id / section_title metadata for citation. The
    agent sees this serialised as JSON in the tool_result content —
    same shape as `vector_search` so the agent's citation handling is
    uniform.

    Bounds k to [1, VECTOR_TOP_K + BM25_TOP_K] defensively — RRF cannot
    produce more candidates than the union of its inputs, and an LLM
    passing an absurd k shouldn't be able to blow up retrieved_context
    tokens.

    Non-int / None `k` (the schema declares integer, but the SDK forwards
    raw JSON so a `k: null` payload arrives as Python None) is coerced
    to DEFAULT_K rather than raising — the alternative inflates
    agent_intermediate tokens via an error tool_result + model retry,
    asymmetrically penalising hybrid_rag's measured cost.
    """
    try:
        k_int = int(k)
    except (TypeError, ValueError):
        k_int = DEFAULT_K
    bounded_k = max(1, min(k_int, _K_CEILING))

    vector_hits = _vector_topk(query, VECTOR_TOP_K)
    bm25_hits = _bm25_topk(query, BM25_TOP_K)
    fused = _rrf_fuse(vector_hits, bm25_hits)
    reranked = _rerank(query, fused, bounded_k)

    return {
        "query": query,
        "k": bounded_k,
        "chunks": [
            {
                "chunk_id": c["chunk_id"],
                "section_id": c["section_id"],
                "section_title": c["section_title"],
                "text": c["text"],
                # Cross-encoder rerank score — parallels naive_rag's per-chunk
                # `distance` so downstream tuning/debugging has retrieval-
                # quality signal at parity across architectures. None when
                # rerank was skipped (≤1 candidate).
                "score": c.get("score"),
            }
            for c in reranked
        ],
    }


HYBRID_SEARCH_SCHEMA: dict[str, Any] = {
    "name": "hybrid_search",
    "description": (
        "Search the Swiss Airlines FAQ corpus. Returns the top-k most "
        "relevant chunks with their section citations. Use this for any "
        "policy or procedure question. Phrase the query as a natural-"
        "language search string, not a keyword list. Default k=6; raise "
        "it only if the first results don't cover the question."
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
                "description": "Number of chunks to retrieve (1-10, default 6).",
            },
        },
        "required": ["query"],
    },
}


# ---------------------------------------------------------------------------
# Combined registry exposed to the agent loop
# ---------------------------------------------------------------------------


TOOL_SCHEMAS: list[dict[str, Any]] = [
    HYBRID_SEARCH_SCHEMA,
    *BOOKING_TOOL_SCHEMAS,
    AUDIT_TOOL_SCHEMA,
]


def _dispatch_hybrid_search(query: str, k: int = DEFAULT_K) -> dict[str, Any]:
    return hybrid_search(query=query, k=k)


TOOL_DISPATCH: dict[str, Any] = {
    "hybrid_search": _dispatch_hybrid_search,
    **BOOKING_TOOL_DISPATCH,
    "audit_log": audit_log,
}


# Tool names whose calls produce category-② "retrieved_context" tokens.
# audit_log is excluded per METHODOLOGY §"Audit log specification".
RETRIEVAL_TOOL_NAMES: set[str] = {"hybrid_search"}
AUDIT_TOOL_NAME = "audit_log"


def execute_tool(name: str, arguments: dict[str, Any]) -> Any:
    """Resolve a tool_use block. Unknown tools raise so the runner can
    surface the error rather than the model silently flailing.
    """
    if name not in TOOL_DISPATCH:
        raise KeyError(f"Unknown tool: {name!r}")
    fn = TOOL_DISPATCH[name]
    return fn(**arguments)


def serialise_tool_result(result: Any) -> str:
    """Tool results travel back to the model as text. JSON is structured
    enough that the model can parse it without a free-text rendering pass.
    """
    return json.dumps(result, default=str, ensure_ascii=False)
