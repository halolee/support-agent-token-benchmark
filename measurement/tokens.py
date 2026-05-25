"""Token counting and 5-category decomposition.

The 5-category Silicon Data decomposition (METHODOLOGY § "What gets counted"):

  1. system_prompt       — count_tokens on the system prompt string
  2. retrieved_context   — count_tokens on concatenated tool_result content
  3. user_message        — count_tokens on user-role text content
  4. tool_overhead       — count_tokens on the tools-schema JSON
  5. response            — provider-reported `output_tokens` (NOT count_tokens)

The sum of categories 1-4 must equal API-reported `input_tokens` within 5%
(METHODOLOGY's tolerance, validated by `tests/test_tokens.py::
TestMethodologyGate`). The gap reflects API framing overhead — message
delimiters, role markers, etc. — which is not attributable to any single
input category.

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
    """Decompose a single API call's tokens into 5 categories.

    Categories 1-4 are counted via the count_tokens API on the relevant
    text. Category 5 (response) is the provider-reported `output_tokens`
    — this is mandated by METHODOLOGY and is NOT computed via count_tokens
    (output tokens differ from input tokens in framing and re-counting
    would inflate the number).
    """
    system_tokens = count_tokens(system, client=client) if system else 0

    user_text = _extract_user_message_text(messages)
    user_tokens = count_tokens(user_text, client=client) if user_text else 0

    retrieved_text = _extract_tool_result_text(messages)
    retrieved_tokens = (
        count_tokens(retrieved_text, client=client) if retrieved_text else 0
    )

    tools_text = json.dumps(tools, separators=(",", ":")) if tools else ""
    tools_tokens = count_tokens(tools_text, client=client) if tools_text else 0

    return {
        "system_prompt": system_tokens,
        "retrieved_context": retrieved_tokens,
        "user_message": user_tokens,
        "tool_overhead": tools_tokens,
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

    `decomposition_input_sum` is the sum of categories 1-4. METHODOLOGY
    requires this to be within 5% of `api_input_tokens`; the runner
    asserts this and flags discrepancies.

    `api_usage` should be an Anthropic Usage object (or any object with
    matching attributes). Cache fields default to 0 when absent.
    """
    return {
        "architecture": architecture,
        "task_id": task_id,
        "decomposition": dict(decomposition),
        "decomposition_input_sum": sum(decomposition[k] for k in _INPUT_CATEGORIES),
        "api_input_tokens": int(api_usage.input_tokens),
        "api_output_tokens": int(api_usage.output_tokens),
        "cache_creation_input_tokens": int(
            getattr(api_usage, "cache_creation_input_tokens", 0) or 0
        ),
        "cache_read_input_tokens": int(
            getattr(api_usage, "cache_read_input_tokens", 0) or 0
        ),
        "response_text": response_text,
    }
