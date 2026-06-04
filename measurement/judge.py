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
import time
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

# `claude-opus-4-7` does not accept the `temperature` parameter (400
# BadRequestError: "`temperature` is deprecated for this model"),
# discovered on the first paid dry-run. Per METHODOLOGY §"Model and
# configuration" only the agent run is pinned to temperature=0; the
# judge has no methodology-required temperature, so we let the model
# default (sampling enabled). Judge calibration relies on the 10%
# manual review per METHODOLOGY §"LLM-as-judge scoring" rather than
# strict per-call reproducibility. Constant retained for the
# `judge_temperature` config field (records "default" so the cause of
# any cross-run variance is explicit in the side-car).
JUDGE_TEMPERATURE: float | None = None

# Output cap. Judge returns a small JSON object + 1-3 sentence rationale;
# 1024 is comfortably above what any score block needs but small enough
# that runaway generations don't burn budget.
JUDGE_MAX_TOKENS = 1024

# METHODOLOGY §"Run protocol": "If any run produces an API error, that
# run is retried up to twice." Applies to all API calls in the framework,
# including the judge — the PR #43 review (issue surfaced by the
# code-review skill) flagged that scoping this to agent runs alone risks
# architecture-asymmetric data loss when a transient 5xx hits one cell
# of the (arch, task, run_index) grid.
_MAX_RETRIES = 2
_RETRY_BACKOFF_BASE_SECONDS = 1.0

# Prompt caching breakpoint. The judge system prompt + per-task prefix
# are identical across the 3 architectures judged back-to-back for a
# given (task, run_index), so caching the system block and the task
# prefix saves the input-token cost on the 2nd and 3rd arch's call.
# Whether caching actually triggers depends on Opus's minimum cacheable
# prefix length; a sub-threshold marker is silently a no-op (no error),
# so this is risk-free. The judge_usage captures
# cache_creation_input_tokens / cache_read_input_tokens so the cost
# accounting stays accurate regardless of whether caching kicks in.
_CACHE_CONTROL: dict[str, str] = {"type": "ephemeral"}

# Pre-sweep schema validation. A task missing any of these fields would
# raise KeyError partway into a paid sweep; surfacing the gap up front
# avoids burning budget before the operator sees an actionable error.
_REQUIRED_TASK_FIELDS = (
    "task_id",
    "class",
    "user_message",
    "expected_answer_summary",
    "rubric",
)
_REQUIRED_RUBRIC_FIELDS = (
    "factual_correctness",
    "citation_accuracy",
    "no_fabrication",
)

# Discrete score set per METHODOLOGY §"LLM-as-judge scoring":
# "Each dimension is scored 0 (fail), 0.5 (partial), or 1 (pass)."
_VALID_SCORES = (0.0, 0.5, 1.0)


class JudgeParseError(ValueError):
    """Judge produced output that could not be coerced to the JSON schema.

    Distinct from API errors so the per-arch errors[] forensics can tell
    a prompt-design problem (parse failures cluster on specific tasks)
    from a transient API problem (errors cluster on time).
    """


def _is_retriable(exc: BaseException) -> bool:
    """True for Anthropic transient errors worth retrying.

    Covers rate-limit (429), connection errors (network), and any 5xx
    status. Other errors (400 bad request, 401 auth, 403 perm, 404 model)
    are deterministic — retrying just wastes budget.
    """
    if isinstance(exc, (anthropic.RateLimitError, anthropic.APIConnectionError)):
        return True
    if isinstance(exc, anthropic.APIStatusError):
        status = getattr(exc, "status_code", None)
        if status is not None and 500 <= status < 600:
            return True
    return False


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


def _build_task_prefix(task: dict[str, Any]) -> str:
    """Render the task-level prompt block (identical across architectures).

    Split out so judge_one can mark this block with cache_control —
    within a given (task, run_index) sweep slot the same prefix is sent
    for all 3 architectures back-to-back, so caching saves the input
    cost on the 2nd and 3rd call. The trailing newline matters: it
    guarantees the agent suffix starts cleanly when the two blocks
    concatenate at the model's view.
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
"""


