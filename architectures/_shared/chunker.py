"""Corpus chunker — splits `corpus/swiss_faq.md` into citation-tagged chunks.

Strategy per `architectures/naive_rag/README.md`:

  1. Split on H2 (`##`) headings into sections.
  2. Map each section title to its canonical section_id via
     `measurement/policy_classes.json` (titles must match exactly — drift
     is a hard error so tasks' `expected_citations` always resolve).
  3. For each section, walk its body into logical blocks. A block is
     either a blank-line-separated paragraph OR a numbered Q-item (the
     "Booking and Cancellation" section has 19 Qs with no blank lines
     between them, so blank lines alone aren't sufficient).
  4. Greedy-pack blocks into chunks ≤ TOKEN_CEILING. Each chunk is
     prefixed with the section heading so retrieval results carry their
     own context.

Token counting during chunking uses a deterministic local estimator
(`len(text) // CHARS_PER_TOKEN`) rather than the Anthropic API. The
ceiling is a chunking target, not a measurement number — burning API
calls on every block during setup would be wasteful, and the methodology
only requires that chunks be roughly in the 300-500 token range. The
actual token count of each chunk text in retrieval is measured via the
real API at agent runtime (where it lands in category ②, retrieved
context).

Reused by Hybrid RAG so vector + BM25 retrieval share the same chunk
boundaries (otherwise the BM25 vs vector comparison would be confounded
by chunking differences).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


# ---------------------------------------------------------------------------
# Tuning knobs
# ---------------------------------------------------------------------------

# Target ~300-500 tokens per chunk (per naive_rag/README.md). The ceiling
# is the upper bound; sections smaller than the ceiling are emitted as
# single chunks regardless.
TOKEN_CEILING = 500

# Rough chars-per-token for the local estimator. Anthropic's tokenizer
# averages ~3.5-4 chars/token for English; 4 is a conservative round
# number. Local estimator is only used to decide chunk boundaries — the
# measurement uses Anthropic's count_tokens API at runtime.
CHARS_PER_TOKEN = 4


# Lines matching this pattern start a numbered Q-item (e.g. "1. How can I…").
# Sub-bullets ("\t* …" or "    * …") continue the parent Q-item and are
# not block boundaries themselves.
_Q_LINE = re.compile(r"^\d+\.\s")


# ---------------------------------------------------------------------------
# Chunk dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Chunk:
    chunk_id: str          # stable id, e.g., "booking-and-cancellation-002"
    section_id: str        # citation id matching policy_classes.json, e.g., "booking-and-cancellation"
    section_title: str     # H2 heading text, e.g., "Booking and Cancellation"
    text: str              # full chunk text including heading prefix

    def to_metadata(self) -> dict[str, str]:
        """Metadata payload for vector-store records (ChromaDB-compatible)."""
        return {
            "section_id": self.section_id,
            "section_title": self.section_title,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def estimate_tokens(text: str) -> int:
    """Local token-count estimate for chunking decisions only.

    Not used for measurement. The measurement uses Anthropic's
    count_tokens API at runtime (see measurement/tokens.py).
    """
    if not text:
        return 0
    return max(1, len(text) // CHARS_PER_TOKEN)


def _load_section_id_map(policy_classes_path: Path) -> dict[str, str]:
    """Build a title → section_id lookup from policy_classes.json.

    The lookup is exact-match on H2 heading text. If the corpus grows a
    new H2 that isn't in policy_classes.json, the chunker raises — task
    citations would otherwise dangle silently.
    """
    data = json.loads(policy_classes_path.read_text())
    return {entry["title"]: entry["id"] for entry in data}


def _split_into_sections(corpus_text: str) -> list[tuple[str, str]]:
    """Walk corpus text → list of (h2_heading_text, body_text).

    Body excludes the heading line itself. Anything before the first H2
    is ignored (the LangGraph corpus has no preamble, but defensively
    skipping it keeps the chunker tolerant).
    """
    sections: list[tuple[str, str]] = []
    current_title: str | None = None
    current_body: list[str] = []

    for line in corpus_text.split("\n"):
        if line.startswith("## "):
            if current_title is not None:
                sections.append((current_title, "\n".join(current_body).strip("\n")))
            current_title = line[3:].strip()
            current_body = []
        else:
            if current_title is not None:
                current_body.append(line)

    if current_title is not None:
        sections.append((current_title, "\n".join(current_body).strip("\n")))

    return sections


def _split_into_blocks(section_body: str) -> list[str]:
    """Section body → list of block strings.

    A block is either:
      - a blank-line-separated paragraph, or
      - a numbered Q-item (line starting `^\\d+\\.\\s`) plus its
        continuation lines (sub-bullets, follow-up paragraphs without
        intervening blank lines or new Q-line).
    """
    blocks: list[str] = []
    current: list[str] = []

    def _flush() -> None:
        if current and any(line.strip() for line in current):
            blocks.append("\n".join(current).rstrip())

    for line in section_body.split("\n"):
        if _Q_LINE.match(line):
            _flush()
            current = [line]
        elif line.strip() == "":
            _flush()
            current = []
        else:
            current.append(line)

    _flush()
    return blocks


def _pack_blocks(
    blocks: list[str], heading: str, ceiling: int
) -> list[str]:
    """Greedy-pack blocks into ≤ ceiling-token chunks, prefixing each
    with the section heading line.

    Each chunk is `"## {heading}\\n\\n{block1}\\n\\n{block2}…"`. If a
    single block exceeds the ceiling on its own, it still emits as one
    chunk — splitting mid-block would break logical structure (sub-bullets
    detached from their parent Q-line). This is a documented tradeoff; in
    practice no single block in swiss_faq.md exceeds 500 tokens.
    """
    heading_line = f"## {heading}"
    heading_tokens = estimate_tokens(heading_line)

    chunks: list[str] = []
    current_blocks: list[str] = []
    current_tokens = heading_tokens

    for block in blocks:
        block_tokens = estimate_tokens(block)
        # +1 token approximation for the joining blank line between blocks
        addition = block_tokens + 1
        if current_blocks and current_tokens + addition > ceiling:
            chunks.append(heading_line + "\n\n" + "\n\n".join(current_blocks))
            current_blocks = [block]
            current_tokens = heading_tokens + block_tokens
        else:
            current_blocks.append(block)
            current_tokens += addition

    if current_blocks:
        chunks.append(heading_line + "\n\n" + "\n\n".join(current_blocks))

    return chunks


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def chunk_corpus(
    *,
    corpus_path: Path,
    policy_classes_path: Path,
    token_ceiling: int = TOKEN_CEILING,
) -> list[Chunk]:
    """Chunk swiss_faq.md → list of citation-tagged Chunks.

    Raises ValueError if a corpus H2 heading has no matching entry in
    policy_classes.json — that's a hard fail because tasks'
    `expected_citations` depend on the section_id mapping.
    """
    corpus_text = corpus_path.read_text()
    section_id_by_title = _load_section_id_map(policy_classes_path)

    sections = _split_into_sections(corpus_text)

    chunks: list[Chunk] = []
    for title, body in sections:
        if title not in section_id_by_title:
            raise ValueError(
                f"Corpus H2 heading {title!r} has no matching entry in "
                f"policy_classes.json. Update policy_classes.json (and any "
                f"affected tasks) before chunking."
            )
        section_id = section_id_by_title[title]

        blocks = _split_into_blocks(body)
        if not blocks:
            continue

        chunk_texts = _pack_blocks(blocks, title, token_ceiling)
        for idx, text in enumerate(chunk_texts, start=1):
            chunks.append(
                Chunk(
                    chunk_id=f"{section_id}-{idx:03d}",
                    section_id=section_id,
                    section_title=title,
                    text=text,
                )
            )

    return chunks
