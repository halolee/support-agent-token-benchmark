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
# Integration: the methodology gate
# =========================================================================


@pytest.mark.requires_api_key
class TestMethodologyGate:
    """Real-API verification of METHODOLOGY's 5% sum gate.

    Without this passing, the project's headline claim that "decomposition
    sums equal API-reported tokens within 5%" is unverified for the chosen
    agent model. This test makes 5 API calls per run (~$0.01 in tokens).
    """

    def test_decomposition_within_5_percent_of_api_input_tokens(self):
        import anthropic

        from measurement.tokens import AGENT_MODEL, decompose_request

        client = anthropic.Anthropic()

        system = "You are a concise assistant. Reply with just 'OK'."
        messages = [{"role": "user", "content": "Acknowledge."}]
        tools = []

        api_response = client.messages.create(
            model=AGENT_MODEL,
            max_tokens=10,
            system=system,
            messages=messages,
        )
        api_input_tokens = api_response.usage.input_tokens

        decomposition = decompose_request(
            system=system,
            messages=messages,
            tools=tools,
            output_tokens=api_response.usage.output_tokens,
            client=client,
        )

        input_sum = sum(
            decomposition[k]
            for k in ("system_prompt", "retrieved_context", "user_message", "tool_overhead")
        )
        ratio = abs(input_sum - api_input_tokens) / api_input_tokens
        assert ratio < 0.05, (
            f"Decomposition input sum {input_sum} differs from API "
            f"input_tokens {api_input_tokens} by {ratio:.1%} "
            f"(METHODOLOGY tolerance: 5%)"
        )