def _build_agent_suffix(record: dict[str, Any]) -> str:
    """Render the architecture-specific block (varies per call)."""
    return f"""\
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

    The system prompt asks for raw JSON (no markdown fence), but Opus
    sometimes adds a ```json fence, a leading "Here is the JSON:"
    preamble, a trailing commentary line, or wraps the object in a
    single-element list. This parser tolerates each via
    `json.JSONDecoder.raw_decode`, which consumes one valid JSON value
    starting from a given index and ignores anything that follows —
    so a trailing ``` or "Note: ..." after the object no longer breaks
    parsing.

    Raises `JudgeParseError` on un-recoverable output. The distinct
    exception type lets the per-arch errors[] forensics tell prompt-
    design failures (parse errors cluster on tasks) from transient
    API failures (cluster on time).
    """
    s = raw.strip()
    if not s:
        raise JudgeParseError("Empty judge output (no content blocks).")

    # Probe both '{' (object) and '[' (Opus occasionally wraps in a
    # single-element list). Whichever appears first is the value.
    obj_start = s.find("{")
    arr_start = s.find("[")
    candidates = [i for i in (obj_start, arr_start) if i != -1]
    if not candidates:
        raise JudgeParseError(f"No JSON value in judge output: {raw[:200]!r}")
    start = min(candidates)

    decoder = json.JSONDecoder()
    try:
        parsed, _end = decoder.raw_decode(s, start)
    except json.JSONDecodeError as e:
        raise JudgeParseError(
            f"Malformed JSON in judge output: {e.msg} at pos {e.pos}; "
            f"raw={raw[:200]!r}"
        ) from e

    if isinstance(parsed, list):
        if not parsed:
            raise JudgeParseError(
                f"Judge returned empty list, expected object: {raw[:200]!r}"
            )
        parsed = parsed[0]
    if not isinstance(parsed, dict):
        raise JudgeParseError(
            f"Judge returned {type(parsed).__name__}, expected object: {raw[:200]!r}"
        )
    return parsed


def _coerce_score(raw: Any) -> tuple[float, bool]:
    """Coerce a judge-emitted dim score to a usable float, flagging drift.

    Returns (value_for_arithmetic, was_coerced). The arithmetic value is
    the raw float when valid (including off-grid floats like 0.7 or 2.0
    so the clamping step records them as raw before snapping). Returns
    (0.0, True) when the judge emitted null, a non-numeric string, or a
    non-finite float (NaN/Inf) — the dim is treated as a 0.0 score AND
    flagged so the per-record forensics show the judge malformed it.
    Replaces a previous `float(judgment.get(d, 0.0))` which crashed on
    `null` (per PR #43 review #3).
    """
    if raw is None:
        return 0.0, True
    if isinstance(raw, bool):
        # bool is a subclass of int; treat True/False as 1.0/0.0 but flag
        # because the judge was asked for numeric scores.
        return (1.0 if raw else 0.0), True
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return 0.0, True
    if v != v or v in (float("inf"), float("-inf")):  # NaN/Inf check
        return 0.0, True
    return v, False


def _clamp_to_grid(v: float) -> float:
    """Snap an arbitrary score onto METHODOLOGY's {0.0, 0.5, 1.0} grid.

    Nearest-value snap (rounded to nearest half), then clamped to [0, 1].
    Combined with `_validate_judgment` which records the raw value too,
    a judge that emits 0.7 ends up with raw=0.7 and clamped=0.5 — the
    drift is visible in the per-record JSON for the 10% manual review
    rather than silently masked.
    """
    snapped = round(v * 2.0) / 2.0
    if snapped < 0.0:
        return 0.0
    if snapped > 1.0:
        return 1.0
    return snapped


