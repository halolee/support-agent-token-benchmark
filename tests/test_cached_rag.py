"""Tests for `architectures/cached_rag/` — wiring + caching markers.

Cached RAG is Naive RAG + cache_control markers on the two stable-prefix
blocks (system prompt and tool definitions). These tests verify:

  1. The wiring is intact (same shape as Naive RAG: schemas == dispatch,
     vector_search + audit_log present, agent registers into the runner).
  2. The caching markers are placed where Phase 3 specifies (system block
     is a typed-block list with cache_control; last tool entry carries
     cache_control).
  3. The shared AUDIT_TOOL_SCHEMA is NOT mutated — Cached RAG attaches
     its cache_control marker to a copy, so Naive RAG / Grep search /
     Hybrid RAG do not accidentally inherit it.

System-prompt token-budget testing is handled by
`tests/test_naive_rag.py::TestPromptTokenBudget` — Cached RAG's prompt
text is identical to Naive RAG's by design, so the budget assertion does
not need to be duplicated.
"""
from __future__ import annotations


class TestToolsRegistry:
    def test_schemas_and_dispatch_match(self):
        from architectures.cached_rag.tools import TOOL_DISPATCH, TOOL_SCHEMAS

        schema_names = {s["name"] for s in TOOL_SCHEMAS}
        dispatch_names = set(TOOL_DISPATCH.keys())
        assert schema_names == dispatch_names

    def test_vector_search_schema_present(self):
        from architectures.cached_rag.tools import TOOL_SCHEMAS

        names = {s["name"] for s in TOOL_SCHEMAS}
        assert "vector_search" in names

    def test_audit_log_dispatch_present(self):
        from architectures.cached_rag.tools import AUDIT_TOOL_NAME, TOOL_DISPATCH

        assert AUDIT_TOOL_NAME in TOOL_DISPATCH


class TestCachingMarkers:
    def test_system_prompt_is_typed_block_list_with_cache_control(self):
        """Cached RAG declares SYSTEM_PROMPT as a list of one typed block
        carrying cache_control. The Anthropic SDK accepts both string and
        list-of-blocks forms for `system`; the list form is required for
        cache_control placement.
        """
        from architectures.cached_rag.prompts import SYSTEM_PROMPT

        assert isinstance(SYSTEM_PROMPT, list)
        assert len(SYSTEM_PROMPT) == 1
        block = SYSTEM_PROMPT[0]
        assert block["type"] == "text"
        assert "text" in block and isinstance(block["text"], str)
        assert block["cache_control"] == {"type": "ephemeral"}

    def test_last_tool_carries_cache_control(self):
        """Anthropic prompt caching: cache_control on a tool entry caches
        every tool from the start of the array up to and including that
        block. Cached RAG places the marker on the LAST entry (audit_log)
        so the entire tool definitions block becomes a single cache
        breakpoint.
        """
        from architectures.cached_rag.tools import TOOL_SCHEMAS

        assert TOOL_SCHEMAS[-1].get("cache_control") == {"type": "ephemeral"}

    def test_intermediate_tools_do_not_carry_cache_control(self):
        """Only the last tool needs the marker. Multiple markers would
        consume extra cache breakpoints (Anthropic's limit: 4 per request)
        without additional caching benefit.
        """
        from architectures.cached_rag.tools import TOOL_SCHEMAS

        for tool in TOOL_SCHEMAS[:-1]:
            assert "cache_control" not in tool, (
                f"Tool {tool.get('name')!r} carries cache_control; only "
                f"the last tool in TOOL_SCHEMAS should be marked. See "
                f"architectures/cached_rag/README.md § 'Cache breakpoint "
                f"placement'."
            )

    def test_shared_audit_schema_not_mutated(self):
        """Cached RAG attaches cache_control to a COPY of AUDIT_TOOL_SCHEMA,
        not the shared one. If this assertion fails, Naive RAG / Grep
        search / Hybrid RAG silently inherited Cached RAG's caching
        marker, which would invalidate the cross-architecture comparison.
        """
        # Force Cached RAG's tools to load (which builds the copy).
        from architectures.cached_rag import tools as _cached_tools  # noqa: F401
        from architectures._shared.audit import AUDIT_TOOL_SCHEMA

        assert "cache_control" not in AUDIT_TOOL_SCHEMA, (
            "Shared AUDIT_TOOL_SCHEMA was mutated to include cache_control. "
            "Cached RAG's tools.py must attach the marker to a copy "
            "(`{**AUDIT_TOOL_SCHEMA, 'cache_control': ...}`), not the "
            "shared dict."
        )


class TestAgentRegistration:
    def test_registers_into_runner_registry(self):
        import architectures.cached_rag.agent  # noqa: F401  (triggers registration)
        from measurement.runner import ARCHITECTURE_REGISTRY

        assert "cached_rag" in ARCHITECTURE_REGISTRY
        assert callable(ARCHITECTURE_REGISTRY["cached_rag"])
