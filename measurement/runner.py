"""Orchestration CLI for the support-agent-token-benchmark project.

Three modes:

  --smoke         Single trivial task end-to-end (Phase 1 verification).
                  Makes one real API call, asserts the 5% methodology
                  gate, exits 0/1. Cost: ~$0.01.

  --architectures Run measurement across listed architectures × tasks ×
                  runs. Writes per-architecture JSON to
                  measurement/results/architecture_<id>.json. Order is
                  per-task across architectures (METHODOLOGY §"Run
                  protocol") to control for time-of-day API variance.
                  Use --limit N to truncate the task set for a cheap
                  end-to-end smoke before the full run.

  --report        Aggregate the per-architecture JSON files into
                  measurement/results/comparison.md.

Architectures register themselves into ARCHITECTURE_REGISTRY when their
agent.py modules are imported. The runner imports them lazily on
--architectures dispatch so unrelated commands (--smoke, --report) don't
pay the import cost or require the architecture's heavy deps.
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any, Callable

# Support both `python measurement/runner.py` and `python -m measurement.runner`.
if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import anthropic

try:
    # Auto-load ANTHROPIC_API_KEY from .env when invoked as a script.
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from measurement.registry import ARCHITECTURE_REGISTRY, register_architecture
from measurement.tokens import AGENT_MODEL, decompose_request, record_run


# `ARCHITECTURE_REGISTRY` and `register_architecture` live in
# `measurement.registry` (re-exported here) so they have a single
# identity even when this module is loaded twice (once as `__main__`,
# once as `measurement.runner`) — see the docstring on
# `measurement.registry` for the full reasoning. Existing callers
# (`from measurement.runner import register_architecture`) keep working.
__all__ = ["ARCHITECTURE_REGISTRY", "register_architecture"]


# ---------------------------------------------------------------------------
# Smoke mode — Phase 1 verification
# ---------------------------------------------------------------------------


# System prompt is deliberately ~150 tokens — the methodology's 5%
# decomposition gate is sensitive to per-call framing overhead at small
# input sizes (see tests/test_tokens.py::TestMethodologyGateRecord and
# the framing-overhead note in measurement/tokens.py::decompose_request).
# Phase 2 architectures will use ~300-500 token system prompts; this
# smoke prompt is sized in the same regime so the gate is a fair test.
_SMOKE_SYSTEM_PROMPT = (
    "You are a customer support agent for Swiss Airlines. Your role is "
    "to help customers with their bookings, flights, and travel policies.\n\n"
    "Guidelines:\n"
    "- Be concise but complete. Don't pad responses with unnecessary "
    "pleasantries.\n"
    "- When citing policy, always reference the specific section.\n"
    "- If a customer's question requires looking up data, use the tools "
    "provided.\n"
    "- If you don't know something, say so directly rather than guessing.\n"
    "- Confirm booking IDs back to the customer before making changes.\n"
    "- For policy questions outside your knowledge, escalate to a human "
    "agent.\n\n"
    "Tone: professional, helpful, calm. The customer is often stressed "
    "about travel."
)

_SMOKE_TASK = {
    "task_id": "SMOKE-1",
    "user_message": (
        "Hi, I'd like to confirm — if my flight is cancelled by your airline, "
        "do I get my money back automatically or do I need to request it?"
    ),
}


def smoke_agent(client: anthropic.Anthropic, task: dict) -> dict:
    """Single-turn agent for --smoke verification.

    NOT a real architecture — just exercises the measurement pipeline
    end-to-end with one direct API call. Returns a record_run() dict.
    """
    system = _SMOKE_SYSTEM_PROMPT
    messages = [{"role": "user", "content": task["user_message"]}]
    tools: list[dict] = []

    response = client.messages.create(
        model=AGENT_MODEL,
        max_tokens=512,
        system=system,
        messages=messages,
    )
    response_text = (
        response.content[0].text
        if response.content and hasattr(response.content[0], "text")
        else ""
    )

    decomposition = decompose_request(
        system=system,
        messages=messages,
        tools=tools,
        output_tokens=response.usage.output_tokens,
        client=client,
    )

    return record_run(
        architecture="smoke",
        task_id=task["task_id"],
        decomposition=decomposition,
        api_usage=response.usage,
        response_text=response_text,
    )


def run_smoke(*, client: anthropic.Anthropic | None = None) -> int:
    """Phase 1 deliverable gate: end-to-end pipeline + 5% decomposition gate.

    Returns 0 on success, 1 on gate failure.
    """
    if client is None:
        client = anthropic.Anthropic()

    record = smoke_agent(client, _SMOKE_TASK)

    input_sum = record["decomposition_input_sum"]
    api_input = record["api_input_tokens"]
    ratio = abs(input_sum - api_input) / api_input

    print(f"Task:     {_SMOKE_TASK['task_id']}")
    print(f"Question: {_SMOKE_TASK['user_message']!r}")
    print(f"Response: {record['response_text'][:120]!r}")
    print()
    print("Token decomposition:")
    for cat, n in record["decomposition"].items():
        print(f"  {cat:25s} {n:>5}")
    print()
    print(f"  API input_tokens          {api_input:>5}")
    print(f"  Decomposition input sum   {input_sum:>5}")
    print(f"  Ratio                     {ratio:.1%}  (METHODOLOGY gate: 5%)")
    print()

    if ratio >= 0.05:
        print(f"FAIL: methodology gate exceeded ({ratio:.1%} > 5%)")
        return 1
    print("PASS: methodology gate held — Phase 1 deliverable verified")
    return 0


# ---------------------------------------------------------------------------
# Full measurement run (Phase 2 — --architectures dispatch)
# ---------------------------------------------------------------------------


# METHODOLOGY §"What gets counted": the decomposition of categories ①–⑤
# (audit-inclusive at the gate level — METHODOLOGY §"Audit log specification")
# must sum to API-reported `input_tokens` within 5%. Breaches are flagged
# in the per-run record, not silenced — see CLAUDE.md invariant.
_GATE_TOLERANCE = 0.05

# METHODOLOGY §"Run protocol": "If any run produces an API error, that
# run is retried up to twice." So initial attempt + 2 retries = 3 tries max.
_MAX_RETRIES = 2


def _load_tasks(path: Path) -> list[dict[str, Any]]:
    """Read tasks.jsonl, skipping comment lines (`# …`) and blank lines.

    The first line of `measurement/tasks.jsonl` is a freeze marker; the
    schema is otherwise one JSON object per line.
    """
    tasks: list[dict[str, Any]] = []
    for line in path.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        tasks.append(json.loads(s))
    return tasks


def _load_architectures(names: list[str]) -> dict[str, Callable]:
    """Resolve architecture names to their `run_task` callables.

    Imports `architectures.<name>.agent` for any name not already in
    ARCHITECTURE_REGISTRY; the agent module's `_register()` side-effect
    populates the registry. Names already present (e.g., test fakes
    inserted via `register_architecture`) are used as-is, so tests can
    inject mocks without touching the filesystem.
    """
    resolved: dict[str, Callable] = {}
    for name in names:
        if name not in ARCHITECTURE_REGISTRY:
            try:
                importlib.import_module(f"architectures.{name}.agent")
            except ModuleNotFoundError as e:
                raise RuntimeError(
                    f"Architecture '{name}' not found "
                    f"(architectures/{name}/agent.py): {e}"
                ) from e
        if name not in ARCHITECTURE_REGISTRY:
            raise RuntimeError(
                f"Architecture '{name}' imported but did not self-register. "
                f"Check architectures/{name}/agent.py::_register() and that "
                f"measurement.runner.register_architecture is importable."
            )
        resolved[name] = ARCHITECTURE_REGISTRY[name]
    return resolved


def _gate_ratio(record: dict[str, Any]) -> float:
    """5% decomposition gate ratio for one run record.

    Uses `decomposition_input_sum_with_audit` when present (multi-turn
    architectures via _shared/agent_loop emit it; audit_log tokens are
    real API input and must be in the gate-side sum, even though they're
    excluded from the *reported* decomposition). Falls back to
    `decomposition_input_sum` for single-turn callers (the smoke path).

    Caching-aware: `api_input_tokens` reports ONLY the standard-priced
    input subset (Anthropic bills cache_creation and cache_read input
    tokens on separate counters). The count_tokens-derived decomposition
    sees the FULL prompt regardless of caching. So for an apples-to-apples
    comparison the denominator must be (api_input + cache_create +
    cache_read) — the total tokens actually processed by the model. The
    fields default to 0 for non-caching architectures, so this is a no-op
    for Naive RAG, Grep search, Hybrid RAG.
    """
    api_input = record["api_input_tokens"]
    cache_create = record.get("cache_creation_input_tokens", 0) or 0
    cache_read = record.get("cache_read_input_tokens", 0) or 0
    total_processed = api_input + cache_create + cache_read
    if total_processed == 0:
        return 0.0
    inclusive = record.get(
        "decomposition_input_sum_with_audit", record["decomposition_input_sum"]
    )
    return abs(inclusive - total_processed) / total_processed


def _dispatch_one(
    *,
    arch_fn: Callable,
    task: dict[str, Any],
    client: anthropic.Anthropic,
    arch_name: str,
    run_index: int,
    runs_total: int,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Run a single (arch, task) pair with retry per METHODOLOGY.

    Returns `(record, None)` on success or `(None, error)` after exhausted
    retries. The error dict preserves the exception's class name and
    message so the per-architecture JSON keeps enough forensic detail to
    distinguish (e.g.) a rate-limit transient from a deterministic bug
    without having to dig through stderr capture — see PR #41 review.
    """
    last_exc: Exception | None = None
    attempts = 0
    while attempts <= _MAX_RETRIES:
        attempts += 1
        try:
            record = arch_fn(task, client=client)
        except Exception as e:
            last_exc = e
            print(
                f"[retry] arch={arch_name} task={task['task_id']} "
                f"run={run_index + 1}/{runs_total} attempt={attempts} "
                f"failed: {type(e).__name__}: {e}",
                file=sys.stderr,
            )
            continue
        record["run_index"] = run_index
        record["attempts"] = attempts
        ratio = _gate_ratio(record)
        record["gate_ratio"] = ratio
        record["gate_breach"] = ratio >= _GATE_TOLERANCE
        if record["gate_breach"]:
            print(
                f"[gate-breach] arch={arch_name} task={task['task_id']} "
                f"run={run_index + 1}/{runs_total} ratio={ratio:.1%} "
                f"(API={record['api_input_tokens']}, "
                f"inclusive_sum={record.get('decomposition_input_sum_with_audit', record['decomposition_input_sum'])}) "
                f"— flagged, not silenced per METHODOLOGY",
                file=sys.stderr,
            )
        print(
            f"[ok] arch={arch_name} task={task['task_id']} "
            f"run={run_index + 1}/{runs_total} "
            f"turns={record.get('turns', 1)} "
            f"input={record['api_input_tokens']} "
            f"output={record['api_output_tokens']} "
            f"gate={ratio:.1%}"
        )
        return record, None
    # Exhausted retries.
    print(
        f"[fail] arch={arch_name} task={task['task_id']} "
        f"run={run_index + 1}/{runs_total} gave up after {attempts} attempts: "
        f"{type(last_exc).__name__}: {last_exc}",
        file=sys.stderr,
    )
    return None, {
        "task_id": task["task_id"],
        "run_index": run_index,
        "attempts": attempts,
        "error_type": type(last_exc).__name__ if last_exc else "Unknown",
        "error_message": str(last_exc) if last_exc else "",
    }


