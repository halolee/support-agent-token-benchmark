"""Grep search tool definitions.

Per METHODOLOGY's modularity constraint, the agent reaches the corpus
ONLY through Support Content's `grep_corpus` tool. Naive "grep" implies
file-system / shell access, which would violate the boundary; this
module implements the moral equivalent — case-insensitive substring
matching with line context — inside Support Content's owned code path
and exposes it as a structured tool with a defined contract.

  - `grep_corpus(keywords, max_results, context_lines)` is the Support
    Content interface for Grep search.
  - The booking tools (Booking Systems) and `audit_log` (Compliance) are
    re-exported from `_shared/` verbatim — identical across architectures.

Lazy initialisation: the corpus text and per-line section index are
loaded on first call to `grep_corpus`, not at import. Keeps the module
cheap to import for tests and the runner registry.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from architectures._shared.audit import AUDIT_TOOL_SCHEMA, audit_log
from architectures._shared.booking_tools import (
    BOOKING_TOOL_DISPATCH,
    BOOKING_TOOL_SCHEMAS,
)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_PATH = _REPO_ROOT / "corpus" / "swiss_faq.md"
POLICY_CLASSES_PATH = _REPO_ROOT / "measurement" / "policy_classes.json"


# ---------------------------------------------------------------------------
# Defaults — per architectures/grep_search/README.md
# ---------------------------------------------------------------------------

DEFAULT_MAX_RESULTS = 10
DEFAULT_CONTEXT_LINES = 2

# Bounds: an LLM passing absurd values shouldn't be able to blow up
# retrieved_context tokens. Same defensive pattern as
# `naive_rag/tools.py::vector_search`'s k clamp.
_MAX_RESULTS_CEILING = 20
_CONTEXT_LINES_CEILING = 5
_MAX_KEYWORDS = 8


# ---------------------------------------------------------------------------
# Indexed corpus (lazy)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _IndexedLine:
    """A single corpus line with its current-H2 section attribution."""

    line_number: int  # 1-based
    text: str
    section_id: str | None
    section_title: str | None


_indexed_lines: list[_IndexedLine] | None = None


def _load_section_id_map() -> dict[str, str]:
    """title → section_id from policy_classes.json.

    Mirrors `_shared/chunker.py::_load_section_id_map` (kept local to
    avoid reaching into chunker's private helper). Exact-match on H2
    heading text — drift between corpus and policy_classes.json is a
    hard error because task `expected_citations` depend on the mapping.
    """
    data = json.loads(POLICY_CLASSES_PATH.read_text())
    return {entry["title"]: entry["id"] for entry in data}


def _build_index() -> list[_IndexedLine]:
    """Walk swiss_faq.md once, tagging each line with its current H2.

    Lines that precede the first H2 (defensive — the LangGraph corpus
    has no preamble) get section_id=None and don't survive the grep
    filter (the agent has no way to cite them anyway).
    """
    title_to_id = _load_section_id_map()
    corpus_text = CORPUS_PATH.read_text()

    indexed: list[_IndexedLine] = []
    current_title: str | None = None
    current_id: str | None = None

    for lineno, raw in enumerate(corpus_text.split("\n"), start=1):
        if raw.startswith("## "):
            current_title = raw[3:].strip()
            current_id = title_to_id.get(current_title)
            if current_id is None:
                raise ValueError(
                    f"Corpus H2 heading {current_title!r} (line {lineno}) "
                    f"has no entry in policy_classes.json. Update the map "
                    f"(and any affected tasks) before grep_corpus can run."
                )
        indexed.append(
            _IndexedLine(
                line_number=lineno,
                text=raw,
                section_id=current_id,
                section_title=current_title,
            )
        )
    return indexed


def _get_index() -> list[_IndexedLine]:
    global _indexed_lines
    if _indexed_lines is None:
        if not CORPUS_PATH.exists():
            raise FileNotFoundError(
                f"Corpus not found at {CORPUS_PATH}. Run the Phase 1 Step 0 "
                f"fetch (see BUILD_PLAN.md)."
            )
        _indexed_lines = _build_index()
    return _indexed_lines


def reset_lazy_state() -> None:
    """Test/debug hook — drops the cached corpus index."""
    global _indexed_lines
    _indexed_lines = None


# ---------------------------------------------------------------------------
# Support Content interface: grep_corpus
# ---------------------------------------------------------------------------


def grep_corpus(
    keywords: list[str],
    max_results: int = DEFAULT_MAX_RESULTS,
    context_lines: int = DEFAULT_CONTEXT_LINES,
) -> dict[str, Any]:
    """Support Content's keyword retrieval interface for Grep search.

    Case-insensitive substring matching against each corpus line. For
    each match, the response includes ±context_lines of surrounding
    lines and the section the match came from (section_id and
    section_title) so the agent can cite uniformly with the other
    architectures.

    Matches are deduplicated by line_number — a line that matches
    multiple keywords appears once, with all matching keywords recorded
    under `matched_keywords`. Truncation is by lowest line_number first
    (corpus order), which gives stable, deterministic results.

    Context is clamped to the matched section. Walking outward from a
    match stops at the first section boundary, so a match near an H2
    won't pull adjacent-section text under this match's citation. The
    practical effect: a match on (or near) an H2 line may get fewer
    than `context_lines` of backward context — that's correct, the
    section starts at the H2.

    Bounds (all defensive, mirror vector_search's k clamp):
      keywords        → first 8 non-empty strings only
      max_results     → clamped to [1, 20]
      context_lines   → clamped to [0, 5]
    """
    bounded_max = max(1, min(int(max_results), _MAX_RESULTS_CEILING))
    bounded_ctx = max(0, min(int(context_lines), _CONTEXT_LINES_CEILING))

    if not isinstance(keywords, list):
        return {
            "keywords": keywords,
            "matches": [],
            "error": "keywords must be a list of strings",
        }
    cleaned: list[str] = []
    for kw in keywords[:_MAX_KEYWORDS]:
        if isinstance(kw, str):
            stripped = kw.strip()
            if stripped:
                cleaned.append(stripped)
    if not cleaned:
        return {"keywords": list(keywords), "matches": []}

    index = _get_index()
    lowered_keywords = [(kw, kw.lower()) for kw in cleaned]

    # First pass: line_number → list of original-cased keywords that hit.
    hits: dict[int, list[str]] = {}
    for line in index:
        if line.section_id is None:
            continue
        haystack = line.text.lower()
        if not haystack:
            continue
        for original, needle in lowered_keywords:
            if needle in haystack:
                hits.setdefault(line.line_number, []).append(original)

    if not hits:
        return {"keywords": cleaned, "matches": []}

    # Stable order: by line number (corpus order). Truncate after sort.
    matches: list[dict[str, Any]] = []
    for lineno in sorted(hits.keys())[:bounded_max]:
        line = index[lineno - 1]
        # Context window is clamped to the matched section. An absolute
        # ±bounded_ctx slice would bleed into adjacent sections when the
        # match sits near an H2 boundary — the agent would then see
        # foreign-section text under this section's citation. Walking
        # outward and stopping at the first section_id change keeps the
        # context honest (Codex PR #18 P2).
        section_id = line.section_id
        ctx_start = lineno
        for _ in range(bounded_ctx):
            if ctx_start <= 1:
                break
            if index[ctx_start - 2].section_id != section_id:
                break
            ctx_start -= 1
        ctx_end = lineno
        for _ in range(bounded_ctx):
            if ctx_end >= len(index):
                break
            if index[ctx_end].section_id != section_id:
                break
            ctx_end += 1
        context_block = "\n".join(
            index[n - 1].text for n in range(ctx_start, ctx_end + 1)
        )
        matches.append(
            {
                "section_id": line.section_id,
                "section_title": line.section_title,
                "line_number": lineno,
                "matched_line": line.text,
                "matched_keywords": hits[lineno],
                "context": context_block,
            }
        )

    return {
        "keywords": cleaned,
        "max_results": bounded_max,
        "context_lines": bounded_ctx,
        "total_matches_before_truncation": len(hits),
        "matches": matches,
    }


GREP_TOOL_SCHEMA: dict[str, Any] = {
    "name": "grep_corpus",
    "description": (
        "Search the Swiss Airlines FAQ corpus by case-insensitive "
        "substring match against each line. Returns matching lines with "
        "surrounding context (±2 lines by default) and the section each "
        "match came from. Use this for any policy / procedure / fare-rule "
        "/ payment question. Pass 1-5 keywords or short phrases drawn "
        "from the customer's wording — not category names. Iterate with "
        "different keywords if the first attempt is sparse or off-topic."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "keywords": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "1-5 keywords or short phrases to search for. "
                    "Case-insensitive substring match."
                ),
            },
            "max_results": {
                "type": "integer",
                "description": "Max matches to return (1-20, default 10).",
            },
            "context_lines": {
                "type": "integer",
                "description": "Lines of context around each match (0-5, default 2).",
            },
        },
        "required": ["keywords"],
    },
}


# ---------------------------------------------------------------------------
# Combined registry exposed to the agent loop
# ---------------------------------------------------------------------------


TOOL_SCHEMAS: list[dict[str, Any]] = [
    GREP_TOOL_SCHEMA,
    *BOOKING_TOOL_SCHEMAS,
    AUDIT_TOOL_SCHEMA,
]


def _dispatch_grep_corpus(
    keywords: list[str],
    max_results: int = DEFAULT_MAX_RESULTS,
    context_lines: int = DEFAULT_CONTEXT_LINES,
) -> dict[str, Any]:
    return grep_corpus(
        keywords=keywords,
        max_results=max_results,
        context_lines=context_lines,
    )


TOOL_DISPATCH: dict[str, Any] = {
    "grep_corpus": _dispatch_grep_corpus,
    **BOOKING_TOOL_DISPATCH,
    "audit_log": audit_log,
}


# Tool names whose calls produce category-② "retrieved_context" tokens.
# audit_log is excluded per METHODOLOGY §"Audit log specification".
RETRIEVAL_TOOL_NAMES: set[str] = {"grep_corpus"}
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
