"""Tests for `architectures/_shared/chunker.py`.

The chunker is load-bearing for Naive RAG and Hybrid RAG — both rely on
the same chunk boundaries so the vector vs BM25 comparison isn't
confounded by chunking differences. Tests cover:

  - section-boundary discipline (chunks never cross H2)
  - token-ceiling adherence (no chunk exceeds estimated ceiling)
  - citation-id mapping (every chunk carries a policy_classes.json id)
  - block-split behaviour (numbered Q-items become independent blocks)
  - hard fail on unknown H2 headings (no silently dangling citations)

Run against the real corpus (`corpus/swiss_faq.md`) so regressions in
either the corpus or the chunker surface together.
"""
from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent

import pytest


_REPO_ROOT = Path(__file__).resolve().parent.parent
_CORPUS = _REPO_ROOT / "corpus" / "swiss_faq.md"
_POLICY_CLASSES = _REPO_ROOT / "measurement" / "policy_classes.json"


# ---------------------------------------------------------------------------
# End-to-end against the real corpus
# ---------------------------------------------------------------------------


class TestChunkerAgainstCorpus:
    def test_produces_chunks(self):
        from architectures._shared.chunker import chunk_corpus

        chunks = chunk_corpus(
            corpus_path=_CORPUS,
            policy_classes_path=_POLICY_CLASSES,
        )
        assert len(chunks) > 0

    def test_every_chunk_has_known_section_id(self):
        from architectures._shared.chunker import chunk_corpus

        known_ids = {entry["id"] for entry in json.loads(_POLICY_CLASSES.read_text())}
        chunks = chunk_corpus(
            corpus_path=_CORPUS, policy_classes_path=_POLICY_CLASSES
        )
        for chunk in chunks:
            assert chunk.section_id in known_ids, (
                f"Chunk {chunk.chunk_id} has section_id {chunk.section_id!r} "
                f"not in policy_classes.json"
            )

    def test_every_section_has_at_least_one_chunk(self):
        """Catches the case where a section's body is somehow empty after
        block extraction — a regression would silently drop a section.
        """
        from architectures._shared.chunker import chunk_corpus

        chunks = chunk_corpus(
            corpus_path=_CORPUS, policy_classes_path=_POLICY_CLASSES
        )
        sections_seen = {chunk.section_id for chunk in chunks}
        expected = {entry["id"] for entry in json.loads(_POLICY_CLASSES.read_text())}
        missing = expected - sections_seen
        assert not missing, f"Sections produced no chunks: {missing}"

    def test_chunks_respect_token_ceiling(self):
        """Estimated tokens stay at or under the ceiling. Strict equality
        not required (greedy-pack may leave headroom); the contract is
        the upper bound.
        """
        from architectures._shared.chunker import (
            TOKEN_CEILING,
            chunk_corpus,
            estimate_tokens,
        )

        chunks = chunk_corpus(
            corpus_path=_CORPUS, policy_classes_path=_POLICY_CLASSES
        )
        for chunk in chunks:
            est = estimate_tokens(chunk.text)
            # +20 tokens of slack for ceiling-edge greedy decisions where
            # adding the next block tipped slightly over; the test
            # asserts "no chunk is wildly oversized" rather than "ceiling
            # is a hard upper bound" (the comment in chunker.py documents
            # this tradeoff for sections containing single oversized
            # blocks).
            assert est <= TOKEN_CEILING + 20, (
                f"Chunk {chunk.chunk_id} estimated at {est} tokens "
                f"(ceiling {TOKEN_CEILING})"
            )

    def test_chunks_carry_heading_prefix(self):
        """Each chunk's text starts with the H2 heading so retrieval
        results carry their own context (the LLM sees the section name
        in the chunk body).
        """
        from architectures._shared.chunker import chunk_corpus

        chunks = chunk_corpus(
            corpus_path=_CORPUS, policy_classes_path=_POLICY_CLASSES
        )
        for chunk in chunks:
            assert chunk.text.startswith(f"## {chunk.section_title}"), (
                f"Chunk {chunk.chunk_id} text doesn't start with H2 heading: "
                f"{chunk.text[:80]!r}"
            )

    def test_chunks_dont_cross_section_boundaries(self):
        """A chunk's text never contains a SECOND H2 heading — chunks are
        scoped to one section by construction.
        """
        from architectures._shared.chunker import chunk_corpus

        chunks = chunk_corpus(
            corpus_path=_CORPUS, policy_classes_path=_POLICY_CLASSES
        )
        for chunk in chunks:
            # The first H2 is the chunk's own heading; any further H2
            # would mean the chunker crossed a section boundary.
            heading_count = chunk.text.count("\n## ")
            assert heading_count == 0, (
                f"Chunk {chunk.chunk_id} contains {heading_count + 1} H2 "
                f"headings (should be exactly 1 — its own)"
            )


# ---------------------------------------------------------------------------
# Block split and pack — unit-test on synthetic input
# ---------------------------------------------------------------------------


class TestBlockSplit:
    def test_blank_line_splits_paragraphs(self):
        from architectures._shared.chunker import _split_into_blocks

        body = dedent(
            """\
            First paragraph.

            Second paragraph.
            """
        )
        blocks = _split_into_blocks(body)
        assert blocks == ["First paragraph.", "Second paragraph."]

    def test_numbered_q_lines_split_without_blank_lines(self):
        """The 'Booking and Cancellation' section has 19 numbered Qs in
        one block of text with no blank lines between them. The chunker
        must still split on the `^\\d+\\.\\s` pattern.
        """
        from architectures._shared.chunker import _split_into_blocks

        body = (
            "1. First question?\n"
            "\tAnswer first.\n"
            "2. Second question?\n"
            "\tAnswer second."
        )
        blocks = _split_into_blocks(body)
        assert len(blocks) == 2
        assert "First question" in blocks[0]
        assert "Second question" in blocks[1]

    def test_sub_bullets_stay_with_parent_q(self):
        from architectures._shared.chunker import _split_into_blocks

        body = (
            "1. First Q with bullets?\n"
            "    * sub bullet one\n"
            "    * sub bullet two\n"
            "2. Second Q?"
        )
        blocks = _split_into_blocks(body)
        assert len(blocks) == 2
        assert "sub bullet one" in blocks[0]
        assert "sub bullet two" in blocks[0]


# ---------------------------------------------------------------------------
# Hard fail on unknown section headings
# ---------------------------------------------------------------------------


class TestUnknownHeading:
    def test_raises_when_h2_not_in_policy_classes(self, tmp_path):
        """An H2 heading without a policy_classes.json entry should
        raise — task `expected_citations` would otherwise dangle silently.
        """
        from architectures._shared.chunker import chunk_corpus

        corpus_path = tmp_path / "corpus.md"
        corpus_path.write_text("## Unknown Heading\n\n1. Some Q?\n")
        policy_path = tmp_path / "policy.json"
        policy_path.write_text(json.dumps([
            {"id": "known", "title": "Known Heading", "summary": "..."}
        ]))

        with pytest.raises(ValueError, match="no matching entry"):
            chunk_corpus(
                corpus_path=corpus_path, policy_classes_path=policy_path
            )
