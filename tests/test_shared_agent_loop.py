"""Tests for `architectures/_shared/agent_loop.py`.

The shared base is parameter-bound by per-architecture wrappers; the
per-architecture test suites verify the wrapper wiring. These tests
cover the loop logic itself with a stub Anthropic client, so loop
bugs surface independently of any architecture's tool stack.

count_tokens is stubbed to a constant — the goal here is control-flow
verification (turn counting, tools_called ordering, audit_log offset
subtraction, MAX_TURNS guard), not token arithmetic. Arithmetic is
covered by tests/test_tokens.py.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Stub client + scripted responses
# ---------------------------------------------------------------------------


def _text_block(text: str) -> MagicMock:
    b = MagicMock()
    b.type = "text"
    b.text = text
    return b


def _tool_use_block(name: str, tu_id: str, tu_input: dict[str, Any]) -> MagicMock:
    b = MagicMock()
    b.type = "tool_use"
    b.id = tu_id
    b.name = name
    b.input = tu_input
    return b


def _response(content_blocks: list[MagicMock], *, in_tokens: int = 50, out_tokens: int = 10) -> MagicMock:
    r = MagicMock()
    r.content = content_blocks
    r.usage.input_tokens = in_tokens
    r.usage.output_tokens = out_tokens
    r.usage.cache_creation_input_tokens = 0
    r.usage.cache_read_input_tokens = 0
    return r


def _make_stub_client(scripted_responses: list[MagicMock]) -> MagicMock:
    """Build a stub Anthropic client.

    - messages.create returns scripted responses in order.
    - beta.messages.count_tokens returns input_tokens=1 for any call
      (control-flow tests don't care about counts).
    """
    client = MagicMock()
    client.messages.create.side_effect = scripted_responses
    client.beta.messages.count_tokens.return_value = MagicMock(input_tokens=1)
    return client


# ---------------------------------------------------------------------------
# Loop terminates on no-tool-call response
# ---------------------------------------------------------------------------


def test_single_turn_text_only_terminates():
    from architectures._shared.agent_loop import run_task

    task = {"task_id": "T-1", "user_message": "hi"}
    client = _make_stub_client([_response([_text_block("hello back")])])

    record = run_task(
        task,
        architecture="test_arch",
        system_prompt="SYS",
        tool_schemas=[],
        tool_dispatch={},
        audit_tool_name="audit_log",
        client=client,
    )

    assert record["turns"] == 1
    assert record["tools_called"] == []
    # audit_log wasn't called, so response_text falls back to turn texts.
    assert record["response_text"] == "hello back"
    # New ledger fields are present.
    assert "decomposition_input_sum_with_audit" in record
    assert record["audit_log_tokens_in_retrieved_context"] == 0
    assert record["audit_log_tokens_in_agent_intermediate"] == 0


# ---------------------------------------------------------------------------
# Tool dispatch threading + ordered tools_called
# ---------------------------------------------------------------------------


def test_tool_dispatch_threaded_and_recorded():
    from architectures._shared.agent_loop import run_task

    task = {"task_id": "T-2", "user_message": "search please"}
    calls: list[tuple[str, dict]] = []

    def fake_search(**kwargs):
        calls.append(("search", kwargs))
        return {"hits": ["a", "b"]}

    scripted = [
        _response([_tool_use_block("search", "tu_1", {"q": "x"})]),
        _response([_text_block("done")]),
    ]
    client = _make_stub_client(scripted)

    record = run_task(
        task,
        architecture="test_arch",
        system_prompt="SYS",
        tool_schemas=[{"name": "search"}],
        tool_dispatch={"search": fake_search},
        audit_tool_name="audit_log",
        client=client,
    )

    assert record["turns"] == 2
    assert record["tools_called"] == ["search"]
    assert calls == [("search", {"q": "x"})]
    assert record["response_text"] == "done"


# ---------------------------------------------------------------------------
# audit_log response capture + offset subtraction
# ---------------------------------------------------------------------------


def test_audit_log_response_capture_and_offset():
    from architectures._shared.agent_loop import run_task

    task = {"task_id": "T-3", "user_message": "answer please"}
    scripted = [
        _response([
            _tool_use_block(
                "audit_log",
                "tu_audit",
                {"task_id": "T-3", "response": "the final answer", "tools_called": []},
            ),
        ]),
        _response([_text_block("ok")]),
    ]
    client = _make_stub_client(scripted)

    def audit_log(**kwargs):
        return {"ok": True}

    record = run_task(
        task,
        architecture="test_arch",
        system_prompt="SYS",
        tool_schemas=[{"name": "audit_log"}],
        tool_dispatch={"audit_log": audit_log},
        audit_tool_name="audit_log",
        client=client,
    )

    # First audit_log call's `response` arg is the canonical final answer.
    assert record["response_text"] == "the final answer"
    assert record["tools_called"] == ["audit_log"]
    # Audit-offset accounting fires (offsets are >0 because count_tokens
    # stub returns 1 for any non-empty concatenation).
    assert record["audit_log_tokens_in_retrieved_context"] >= 0
    assert record["audit_log_tokens_in_agent_intermediate"] >= 0
    # Inclusive sum (with audit) >= reporting sum (without).
    assert (
        record["decomposition_input_sum_with_audit"]
        >= record["decomposition_input_sum"]
    )


# ---------------------------------------------------------------------------
# MAX_TURNS guard
# ---------------------------------------------------------------------------


def test_max_turns_guard_caps_loop():
    from architectures._shared.agent_loop import MAX_TURNS, run_task

    task = {"task_id": "T-4", "user_message": "loop forever"}

    # Script MAX_TURNS responses, all returning a tool_use so the loop
    # never naturally terminates.
    scripted = [
        _response([_tool_use_block("search", f"tu_{i}", {"q": str(i)})])
        for i in range(MAX_TURNS + 2)  # extras would be consumed if the cap were broken
    ]
    client = _make_stub_client(scripted)

    def fake_search(**kwargs):
        return {"hits": []}

    record = run_task(
        task,
        architecture="test_arch",
        system_prompt="SYS",
        tool_schemas=[{"name": "search"}],
        tool_dispatch={"search": fake_search},
        audit_tool_name="audit_log",
        client=client,
    )

    assert record["turns"] == MAX_TURNS
    assert len(record["tools_called"]) == MAX_TURNS
    assert "ERROR: agent exceeded MAX_TURNS" in record["response_text"]


# ---------------------------------------------------------------------------
# Tool dispatch error is captured as is_error result, loop continues
# ---------------------------------------------------------------------------


def test_tool_error_becomes_is_error_result_and_loop_continues():
    from architectures._shared.agent_loop import run_task

    task = {"task_id": "T-5", "user_message": "trigger an error"}

    def raises(**kwargs):
        raise RuntimeError("boom")

    scripted = [
        _response([_tool_use_block("broken", "tu_1", {})]),
        _response([_text_block("recovered")]),
    ]
    client = _make_stub_client(scripted)

    record = run_task(
        task,
        architecture="test_arch",
        system_prompt="SYS",
        tool_schemas=[{"name": "broken"}],
        tool_dispatch={"broken": raises},
        audit_tool_name="audit_log",
        client=client,
    )

    # Loop survives a tool exception; the next turn proceeds normally.
    assert record["turns"] == 2
    assert record["tools_called"] == ["broken"]
    assert record["response_text"] == "recovered"
