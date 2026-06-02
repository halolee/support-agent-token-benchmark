"""Cassette utilities — record live Anthropic API exchanges, replay for free.

Pattern:
    1. A test marked `@pytest.mark.live_api @pytest.mark.requires_api_key`
       makes the real API calls once and writes a fixture JSON to
       tests/fixtures/. Cost: typically <$0.05 per cassette.

    2. A replay test (no markers, runs in every session) loads the fixture
       and constructs a mock client whose `count_tokens` behavior matches
       the recorded counts. The actual `decompose_request` logic runs
       against this mock — so the test validates real logic against real
       (recorded) numbers without burning API budget.

The replay client is a STRICT mock: it raises KeyError if asked to count
a text not in the recorded set. This makes cassette staleness fail loudly
rather than silently passing on stale data.

Re-record a cassette by running: pytest --run-live-api (with
ANTHROPIC_API_KEY set). See BUDGET.md § "Tier 2" for the policy.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock


CASSETTE_DIR = Path(__file__).parent / "fixtures"


def save_cassette(fixture: dict[str, Any], path: Path) -> None:
    """Write a cassette to JSON. Pretty-printed for human review."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fixture, indent=2, sort_keys=True) + "\n")


def load_cassette(path: Path) -> dict[str, Any] | None:
    """Load a cassette, or return None if the file doesn't exist."""
    if not path.exists():
        return None
    return json.loads(path.read_text())


def make_replay_client(fixture: dict[str, Any]) -> MagicMock:
    """Build a mock Anthropic client that replays count_tokens responses.

    The cassette format supports two kinds of recorded counts:
      - `count_tokens_for_pieces`: keyed by message text content (used
        for standalone count_tokens(text, ...) calls).
      - `count_tokens_request_shapes` (optional, added in Phase 2): keyed
        by a discriminator built from the call shape (baseline, +system,
        +tools). Used by decompose_request's differential measurement of
        system_prompt and tool_overhead, which include framing that pure
        text counts can't see.

    The mock raises KeyError if asked to count something not in the
    recorded set — stale cassettes fail loudly rather than silently
    passing on stale data.
    """
    counts_by_text: dict[str, int] = fixture.get("count_tokens_for_pieces", {})
    counts_by_shape: dict[str, int] = fixture.get("count_tokens_request_shapes", {})

    def count_tokens_side_effect(*args, **kwargs):
        system = kwargs.get("system")
        tools = kwargs.get("tools")
        messages = kwargs.get("messages", [])

        # Differential-shape calls (decompose_request's baseline + system
        # + tools probes) use a sentinel single-character message. Route
        # those to the shape-keyed counts.
        is_shape_call = False
        if messages and len(messages) == 1:
            content = messages[0].get("content", "")
            if isinstance(content, str) and content == "_":
                is_shape_call = True

        if is_shape_call:
            if system and not tools:
                shape_key = "baseline+system"
            elif tools and not system:
                shape_key = "baseline+tools"
            elif system and tools:
                shape_key = "baseline+system+tools"
            else:
                shape_key = "baseline"
            if shape_key not in counts_by_shape:
                raise KeyError(
                    f"Cassette has no recorded count for shape {shape_key!r}. "
                    f"Re-record with --run-live-api."
                )
            return MagicMock(input_tokens=counts_by_shape[shape_key])

        # Standalone count_tokens(text, ...) call — key by message text.
        text = ""
        if messages:
            content = messages[0].get("content", "")
            if isinstance(content, str):
                text = content
        if text not in counts_by_text:
            preview = text[:80] + ("..." if len(text) > 80 else "")
            raise KeyError(
                f"Cassette has no recorded count for text: {preview!r}. "
                f"Either the cassette is stale (re-record with "
                f"--run-live-api) or the test exercises a new input path "
                f"not covered by the cassette."
            )
        return MagicMock(input_tokens=counts_by_text[text])

    client = MagicMock()
    client.beta.messages.count_tokens.side_effect = count_tokens_side_effect
    return client
