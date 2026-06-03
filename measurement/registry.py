"""Architecture registry — a single module that's imported the same way
no matter how the runner is invoked.

Why this is its own module: `python -m measurement.runner` (or
`python measurement/runner.py`) loads the runner under the name
`__main__`. When an architecture's `agent.py` then does
`from measurement.runner import register_architecture`, Python imports
the runner a SECOND time under the name `measurement.runner` — two
separate module objects with separate top-level globals. A registry
defined on the runner itself ends up populated in one copy and queried
on the other, and dispatch sees an empty dict.

Pinning the registry to `measurement.registry` removes the ambiguity:
both copies of the runner import the same `measurement.registry` module,
so the dict has exactly one identity in `sys.modules`. The agents
continue importing `register_architecture` from `measurement.runner`
(unchanged) — the runner re-exports the function from here.
"""
from __future__ import annotations

from typing import Callable


ARCHITECTURE_REGISTRY: dict[str, Callable] = {}


def register_architecture(name: str, agent_fn: Callable) -> None:
    """Register an architecture's agent function. Called from each
    `architectures/<arch>/agent.py` module at import time.
    """
    ARCHITECTURE_REGISTRY[name] = agent_fn
