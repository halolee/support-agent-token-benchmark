"""Tests for `architectures/grep_search/` — tools, prompts, agent wiring.

Live API tests are marked `live_api` (opt-in). The unit tests here cover
the wiring: that tools dispatch correctly, the grep_corpus implementation
behaves per `architectures/grep_search/README.md`, the system prompt sits
in the ~300-400 token target band, and the agent registers into the runner.

grep_corpus tests do NOT need the API — they exercise the real corpus
file on disk, which is checked in (the LangGraph reference asset).
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Schemas and dispatch
# ---------------------------------------------------------------------------


class TestToolsRegistry:
    def test_schemas_and_dispatch_match(self):
        from architectures.grep_search.tools import TOOL_DISPATCH, TOOL_SCHEMAS

        schema_names = {s["name"] for s in TOOL_SCHEMAS}
        dispatch_names = set(TOOL_DISPATCH.keys())
        assert schema_names == dispatch_names

    def test_grep_corpus_schema_present(self):
        from architectures.grep_search.tools import TOOL_SCHEMAS

        names = {s["name"] for s in TOOL_SCHEMAS}
        assert "grep_corpus" in names

    def test_audit_log_dispatch_present(self):
        from architectures.grep_search.tools import AUDIT_TOOL_NAME, TOOL_DISPATCH

        assert AUDIT_TOOL_NAME in TOOL_DISPATCH

    def test_booking_tools_present(self):
        from architectures.grep_search.tools import TOOL_DISPATCH

        # Identical-across-architectures invariant: booking tools must be
        # the same set as Naive RAG. Spot-check the 5 named in CLAUDE.md.
        for name in (
            "get_booking_status",
            "get_flight_status",
            "search_flights",
            "search_hotels",
            "search_cars",
        ):
            assert name in TOOL_DISPATCH

    def test_unknown_tool_raises_keyerror(self):
        from architectures.grep_search.tools import execute_tool

        with pytest.raises(KeyError, match="Unknown tool"):
            execute_tool("nonexistent", {})


# ---------------------------------------------------------------------------
# grep_corpus behavior
# ---------------------------------------------------------------------------


class TestGrepCorpus:
    def test_returns_matches_with_citation_metadata(self):
        from architectures.grep_search.tools import grep_corpus

        result = grep_corpus(keywords=["pay per invoice"], max_results=5)
        assert "matches" in result
        assert result["matches"], "expected at least one match for 'pay per invoice'"
        for m in result["matches"]:
            # Citation parity with vector_search — agents must be able to
            # cite by section_title and section_id.
            assert "section_id" in m
            assert "section_title" in m
            assert "line_number" in m
            assert "matched_line" in m
            assert "context" in m
            assert m["section_id"] == "pay-per-invoice"
            assert m["section_title"] == "Pay per invoice"

    def test_case_insensitive(self):
        from architectures.grep_search.tools import grep_corpus

        lower = grep_corpus(keywords=["powerpay"])
        upper = grep_corpus(keywords=["POWERPAY"])
        mixed = grep_corpus(keywords=["PowerPay"])
        lines = lambda r: {m["line_number"] for m in r["matches"]}
        assert lines(lower) == lines(upper) == lines(mixed)
        assert lines(lower), "expected POWERPAY to match somewhere in the corpus"

    def test_multi_keyword_dedup_by_line(self):
        """A line that matches two keywords appears once, with both
        keywords in `matched_keywords`. Per README:
        'Multi-keyword support: when multiple keywords passed, returns
        matches for each, deduplicated.'
        """
        from architectures.grep_search.tools import grep_corpus

        # Both keywords appear in the Pay per invoice eligibility line.
        result = grep_corpus(
            keywords=["Switzerland", "Liechtenstein"], max_results=20
        )
        # Look for the eligibility line that contains both.
        eligibility = [
            m for m in result["matches"]
            if "Switzerland" in m["matched_line"] and "Liechtenstein" in m["matched_line"]
        ]
        assert eligibility, "expected at least one line containing both keywords"
        for m in eligibility:
            # Both keywords credited to the same line, not two separate matches.
            assert set(m["matched_keywords"]) == {"Switzerland", "Liechtenstein"}

    def test_max_results_clamped(self):
        from architectures.grep_search.tools import grep_corpus
        from architectures.grep_search.tools import _MAX_RESULTS_CEILING

        # Pass an absurd max_results — must clamp to the ceiling.
        r = grep_corpus(keywords=["the"], max_results=10_000)
        assert len(r["matches"]) <= _MAX_RESULTS_CEILING
        assert r["max_results"] == _MAX_RESULTS_CEILING

    def test_context_lines_clamped(self):
        from architectures.grep_search.tools import grep_corpus, _CONTEXT_LINES_CEILING

        r = grep_corpus(keywords=["invoice"], max_results=1, context_lines=999)
        assert r["context_lines"] == _CONTEXT_LINES_CEILING

    def test_no_matches_returns_empty_list(self):
        from architectures.grep_search.tools import grep_corpus

        r = grep_corpus(keywords=["asdfghjklqwertyuiopzxcvbnm"])
        assert r["matches"] == []

    def test_empty_keywords_returns_empty(self):
        from architectures.grep_search.tools import grep_corpus

        # Empty list, whitespace-only entries, None-shaped — all handled.
        assert grep_corpus(keywords=[])["matches"] == []
        assert grep_corpus(keywords=["", "   "])["matches"] == []

    def test_non_list_keywords_returns_error_shape(self):
        from architectures.grep_search.tools import grep_corpus

        r = grep_corpus(keywords="not a list")  # type: ignore[arg-type]
        assert r["matches"] == []
        assert "error" in r

    def test_matches_in_corpus_order(self):
        from architectures.grep_search.tools import grep_corpus

        r = grep_corpus(keywords=["the"], max_results=10)
        line_numbers = [m["line_number"] for m in r["matches"]]
        assert line_numbers == sorted(line_numbers), (
            "matches should be returned in corpus (line-number) order for "
            "deterministic results"
        )

    def test_context_does_not_bleed_across_section_boundary(self):
        """A match within `context_lines` of an H2 boundary must not
        pull adjacent-section text into its context block — the agent
        would otherwise see foreign-section content under this match's
        citation. Codex PR #18 P2.

        Scenario: match on the H2 heading line of "Booking and
        Cancellation" with context_lines=5. Without clamping, backward
        context would include the tail of "Invoice Questions" (which
        ends just before line 26).
        """
        from architectures.grep_search.tools import _get_index, grep_corpus

        r = grep_corpus(
            keywords=["Booking and Cancellation"],
            max_results=10,
            context_lines=5,
        )
        heading_match = next(
            (
                m for m in r["matches"]
                if m["section_id"] == "booking-and-cancellation"
                and m["matched_line"].startswith("## ")
            ),
            None,
        )
        assert heading_match is not None, (
            "expected a match on the 'Booking and Cancellation' H2 line"
        )

        # Every non-blank line in the returned context must belong to
        # the same section as the match. Re-derive each context line's
        # section by matching against the index. (We use line_number-
        # anchored lookup so duplicate texts like blank lines don't
        # collide across sections.)
        index = _get_index()
        match_lineno = heading_match["line_number"]
        ctx_text = heading_match["context"].split("\n")

        # ctx_text starts at some ctx_start ≤ match_lineno. Find the
        # offset by aligning ctx_text[0] with the index.
        ctx_start = None
        for candidate in range(max(1, match_lineno - 5), match_lineno + 1):
            if index[candidate - 1].text == ctx_text[0]:
                # Confirm the full slice aligns.
                slice_lines = [
                    index[candidate - 1 + i].text for i in range(len(ctx_text))
                ]
                if slice_lines == ctx_text:
                    ctx_start = candidate
                    break
        assert ctx_start is not None, "could not anchor context block back to index"

        for offset, _ in enumerate(ctx_text):
            real_line = index[ctx_start - 1 + offset]
            assert real_line.section_id == heading_match["section_id"], (
                f"context bled across boundary at line "
                f"{real_line.line_number}: section_id="
                f"{real_line.section_id!r} but match cites "
                f"{heading_match['section_id']!r}"
            )

    def test_context_window_does_not_crash_at_edges(self):
        """First and last lines of the corpus shouldn't index-error when
        building the ±context window.
        """
        from architectures.grep_search.tools import _get_index, grep_corpus

        index = _get_index()
        # First content line of the corpus is "## Invoice Questions" (line 1).
        # Confirm we can match on a substring of it and the context block
        # is non-empty without indexing below line 1.
        r = grep_corpus(keywords=["Invoice Questions"], context_lines=5)
        first = next(
            (m for m in r["matches"] if m["line_number"] == 1), None
        )
        assert first is not None, "expected 'Invoice Questions' match on line 1"
        assert first["context"], "context block should be non-empty"

        # Last line of the corpus — grep something unique near the end.
        last_lineno = len(index)
        # Walk back to find a non-empty line near the bottom.
        tail_line = next(
            (l for l in reversed(index) if l.text.strip()),
            None,
        )
        if tail_line is not None and tail_line.text.strip():
            # Pick a token from the tail line itself.
            token = tail_line.text.strip().split()[0]
            if len(token) >= 4:
                r2 = grep_corpus(keywords=[token], context_lines=5)
                # At least one match (the tail line itself) should appear.
                assert any(
                    m["line_number"] == tail_line.line_number for m in r2["matches"]
                )


# ---------------------------------------------------------------------------
# System prompt token budget
# ---------------------------------------------------------------------------


class TestPromptTokenBudget:
    @pytest.mark.live_api
    @pytest.mark.requires_api_key
    def test_system_prompt_in_target_band(self):
        """Per architectures/grep_search/README.md and CLAUDE.md: ~300-400
        tokens. Allow a slightly wider ±25% band (240-500) — outside is
        a design drift signal worth raising consciously.
        """
        import anthropic

        from architectures.grep_search.prompts import SYSTEM_PROMPT
        from measurement.tokens import AGENT_MODEL

        client = anthropic.Anthropic()
        response = client.beta.messages.count_tokens(
            model=AGENT_MODEL,
            messages=[{"role": "user", "content": SYSTEM_PROMPT}],
        )
        n = response.input_tokens
        assert 240 <= n <= 500, (
            f"System prompt is {n} tokens; target is ~300-400 (±25%). "
            f"Update prompts.py or revise the band consciously."
        )


# ---------------------------------------------------------------------------
# Agent registration
# ---------------------------------------------------------------------------


class TestAgentRegistration:
    def test_registers_into_runner_registry(self):
        import architectures.grep_search.agent  # noqa: F401  (triggers registration)
        from measurement.runner import ARCHITECTURE_REGISTRY

        assert "grep_search" in ARCHITECTURE_REGISTRY
        assert callable(ARCHITECTURE_REGISTRY["grep_search"])

    def test_register_surfaces_broken_runner_import(self, monkeypatch):
        """Issue #33: if measurement.runner exists but `register_architecture`
        can't be imported (e.g., a transitive import failed), `_register()`
        must surface the ImportError — not silently pass.
        """
        import measurement.runner

        from architectures.grep_search.agent import _register

        monkeypatch.delattr(measurement.runner, "register_architecture")
        with pytest.raises(ImportError):
            _register()

    def test_register_silent_when_measurement_package_absent(self, monkeypatch):
        """Codex PR #37 review: find_spec raises ModuleNotFoundError when
        the parent `measurement` package isn't on sys.path. _register()
        must catch that and skip silently.
        """
        import importlib.util

        from architectures.grep_search.agent import _register

        def _missing_parent(name, *args, **kwargs):
            raise ModuleNotFoundError(f"No module named 'measurement'")

        monkeypatch.setattr(importlib.util, "find_spec", _missing_parent)
        _register()
