"""LLM-as-judge scoring for BUILD_PLAN §9.

Reads per-architecture run JSONs produced by `measurement.runner`, scores
each `response_text` against the task's frozen three-dimension rubric
using `claude-opus-4-7`, and writes side-car `judgments_<arch>.json`
files alongside the input run JSONs.

Three modes (mirrors runner.py shape):

  --runs-dir <path>         Directory containing `architecture_*.json`
                            run records (e.g. the dated 8B dir). Reads
                            every architecture present unless filtered.
  --architectures <list>    Restrict to a comma-separated subset.
  --task-ids <list>         Restrict to a comma-separated subset of
                            task IDs (used by the dry-run gate).
  --output-dir <path>       Where to write `judgments_<arch>.json`.
                            Defaults to --runs-dir (side-car layout).

METHODOLOGY §"LLM-as-judge scoring" (rubric definitions, 0/0.5/1
scoring, 1.0-on-all-three = pass) is the authority. The per-task rubric
strings are pulled verbatim from `tasks.jsonl` so judge calibration
tracks the frozen task set, not a copy that could drift.

Cost discipline: per-architecture JSONs are rewritten atomically after
every judgment so an interrupted sweep keeps work-in-progress. The
caller (the dated 8B dir) is the canonical location; the latest-run
dir at `measurement/results/` is not touched.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import anthropic

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


# METHODOLOGY §"Model and configuration": judge is opus 4.7 dateless ID.
JUDGE_MODEL = "claude-opus-4-7"

# Judge call is deterministic — same rubric + same response should yield
# the same score. temperature=0.0 keeps repeated runs reproducible.
JUDGE_TEMPERATURE = 0.0

# Output cap. Judge returns a small JSON object + 1-3 sentence rationale;
# 1024 is comfortably above what any score block needs but small enough
# that runaway generations don't burn budget.
JUDGE_MAX_TOKENS = 1024


_JUDGE_SYSTEM_PROMPT = """\
You are an evaluation judge for a customer-support-agent benchmark. You score one agent response against one task's frozen rubric across three dimensions.

Scoring rule per dimension (METHODOLOGY §"LLM-as-judge scoring"):
- 1.0 — Response fully satisfies the dimension's rubric statement.
- 0.5 — Response partially satisfies it (e.g., gets the main fact right but omits a required caveat; cites the right section but mis-attributes a detail).
- 0.0 — Response fails the dimension (wrong fact, wrong/missing citation, or fabricates content not in the source).

The three dimensions are:
1. factual_correctness — does the response state the right policy / transactional fact, per the task's `factual_correctness` rubric?
2. citation_accuracy — when policy is invoked, is the cited source correct, per the task's `citation_accuracy` rubric? For pure-transactional tasks where the rubric explicitly says no corpus citation is needed, score 1.0 if the response correctly does not fabricate a corpus citation.
3. no_fabrication — does the response avoid stating content not supported by the source corpus or available tools, per the task's `no_fabrication` rubric? Some tasks flag specific HARD FAILURE patterns (e.g., surfacing the unverified `877-5O7-7341` phone number, fabricating Comfort-fare entitlements); those patterns force 0.0 on this dimension when present.

A task is considered "passed" only when all three dimensions score 1.0. Half-credit on any dimension means the task is not passed.

Output ONLY a JSON object with this exact shape (no markdown fence, no commentary):
{
  "factual_correctness": <0.0 | 0.5 | 1.0>,
  "citation_accuracy":   <0.0 | 0.5 | 1.0>,
  "no_fabrication":      <0.0 | 0.5 | 1.0>,
  "task_passed":         <true | false>,
  "rationale":           "<one to three sentences quoting the response or rubric to justify the score>"
}