def _validate_judgment(judgment: dict[str, Any]) -> dict[str, Any]:
    """Coerce the judge's parsed output to the canonical schema.

    For each dimension: tolerate null / non-numeric / off-grid scores
    without losing the record (a single bad dim previously dumped the
    whole judgment to errors[]). Records both the snapped score
    (used for `task_passed`) and the raw value (for calibration).

    Output schema:
    - factual_correctness / citation_accuracy / no_fabrication: float
      in {0.0, 0.5, 1.0} — snapped from raw per METHODOLOGY's discrete grid.
    - raw_scores: dict of the same three keys → the original judge-emitted
      value (post-coercion of null/non-numeric to 0.0). Equal to the
      snapped score when the judge complied; differs when the judge
      emitted off-grid values (a calibration signal for the 10% review).
    - coerced_dims: list of dim names where the judge's value was null,
      non-numeric, or NaN. Empty when the judge complied.
    - off_grid_dims: list of dim names where the raw score was a valid
      number but not in {0, 0.5, 1.0}. Empty when the judge complied.
    - task_passed: bool, recomputed from snapped scores (METHODOLOGY:
      pass = 1.0 on all three). Authoritative.
    - task_passed_raw: bool|None, the judge's own claim — kept for the
      10% manual review so analyst can spot self-inconsistency
      (e.g. judge writes 0.5/1.0/1.0 + task_passed=true).
    - rationale: str, the judge's free-text justification.
    """
    dims = ("factual_correctness", "citation_accuracy", "no_fabrication")
    snapped: dict[str, float] = {}
    raw_scores: dict[str, float] = {}
    coerced_dims: list[str] = []
    off_grid_dims: list[str] = []
    for d in dims:
        value, was_coerced = _coerce_score(judgment.get(d))
        clamped = _clamp_to_grid(value)
        snapped[d] = clamped
        raw_scores[d] = value
        if was_coerced:
            coerced_dims.append(d)
        elif clamped != value:
            off_grid_dims.append(d)

    raw_task_passed = judgment.get("task_passed")
    if not isinstance(raw_task_passed, bool):
        raw_task_passed = None

    out: dict[str, Any] = dict(snapped)
    out["raw_scores"] = raw_scores
    out["coerced_dims"] = coerced_dims
    out["off_grid_dims"] = off_grid_dims
    out["task_passed"] = all(snapped[d] >= 1.0 for d in dims)
    out["task_passed_raw"] = raw_task_passed
    out["rationale"] = str(judgment.get("rationale", "")).strip()
    return out


