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

    The mock raises KeyError if asked to count a text not in the recorded
    set — this is intentional, so stale cassettes fail loudly.
    """
    counts_by_text: dict[str, int] = fixture["count_tokens_for_pieces"]

    def count_tokens_side_effect(*args, **kwargs):
        messages = kwargs.get("messages", [])
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
