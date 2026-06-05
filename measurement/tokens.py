"""Token counting and 6-category decomposition.

The 6-category extension of the Silicon Data decomposition (METHODOLOGY §
"What gets counted"). The original Silicon Data model has 5 categories;
adding `agent_intermediate` was necessary once multi-turn tool loops
landed in Phase 2 — the model's own prior-turn assistant content gets
echoed back as input on every subsequent turn, and that cost wasn't
attributable to any of the original 5 categories.

  1. system_prompt        — count_tokens on the system prompt string
  2. retrieved_context    — count_tokens on concatenated tool_result content
  3. user_message         — count_tokens on user-role text content
  4. tool_overhead        — count_tokens on the tools-schema JSON
  5. agent_intermediate   — count_tokens on assistant-role content from prior
                            turns (text + tool_use blocks) that gets echoed
                            back as input on subsequent turns
  6. response             — provider-reported `output_tokens` (NOT count_tokens)

The sum of categories 1-5 (input-side) must equal API-reported
`input_tokens` within 5% (METHODOLOGY's tolerance, validated by
`tests/test_tokens.py::TestMethodologyGate`). The remaining gap reflects
API framing overhead — message delimiters, role markers, etc. — which is
not attributable to any single input category.

Tokenization rule: this module uses Anthropic's official
`client.beta.messages.count_tokens()` API. We do NOT use `tiktoken`
(OpenAI's tokenizer, which produces wrong counts for Anthropic models).
"""
from __future__ import annotations

import json
from typing import Any

import anthropic


# Pinned per METHODOLOGY § "Model and configuration". Token counts are
# model-specific; using a different model here would silently produce
# wrong decomposition numbers.
AGENT_MODEL = "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# count_tokens
# ---------------------------------------------------------------------------


def count_tokens(text: str, *, client: anthropic.Anthropic) -> int:
    """Return the token count of `text` per the AGENT_MODEL tokenizer.

    Delegates to Anthropic's beta count_tokens endpoint. The text is sent
    as a single user-role message body — the framing overhead this adds
    is negligible for individual category counts and is absorbed by the
    5% tolerance at the decomposition level.
    """
    response = client.beta.messages.count_tokens(
        model=AGENT_MODEL,
        messages=[{"role": "user", "content": text}],
    )
    return int(response.input_tokens)


# Minimal user message used as the differential baseline for system_prompt
# and tool_overhead. The API rejects whitespace-only content, so we use a
# fixed single-character marker; its contribution cancels out in the
# differential.
_BASELINE_MESSAGE = [{"role": "user", "content": "_"}]


def _count_with_request_shape(
    *,
    client: anthropic.Anthropic,
    system: str | None = None,
    tools: list[dict] | None = None,
) -> int:
    """count_tokens against a baseline user message, optionally with
    system and/or tools attached. Used for the differential measurement
    of system_prompt and tool_overhead, which include framing the
    standalone-text counting can't see (the API renders tool schemas in
    a model-specific template that adds ~600 tokens of per-call framing
    a `json.dumps(tools)` doesn't capture).
    """
    kwargs: dict[str, Any] = {
        "model": AGENT_MODEL,
        "messages": _BASELINE_MESSAGE,
    }
    if system:
        kwargs["system"] = system
    if tools:
        kwargs["tools"] = tools
    response = client.beta.messages.count_tokens(**kwargs)
    return int(response.input_tokens)


# ---------------------------------------------------------------------------
# Helpers: extract category text from a messages list
# ---------------------------------------------------------------------------


def _extract_user_message_text(messages: list[dict]) -> str:
    """Concatenated text from user-role messages, EXCLUDING tool_result blocks.

    Tool results are also delivered in user-role messages but represent
    retrieved context (category 2), not user input (category 3). This
    helper separates them.
    """
    parts: list[str] = []
    for msg in messages:
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
    return "\n".join(parts)


def _extract_tool_result_text(messages: list[dict]) -> str:
    """Concatenated text from tool_result blocks across all messages."""
    parts: list[str] = []
    for msg in messages:
        content = msg.get("content", "")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            inner = block.get("content", "")
            if isinstance(inner, str):
                parts.append(inner)
            elif isinstance(inner, list):
                for sub in inner:
                    if isinstance(sub, dict) and sub.get("type") == "text":
                        parts.append(sub.get("text", ""))
    return "\n".join(parts)


def _extract_agent_intermediate_text(messages: list[dict]) -> str:
    """Concatenated text/tool_use payload from assistant-role messages.

    In multi-turn tool loops, each assistant turn's content (text blocks
    + tool_use blocks) is appended to `messages` and echoed back as input
    on every subsequent API call. Those echoed tokens don't fit any of
    the original 5 Silicon Data categories — they're the agent talking
    to itself across turns. This helper captures them so the
    decomposition gate holds for multi-turn architectures.

    Anthropic's tokenizer counts text blocks as their text content and
    tool_use blocks roughly as `name + serialised input`. We mirror that
    by serialising tool_use blocks as a compact JSON string. The gate's
    5% tolerance absorbs the small per-block framing overhead.
    """
    parts: list[str] = []
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content", "")
        if isinstance(content, str):
            parts.append(content)
            continue
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                parts.append(block.get("text", ""))
            elif btype == "tool_use":
                tu_payload = {
                    "name": block.get("name", ""),
                    "input": block.get("input", {}),
                }
                parts.append(
                    json.dumps(tu_payload, separators=(",", ":"), default=str)
                )
            elif btype == "thinking":
                parts.append(block.get("thinking", ""))
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# decompose_request
# ---------------------------------------------------------------------------


