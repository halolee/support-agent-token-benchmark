"""Tests for `architectures/hybrid_rag/` — tools, prompts, agent wiring.

Same shape as `tests/test_naive_rag.py` and `tests/test_grep_search.py`:

  - schemas/dispatch match,
  - hybrid_search bounds and pure-function fusion logic exercised without
    loading any models (RRF is a pure function),
  - end-to-end retrieval against the live BGE-M3 + ChromaDB + BM25 +
    cross-encoder pipeline is marked `slow` and skipped if the indices
    haven't been built,
  - system prompt sits in the ~500-token target band (live_api).
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Schemas and dispatch
# ---------------------------------------------------------------------------


class TestToolsRegistry:
    def test_schemas_and_dispatch_match(self):
        from architectures.hybrid_rag.tools import TOOL_DISPATCH, TOOL_SCHEMAS

        schema_names = {s["name"] for s in TOOL_SCHEMAS}
        dispatch_names = set(TOOL_DISPATCH.keys())
        assert schema_names == dispatch_names

    def test_hybrid_search_schema_present(self):
        from architectures.hybrid_rag.tools import TOOL_SCHEMAS

        names = {s["name"] for s in TOOL_SCHEMAS}
        assert "hybrid_search" in names

    def test_audit_log_dispatch_present(self):
        from architectures.hybrid_rag.tools import AUDIT_TOOL_NAME, TOOL_DISPATCH

        assert AUDIT_TOOL_NAME in TOOL_DISPATCH

    def test_booking_tools_present(self):
        from architectures.hybrid_rag.tools import TOOL_DISPATCH

        # Identical-across-architectures invariant: booking tools must be
        # the same set as Naive RAG / Grep search. Spot-check the 5 named
        # in CLAUDE.md.
        for name in (
            "get_booking_status",
            "get_flight_status",
            "search_flights",
            "search_hotels",
            "search_cars",
        ):
            assert name in TOOL_DISPATCH

    def test_unknown_tool_raises_keyerror(self):
        from architectures.hybrid_rag.tools import execute_tool

        with pytest.raises(KeyError, match="Unknown tool"):
            execute_tool("nonexistent", {})

    def test_hybrid_search_schema_documents_default_k(self):
        from architectures.hybrid_rag.tools import DEFAULT_K, HYBRID_SEARCH_SCHEMA

        assert DEFAULT_K == 6
        assert (
            HYBRID_SEARCH_SCHEMA["input_schema"]["properties"]["k"]["type"]
            == "integer"
        )


# ---------------------------------------------------------------------------
# Pure-function fusion logic (no models loaded)
# ---------------------------------------------------------------------------


def _hit(chunk_id: str, section_id: str = "x") -> dict:
    return {
        "chunk_id": chunk_id,
        "section_id": section_id,
        "section_title": section_id,
        "text": f"text-of-{chunk_id}",
    }


class TestRRFFusion:
    def test_overlapping_chunks_score_higher_than_singletons(self):
        """A chunk that appears in BOTH lists should rank ahead of any
        chunk that appears in only one — RRF's whole point.
        """
        from architectures.hybrid_rag.tools import _rrf_fuse

        vector = [_hit("A"), _hit("B"), _hit("C")]
        bm25 = [_hit("X"), _hit("A"), _hit("Y")]
        out = _rrf_fuse(vector, bm25)
        ids = [c["chunk_id"] for c in out]
        # A appears in both (ranks 1 and 2) → highest fused score.
        assert ids[0] == "A"

    def test_dedup_preserves_first_seen_chunk_dict(self):
        """A chunk appearing in both inputs is emitted once, with the
        first-seen dict (so vector-side metadata wins when identical
        chunk_id appears in both, but in practice they're built from the
        same chunker so the dicts match).
        """
        from architectures.hybrid_rag.tools import _rrf_fuse

        vector = [_hit("A", "vector-section")]
        bm25 = [_hit("A", "bm25-section")]
        out = _rrf_fuse(vector, bm25)
        assert len(out) == 1
        assert out[0]["section_id"] == "vector-section"

    def test_empty_lists_return_empty(self):
        from architectures.hybrid_rag.tools import _rrf_fuse

        assert _rrf_fuse([], []) == []

    def test_one_empty_list_returns_other(self):
        from architectures.hybrid_rag.tools import _rrf_fuse

        vector = [_hit("A"), _hit("B")]
        out = _rrf_fuse(vector, [])
        assert [c["chunk_id"] for c in out] == ["A", "B"]

    def test_empty_vector_returns_bm25_hits(self):
        """Symmetric to test_one_empty_list_returns_other — guards
        against a refactor that accidentally drops the BM25 loop.
        """
        from architectures.hybrid_rag.tools import _rrf_fuse

        bm25 = [_hit("X"), _hit("Y")]
        out = _rrf_fuse([], bm25)
        assert [c["chunk_id"] for c in out] == ["X", "Y"]

    def test_rank_within_list_drives_score(self):
        """Rank 1 contributes 1/(k+1); rank 2 contributes 1/(k+2). So a
        chunk at rank 1 in one list should beat a chunk at rank 5 in
        the same list when both are unique.
        """
        from architectures.hybrid_rag.tools import _rrf_fuse

        vector = [_hit(f"V{i}") for i in range(1, 6)]
        bm25: list[dict] = []
        out = _rrf_fuse(vector, bm25)
        assert [c["chunk_id"] for c in out] == ["V1", "V2", "V3", "V4", "V5"]


class TestHybridSearchBounds:
    def test_k_ceiling_documented(self):
        from architectures.hybrid_rag.tools import (
            BM25_TOP_K,
            VECTOR_TOP_K,
            _K_CEILING,
        )

        # K_initial pool = vector top-K + BM25 top-K. README spec: 5 + 5.
        assert VECTOR_TOP_K == 5
        assert BM25_TOP_K == 5
        assert _K_CEILING == VECTOR_TOP_K + BM25_TOP_K

    def test_hybrid_search_clamps_oversized_k_without_models(self, monkeypatch):
        """Fast unit test for the k clamp — stubs the retrieval components
        so we exercise the bound without loading BGE-M3 or the cross-
        encoder. The `slow` end-to-end test covers the same path against
        real indices; this one runs in default pytest and catches a
        regression that removes the max(1, min(int(k), _K_CEILING)) wrap.
        """
        from architectures.hybrid_rag import tools

        monkeypatch.setattr(
            tools,
            "_vector_topk",
            lambda q, n: [_hit(f"V{i}") for i in range(n)],
        )
        monkeypatch.setattr(
            tools,
            "_bm25_topk",
            lambda q, n: [_hit(f"B{i}") for i in range(n)],
        )
        # Bypass the cross-encoder load — return the candidates trimmed
        # to k so we can observe the clamp without invoking the model.
        monkeypatch.setattr(tools, "_rerank", lambda q, c, k: c[:k])

        result = tools.hybrid_search("anything", k=10_000)
        assert result["k"] == tools._K_CEILING
        assert len(result["chunks"]) <= tools._K_CEILING

    def test_hybrid_search_coerces_non_int_k_to_default(self, monkeypatch):
        """Schema declares k as integer but the Anthropic SDK forwards
        raw JSON — `k: null` arrives as Python None. int(None) would
        TypeError out of dispatch; coerce to DEFAULT_K instead.
        """
        from architectures.hybrid_rag import tools

        monkeypatch.setattr(tools, "_vector_topk", lambda q, n: [])
        monkeypatch.setattr(tools, "_bm25_topk", lambda q, n: [])
        monkeypatch.setattr(tools, "_rerank", lambda q, c, k: c[:k])

        # k=None (model passed "k": null)
        result_none = tools.hybrid_search("x", k=None)
        assert result_none["k"] == tools.DEFAULT_K
        # k="abc" (model hallucinated a non-numeric string)
        result_str = tools.hybrid_search("x", k="abc")
        assert result_str["k"] == tools.DEFAULT_K


class TestBM25Tokenizer:
    def test_lowercase_word_split(self):
        from architectures.hybrid_rag.setup_indices import tokenize_for_bm25

        assert tokenize_for_bm25("Pay per Invoice") == ["pay", "per", "invoice"]

    def test_strips_punctuation(self):
        from architectures.hybrid_rag.setup_indices import tokenize_for_bm25

        assert tokenize_for_bm25("hello, world!") == ["hello", "world"]

    def test_preserves_alphanumeric_tokens(self):
        from architectures.hybrid_rag.setup_indices import tokenize_for_bm25

        # Flight numbers, fare codes, etc. should survive tokenisation.
        assert tokenize_for_bm25("Flight LX317 and ticket 724") == [
            "flight",
            "lx317",
            "and",
            "ticket",
            "724",
        ]

    def test_empty_string_yields_empty(self):
        from architectures.hybrid_rag.setup_indices import tokenize_for_bm25

        assert tokenize_for_bm25("") == []


# ---------------------------------------------------------------------------
# System prompt token budget
# ---------------------------------------------------------------------------


class TestPromptTokenBudget:
    @pytest.mark.live_api
    @pytest.mark.requires_api_key
    def test_system_prompt_in_target_band(self):
        """Per architectures/hybrid_rag/README.md and CLAUDE.md: ~500
        tokens. Allow ±20% band; outside is a design drift signal.
        """
        import anthropic

        from architectures.hybrid_rag.prompts import SYSTEM_PROMPT
        from measurement.tokens import AGENT_MODEL

        client = anthropic.Anthropic()
        response = client.beta.messages.count_tokens(
            model=AGENT_MODEL,
            messages=[{"role": "user", "content": SYSTEM_PROMPT}],
        )
        n = response.input_tokens
        assert 400 <= n <= 600, (
            f"System prompt is {n} tokens; target is ~500 (±20%). "
            f"Update prompts.py or revise the band consciously."
        )


# ---------------------------------------------------------------------------
# Agent registration
# ---------------------------------------------------------------------------


class TestAgentRegistration:
    def test_registers_into_runner_registry(self, monkeypatch):
        """Actively exercise _register(): drop any pre-existing
        `hybrid_rag` entry and force a fresh module import so the test
        verifies the registration code path actually runs — not just
        that some prior test left a stub behind.
        """
        import sys

        from measurement.runner import ARCHITECTURE_REGISTRY

        monkeypatch.delitem(ARCHITECTURE_REGISTRY, "hybrid_rag", raising=False)
        sys.modules.pop("architectures.hybrid_rag.agent", None)

        import architectures.hybrid_rag.agent  # noqa: F401  (triggers registration)

        assert "hybrid_rag" in ARCHITECTURE_REGISTRY
        assert callable(ARCHITECTURE_REGISTRY["hybrid_rag"])

    def test_register_surfaces_broken_runner_import(self, monkeypatch):
        """Issue #33: if measurement.runner exists but `register_architecture`
        can't be imported (e.g., a transitive import failed), `_register()`
        must surface the ImportError — not silently pass.
        """
        import measurement.runner

        from architectures.hybrid_rag.agent import _register

        monkeypatch.delattr(measurement.runner, "register_architecture")
        with pytest.raises(ImportError):
            _register()


# ---------------------------------------------------------------------------
# End-to-end retrieval against real indices (slow)
# ---------------------------------------------------------------------------


class TestHybridSearchEndToEnd:
    @pytest.mark.slow
    def test_returns_chunks_with_citation_metadata(self):
        """Run a real query against the live indices. Marked slow because
        it loads BGE-M3 (~2.3GB) + cross-encoder (~80MB) into memory.
        """
        from architectures.hybrid_rag.setup_indices import (
            BM25_INDEX_PATH,
            VECTOR_STORE_DIR,
        )

        if not VECTOR_STORE_DIR.exists() or not BM25_INDEX_PATH.exists():
            pytest.skip(
                "Hybrid RAG indices not built — run "
                "`python -m architectures.hybrid_rag.setup_indices`"
            )
        from architectures.hybrid_rag.tools import hybrid_search

        result = hybrid_search("pay per invoice eligibility", k=3)
        assert "chunks" in result
        chunks = result["chunks"]
        assert len(chunks) <= 3
        for chunk in chunks:
            assert "chunk_id" in chunk
            assert "section_id" in chunk
            assert "section_title" in chunk
            assert "text" in chunk
            assert isinstance(chunk["section_id"], str)

    @pytest.mark.slow
    def test_k_clamped_to_pool_size(self):
        """hybrid_search bounds k to the K_initial pool size — an LLM
        passing k=10000 shouldn't blow up retrieved_context. Returns at
        most _K_CEILING chunks regardless of input.
        """
        from architectures.hybrid_rag.setup_indices import (
            BM25_INDEX_PATH,
            VECTOR_STORE_DIR,
        )

        if not VECTOR_STORE_DIR.exists() or not BM25_INDEX_PATH.exists():
            pytest.skip("Hybrid RAG indices not built")
        from architectures.hybrid_rag.tools import _K_CEILING, hybrid_search

        result = hybrid_search("invoice", k=10_000)
        assert result["k"] == _K_CEILING
        assert len(result["chunks"]) <= _K_CEILING