Be strict but fair. Quote the response text when penalising. If the rubric specifies a HARD FAILURE pattern and the response triggers it, score 0.0 on `no_fabrication` and say so in the rationale.
"""


def _format_tools_called(tools_called: Any) -> str:
    """Render tools_called as a short bulleted list for the judge prompt.

    The judge mostly needs the response text, but tools_called helps
    distinguish (e.g.) "agent didn't call get_booking_status and fabricated
    the answer" from "agent called the tool but mis-stated the result".
    """
    if not tools_called:
        return "(none — agent answered without tool calls)"
    lines = []
    for entry in tools_called:
        if isinstance(entry, dict):
            name = entry.get("name") or entry.get("tool") or "?"
            args = entry.get("input") or entry.get("arguments") or {}
            try:
                args_s = json.dumps(args, separators=(",", ":"))
            except (TypeError, ValueError):
                args_s = str(args)
            if len(args_s) > 200:
                args_s = args_s[:200] + "…"
            lines.append(f"- {name}({args_s})")
        else:
            lines.append(f"- {entry}")
    return "\n".join(lines)


def _build_user_message(task: dict[str, Any], record: dict[str, Any]) -> str:
    """Render the per-record judge prompt body.

    Includes everything the judge needs to score one record without
    needing to read external files: task metadata, the frozen rubric
    strings, the customer-facing question, and the agent's response +
    tool trace.
    """
    rubric = task["rubric"]
    expected_citations = task.get("expected_citations") or []
    cites_str = (
        ", ".join(f"`{c}`" for c in expected_citations)
        if expected_citations
        else "(none — pure-transactional task; rubric forbids fabricating a corpus citation)"
    )
    return f"""\
# Task

- task_id: {task['task_id']}
- class: {task['class']}
- booking_data_required: {task.get('booking_data_required', False)}

## Customer message

{task['user_message']}

## Expected answer (summary)

{task['expected_answer_summary']}

## Expected citations

{cites_str}

## Rubric (frozen — score against these statements verbatim)

- factual_correctness: {rubric['factual_correctness']}
- citation_accuracy: {rubric['citation_accuracy']}
- no_fabrication: {rubric['no_fabrication']}

# Agent under evaluation

- architecture: {record['architecture']}
- run_index: {record['run_index']}
- turns: {record.get('turns', 1)}

## Tools called by the agent

{_format_tools_called(record.get('tools_called'))}

## Agent response

{record['response_text']}

# Your task