def decompose_request(
    *,
    system: str,
    messages: list[dict],
    tools: list[dict],
    output_tokens: int,
    client: anthropic.Anthropic,
) -> dict[str, int]:
    """Decompose a single API call's tokens into 6 categories.

    Categories 1-5 are counted via the count_tokens API on the relevant
    text. Category 6 (response) is the provider-reported `output_tokens`
    — this is mandated by METHODOLOGY and is NOT computed via count_tokens
    (output tokens differ from input tokens in framing and re-counting
    would inflate the number).

    METHODOLOGY note on framing overhead:
        Each count_tokens call adds ~7 tokens of envelope/role framing.
        For Phase 2 inputs (~500-token system prompts, ~200-token retrieved
        chunks), this overhead is <2% per category and the 5% sum gate
        comfortably holds. For tiny inputs (<50 tokens), framing dominates
        and the gate may fail — but that regime isn't what we measure.
        See `tests/test_tokens.py::TestMethodologyGateRecord` for the
        realistic-scenario baseline.

    METHODOLOGY note on multi-turn loops:
        `agent_intermediate` captures assistant-role content (text +
        tool_use blocks) that the model emitted on PRIOR turns and gets
        re-sent as input on subsequent turns. For a single-turn call this
        category is zero; for multi-turn tool loops it grows quickly. The
        gate's 5% tolerance is held across both regimes by including it.
    """
    # system_prompt and tool_overhead are measured DIFFERENTIALLY against
    # a baseline empty user message — the API renders tool schemas in a
    # model-specific template that adds ~600 tokens of per-call framing
    # which `count_tokens(json.dumps(tools))` doesn't capture. Caching
    # the baseline on the client avoids one count_tokens call per
    # decomposition; count_tokens itself is not billed for input tokens
    # (per Anthropic's count_tokens endpoint docs).
    if system or tools:
        baseline = _count_with_request_shape(client=client)
    else:
        baseline = 0

    if system:
        system_total = _count_with_request_shape(client=client, system=system)
        system_tokens = max(0, system_total - baseline)
    else:
        system_tokens = 0

    if tools:
        tools_total = _count_with_request_shape(client=client, tools=tools)
        tools_tokens = max(0, tools_total - baseline)
    else:
        tools_tokens = 0

    user_text = _extract_user_message_text(messages)
    user_tokens = count_tokens(user_text, client=client) if user_text else 0

    retrieved_text = _extract_tool_result_text(messages)
    retrieved_tokens = (
        count_tokens(retrieved_text, client=client) if retrieved_text else 0
    )

    agent_text = _extract_agent_intermediate_text(messages)
    agent_intermediate_tokens = (
        count_tokens(agent_text, client=client) if agent_text else 0
    )

    return {
        "system_prompt": system_tokens,
        "retrieved_context": retrieved_tokens,
        "user_message": user_tokens,
        "tool_overhead": tools_tokens,
        "agent_intermediate": agent_intermediate_tokens,
        "response": int(output_tokens),
    }


# ---------------------------------------------------------------------------
# record_run
# ---------------------------------------------------------------------------


_INPUT_CATEGORIES = (
    "system_prompt",
    "retrieved_context",
    "user_message",
    "tool_overhead",
    "agent_intermediate",
)


def record_run(
    *,
    architecture: str,
    task_id: str,
    decomposition: dict[str, int],
    api_usage: Any,
    response_text: str,
) -> dict[str, Any]:
    """Build a structured record for one task-architecture-run.

    `decomposition_input_sum` is the sum of input categories 1–5
    (system_prompt, retrieved_context, user_message, tool_overhead,
    agent_intermediate). METHODOLOGY requires this to be within 5% of
    `processed_input_tokens`; the runner asserts this and flags
    discrepancies.

    `processed_input_tokens` is the total input the model processed —
    `api_input_tokens + cache_creation_input_tokens + cache_read_input_tokens`.
    Collapses to `api_input_tokens` for uncached architectures (cache fields
    zero); the gate denominator and report aggregations should reference this
    field rather than recomputing the sum at each call site.

    `api_usage` should be an Anthropic Usage object (or any object with
    matching attributes). Cache fields default to 0 when absent.
    """
    api_input = int(api_usage.input_tokens)
    cache_create = int(getattr(api_usage, "cache_creation_input_tokens", 0) or 0)
    cache_read = int(getattr(api_usage, "cache_read_input_tokens", 0) or 0)
    return {
        "architecture": architecture,
        "task_id": task_id,
        "decomposition": dict(decomposition),
        "decomposition_input_sum": sum(decomposition[k] for k in _INPUT_CATEGORIES),
        "api_input_tokens": api_input,
        "api_output_tokens": int(api_usage.output_tokens),
        "cache_creation_input_tokens": cache_create,
        "cache_read_input_tokens": cache_read,
        "processed_input_tokens": api_input + cache_create + cache_read,
        "response_text": response_text,
    }


def get_processed_input_tokens(record: dict[str, Any]) -> int:
    """Return `processed_input_tokens` from a record, recomputing if absent.

    Prefers the explicit field (records produced by `record_run` since the
    field was added). Falls back to summing `api_input_tokens +
    cache_creation_input_tokens + cache_read_input_tokens` so legacy
    architecture_*.json from earlier runs still aggregate correctly.

    Treats an explicit `None` the same as a missing field — falls through
    to the component sum. Without the None-collapse the explicit branch
    would raise `TypeError: int() argument must not be NoneType` on
    hand-edited / partially-migrated records, while the fallback branch
    silently handled the same case on the cache counters.
    """
    value = record.get("processed_input_tokens")
    if value is not None:
        return int(value)
    return (
        int(record.get("api_input_tokens", 0) or 0)
        + int(record.get("cache_creation_input_tokens", 0) or 0)
        + int(record.get("cache_read_input_tokens", 0) or 0)
    )