def judge_one(
    *,
    client: anthropic.Anthropic,
    task: dict[str, Any],
    record: dict[str, Any],
) -> dict[str, Any]:
    """Score a single run record against its task rubric.

    Three changes relative to the v1 implementation, driven by PR #43
    review:

    1. **Prompt caching.** The system prompt and the task-level user
       message prefix are marked with `cache_control: ephemeral`.
       Within a (task, run_index) slot the same prefix goes to all 3
       architectures back-to-back, so the 2nd and 3rd calls read the
       cached prefix instead of re-paying its input cost. Whether
       caching actually fires depends on Opus's minimum prefix length;
       below threshold the markers are silently a no-op (no error).
       `judge_usage` captures both `cache_creation_input_tokens` and
       `cache_read_input_tokens` so cost accounting is accurate
       regardless.

    2. **Retry on transient API errors.** METHODOLOGY §"Run protocol":
       "If any run produces an API error, that run is retried up to
       twice." `_is_retriable` selects 429/connection/5xx; other API
       errors (auth, bad request, model not found) are deterministic
       and bubble immediately.

    3. **Gate-breach propagation + stop_reason capture.** Copies
       `gate_breach` and `gate_ratio` from the source record so the
       judgment side-car is self-contained for downstream join, and
       records `stop_reason` so a `max_tokens` truncation (issue #44)
       is distinguishable from a malformed-output parse error.
    """
    system_blocks = [
        {"type": "text", "text": _JUDGE_SYSTEM_PROMPT, "cache_control": _CACHE_CONTROL}
    ]
    user_content = [
        {"type": "text", "text": _build_task_prefix(task), "cache_control": _CACHE_CONTROL},
        {"type": "text", "text": _build_agent_suffix(record)},
    ]
    messages = [{"role": "user", "content": user_content}]

    create_kwargs: dict[str, Any] = {
        "model": JUDGE_MODEL,
        "max_tokens": JUDGE_MAX_TOKENS,
        "system": system_blocks,
        "messages": messages,
    }
    if JUDGE_TEMPERATURE is not None:
        create_kwargs["temperature"] = JUDGE_TEMPERATURE

    attempts = 0
    while True:
        attempts += 1
        try:
            response = client.messages.create(**create_kwargs)
            break
        except Exception as e:
            if attempts > _MAX_RETRIES or not _is_retriable(e):
                raise
            backoff = _RETRY_BACKOFF_BASE_SECONDS * (2 ** (attempts - 1))
            print(
                f"[judge-retry] task={record['task_id']} "
                f"arch={record['architecture']} run={record['run_index']} "
                f"attempt={attempts} backoff={backoff:.1f}s: "
                f"{type(e).__name__}: {e}",
                file=sys.stderr,
            )
            time.sleep(backoff)

    raw_text = "".join(
        block.text for block in response.content if hasattr(block, "text")
    )
    parsed = _parse_judge_output(raw_text)
    judgment = _validate_judgment(parsed)

    usage = response.usage
    judgment.update(
        {
            "task_id": record["task_id"],
            "architecture": record["architecture"],
            "run_index": record["run_index"],
            "gate_breach": record.get("gate_breach"),
            "gate_ratio": record.get("gate_ratio"),
            "stop_reason": getattr(response, "stop_reason", None),
            "attempts": attempts,
            "judge_usage": {
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cache_creation_input_tokens": getattr(
                    usage, "cache_creation_input_tokens", 0
                )
                or 0,
                "cache_read_input_tokens": getattr(
                    usage, "cache_read_input_tokens", 0
                )
                or 0,
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
        # Explicit utf-8 — tasks.jsonl and corpus content carry em-dashes
        # and other typographic punctuation; locale-default decoding would
        # mojibake on Windows.
        data = json.loads(p.read_text(encoding="utf-8"))
        out[data["architecture"]] = data
    return out


def _load_tasks(tasks_path: Path) -> dict[str, dict[str, Any]]:
    """Read tasks.jsonl (skipping `# …` comment lines) keyed by task_id."""
    tasks: dict[str, dict[str, Any]] = {}
    for line in tasks_path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        t = json.loads(s)
        tasks[t["task_id"]] = t
    return tasks


def _resolve_runs_per_task(
    runs: dict[str, dict[str, Any]], arch_names: list[str]
) -> int:
    """Derive runs_per_task from the runner config, not from successful records.

    Codex's PR #43 finding: deriving from `max(run_index for r in runs)`
    over the first architecture's successful records undercounts when
    that arch had errors at its highest run_index — those errored runs
    sit in `errors[]`, not `runs[]`. The runner writes the intended
    cardinality into `config.runs_per_task`; that's the truth.

    Fallback order:
      1. First arch's `config.runs_per_task` (the runner.py source of truth).
      2. Max of `config.runs_per_task` across all arches (in case the
         first arch's config was somehow truncated but others ran with
         a longer schedule — unlikely but defensive).
      3. Max of (max(run_index)+1) across all arches' successful records
         AND error records — used only when no config field is present
         (e.g., an older pre-#41 snapshot).
    """
    config_values: list[int] = []
    for arch in arch_names:
        if arch not in runs:
            continue
        cfg = runs[arch].get("config") or {}
        v = cfg.get("runs_per_task")
        if isinstance(v, int) and v > 0:
            config_values.append(v)
    if config_values:
        return max(config_values)

    # Fallback: scan both runs[] and errors[] so an errored highest-index
    # run still counts toward cardinality.
    observed: list[int] = []
    for arch in arch_names:
        if arch not in runs:
            continue
        payload = runs[arch]
        for r in payload.get("runs", []):
            idx = r.get("run_index")
            if isinstance(idx, int):
                observed.append(idx)
        for e in payload.get("errors", []):
            idx = e.get("run_index")
            if isinstance(idx, int):
                observed.append(idx)
    return (max(observed) + 1) if observed else 0


def _log_orphan_records(
    indexed: dict[str, dict[tuple[str, int], dict[str, Any]]],
    known_task_ids: set[str],
    runs_per_task: int,
) -> None:
    """Warn about run records with task_ids absent from tasks.jsonl.

    "Orphan" means the record's `task_id` isn't in tasks.jsonl at all
    (deprecated task still in the run JSON, or task added since the
    run was produced) — NOT records filtered out by --task-ids. The
    earlier draft conflated the two and spammed the log when --task-ids
    was used; the dry-run on POL-001+EDGE-001 made the noise obvious.

    Also flags records whose run_index is outside [0, runs_per_task)
    for tasks that ARE in tasks.jsonl — that's the same "silently
    skipped" failure mode for a different reason.
    """
    for arch, by_key in indexed.items():
        for (tid, ridx) in sorted(by_key.keys()):
            if tid not in known_task_ids:
                print(
                    f"[orphan] arch={arch} task={tid} run_index={ridx} — "
                    f"task_id absent from tasks.jsonl",
                    file=sys.stderr,
                )
            elif not (0 <= ridx < runs_per_task):
                print(
                    f"[orphan] arch={arch} task={tid} run_index={ridx} — "
                    f"run_index outside [0, {runs_per_task})",
                    file=sys.stderr,
                )


def _validate_task_schema(tasks: dict[str, dict[str, Any]], task_ids: list[str]) -> None:
    """Fail-fast pre-sweep check: every task has the fields judge_one reads.

    Runs before the first paid API call so an operator who edits
    tasks.jsonl and forgets to fill a rubric dimension sees a single
    diagnostic instead of a wall of [fail] lines mid-sweep.
    """
    missing: list[str] = []
    for tid in task_ids:
        task = tasks[tid]
        for field in _REQUIRED_TASK_FIELDS:
            if field not in task:
                missing.append(f"{tid}.{field}")
        rubric = task.get("rubric") or {}
        for field in _REQUIRED_RUBRIC_FIELDS:
            if field not in rubric:
                missing.append(f"{tid}.rubric.{field}")
    if missing:
        raise RuntimeError(
            f"tasks.jsonl missing required fields, refusing to start paid "
            f"sweep: {missing[:10]}"
            + (f" (+{len(missing) - 10} more)" if len(missing) > 10 else "")
        )


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
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
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

    if not tasks:
        print(
            f"No tasks loaded from {tasks_path} (parallel to runner.py guard).",
            file=sys.stderr,
        )
        return 1

    arch_names = architectures or sorted(runs.keys())
    output_dir.mkdir(parents=True, exist_ok=True)
    out_paths = {arch: output_dir / f"judgments_{arch}.json" for arch in arch_names}

    # Index runs by (task_id, run_index) per architecture for the
    # per-task interleave loop below.
    indexed: dict[str, dict[tuple[str, int], dict[str, Any]]] = {}
    for arch, payload in runs.items():
        indexed[arch] = {(r["task_id"], r["run_index"]): r for r in payload["runs"]}

    # Honor the frozen tasks.jsonl ordering, optionally filtered.
    if task_ids:
        wanted = set(task_ids)
        unknown = wanted - tasks.keys()
        if unknown:
            raise RuntimeError(f"Unknown task IDs in --task-ids: {sorted(unknown)}")
        sweep_task_ids = [tid for tid in tasks if tid in wanted]
    else:
        sweep_task_ids = list(tasks.keys())

    # Pre-sweep validation — fail before any paid API call if any task
    # is missing fields judge_one reads.
    _validate_task_schema(tasks, sweep_task_ids)

    # `runs_per_task` from the runner config rather than `max(run_index)`
    # over successful records — if `arch_names[0]` had errors at its
    # highest index (recorded in errors[], not runs[]), the max would
    # under-count and silently skip other archs' completed runs at that
    # index. Falls back to a max-across-all-archs scan if the source JSON
    # predates the runner.py field (older 8B snapshots).
    runs_per_task = _resolve_runs_per_task(runs, arch_names)

    # Surface records that exist in the run JSONs but have no corresponding
    # task in tasks.jsonl (deprecated task IDs, or tasks added since the
    # run was produced) — previously silently skipped. Pass the full
    # tasks.keys() set, not sweep_task_ids, so --task-ids filtering
    # doesn't spam every excluded task as a false-positive orphan.
    _log_orphan_records(indexed, set(tasks.keys()), runs_per_task)

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
    total_cache_creation = 0
    total_cache_read = 0
    n_done = 0
    n_total = runs_per_task * len(sweep_task_ids) * len(arch_names)

    print(
        f"Judge sweep: {len(arch_names)} arch × {len(sweep_task_ids)} task × "
        f"{runs_per_task} run = {n_total} judgments.",
        file=sys.stderr,
    )

    def _checkpoint(arch: str) -> None:
        """Atomic per-arch flush. Called after every iteration regardless
        of branch — a long run of [miss] / [fail] on one arch before any
        success no longer loses diagnostics on Ctrl-C."""
        _write_judgments(
            path=out_paths[arch],
            architecture=arch,
            config=_config(completed_at=None),
            judgments=per_arch_judgments[arch],
            errors=per_arch_errors[arch],
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
                    print(
                        f"[miss] arch={arch} task={tid} "
                        f"run={run_index + 1}/{runs_per_task} — no record",
                        file=sys.stderr,
                    )
                    _checkpoint(arch)
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
                        f"[fail] arch={arch} task={tid} "
                        f"run={run_index + 1}/{runs_per_task} "
                        f"{type(e).__name__}: {e}",
                        file=sys.stderr,
                    )
                else:
                    per_arch_judgments[arch].append(judgment)
                    u = judgment["judge_usage"]
                    total_input += u["input_tokens"]
                    total_output += u["output_tokens"]
                    total_cache_creation += u["cache_creation_input_tokens"]
                    total_cache_read += u["cache_read_input_tokens"]
                    n_done += 1
                    pass_str = "PASS" if judgment["task_passed"] else "FAIL"
                    drift = ""
                    if judgment["coerced_dims"] or judgment["off_grid_dims"]:
                        drift = (
                            f" [drift coerced={judgment['coerced_dims']} "
                            f"off_grid={judgment['off_grid_dims']}]"
                        )
                    print(
                        f"[{pass_str}] {n_done}/{n_total} arch={arch} task={tid} "
                        f"run={run_index + 1}/{runs_per_task} "
                        f"fc={judgment['factual_correctness']} "
                        f"cite={judgment['citation_accuracy']} "
                        f"nofab={judgment['no_fabrication']} "
                        f"(input={u['input_tokens']}, "
                        f"output={u['output_tokens']}, "
                        f"cache_w={u['cache_creation_input_tokens']}, "
                        f"cache_r={u['cache_read_input_tokens']}){drift}"
                    )
                _checkpoint(arch)

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
        f"Cost: input={total_input} (cache_w={total_cache_creation}, "
        f"cache_r={total_cache_read}), output={total_output} tokens "
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