Score this response against the three rubric dimensions above. Output ONLY the JSON object.
"""


def _parse_judge_output(raw: str) -> dict[str, Any]:
    """Extract the judgment JSON object from the judge's response text.

    The system prompt asks for raw JSON (no markdown fence), but
    defensively strip a leading/trailing code-fence if the model
    decides to add one anyway. Raises ValueError on malformed JSON so
    the caller can record the failure rather than silently coercing.
    """
    s = raw.strip()
    if s.startswith("```"):
        # Trim ```json … ``` fence
        lines = s.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        s = "\n".join(lines).strip()
    # Some models emit a leading "Here is the JSON:" preamble despite
    # being told not to. Locate the first '{' and parse from there.
    start = s.find("{")
    if start == -1:
        raise ValueError(f"No JSON object in judge output: {raw[:200]!r}")
    return json.loads(s[start:])


def _validate_judgment(judgment: dict[str, Any]) -> dict[str, Any]:
    """Coerce the judge's parsed output to the canonical schema.

    Numeric scores are clamped to the allowed {0.0, 0.5, 1.0} set.
    `task_passed` is recomputed from the three dimensions so the judge
    can't disagree with its own scores (METHODOLOGY: pass = 1.0 on all
    three).
    """
    dims = ("factual_correctness", "citation_accuracy", "no_fabrication")
    out: dict[str, Any] = {}
    for d in dims:
        v = float(judgment.get(d, 0.0))
        if v >= 1.0:
            out[d] = 1.0
        elif v >= 0.5:
            out[d] = 0.5
        else:
            out[d] = 0.0
    out["task_passed"] = all(out[d] >= 1.0 for d in dims)
    out["rationale"] = str(judgment.get("rationale", "")).strip()
    return out


def judge_one(
    *,
    client: anthropic.Anthropic,
    task: dict[str, Any],
    record: dict[str, Any],
) -> dict[str, Any]:
    """Score a single run record against its task rubric.

    Returns a judgment dict augmented with provenance fields:
    `task_id`, `architecture`, `run_index`, the four scoring fields,
    and `judge_usage` for cost accounting. Errors (parse failures,
    API errors) bubble up to the caller.
    """
    user_message = _build_user_message(task, record)
    response = client.messages.create(
        model=JUDGE_MODEL,
        max_tokens=JUDGE_MAX_TOKENS,
        temperature=JUDGE_TEMPERATURE,
        system=_JUDGE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    raw_text = ""
    for block in response.content:
        if hasattr(block, "text"):
            raw_text += block.text
    parsed = _parse_judge_output(raw_text)
    judgment = _validate_judgment(parsed)
    judgment.update(
        {
            "task_id": record["task_id"],
            "architecture": record["architecture"],
            "run_index": record["run_index"],
            "judge_usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
        }
    )
    return judgment


def _load_runs(runs_dir: Path, architectures: list[str] | None) -> dict[str, dict[str, Any]]:
    """Load the architecture_*.json files from runs_dir.

    Returns {arch_name: payload_dict}. If `architectures` is None, every
    `architecture_*.json` in the directory is loaded; otherwise the
    listed names are required to be present (missing arch → RuntimeError).
    """
    if not runs_dir.is_dir():
        raise RuntimeError(f"--runs-dir does not exist: {runs_dir}")
    if architectures:
        paths = [runs_dir / f"architecture_{a}.json" for a in architectures]
        missing = [p for p in paths if not p.is_file()]
        if missing:
            raise RuntimeError(f"Missing run JSONs: {missing}")
    else:
        paths = sorted(runs_dir.glob("architecture_*.json"))
        if not paths:
            raise RuntimeError(f"No architecture_*.json files in {runs_dir}")
    out: dict[str, dict[str, Any]] = {}
    for p in paths:
        data = json.loads(p.read_text())
        out[data["architecture"]] = data
    return out


def _load_tasks(tasks_path: Path) -> dict[str, dict[str, Any]]:
    """Read tasks.jsonl (skipping `# …` comment lines) keyed by task_id."""
    tasks: dict[str, dict[str, Any]] = {}
    for line in tasks_path.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        t = json.loads(s)
        tasks[t["task_id"]] = t
    return tasks


def _write_judgments(
    *,
    path: Path,
    architecture: str,
    config: dict[str, Any],
    judgments: list[dict[str, Any]],
    errors: list[dict[str, Any]],
) -> None:
    """Atomic write of judgments_<arch>.json (tmp + rename)."""
    payload = {
        "architecture": architecture,
        "config": config,
        "judgments": judgments,
        "errors": errors,
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n")
    tmp.replace(path)


def run_judge(
    *,
    runs_dir: Path,
    tasks_path: Path,
    output_dir: Path,
    architectures: list[str] | None = None,
    task_ids: list[str] | None = None,
    client: anthropic.Anthropic | None = None,
) -> int:
    """Score every record in the loaded runs against its rubric.

    Order: outer loop = run_index (controls for any rate-limit pacing),
    then for each task, judge every architecture back-to-back. Mirrors
    the runner.py per-task interleave so judges sees comparable response
    pairs near each other in the call stream — useful if a future
    investigation wants to inspect the prompt cache behavior.

    Atomic checkpoint after every successful judgment; an interruption
    keeps prior work.

    Returns 0 on completion (even if some records errored), 1 only on
    setup failure (missing runs dir, no tasks).
    """
    if client is None:
        client = anthropic.Anthropic()

    runs = _load_runs(runs_dir, architectures)
    tasks = _load_tasks(tasks_path)

    arch_names = architectures or sorted(runs.keys())
    output_dir.mkdir(parents=True, exist_ok=True)
    out_paths = {arch: output_dir / f"judgments_{arch}.json" for arch in arch_names}

    # Index runs by (task_id, run_index) per architecture for the
    # per-task interleave loop below.
    indexed: dict[str, dict[tuple[str, int], dict[str, Any]]] = {}
    for arch, payload in runs.items():
        indexed[arch] = {(r["task_id"], r["run_index"]): r for r in payload["runs"]}

    # Build the (task_id, run_index) sweep order. The runner produced
    # runs_per_task copies of each task; pull max(run_index)+1 from the
    # first architecture's records as the truth.
    first_arch = arch_names[0]
    first_runs = runs[first_arch]["runs"]
    runs_per_task = (
        max((r["run_index"] for r in first_runs), default=-1) + 1 if first_runs else 0
    )

    # Honor the frozen tasks.jsonl ordering, optionally filtered.
    if task_ids:
        sweep_task_ids = [tid for tid in tasks if tid in set(task_ids)]
        missing = set(task_ids) - set(sweep_task_ids)
        if missing:
            raise RuntimeError(f"Unknown task IDs in --task-ids: {sorted(missing)}")
    else:
        sweep_task_ids = list(tasks.keys())

    started_at = datetime.now(timezone.utc).isoformat()

    def _config(completed_at: str | None) -> dict[str, Any]:
        return {
            "runs_dir": str(runs_dir),
            "tasks_path": str(tasks_path),
            "judge_model": JUDGE_MODEL,
            "judge_temperature": JUDGE_TEMPERATURE,
            "judge_max_tokens": JUDGE_MAX_TOKENS,
            "filtered_task_ids": task_ids,
            "started_at": started_at,
            "completed_at": completed_at,
        }

    per_arch_judgments: dict[str, list[dict[str, Any]]] = {a: [] for a in arch_names}
    per_arch_errors: dict[str, list[dict[str, Any]]] = {a: [] for a in arch_names}
    total_input = 0
    total_output = 0
    n_done = 0
    n_total = runs_per_task * len(sweep_task_ids) * len(arch_names)

    print(
        f"Judge sweep: {len(arch_names)} arch × {len(sweep_task_ids)} task × "
        f"{runs_per_task} run = {n_total} judgments.",
        file=sys.stderr,
    )

    for run_index in range(runs_per_task):
        for tid in sweep_task_ids:
            task = tasks[tid]
            for arch in arch_names:
                key = (tid, run_index)
                record = indexed.get(arch, {}).get(key)
                if record is None:
                    err = {
                        "task_id": tid,
                        "architecture": arch,
                        "run_index": run_index,
                        "error_type": "MissingRunRecord",
                        "error_message": "No record in architecture_*.json for this (task_id, run_index).",
                    }
                    per_arch_errors[arch].append(err)
                    print(f"[miss] arch={arch} task={tid} run={run_index + 1}/{runs_per_task} — no record", file=sys.stderr)
                    continue
                try:
                    judgment = judge_one(client=client, task=task, record=record)
                except Exception as e:
                    err = {
                        "task_id": tid,
                        "architecture": arch,
                        "run_index": run_index,
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                    }
                    per_arch_errors[arch].append(err)
                    print(
                        f"[fail] arch={arch} task={tid} run={run_index + 1}/{runs_per_task} "
                        f"{type(e).__name__}: {e}",
                        file=sys.stderr,
                    )
                else:
                    per_arch_judgments[arch].append(judgment)
                    total_input += judgment["judge_usage"]["input_tokens"]
                    total_output += judgment["judge_usage"]["output_tokens"]
                    n_done += 1
                    pass_str = "PASS" if judgment["task_passed"] else "FAIL"
                    print(
                        f"[{pass_str}] {n_done}/{n_total} arch={arch} task={tid} "
                        f"run={run_index + 1}/{runs_per_task} "
                        f"fc={judgment['factual_correctness']} "
                        f"cite={judgment['citation_accuracy']} "
                        f"nofab={judgment['no_fabrication']} "
                        f"(input={judgment['judge_usage']['input_tokens']}, "
                        f"output={judgment['judge_usage']['output_tokens']})"
                    )
                # Atomic checkpoint after every dispatch.
                _write_judgments(
                    path=out_paths[arch],
                    architecture=arch,
                    config=_config(completed_at=None),
                    judgments=per_arch_judgments[arch],
                    errors=per_arch_errors[arch],
                )

    completed_at = datetime.now(timezone.utc).isoformat()
    for arch in arch_names:
        _write_judgments(
            path=out_paths[arch],
            architecture=arch,
            config=_config(completed_at=completed_at),
            judgments=per_arch_judgments[arch],
            errors=per_arch_errors[arch],
        )

    print(
        f"\nDone. Judgments written under {output_dir}/.",
        file=sys.stderr,
    )
    print(
        f"Cost: input={total_input} tokens, output={total_output} tokens "
        f"across {n_done} successful judgments.",
        file=sys.stderr,
    )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="judge.py",
        description="LLM-as-judge scoring for the support-agent-token-benchmark.",
    )
    parser.add_argument(
        "--runs-dir",
        type=Path,
        required=True,
        help="Directory containing architecture_*.json run records.",
    )
    parser.add_argument(
        "--tasks",
        type=Path,
        default=Path("measurement/tasks.jsonl"),
        help="Path to tasks.jsonl (provides the frozen rubric strings).",
    )
    parser.add_argument(
        "--architectures",
        type=str,
        default=None,
        help="Comma-separated arch names to score (default: all in --runs-dir).",
    )
    parser.add_argument(
        "--task-ids",
        type=str,
        default=None,
        help="Comma-separated task IDs to score (default: all in tasks.jsonl).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Where to write judgments_<arch>.json (default: --runs-dir).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    archs = (
        [a.strip() for a in args.architectures.split(",") if a.strip()]
        if args.architectures
        else None
    )
    task_ids = (
        [t.strip() for t in args.task_ids.split(",") if t.strip()]
        if args.task_ids
        else None
    )
    output_dir = args.output_dir or args.runs_dir
    return run_judge(
        runs_dir=args.runs_dir,
        tasks_path=args.tasks,
        output_dir=output_dir,
        architectures=archs,
        task_ids=task_ids,
    )


if __name__ == "__main__":
    sys.exit(main())