def _write_arch_json(
    *,
    path: Path,
    architecture: str,
    config: dict[str, Any],
    runs: list[dict[str, Any]],
    errors: list[dict[str, Any]],
) -> None:
    """Write `architecture_<name>.json` to a sibling .tmp then rename.

    Called after every dispatch (not just at end-of-run) so an
    interruption mid-paid-run keeps the records produced so far. The
    tmp+rename gives atomic-enough writes on POSIX — a reader either
    sees the previous full file or the new full file, not a torn one.
    """
    payload = {
        "architecture": architecture,
        "config": config,
        "runs": runs,
        "errors": errors,
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n")
    tmp.replace(path)


def run_measurement(
    *,
    architectures: list[str],
    tasks_path: Path,
    runs: int,
    results_dir: Path,
    limit: int | None = None,
    client: anthropic.Anthropic | None = None,
) -> int:
    """Drive every (architecture, task, run_index) triple and persist results.

    Order (METHODOLOGY §"Run protocol" — control for time-of-day API
    variance): outer loop = run_index, then for each task, dispatch every
    architecture back-to-back before moving to the next task.

    Output: one `architecture_<name>.json` per architecture in
    `results_dir`, rewritten after every successful dispatch (atomic via
    tmp+rename) so an interruption mid-run keeps the records produced so
    far. Shape compatible with `--report` aggregation:
        {
          "architecture": <name>,
          "config": {..., "completed_at": null until end-of-run},
          "runs": [<record_run dict with run_index/gate_ratio/etc>, ...],
          "errors": [
              {"task_id", "run_index", "attempts",
               "error_type", "error_message"},
              ...
          ]
        }

    Returns 0 on completion (even if some runs hit the gate or errored —
    those are flagged in the records and errors list). Returns 1 only on
    no-tasks. An unresolvable architecture is a misconfigured CLI
    invocation; `_load_architectures` raises `RuntimeError` so the
    operator sees the failure immediately rather than after a normal-
    looking exit.
    """
    if client is None:
        client = anthropic.Anthropic()

    arch_fns = _load_architectures(architectures)
    tasks = _load_tasks(tasks_path)
    if limit is not None:
        tasks = tasks[:limit]
    if not tasks:
        print(f"No tasks loaded from {tasks_path}", file=sys.stderr)
        return 1

    per_arch_runs: dict[str, list[dict[str, Any]]] = {n: [] for n in architectures}
    per_arch_errors: dict[str, list[dict[str, Any]]] = {n: [] for n in architectures}
    breach_count = 0
    started_at = datetime.now(timezone.utc).isoformat()
    results_dir.mkdir(parents=True, exist_ok=True)

    def _config(completed_at: str | None) -> dict[str, Any]:
        return {
            "tasks_path": str(tasks_path),
            "tasks_count": len(tasks),
            "runs_per_task": runs,
            "limit": limit,
            "started_at": started_at,
            "completed_at": completed_at,
        }

    total_calls = runs * len(tasks) * len(architectures)
    print(
        f"Starting measurement: {len(architectures)} arch × {len(tasks)} task × "
        f"{runs} run = {total_calls} (architecture, task, run) triples.",
        file=sys.stderr,
    )

    arch_paths = {
        arch: results_dir / f"architecture_{arch}.json"
        for arch in architectures
    }

    for run_index in range(runs):
        for task in tasks:
            for arch in architectures:
                record, error = _dispatch_one(
                    arch_fn=arch_fns[arch],
                    task=task,
                    client=client,
                    arch_name=arch,
                    run_index=run_index,
                    runs_total=runs,
                )
                if error is not None:
                    per_arch_errors[arch].append(error)
                else:
                    if record["gate_breach"]:
                        breach_count += 1
                    per_arch_runs[arch].append(record)
                # Checkpoint after every dispatch: an interrupted paid run
                # (e.g., SIGINT at call ~150 of ~150) keeps the records
                # produced so far instead of losing the entire sweep.
                _write_arch_json(
                    path=arch_paths[arch],
                    architecture=arch,
                    config=_config(completed_at=None),
                    runs=per_arch_runs[arch],
                    errors=per_arch_errors[arch],
                )

    completed_at = datetime.now(timezone.utc).isoformat()
    for arch in architectures:
        _write_arch_json(
            path=arch_paths[arch],
            architecture=arch,
            config=_config(completed_at=completed_at),
            runs=per_arch_runs[arch],
            errors=per_arch_errors[arch],
        )
        print(
            f"Wrote {arch_paths[arch]}: "
            f"{len(per_arch_runs[arch])} runs, "
            f"{len(per_arch_errors[arch])} errors."
        )

    if breach_count:
        print(
            f"\nNOTE: {breach_count} run(s) exceeded the 5% decomposition "
            f"gate. See gate_breach=true entries in the result JSONs. "
            f"Per CLAUDE.md these are flagged, not silenced.",
            file=sys.stderr,
        )
    return 0


# ---------------------------------------------------------------------------
# Report aggregation
# ---------------------------------------------------------------------------


def generate_report(
    *, results_dir: Path, output_path: Path
) -> int:
    """Aggregate per-architecture JSON results into a comparison.md.

    Phase 1 implementation: discover architecture_*.json files in
    results_dir, compute mean/median tokens per architecture, write a
    minimal comparison markdown that overwrites output_path.

    Phase 2 / Step 11 TODO: replace this stub with a template-driven
    renderer that populates `measurement/results/comparison.md` in place,
    preserving the hand-written sections (intro, Mermaid diagram,
    adversarial review, etc.) instead of overwriting them. Until then,
    the stub mirrors the diagram and section structure of the template
    so an accidental --report run doesn't silently lose the diagram.
    """
    result_files = sorted(results_dir.glob("architecture_*.json"))

    if not result_files:
        print(
            f"No architecture result files in {results_dir}/. "
            f"Run measurements first.",
            file=sys.stderr,
        )
        return 1

    rows: list[dict] = []
    for path in result_files:
        data = json.loads(path.read_text())
        arch = data.get("architecture", path.stem.replace("architecture_", ""))
        runs = data.get("runs", [])
        if not runs:
            continue
        input_tokens = [r["api_input_tokens"] for r in runs]
        output_tokens = [r["api_output_tokens"] for r in runs]
        rows.append(
            {
                "architecture": arch,
                "n_runs": len(runs),
                "mean_input": mean(input_tokens) if input_tokens else 0,
                "median_input": median(input_tokens) if input_tokens else 0,
                "mean_output": mean(output_tokens) if output_tokens else 0,
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Comparison Report (Phase 1 stub)",
        "",
        "Auto-generated by `measurement/runner.py --report`. Phase 2 / Step 11",
        "will replace this stub with a template-driven renderer that populates",
        "the hand-written `comparison.md` template in place. Until then, this",
        "stub mirrors the template's diagram and section structure so an",
        "accidental --report run doesn't silently drop the Mermaid diagram or",
        "Silicon Data decomposition framing.",
        "",
        "| Architecture | n_runs | mean input | median input | mean output |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['architecture']} | {r['n_runs']} | "
            f"{r['mean_input']:.0f} | {r['median_input']:.0f} | "
            f"{r['mean_output']:.0f} |"
        )
    lines.extend(
        [
            "",
            "## Token decomposition (Silicon Data methodology)",
            "",
            "Per the [Silicon Data model](https://www.silicondata.com/blog/llm-cost-per-token), "
            "extended with a sixth category (`agent_intermediate`) for multi-turn tool loops, "
            "every model call's token cost is the sum of five input categories and one output category. "
            "The runner asserts that categories ①–⑤ sum to API-reported `input_tokens` "
            "within 5%; discrepancies are flagged, not silenced "
            "(see `METHODOLOGY.md` §\"What gets counted\" and §\"Multi-turn extension\").",
            "",
            "```mermaid",
            "flowchart LR",
            "    Q[User query] -->|\"③ User message<br/>identical across architectures\"| API[Model call]",
            "    SP[\"① System prompt<br/>~300–500 tokens<br/>architecture-set, ~constant per arch\"] -->|added per call| API",
            "    TS[\"④ Tool call overhead<br/>tool schema JSON<br/>architecture-set, ~constant per arch\"] -->|added per call| API",
            "    CTX[\"② Retrieved/injected context<br/>retrieval architecture sets the size<br/>where the comparison lives\"] -->|added per call| API",
            "    AI[\"⑤ Agent intermediate<br/>prior-turn assistant content (text + tool_use)<br/>re-sent every turn\"] -->|added per call| API",
            "    API -->|\"⑥ Response<br/>agent-set, varies per task\"| Out[Agent response]",
            "",
            "    API ==> Assert{{\"input_tokens ≈ ① + ② + ③ + ④ + ⑤<br/>within 5% tolerance\"}}",
            "```",
            "",
            "The architecture comparison lives in category ②. Categories ①, ③, ④ are "
            "approximately constant within an architecture; category ⑤ scales with loop length "
            "and tool_use verbosity; category ⑥ is bounded by the agent's `max_tokens` and varies "
            "with task. Architecture differences in mean tokens per task are driven primarily by "
            "② (retrieved/injected context), with ⑤ as a secondary driver for chatty multi-turn agents.",
        ]
    )
    output_path.write_text("\n".join(lines) + "\n")
    print(f"Wrote {output_path} ({len(rows)} architecture(s) summarized).")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="runner.py",
        description="Run the support-agent-token-benchmark measurement.",
    )
    parser.add_argument(
        "--architectures",
        type=str,
        default=None,
        help="Comma-separated architecture names (e.g., naive_rag,grep_search,hybrid_rag).",
    )
    parser.add_argument(
        "--tasks",
        type=Path,
        default=None,
        help="Path to tasks.jsonl (Phase 2 only).",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=3,
        help="Number of runs per task per architecture (default: 3).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help=(
            "Truncate task set to the first N tasks. Use for a cheap "
            "end-to-end smoke (--limit 1 --runs 1 across all archs is "
            "~one paid API call per architecture) before kicking off "
            "the full run."
        ),
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Aggregate result JSONs into measurement/results/comparison.md.",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Run a single trivial task end-to-end (Phase 1 verification).",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=Path("measurement/results"),
        help="Directory for per-architecture JSON output (default: measurement/results).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.smoke:
        return run_smoke()

    if args.report:
        return generate_report(
            results_dir=args.results_dir,
            output_path=args.results_dir / "comparison.md",
        )

    if args.architectures:
        archs = [a.strip() for a in args.architectures.split(",") if a.strip()]
        if not archs:
            print("--architectures was empty after parsing.", file=sys.stderr)
            return 2
        tasks_path = args.tasks or Path("measurement/tasks.jsonl")
        return run_measurement(
            architectures=archs,
            tasks_path=tasks_path,
            runs=args.runs,
            results_dir=args.results_dir,
            limit=args.limit,
        )

    print(
        "Usage: runner.py --smoke | --report | "
        "--architectures naive_rag,grep_search,hybrid_rag "
        "[--tasks measurement/tasks.jsonl] [--runs 3] [--limit N]",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
