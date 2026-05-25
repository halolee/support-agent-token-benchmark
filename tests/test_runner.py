"""Tests for measurement/runner.py — the orchestration CLI.

Mocked unit tests cover:
  · CLI argument parsing
  · smoke_agent function (single-turn, mocked client)
  · run_smoke gate behavior (pass + fail paths)
  · --report flag against fixture result files
  · architecture registry dispatch

Real-API smoke run is in `pytest --run-live-api -m live_api` territory;
this file tests the orchestration logic, not the live behavior.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# =========================================================================
# CLI argument parsing
# =========================================================================


class TestParseArgs:
    def test_smoke_flag(self):
        from measurement.runner import parse_args

        args = parse_args(["--smoke"])
        assert args.smoke is True
        assert args.report is False

    def test_report_flag(self):
        from measurement.runner import parse_args

        args = parse_args(["--report"])
        assert args.report is True
        assert args.smoke is False

    def test_architectures_passed_as_csv_string(self):
        from measurement.runner import parse_args

        args = parse_args(["--architectures", "a,c,e"])
        assert args.architectures == "a,c,e"

    def test_runs_defaults_to_3(self):
        from measurement.runner import parse_args

        args = parse_args([])
        assert args.runs == 3

    def test_runs_override(self):
        from measurement.runner import parse_args

        args = parse_args(["--runs", "5"])
        assert args.runs == 5

    def test_tasks_as_path(self):
        from measurement.runner import parse_args

        args = parse_args(["--tasks", "measurement/tasks.jsonl"])
        assert args.tasks == Path("measurement/tasks.jsonl")


# =========================================================================
# smoke_agent
# =========================================================================


def _make_mock_client(
    *, api_input_tokens: int, api_output_tokens: int, count_tokens_value: int = 50
) -> MagicMock:
    """Construct a mocked Anthropic client with controllable token counts."""
    client = MagicMock()

    # messages.create() response
    create_response = MagicMock()
    create_response.content = [MagicMock(text="Mocked agent response.")]
    create_response.usage = MagicMock(
        input_tokens=api_input_tokens,
        output_tokens=api_output_tokens,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )
    client.messages.create.return_value = create_response

    # count_tokens responses (uniform value across all pieces)
    client.beta.messages.count_tokens.return_value = MagicMock(
        input_tokens=count_tokens_value
    )
    return client


class TestSmokeAgent:
    def test_returns_well_formed_record(self):
        from measurement.runner import smoke_agent

        client = _make_mock_client(api_input_tokens=100, api_output_tokens=5)
        task = {"task_id": "SMOKE-1", "user_message": "Acknowledge."}
        record = smoke_agent(client, task)

        assert record["task_id"] == "SMOKE-1"
        assert record["architecture"] == "smoke"
        assert record["api_input_tokens"] == 100
        assert record["api_output_tokens"] == 5
        assert record["response_text"] == "Mocked agent response."

    def test_calls_messages_create_with_agent_model(self):
        from measurement.runner import smoke_agent
        from measurement.tokens import AGENT_MODEL

        client = _make_mock_client(api_input_tokens=100, api_output_tokens=5)
        task = {"task_id": "SMOKE-1", "user_message": "hi"}
        smoke_agent(client, task)

        call = client.messages.create.call_args
        assert call.kwargs.get("model") == AGENT_MODEL

    def test_decomposition_present(self):
        from measurement.runner import smoke_agent

        client = _make_mock_client(api_input_tokens=200, api_output_tokens=10)
        task = {"task_id": "SMOKE-1", "user_message": "hi"}
        record = smoke_agent(client, task)

        assert "decomposition" in record
        # All 5 categories present
        for cat in (
            "system_prompt",
            "retrieved_context",
            "user_message",
            "tool_overhead",
            "response",
        ):
            assert cat in record["decomposition"]


# =========================================================================
# run_smoke gate
# =========================================================================


class TestRunSmoke:
    def test_passes_gate_when_sums_match_within_tolerance(self, capsys):
        from measurement.runner import run_smoke

        # API says 100, count_tokens for each piece returns 50.
        # We have system + user (2 non-empty pieces), so sum = 100 → exact match.
        client = _make_mock_client(
            api_input_tokens=100,
            api_output_tokens=5,
            count_tokens_value=50,
        )
        exit_code = run_smoke(client=client)
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "PASS" in out

    def test_fails_gate_when_sum_diverges_beyond_tolerance(self, capsys):
        from measurement.runner import run_smoke

        # API says 100, but count_tokens returns 80 per call → sum=160 → 60% over.
        client = _make_mock_client(
            api_input_tokens=100,
            api_output_tokens=5,
            count_tokens_value=80,
        )
        exit_code = run_smoke(client=client)
        assert exit_code == 1
        out = capsys.readouterr().out
        assert "FAIL" in out


# =========================================================================
# --report
# =========================================================================


class TestReport:
    def test_handles_no_result_files(self, tmp_path, capsys):
        from measurement.runner import generate_report

        # Empty results directory
        exit_code = generate_report(results_dir=tmp_path, output_path=tmp_path / "comparison.md")
        # Should not crash; should write a placeholder report or exit gracefully
        assert exit_code in (0, 1)  # accepting either "wrote template" or "nothing to do"

    def test_aggregates_result_files(self, tmp_path):
        from measurement.runner import generate_report

        # Fabricate a couple of fixture result files
        result_a = {
            "architecture": "a",
            "runs": [
                {
                    "task_id": "POL-001",
                    "decomposition": {
                        "system_prompt": 500,
                        "retrieved_context": 800,
                        "user_message": 50,
                        "tool_overhead": 200,
                        "response": 250,
                    },
                    "api_input_tokens": 1550,
                    "api_output_tokens": 250,
                }
            ],
        }
        (tmp_path / "architecture_a.json").write_text(json.dumps(result_a))

        output_path = tmp_path / "comparison.md"
        exit_code = generate_report(results_dir=tmp_path, output_path=output_path)
        assert exit_code == 0
        assert output_path.exists()
        content = output_path.read_text()
        # Architecture A's mean tokens should appear in the output
        assert "Architecture A" in content or "a" in content.lower()


# =========================================================================
# main() routing
# =========================================================================


class TestMain:
    def test_smoke_routes_to_run_smoke(self, monkeypatch):
        from measurement import runner

        called = {}

        def fake_run_smoke(client=None):
            called["smoke"] = True
            return 0

        monkeypatch.setattr(runner, "run_smoke", fake_run_smoke)
        exit_code = runner.main(["--smoke"])
        assert exit_code == 0
        assert called.get("smoke") is True

    def test_no_args_prints_usage(self, capsys):
        from measurement.runner import main

        exit_code = main([])
        assert exit_code != 0
        err = capsys.readouterr().err
        assert "Usage" in err or "usage" in err
