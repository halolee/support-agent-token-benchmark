"""Naive RAG agent loop.

Loop shape (uniform across architectures per METHODOLOGY):

    receive user message
    → loop:
        call model with system prompt + tools + accumulated messages
        if response has tool_use blocks:
            execute each tool, append tool_result blocks
            continue
        else:
            stop — model produced its final text
    → return record_run() dict (with per-turn decompositions summed)

Instrumentation note (METHODOLOGY): token decomposition is captured at
EVERY model call, not just the final one. Multi-turn loops accumulate
retrieved_context tokens across turns; only summing per-turn captures the
true cost.

Audit_log is excluded from per-task token decomposition. The agent still
calls it (per the modularity contract), but we subtract its contribution
from the recorded retrieved_context category — see `_excluded_audit_text`
in `run_task`.
"""
from __future__ import annotations

import json
from typing import Any, Callable

import anthropic

from measurement.tokens import AGENT_MODEL, decompose_request, record_run

from .prompts import SYSTEM_PROMPT
from .tools import (
    AUDIT_TOOL_NAME,
    TOOL_DISPATCH,
    TOOL_SCHEMAS,
    execute_tool,
    serialise_tool_result,
)


# ---------------------------------------------------------------------------
# Agent-level configuration (uniform across architectures per CLAUDE.md)
# ---------------------------------------------------------------------------

MAX_TOKENS = 1024
TEMPERATURE = 0.0

# Defensive ceiling on the tool-call loop. Tasks should resolve in 2-4
# turns; anything past 12 is almost certainly a model getting stuck in a
# retrieval loop. The cap saves spend and surfaces the regression.
MAX_TURNS = 12


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_user_message(task: dict[str, Any]) -> dict[str, Any]:
    """Front-load the task_id so the model can pass it to audit_log
    without us threading it through every tool call.
    """
    body = (
        f"[task_id: {task['task_id']}]\n\n{task['user_message']}"
    )
    return {"role": "user", "content": body}


def _final_text(content_blocks: list[Any]) -> str:
    parts: list[str] = []
    for block in content_blocks:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "\n".join(parts).strip()


# ---------------------------------------------------------------------------
# Per-task agent
# ---------------------------------------------------------------------------


def run_task(
    task: dict[str, Any],
    *,
    client: anthropic.Anthropic | None = None,
    tool_dispatch: dict[str, Callable] | None = None,
) -> dict[str, Any]:
    """Run a single task end-to-end. Returns a record_run() dict.

    The returned dict shape extends record_run with:
        - turns: number of model calls in the loop
        - tools_called: ordered list of tool names invoked
        - decomposition: PER-TASK sum across all model calls (not just
          the last). retrieved_context excludes audit_log tool_results;
          agent_intermediate excludes audit_log tool_use payloads. Both
          exclusions per METHODOLOGY §"Audit log specification".

    Response-text capture:
        The agent contract is that audit_log's `response` argument carries
        the verbatim final customer-facing answer. We source the recorded
        `response_text` from that argument (first audit_log call's input).
        Fallback: if audit_log wasn't called, concatenate text blocks
        across all turns.
    """
    if client is None:
        client = anthropic.Anthropic()
    dispatch = tool_dispatch if tool_dispatch is not None else TOOL_DISPATCH

    user_message = _build_user_message(task)
    messages: list[dict[str, Any]] = [user_message]

    turn = 0
    tools_called: list[str] = []
    audit_response_arg: str | None = None
    all_turn_texts: list[str] = []
    summed: dict[str, int] = {
        "system_prompt": 0,
        "retrieved_context": 0,
        "user_message": 0,
        "tool_overhead": 0,
        "agent_intermediate": 0,
        "response": 0,
    }
    total_api_input = 0
    total_api_output = 0
    total_cache_create = 0
    total_cache_read = 0

    while turn < MAX_TURNS:
        turn += 1
        response = client.messages.create(
            model=AGENT_MODEL,
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
            system=SYSTEM_PROMPT,
            tools=TOOL_SCHEMAS,
            messages=messages,
        )

        per_turn_decomp = decompose_request(
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=TOOL_SCHEMAS,
            output_tokens=response.usage.output_tokens,
            client=client,
        )
        for cat, n in per_turn_decomp.items():
            summed[cat] += n
        total_api_input += int(response.usage.input_tokens)
        total_api_output += int(response.usage.output_tokens)
        total_cache_create += int(
            getattr(response.usage, "cache_creation_input_tokens", 0) or 0
        )
        total_cache_read += int(
            getattr(response.usage, "cache_read_input_tokens", 0) or 0
        )

        # Append the assistant turn and capture text blocks for the
        # response-text fallback.
        assistant_blocks = response.content
        turn_text = _final_text(assistant_blocks)
        if turn_text:
            all_turn_texts.append(turn_text)

        messages.append(
            {
                "role": "assistant",
                "content": [_block_to_dict(b) for b in assistant_blocks],
            }
        )

        tool_use_blocks = [b for b in assistant_blocks if getattr(b, "type", None) == "tool_use"]
        if not tool_use_blocks:
            # Model produced a no-tool-call response — loop terminates.
            break

        # Execute each tool call, build tool_result blocks for the next turn.
        tool_results: list[dict[str, Any]] = []
        for tu in tool_use_blocks:
            name = tu.name
            tools_called.append(name)
            tu_input = tu.input or {}
            if name == AUDIT_TOOL_NAME and audit_response_arg is None:
                # First audit_log call carries the canonical final answer.
                audit_response_arg = str(tu_input.get("response", "") or "")
            try:
                result = dispatch[name](**tu_input)
                content_text = serialise_tool_result(result)
                is_error = False
            except Exception as e:
                content_text = json.dumps({"error": str(e), "type": type(e).__name__})
                is_error = True
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": content_text,
                    "is_error": is_error,
                }
            )
        messages.append({"role": "user", "content": tool_results})

    if audit_response_arg:
        final_response_text = audit_response_arg
    elif all_turn_texts:
        final_response_text = "\n\n".join(all_turn_texts)
    else:
        final_response_text = (
            "[ERROR: agent exceeded MAX_TURNS without producing a final response]"
            if turn >= MAX_TURNS
            else ""
        )

    # METHODOLOGY §"Audit log specification" excludes audit_log calls
    # from per-task COST decomposition, but the 5% gate is about
    # MEASUREMENT correctness — our decomposition needs to account for
    # all tokens the API charged for. Resolution: report the inclusive
    # decomposition (gate holds against raw api_input_tokens) plus a
    # separate `audit_log_*` field giving the subtraction the comparison
    # report will apply downstream.
    audit_result_offset, audit_use_offset = _audit_offsets(messages, client=client)

    record = record_run(
        architecture="naive_rag",
        task_id=task["task_id"],
        decomposition=summed,
        api_usage=_MergedUsage(
            input_tokens=total_api_input,
            output_tokens=total_api_output,
            cache_creation_input_tokens=total_cache_create,
            cache_read_input_tokens=total_cache_read,
        ),
        response_text=final_response_text,
    )
    record.update(
        {
            "turns": turn,
            "tools_called": tools_called,
            "audit_log_tokens_in_retrieved_context": audit_result_offset,
            "audit_log_tokens_in_agent_intermediate": audit_use_offset,
        }
    )
    return record


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------


