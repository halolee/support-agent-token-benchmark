"""Compliance's audit_log tool — uniform payload across architectures.

Per METHODOLOGY §"Audit log specification":

    Required fields per audit_log call:
        task_id      — string, identifier of the task being processed
        response     — string, the agent's final response to the customer
        tools_called — list, names of tools invoked during this task (in order)

    Forbidden in the audit payload (would introduce architectural variance):
        - Retrieved chunk content
        - Search keywords or query embeddings
        - Internal reasoning traces

    audit_log calls and their token cost are EXCLUDED from the per-task
    token decomposition.

The agent calls this tool once, at the end of each task, before returning
its final response. Implementation is a no-op append to an in-memory list
during measurement runs — Compliance's real backing store is out of scope.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class AuditRecord:
    task_id: str
    response: str
    tools_called: list[str]


# Module-level sink for measurement runs. Tests can clear and inspect this.
AUDIT_LOG: list[AuditRecord] = []


def audit_log(
    *, task_id: str, response: str, tools_called: list[str]
) -> dict[str, Any]:
    """Record a uniform audit entry. Returns a small ack the agent sees."""
    record = AuditRecord(
        task_id=str(task_id),
        response=str(response),
        tools_called=[str(name) for name in tools_called],
    )
    AUDIT_LOG.append(record)
    return {"status": "logged", "task_id": record.task_id}


AUDIT_TOOL_SCHEMA: dict[str, Any] = {
    "name": "audit_log",
    "description": (
        "Compliance audit logging. Call this once, at the end of the task, "
        "with the task_id, your final response text, and the ordered list "
        "of tool names you invoked. The payload is intentionally uniform "
        "across all support-agent architectures."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "Identifier of the task being processed.",
            },
            "response": {
                "type": "string",
                "description": "Your final response to the customer (verbatim).",
            },
            "tools_called": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Ordered list of tool names invoked for this task.",
            },
        },
        "required": ["task_id", "response", "tools_called"],
    },
}
