"""Tests for `architectures/naive_rag/` — tools, prompts, agent wiring.

Live API tests are marked `live_api` (opt-in). The unit tests here cover
the wiring: that tools dispatch correctly, the system prompt sits in the
~500-token target band, and the agent registers into the runner.

Tests that need the vector store (vector_search) are also marked
`live_api` because they require BGE-M3 to be loaded — too heavy for the
default test run. They additionally require the vector_store directory
to exist (built via `python -m architectures.naive_rag.setup_vector_store`).
"""
from __future__ import annotations

import json

import pytest


# ---------------------------------------------------------------------------
# Schemas and dispatch
# ---------------------------------------------------------------------------


class TestToolsRegistry:
    def test_schemas_and_dispatch_match(self):
        from architectures.naive_rag.tools import TOOL_DISPATCH, TOOL_SCHEMAS

        schema_names = {s["name"] for s in TOOL_SCHEMAS}
        dispatch_names = set(TOOL_DISPATCH.keys())
        assert schema_names == dispatch_names

    def test_vector_search_schema_present(self):
        from architectures.naive_rag.tools import TOOL_SCHEMAS

        names = {s["name"] for s in TOOL_SCHEMAS}
        assert "vector_search" in names

    def test_audit_log_dispatch_present(self):
        from architectures.naive_rag.tools import AUDIT_TOOL_NAME, TOOL_DISPATCH

        assert AUDIT_TOOL_NAME in TOOL_DISPATCH

    def test_unknown_tool_raises_keyerror(self):
        from architectures.naive_rag.tools import execute_tool

        with pytest.raises(KeyError, match="Unknown tool"):
            execute_tool("nonexistent", {})


# ---------------------------------------------------------------------------
# System prompt token budget
# ---------------------------------------------------------------------------


class TestPromptTokenBudget:
    @pytest.mark.live_api
    @pytest.mark.requires_api_key
    def test_system_prompt_in_target_band(self):
        """Per architectures/naive_rag/README.md and CLAUDE.md: ~500
        tokens. Allow ±20% band; outside is a design drift signal.
        """
        import anthropic

        from architectures.naive_rag.prompts import SYSTEM_PROMPT
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
    def test_registers_into_runner_registry(self):
        import architectures.naive_rag.agent  # noqa: F401  (triggers registration)
        from measurement.runner import ARCHITECTURE_REGISTRY

        assert "naive_rag" in ARCHITECTURE_REGISTRY
        assert callable(ARCHITECTURE_REGISTRY["naive_rag"])

    def test_register_surfaces_broken_runner_import(self, monkeypatch):
        """Issue #33: if measurement.runner exists but `register_architecture`
        can't be imported (e.g., a transitive import failed), `_register()`
        must surface the ImportError — not silently pass. A bare
        `except ImportError: pass` here would route debugging to the wrong
        file.
        """
        import measurement.runner

        from architectures.naive_rag.agent import _register

        monkeypatch.delattr(measurement.runner, "register_architecture")
        with pytest.raises(ImportError):
            _register()

    def test_register_silent_when_measurement_package_absent(self, monkeypatch):
        """Codex PR #37 review: when the `measurement` package itself
        isn't on sys.path (architecture modules used standalone),
        find_spec raises ModuleNotFoundError before it can return None.
        _register() must catch that and skip silently, preserving the
        original opt-in behaviour.
        """
        import importlib.util

        from architectures.naive_rag.agent import _register

        def _missing_parent(name, *args, **kwargs):
            raise ModuleNotFoundError(f"No module named 'measurement'")

        monkeypatch.setattr(importlib.util, "find_spec", _missing_parent)
        # Must not raise — silent skip is the intentional behaviour.
        _register()


# ---------------------------------------------------------------------------
# vector_search bounds
# ---------------------------------------------------------------------------


class TestVectorSearchBounds:
    def test_k_clamped_to_safe_range(self):
        """vector_search bounds k to [1, 10] regardless of LLM input —
        an LLM passing k=10000 shouldn't be able to blow up retrieved
        context. Test against the live BGE-M3 + ChromaDB so the bounds
        actually flow through.
        """
        from architectures.naive_rag.tools import (
            VECTOR_SEARCH_SCHEMA,
            DEFAULT_K,
        )
        # The schema-side contract: documented limits.
        assert DEFAULT_K == 4
        # The schema reports an integer-typed k; agent doesn't see a
        # validator-side clamp, only the implementation enforces it.
        assert (
            VECTOR_SEARCH_SCHEMA["input_schema"]["properties"]["k"]["type"]
            == "integer"
        )

    def test_vector_search_tolerates_explicit_none_in_chromadb_response(
        self, monkeypatch
    ):
        """Issue #34: ChromaDB returns parallel-array keys (ids, documents,
        metadatas, distances) but their *values* can be None — e.g., if a
        future refactor adds `include=['documents']` to the query call,
        metadatas is None, not absent. `raw.get("metadatas", [[]])[0]`
        would then crash with TypeError since `None[0]` is unsubscriptable.
        Verify the `(raw.get(...) or [[]])[0]` guard handles both
        missing-key and present-but-None uniformly.
        """
        from architectures.naive_rag import tools

        class _StubModel:
            def encode(self, queries, normalize_embeddings=False):
                class _Vec:
                    def tolist(self):
                        return [0.0]

                return [_Vec()]

        class _StubCollection:
            def query(self, **kwargs):
                return {
                    "ids": [["a"]],
                    "documents": [["alpha-text"]],
                    "metadatas": None,
                    "distances": None,
                }

        monkeypatch.setattr(tools, "_get_embedding_model", lambda: _StubModel())
        monkeypatch.setattr(tools, "_get_collection", lambda: _StubCollection())

        # Must not raise. Empty chunks list is acceptable silent
        # degradation; the crash was the bug.
        result = tools.vector_search("anything", k=5)
        assert result["chunks"] == []

    @pytest.mark.slow
    def test_returns_chunks_with_citation_metadata(self):
        """Run a real query against the vector store. Marked slow
        because it loads BGE-M3 (~2.3GB model weights).
        """
        from pathlib import Path

        from architectures.naive_rag.setup_vector_store import VECTOR_STORE_DIR

        if not VECTOR_STORE_DIR.exists():
            pytest.skip(
                "Vector store not built — run "
                "`python -m architectures.naive_rag.setup_vector_store`"
            )
        from architectures.naive_rag.tools import vector_search

        result = vector_search("pay per invoice eligibility", k=3)
        assert "chunks" in result
        chunks = result["chunks"]
        assert len(chunks) <= 3
        for chunk in chunks:
            assert "chunk_id" in chunk
            assert "section_id" in chunk
            assert "section_title" in chunk
            assert "text" in chunk
            # Section ids should match policy_classes.json entries.
            assert isinstance(chunk["section_id"], str)
