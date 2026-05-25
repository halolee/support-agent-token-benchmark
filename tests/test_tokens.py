"""Tests for measurement/tokens.py.

The spec for the token decomposition primitives:
- count_tokens         — wraps Anthropic's beta count_tokens API
- decompose_request    — produces the 5-category Silicon Data breakdown
- record_run           — structured logging record per task-run

Unit tests use a mocked Anthropic client.

The integration test (`requires_api_key`) makes real API calls to
validate the methodology's gate: sum of input-side categories must
match API-reported `input_tokens` within 5%. Skipped automatically
when ANTHROPIC_API_KEY is missing (see conftest.py).
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# =========================================================================
# count_tokens
# =========================================================================


class TestCountTokens:
    def test_returns_int_from_mocked_client(self):
        from measurement.tokens import count_tokens

        client = MagicMock()
        client.beta.messages.count_tokens.return_value = MagicMock(input_tokens=42)
        n = count_tokens("hello world", client=client)
        assert isinstance(n, int)
        assert n == 42

    def test_empty_string_returns_count_from_api(self):
        """We delegate to the API even for empty strings; behavior comes from there."""
        from measurement.tokens import count_tokens

        client = MagicMock()
        client.beta.messages.count_tokens.return_value = MagicMock(input_tokens=0)
        assert count_tokens("", client=client) == 0

    def test_uses_agent_model(self):
        """count_tokens must pin the agent model so counts are model-correct."""
        from measurement.tokens import AGENT_MODEL, count_tokens

        client = MagicMock()
        client.beta.messages.count_tokens.return_value = MagicMock(input_tokens=5)
        count_tokens("test", client=client)
        call = client.beta.messages.count_tokens.call_args
        assert call.kwargs.get("model") == AGENT_MODEL


# =========================================================================
# decompose_request
# =========================================================================


class TestDecomposeRequest:
    def test_returns_five_categories(self):
        from measurement.tokens import decompose_request

        client = MagicMock()
        client.beta.messages.count_tokens.return_value = MagicMock(input_tokens=10)
        result = decompose_request(
            system="You are a helpful agent",
            messages=[{"role": "user", "content": "hi"}],
            tools=[{"name": "test", "description": "x", "input_schema": {"type": "object"}}],
            output_tokens=5,
            client=client,
        )
        expected = {
            "system_prompt",
            "retrieved_context",
            "user_message",
            "tool_overhead",
            "response",
        }
        assert set(result.keys()) == expected
        for k, v in result.items():
            assert isinstance(v, int), f"{k} should be int, got {type(v).__name__}"

    def test_response_uses_provider_output_tokens_not_count_tokens(self):
        """Category 5 is provider-reported output_tokens, NOT a separate count_tokens call."""
        from measurement.tokens import decompose_request

        client = MagicMock()
        # Even though the mock would return 100, we expect the function to use
        # the provided output_tokens value of 42.
        client.beta.messages.count_tokens.return_value = MagicMock(input_tokens=100)
        result = decompose_request(
            system="",
            messages=[],
            tools=[],
            output_tokens=42,
            client=client,
        )
        assert result["response"] == 42

    def test_tool_result_blocks_become_retrieved_context_not_user_message(self):
        """Tool_result content is retrieved_context. User text is user_message."""
        from measurement.tokens import decompose_request

        client = MagicMock()

        def fake_count(*, model, messages=None, **kwargs):
            # Return the character count of the input as a stand-in for tokens
            if not messages:
                return MagicMock(input_tokens=0)
            text = ""
            for m in messages:
                content = m.get("content", "")
                if isinstance(content, str):
                    text += content
                elif isinstance(content, list):
                    for b in content:
                        if isinstance(b, dict):
                            text += b.get("text", "") + str(b.get("content", ""))
            return MagicMock(input_tokens=len(text))

        client.beta.messages.count_tokens.side_effect = fake_count

        result = decompose_request(
            system="sys",
            messages=[
                {"role": "user", "content": "USER_INITIAL"},
                {
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "id": "1", "name": "t", "input": {}},
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "1",
                            "content": "RETRIEVED_CONTENT_FROM_TOOL",
                        }
                    ],
                },
            ],
            tools=[{"name": "t"}],
            output_tokens=0,
            client=client,
        )
        # user_message reflects "USER_INITIAL", retrieved_context reflects the tool_result
        assert result["user_message"] == len("USER_INITIAL")
        assert result["retrieved_context"] == len("RETRIEVED_CONTENT_FROM_TOOL")

    def test_empty_inputs_yield_zero_categories(self):
        """No system + no messages + no tools → all input categories zero."""
        from measurement.tokens import decompose_request

        client = MagicMock()
        client.beta.messages.count_tokens.return_value = MagicMock(input_tokens=99)
        result = decompose_request(
            system="",
            messages=[],
            tools=[],
            output_tokens=0,
            client=client,
        )
        assert result["system_prompt"] == 0
        assert result["user_message"] == 0
        assert result["retrieved_context"] == 0
        assert result["tool_overhead"] == 0


# =========================================================================
# record_run
# =========================================================================


class TestRecordRun:
    def test_well_formed_record(self):
        from measurement.tokens import record_run

        api_usage = MagicMock(
            input_tokens=1000,
            output_tokens=200,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
        )
        decomposition = {
            "system_prompt": 500,
            "retrieved_context": 300,
            "user_message": 50,
            "tool_overhead": 150,
            "response": 200,
        }
        record = record_run(
            architecture="a",
            task_id="POL-001",
            decomposition=decomposition,
            api_usage=api_usage,
            response_text="The answer is...",
        )
        assert record["architecture"] == "a"
        assert record["task_id"] == "POL-001"
        assert record["decomposition"] == decomposition
        assert record["api_input_tokens"] == 1000
        assert record["api_output_tokens"] == 200
        assert record["cache_creation_input_tokens"] == 0
        assert record["cache_read_input_tokens"] == 0
        assert record["response_text"] == "The answer is..."

    def test_decomposition_input_sum_field(self):
        """Records include a derived input-sum field for the 5% methodology check."""
        from measurement.tokens import record_run

        api_usage = MagicMock(
            input_tokens=1000,
            output_tokens=200,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
        )
        decomposition = {
            "system_prompt": 500,
            "retrieved_context": 300,
            "user_message": 50,
            "tool_overhead": 150,
            "response": 200,
        }
        record = record_run(
            architecture="a",
            task_id="POL-001",
            decomposition=decomposition,
            api_usage=api_usage,
            response_text="x",
        )
        assert record["decomposition_input_sum"] == 500 + 300 + 50 + 150

    def test_handles_missing_cache_fields_gracefully(self):
        """Some test/mock api_usage objects may lack cache fields entirely."""
        from measurement.tokens import record_run

        # Use a class-based mock without cache attributes
        class FakeUsage:
            input_tokens = 100
            output_tokens = 20

        record = record_run(
            architecture="c",
            task_id="TXN-001",
            decomposition={
                "system_prompt": 50,
                "retrieved_context": 0,
                "user_message": 25,
                "tool_overhead": 20,
                "response": 20,
            },
            api_usage=FakeUsage(),
            response_text="x",
        )
        assert record["cache_creation_input_tokens"] == 0
        assert record["cache_read_input_tokens"] == 0


# =========================================================================
# Methodology gate — cassette pattern (record once, replay forever)
# =========================================================================
#
# See BUDGET.md § "Tier 2" for why this is split into record + replay.
# In short: live API calls are the only way to verify the measurement
# infrastructure (the measurement IS the thing being measured), but we
# don't want to burn API budget on every session. Record once with a key,
# replay for free thereafter.


CASSETTE_PATH = Path(__file__).parent / "fixtures" / "methodology_gate.json"


@pytest.mark.live_api
@pytest.mark.requires_api_key
class TestMethodologyGateRecord:
    """Records the methodology-gate cassette via real API calls.

    Run with: pytest --run-live-api  (needs ANTHROPIC_API_KEY)
    Cost: ~$0.01 per record. Re-record only when the model version
    changes or `decompose_request` logic changes.
    """

    def test_record_methodology_gate_cassette(self):
        from datetime import datetime, timezone

        import anthropic

        from measurement.tokens import (
            AGENT_MODEL,
            _extract_tool_result_text,
            _extract_user_message_text,
            count_tokens,
        )
        from tests.cassette import save_cassette

        client = anthropic.Anthropic()

        # Simple scenario covering categories 1 (system) and 3 (user message).
        # Categories 2 (retrieved_context) and 4 (tool_overhead) are empty
        # here — they'll be 0 in the decomposition. A multi-turn scenario
        # could be added later as a second cassette if needed.
        scenario = {
            "system": "You are a concise assistant. Reply with just 'OK'.",
            "messages": [{"role": "user", "content": "Acknowledge."}],
            "tools": [],
        }

        api_response = client.messages.create(
            model=AGENT_MODEL,
            max_tokens=10,
            system=scenario["system"],
            messages=scenario["messages"],
        )

        # Record per-category count_tokens responses for the texts
        # decompose_request will ask for.
        texts_to_record: list[str] = []
        if scenario["system"]:
            texts_to_record.append(scenario["system"])
        user_text = _extract_user_message_text(scenario["messages"])
        if user_text:
            texts_to_record.append(user_text)
        retrieved_text = _extract_tool_result_text(scenario["messages"])
        if retrieved_text:
            texts_to_record.append(retrieved_text)
        if scenario["tools"]:
            tools_text = json.dumps(scenario["tools"], separators=(",", ":"))
            texts_to_record.append(tools_text)

        counts_by_text: dict[str, int] = {}
        for text in texts_to_record:
            if text not in counts_by_text:
                counts_by_text[text] = count_tokens(text, client=client)

        fixture = {
            "model": AGENT_MODEL,
            "anthropic_sdk_version": anthropic.__version__,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "scenario": scenario,
            "api_create_response": {
                "input_tokens": api_response.usage.input_tokens,
                "output_tokens": api_response.usage.output_tokens,
            },
            "count_tokens_for_pieces": counts_by_text,
        }
        save_cassette(fixture, CASSETTE_PATH)


class TestMethodologyGateReplay:
    """Verifies METHODOLOGY's 5% sum gate using the recorded cassette.

    Runs in every session. Exercises real `decompose_request` logic
    against a mock client that replays the cassette's count_tokens
    responses. If the gate fails here, either the decomposition logic
    is wrong or the cassette is stale (re-record).
    """

    def test_decomposition_within_5_percent_of_recorded_api_tokens(self):
        from tests.cassette import load_cassette, make_replay_client

        from measurement.tokens import decompose_request

        fixture = load_cassette(CASSETTE_PATH)
        if fixture is None:
            pytest.skip(
                "Methodology-gate cassette not yet recorded. Run "
                "`pytest --run-live-api` with ANTHROPIC_API_KEY set "
                "to record (see BUDGET.md Tier 2)."
            )

        scenario = fixture["scenario"]
        client = make_replay_client(fixture)

        decomposition = decompose_request(
            system=scenario["system"],
            messages=scenario["messages"],
            tools=scenario["tools"],
            output_tokens=fixture["api_create_response"]["output_tokens"],
            client=client,
        )

        input_sum = sum(
            decomposition[k]
            for k in ("system_prompt", "retrieved_context", "user_message", "tool_overhead")
        )
        api_input_tokens = fixture["api_create_response"]["input_tokens"]
        ratio = abs(input_sum - api_input_tokens) / api_input_tokens
        assert ratio < 0.05, (
            f"Decomposition input sum {input_sum} differs from recorded "
            f"API input_tokens {api_input_tokens} by {ratio:.1%} "
            f"(METHODOLOGY tolerance: 5%). "
            f"Cassette: {CASSETTE_PATH.name}, "
            f"recorded {fixture.get('recorded_at')}"
        )
