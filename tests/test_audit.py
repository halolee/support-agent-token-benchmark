"""Tests for `architectures/_shared/audit.py`.

Compliance's audit_log tool — uniform payload across architectures per
METHODOLOGY §"Audit log specification". The tests pin the contract so
the comparison can't be confounded by per-architecture audit shapes.
"""
from __future__ import annotations


class TestAuditLog:
    def setup_method(self):
        from architectures._shared.audit import AUDIT_LOG

        AUDIT_LOG.clear()

    def test_records_uniform_payload(self):
        from architectures._shared.audit import AUDIT_LOG, audit_log

        ack = audit_log(
            task_id="POL-001",
            response="The answer is...",
            tools_called=["vector_search", "audit_log"],
        )
        assert ack == {"status": "logged", "task_id": "POL-001"}
        assert len(AUDIT_LOG) == 1
        record = AUDIT_LOG[0]
        assert record.task_id == "POL-001"
        assert record.response == "The answer is..."
        assert record.tools_called == ["vector_search", "audit_log"]

    def test_coerces_types(self):
        from architectures._shared.audit import AUDIT_LOG, audit_log

        audit_log(task_id=123, response=None, tools_called=["t"])
        record = AUDIT_LOG[0]
        assert isinstance(record.task_id, str) and record.task_id == "123"
        assert isinstance(record.response, str)
        assert record.tools_called == ["t"]


class TestAuditSchema:
    def test_schema_has_required_keys(self):
        from architectures._shared.audit import AUDIT_TOOL_SCHEMA

        assert AUDIT_TOOL_SCHEMA["name"] == "audit_log"
        props = AUDIT_TOOL_SCHEMA["input_schema"]["properties"]
        assert set(props.keys()) == {"task_id", "response", "tools_called"}
        required = AUDIT_TOOL_SCHEMA["input_schema"]["required"]
        assert set(required) == {"task_id", "response", "tools_called"}

    def test_forbidden_fields_not_in_schema(self):
        """METHODOLOGY forbids retrieved-chunk content, search keywords,
        and internal reasoning traces in the audit payload (would
        introduce architectural variance). Verify they're not in the schema.
        """
        from architectures._shared.audit import AUDIT_TOOL_SCHEMA

        props = AUDIT_TOOL_SCHEMA["input_schema"]["properties"]
        for forbidden in ("chunks", "keywords", "query_embedding", "reasoning"):
            assert forbidden not in props
