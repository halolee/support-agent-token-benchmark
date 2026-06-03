"""Naive RAG agent — thin wrapper around the shared agent loop.

Per-architecture binding only: SYSTEM_PROMPT, TOOL_SCHEMAS, TOOL_DISPATCH,
AUDIT_TOOL_NAME. The loop logic (multi-turn tool execution, per-turn 6-
category decomposition summing, two-line audit ledger, MAX_TURNS guard,
response-text capture) lives in `architectures._shared.agent_loop` and is
identical across architectures by design — see METHODOLOGY § "Cross-
architecture parity rules".
"""
from __future__ import annotations

from typing import Any, Callable

import anthropic

from architectures._shared.agent_loop import run_task as _shared_run_task

from .prompts import SYSTEM_PROMPT
from .tools import AUDIT_TOOL_NAME, TOOL_DISPATCH, TOOL_SCHEMAS


def run_task(
    task: dict[str, Any],
    *,
    client: anthropic.Anthropic | None = None,
    tool_dispatch: dict[str, Callable] | None = None,
) -> dict[str, Any]:
    """Run a single Naive RAG task end-to-end. Returns a record_run() dict.

    `tool_dispatch` overrides the default TOOL_DISPATCH (used by tests to
    inject stubs). See `architectures._shared.agent_loop.run_task` for the
    full record shape.
    """
    return _shared_run_task(
        task,
        architecture="naive_rag",
        system_prompt=SYSTEM_PROMPT,
        tool_schemas=TOOL_SCHEMAS,
        tool_dispatch=tool_dispatch if tool_dispatch is not None else TOOL_DISPATCH,
        audit_tool_name=AUDIT_TOOL_NAME,
        client=client,
    )


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
