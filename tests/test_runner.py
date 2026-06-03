"""Tests for measurement/runner.py — the orchestration CLI.

Mocked unit tests cover:
  · CLI argument parsing
  · smoke_agent function (single-turn, mocked client)
  · run_smoke gate behavior (pass + fail paths)
  · --report flag against fixture result files
  · architecture registry dispatch
  · run_measurement orchestration (alternating order, retry, gate, JSON shape)

Real-API smoke run is in `pytest --run-live-api -m live_api` territory;
this file tests the orchestration logic, not the live behavior.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def clean_registry():
    """Snapshot ARCHITECTURE_REGISTRY before a test and restore after.

    Tests that inject fake architectures (or assert post-import state)
    must not leak registrations into sibling tests — the real agent
    modules register themselves at import time and we want a clean slate
    around each manipulation.
    """
    from measurement.runner import ARCHITECTURE_REGISTRY

    before = dict(ARCHITECTURE_REGISTRY)
    ARCHITECTURE_REGISTRY.clear()
    try:
        yield ARCHITECTURE_REGISTRY
    finally:
        ARCHITECTURE_REGISTRY.clear()
        ARCHITECTURE_REGISTRY.update(before)


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

        args = parse_args(["--architectures", "naive_rag,grep_search,hybrid_rag"])
        assert args.architectures == "naive_rag,grep_search,hybrid_rag"

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

    def test_limit_arg(self):
        from measurement.runner import parse_args

        args = parse_args(["--limit", "1"])
        assert args.limit == 1
        # Default is None — full task set.
        assert parse_args([]).limit is None


# =========================================================================
# smoke_agent
# =========================================================================


def _make_mock_client(
    *,
    api_input_tokens: int,
    api_output_tokens: int,
    count_tokens_value: int = 50,
    baseline_value: int = 5,
    system_delta: int | None = None,
    tools_delta: int | None = None,
) -> MagicMock:
    """Construct a mocked Anthropic client with controllable token counts.

    decompose_request issues two kinds of count_tokens calls:
      (a) Standalone text counts — `messages=[{role:user, content:<text>}]`.
          Returns `count_tokens_value` for any non-baseline text.
      (b) Differential shape probes — `messages=_BASELINE_MESSAGE` plus
          optional `system=`/`tools=`. Returns `baseline_value`, or
          `baseline_value + system_delta` / `+ tools_delta` when those
          kwargs are present.

    Defaults are tuned so the smoke flow's sum lands on `api_input_tokens`:
    one system + one user piece, no tools → sum = system_delta + count_tokens_value.
    """
    client = MagicMock()

    create_response = MagicMock()
    create_response.content = [MagicMock(text="Mocked agent response.")]
    create_response.usage = MagicMock(
        input_tokens=api_input_tokens,
        output_tokens=api_output_tokens,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )
    client.messages.create.return_value = create_response

    def count_tokens_side_effect(*args, **kwargs):
        messages = kwargs.get("messages", [])
        system = kwargs.get("system")
        tools = kwargs.get("tools")
        is_baseline = (
            isinstance(messages, list)
            and len(messages) == 1
            and isinstance(messages[0].get("content"), str)
            and messages[0]["content"] == "_"
        )
        if is_baseline:
            total = baseline_value
            if system and system_delta is not None:
                total += system_delta
            if tools and tools_delta is not None:
                total += tools_delta
            return MagicMock(input_tokens=total)
        return MagicMock(input_tokens=count_tokens_value)

    client.beta.messages.count_tokens.side_effect = count_tokens_side_effect
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
        # All 6 categories present (5 input-side + response)
        for cat in (
            "system_prompt",
            "retrieved_context",
            "user_message",
            "tool_overhead",
            "agent_intermediate",
            "response",
        ):
            assert cat in record["decomposition"]


# =========================================================================
# run_smoke gate
# =========================================================================


class TestRunSmoke:
    def test_passes_gate_when_sums_match_within_tolerance(self, capsys):
        from measurement.runner import run_smoke

        # API says 100. Smoke scenario has system + user, no tools, no
        # tool_results, no assistant turns. Differential gives
        # system_tokens = system_delta, plus standalone user = 50. So
        # sum = 50 + 50 = 100 → exact match.
        client = _make_mock_client(
            api_input_tokens=100,
            api_output_tokens=5,
            count_tokens_value=50,
            baseline_value=5,
            system_delta=50,
        )
        exit_code = run_smoke(client=client)
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "PASS" in out

    def test_fails_gate_when_sum_diverges_beyond_tolerance(self, capsys):
        from measurement.runner import run_smoke

        # API says 100. With system_delta=80 and user=80, sum=160 → 60% over.
        client = _make_mock_client(
            api_input_tokens=100,
            api_output_tokens=5,
            count_tokens_value=80,
            baseline_value=5,
            system_delta=80,
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
            "architecture": "naive_rag",
            "runs": [
                {
                    "task_id": "POL-001",
                    "decomposition": {
                        "system_prompt": 500,
                        "retrieved_context": 800,
                        "user_message": 50,
                        "tool_overhead": 200,
                        "agent_intermediate": 0,
                        "response": 250,
                    },
                    "api_input_tokens": 1550,
                    "api_output_tokens": 250,
                }
            ],
        }
        (tmp_path / "architecture_naive_rag.json").write_text(json.dumps(result_a))

        output_path = tmp_path / "comparison.md"
        exit_code = generate_report(results_dir=tmp_path, output_path=output_path)
        assert exit_code == 0
        assert output_path.exists()
        content = output_path.read_text()
        # Naive RAG's mean tokens should appear in the output
        assert "naive_rag" in content.lower()


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


# =========================================================================
# Full measurement run (--architectures dispatch path)
# =========================================================================


def _good_record(arch: str, task_id: str, *, api_input: int = 1500) -> dict:
    """A minimal record_run-shaped dict the runner is comfortable with.

    Mirrors what `architectures._shared.agent_loop.run_task` returns:
    decomposition with all six categories, decomposition_input_sum
    (audit-excluded), decomposition_input_sum_with_audit (audit-included,
    matches api_input_tokens for a clean gate pass).
    """
    decomposition = {
        "system_prompt": 500,
        "retrieved_context": 700,
        "user_message": 50,
        "tool_overhead": 200,
        "agent_intermediate": 50,
        "response": 200,
    }
    inclusive = sum(decomposition[k] for k in decomposition if k != "response")
    return {
        "architecture": arch,
        "task_id": task_id,
        "decomposition": decomposition,
        "decomposition_input_sum": inclusive,
        "decomposition_input_sum_with_audit": api_input,
        "api_input_tokens": api_input,
        "api_output_tokens": 200,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "response_text": "ok",
        "turns": 2,
        "tools_called": ["vector_search", "audit_log"],
        "audit_log_tokens_in_retrieved_context": 0,
        "audit_log_tokens_in_agent_intermediate": 0,
    }


def _write_tasks_file(tmp_path: Path, tasks: list[dict]) -> Path:
    """JSONL with a leading comment line, mirroring the real tasks.jsonl."""
    lines = ["# COMPLETE — frozen for test."]
    lines.extend(json.dumps(t) for t in tasks)
    path = tmp_path / "tasks.jsonl"
    path.write_text("\n".join(lines) + "\n")
    return path


class TestLoadTasks:
    def test_skips_comments_and_blank_lines(self, tmp_path):
        from measurement.runner import _load_tasks

        path = tmp_path / "tasks.jsonl"
        path.write_text(
            "# header comment\n"
            "\n"
            '{"task_id": "T1", "user_message": "hi"}\n'
            "  \n"
            '{"task_id": "T2", "user_message": "bye"}\n'
        )
        tasks = _load_tasks(path)
        assert [t["task_id"] for t in tasks] == ["T1", "T2"]


class TestLoadArchitectures:
    def test_uses_pre_registered_fakes_without_importing(self, clean_registry):
        from measurement.runner import _load_architectures, register_architecture

        sentinel = lambda *a, **k: None  # noqa: E731
        register_architecture("fake_arch", sentinel)

        resolved = _load_architectures(["fake_arch"])
        assert resolved == {"fake_arch": sentinel}

    def test_unknown_architecture_raises(self, clean_registry):
        from measurement.runner import _load_architectures

        with pytest.raises(RuntimeError, match="not found"):
            _load_architectures(["does_not_exist_arch"])


class TestRunMeasurementOrder:
    def test_alternates_archs_per_task(self, tmp_path, clean_registry):
        """METHODOLOGY §"Run protocol": for each task within a run pass,
        every architecture dispatches before moving to the next task.
        """
        from measurement.runner import register_architecture, run_measurement

        order: list[tuple[str, str, int]] = []

        def make_fn(name):
            counter = {"i": 0}

            def fn(task, *, client=None):
                rec = _good_record(name, task["task_id"])
                order.append((name, task["task_id"], counter["i"]))
                counter["i"] += 1
                return rec

            return fn

        register_architecture("arch_a", make_fn("arch_a"))
        register_architecture("arch_b", make_fn("arch_b"))

        tasks_path = _write_tasks_file(
            tmp_path,
            [
                {"task_id": "T1", "user_message": "q1"},
                {"task_id": "T2", "user_message": "q2"},
            ],
        )
        results_dir = tmp_path / "results"
        exit_code = run_measurement(
            architectures=["arch_a", "arch_b"],
            tasks_path=tasks_path,
            runs=2,
            results_dir=results_dir,
            client=MagicMock(),
        )
        assert exit_code == 0
        # Run 1: T1-a, T1-b, T2-a, T2-b. Run 2: same. Eight total dispatches.
        names_in_order = [n for n, _, _ in order]
        assert names_in_order == [
            "arch_a", "arch_b",
            "arch_a", "arch_b",
            "arch_a", "arch_b",
            "arch_a", "arch_b",
        ]
        task_in_order = [t for _, t, _ in order]
        assert task_in_order == ["T1", "T1", "T2", "T2", "T1", "T1", "T2", "T2"]


class TestRunMeasurementOutput:
    def test_writes_one_json_per_architecture_with_runs(
        self, tmp_path, clean_registry
    ):
        from measurement.runner import register_architecture, run_measurement

        register_architecture(
            "arch_a", lambda task, **_: _good_record("arch_a", task["task_id"])
        )
        register_architecture(
            "arch_b", lambda task, **_: _good_record("arch_b", task["task_id"])
        )

        tasks_path = _write_tasks_file(
            tmp_path, [{"task_id": "T1", "user_message": "q"}]
        )
        results_dir = tmp_path / "results"
        run_measurement(
            architectures=["arch_a", "arch_b"],
            tasks_path=tasks_path,
            runs=3,
            results_dir=results_dir,
            client=MagicMock(),
        )

        for arch in ("arch_a", "arch_b"):
            path = results_dir / f"architecture_{arch}.json"
            assert path.exists()
            payload = json.loads(path.read_text())
            assert payload["architecture"] == arch
            assert payload["config"]["runs_per_task"] == 3
            assert payload["config"]["tasks_count"] == 1
            assert len(payload["runs"]) == 3  # 1 task × 3 runs
            assert payload["errors"] == []
            run0 = payload["runs"][0]
            assert run0["run_index"] == 0
            assert run0["task_id"] == "T1"
            assert "gate_ratio" in run0
            assert run0["gate_breach"] is False

    def test_output_round_trips_into_report(self, tmp_path, clean_registry):
        """The per-architecture JSON the run produces is the same shape
        `--report` consumes. Catches the easy mistake of changing the
        record schema in one place without the other.
        """
        from measurement.runner import (
            generate_report,
            register_architecture,
            run_measurement,
        )

        register_architecture(
            "arch_a", lambda task, **_: _good_record("arch_a", task["task_id"])
        )
        tasks_path = _write_tasks_file(
            tmp_path, [{"task_id": "T1", "user_message": "q"}]
        )
        results_dir = tmp_path / "results"
        run_measurement(
            architectures=["arch_a"],
            tasks_path=tasks_path,
            runs=2,
            results_dir=results_dir,
            client=MagicMock(),
        )
        exit_code = generate_report(
            results_dir=results_dir, output_path=results_dir / "comparison.md"
        )
        assert exit_code == 0
        report = (results_dir / "comparison.md").read_text()
        assert "arch_a" in report


class TestRunMeasurementRetry:
    def test_retries_transient_error_and_succeeds(self, tmp_path, clean_registry):
        from measurement.runner import register_architecture, run_measurement

        attempts = {"n": 0}

        def flaky(task, **_):
            attempts["n"] += 1
            if attempts["n"] < 2:
                raise RuntimeError("transient API blip")
            return _good_record("flaky", task["task_id"])

        register_architecture("flaky", flaky)
        tasks_path = _write_tasks_file(
            tmp_path, [{"task_id": "T1", "user_message": "q"}]
        )
        results_dir = tmp_path / "results"
        run_measurement(
            architectures=["flaky"],
            tasks_path=tasks_path,
            runs=1,
            results_dir=results_dir,
            client=MagicMock(),
        )
        payload = json.loads(
            (results_dir / "architecture_flaky.json").read_text()
        )
        assert len(payload["runs"]) == 1
        assert payload["runs"][0]["attempts"] == 2
        assert payload["errors"] == []

    def test_records_error_after_exhausted_retries(self, tmp_path, clean_registry):
        """METHODOLOGY §"Run protocol": initial attempt + 2 retries.
        After three failures the task is flagged for that run."""
        from measurement.runner import register_architecture, run_measurement

        def always_fails(task, **_):
            raise RuntimeError("persistent failure")

        register_architecture("dead", always_fails)
        tasks_path = _write_tasks_file(
            tmp_path, [{"task_id": "T1", "user_message": "q"}]
        )
        results_dir = tmp_path / "results"
        run_measurement(
            architectures=["dead"],
            tasks_path=tasks_path,
            runs=1,
            results_dir=results_dir,
            client=MagicMock(),
        )
        payload = json.loads(
            (results_dir / "architecture_dead.json").read_text()
        )
        assert payload["runs"] == []
        assert len(payload["errors"]) == 1
        err = payload["errors"][0]
        assert err["task_id"] == "T1"
        assert err["attempts"] == 3  # initial + 2 retries


class TestRunMeasurementGate:
    def test_gate_breach_flagged_not_silenced(self, tmp_path, clean_registry, capsys):
        """CLAUDE.md invariant: runner asserts the 5% gate and flags
        discrepancies; do not silence."""
        from measurement.runner import register_architecture, run_measurement

        def bad_record(task, **_):
            rec = _good_record("breachy", task["task_id"], api_input=2000)
            # Sum-with-audit is 1500; API is 2000 → 25% gap.
            rec["decomposition_input_sum_with_audit"] = 1500
            return rec

        register_architecture("breachy", bad_record)
        tasks_path = _write_tasks_file(
            tmp_path, [{"task_id": "T1", "user_message": "q"}]
        )
        results_dir = tmp_path / "results"
        run_measurement(
            architectures=["breachy"],
            tasks_path=tasks_path,
            runs=1,
            results_dir=results_dir,
            client=MagicMock(),
        )
        payload = json.loads(
            (results_dir / "architecture_breachy.json").read_text()
        )
        run0 = payload["runs"][0]
        assert run0["gate_breach"] is True
        assert run0["gate_ratio"] >= 0.05
        # Breach is also surfaced on stderr — flagged, not silent.
        err = capsys.readouterr().err
        assert "gate-breach" in err


class TestRunMeasurementLimit:
    def test_limit_truncates_task_set(self, tmp_path, clean_registry):
        from measurement.runner import register_architecture, run_measurement

        seen: list[str] = []

        def arch(task, **_):
            seen.append(task["task_id"])
            return _good_record("trunc", task["task_id"])

        register_architecture("trunc", arch)
        tasks_path = _write_tasks_file(
            tmp_path,
            [
                {"task_id": "T1", "user_message": "q1"},
                {"task_id": "T2", "user_message": "q2"},
                {"task_id": "T3", "user_message": "q3"},
            ],
        )
        run_measurement(
            architectures=["trunc"],
            tasks_path=tasks_path,
            runs=1,
            results_dir=tmp_path / "results",
            limit=1,
            client=MagicMock(),
        )
        assert seen == ["T1"]


class TestMainArchitecturesDispatch:
    def test_main_routes_architectures_to_run_measurement(
        self, tmp_path, monkeypatch
    ):
        """main() with --architectures must dispatch to run_measurement
        and not the old Phase-2 stub message."""
        from measurement import runner

        called: dict = {}

        def fake_run_measurement(**kwargs):
            called.update(kwargs)
            return 0

        monkeypatch.setattr(runner, "run_measurement", fake_run_measurement)
        tasks_path = tmp_path / "tasks.jsonl"
        tasks_path.write_text('{"task_id":"T","user_message":"q"}\n')

        exit_code = runner.main(
            [
                "--architectures", "naive_rag,grep_search",
                "--tasks", str(tasks_path),
                "--runs", "1",
                "--limit", "1",
                "--results-dir", str(tmp_path / "results"),
            ]
        )
        assert exit_code == 0
        assert called["architectures"] == ["naive_rag", "grep_search"]
        assert called["tasks_path"] == tasks_path
        assert called["runs"] == 1
        assert called["limit"] == 1