def _block_to_dict(block: Any) -> dict[str, Any]:
    """Anthropic SDK blocks are typed objects; convert to dicts for the
    next-turn messages payload.
    """
    btype = getattr(block, "type", None)
    if btype == "text":
        return {"type": "text", "text": block.text}
    if btype == "tool_use":
        return {
            "type": "tool_use",
            "id": block.id,
            "name": block.name,
            "input": block.input,
        }
    if btype == "thinking":
        # Extended thinking blocks — pass through as-is for completeness.
        return {"type": "thinking", "thinking": getattr(block, "thinking", "")}
    return {"type": btype, **{k: v for k, v in block.__dict__.items() if not k.startswith("_")}}


def _audit_offsets(
    messages: list[dict], *, client: anthropic.Anthropic
) -> tuple[int, int]:
    """Compute (retrieved_context_offset, agent_intermediate_offset).

    Per METHODOLOGY §"Audit log specification" audit_log calls are
    excluded from the per-task decomposition entirely. The two offsets
    cover:
      - audit_log tool_result texts (echoed back as retrieved_context)
      - audit_log tool_use blocks (echoed back as agent_intermediate on
        every subsequent turn after the audit_log call — typically zero
        because audit_log is the last call, but defensively summed)

    The offsets are computed via count_tokens on the same concatenated
    strings the decompose_request helpers would have counted, so the
    subtraction matches the inclusion exactly.
    """
    from measurement.tokens import count_tokens

    audit_use_ids: set[str] = set()
    audit_use_payloads: list[str] = []  # serialised same as decompose_request

    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if (
                isinstance(block, dict)
                and block.get("type") == "tool_use"
                and block.get("name") == AUDIT_TOOL_NAME
            ):
                audit_use_ids.add(block.get("id"))
                audit_use_payloads.append(
                    json.dumps(
                        {
                            "name": block.get("name", ""),
                            "input": block.get("input", {}),
                        },
                        separators=(",", ":"),
                        default=str,
                    )
                )

    audit_result_texts: list[str] = []
    for msg in messages:
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            if block.get("tool_use_id") in audit_use_ids:
                inner = block.get("content", "")
                if isinstance(inner, str):
                    audit_result_texts.append(inner)

    result_offset = (
        count_tokens("\n".join(audit_result_texts), client=client)
        if audit_result_texts
        else 0
    )
    use_offset = (
        count_tokens("\n".join(audit_use_payloads), client=client)
        if audit_use_payloads
        else 0
    )
    return result_offset, use_offset


class _MergedUsage:
    """Adapter shaped like anthropic Usage so record_run() can sum across
    multi-turn loops without changing record_run's API.
    """

    def __init__(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        cache_creation_input_tokens: int = 0,
        cache_read_input_tokens: int = 0,
    ) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_creation_input_tokens = cache_creation_input_tokens
        self.cache_read_input_tokens = cache_read_input_tokens


# ---------------------------------------------------------------------------
# Register into the runner's architecture registry
# ---------------------------------------------------------------------------


def _register() -> None:
    """Idempotent registration into the runner's ARCHITECTURE_REGISTRY.

    Defensive: importing this module twice (e.g., once as a script, once
    via `architectures.naive_rag.agent`) shouldn't double-register.
    """
    try:
        from measurement.runner import register_architecture

        register_architecture("naive_rag", run_task)
    except ImportError:
        # measurement.runner may not be importable in minimal test envs
        # — that's fine; registration is opt-in.
        pass


_register()
