"""Grep search agent — thin wrapper around the shared agent loop.

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
    """Run a single Grep search task end-to-end. Returns a record_run() dict.

    `tool_dispatch` overrides the default TOOL_DISPATCH (used by tests to
    inject stubs). See `architectures._shared.agent_loop.run_task` for the
    full record shape.
    """
    return _shared_run_task(
        task,
        architecture="grep_search",
        system_prompt=SYSTEM_PROMPT,
        tool_schemas=TOOL_SCHEMAS,
        tool_dispatch=tool_dispatch if tool_dispatch is not None else TOOL_DISPATCH,
        audit_tool_name=AUDIT_TOOL_NAME,
        client=client,
    )


def _register() -> None:
    """Idempotent registration into the runner's ARCHITECTURE_REGISTRY.

    Defensive: importing this module twice (e.g., once as a script, once
    via `architectures.grep_search.agent`) shouldn't double-register.

    The find_spec gate distinguishes "measurement.runner module is
    genuinely absent" (minimal test envs — silent skip is correct) from
    "runner exists but its import chain broke" (typo in measurement.tokens,
    missing transitive dep, etc.). A bare `except ImportError: pass` here
    would swallow the second case and the architecture would silently fail
    to register, routing debugging to the wrong file. See issue #33.

    Note find_spec itself raises ModuleNotFoundError when the parent
    `measurement` package isn't on sys.path at all (vs returning None
    when the parent exists but `runner` is missing as a submodule).
    Catch ModuleNotFoundError specifically — NOT the broader ImportError —
    so a broken `measurement/__init__.py` (ImportError but not
    ModuleNotFoundError) still propagates loudly, preserving the spirit
    of the fix.
    """
    import importlib.util

    try:
        spec = importlib.util.find_spec("measurement.runner")
    except ModuleNotFoundError:
        return
    if spec is None:
        return
    from measurement.runner import register_architecture

    register_architecture("grep_search", run_task)


_register()
