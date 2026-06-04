"""§10 judge stability test on the POL-001 hybrid-vs-naive paired records.

Context: the 20-record manual review (`runs/2026-06-04-phase2-step8b/judgment_summary.md`)
flagged record #16 (POL-001 / hybrid_rag / run 0, FAIL with nofab=0.5) as a `dispute`
because every "specific numeric" the judge penalised is a verbatim corpus quote
(corpus lines 192-227). Record #17 (POL-001 / naive_rag / run 2, PASS) contains
functionally equivalent content. The judge passed naive and failed hybrid on the
same content type. Two competing hypotheses:

  H1 — judge non-determinism (open question 6): judge.py runs at default
       temperature because opus-4-7 rejects the parameter (see PR #45), so
       repeated judgments of the same response will flip across runs.
  H2 — stable judge bias against hybrid: the judge systematically penalises
       hybrid more than naive even on content equal to passing naive.

This script runs `judge_one()` N=5 times on each of the two records and tallies
the verdicts. Outcomes:
  - #16 mostly PASS → H1 confirmed; original FAIL was a one-off
  - #16 mostly FAIL with same rationale → H2 confirmed; stable bias
  - mixed → genuine judge noise on borderline content; report as scope limit

Output: `measurement/results/runs/2026-06-04-step10-stability-pol001/stability_judgments.json`.

Frozen-artifact rule: this script does NOT mutate `judgments_*.json` or
`architecture_*.json` under `runs/2026-06-04-phase2-step8b/`. It creates a new
dated dir.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import anthropic

# Import judge_one from the project module
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from measurement.judge import judge_one  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_RUN_DIR = REPO_ROOT / "measurement" / "results" / "runs" / "2026-06-04-phase2-step8b"
TASKS_PATH = REPO_ROOT / "measurement" / "tasks.jsonl"

# Pair under test: hybrid (disputed FAIL) vs naive (confirmed PASS) on POL-001
TARGETS = [
    {"task_id": "POL-001", "architecture": "hybrid_rag", "run_index": 0,
     "original_verdict": "FAIL", "original_scores": (1.0, 1.0, 0.5)},
    {"task_id": "POL-001", "architecture": "naive_rag", "run_index": 2,
     "original_verdict": "PASS", "original_scores": (1.0, 1.0, 1.0)},
]

N_REPEATS = 5

OUTPUT_DIR = REPO_ROOT / "measurement" / "results" / "runs" / "2026-06-04-step10-stability-pol001"
OUTPUT_FILE = OUTPUT_DIR / "stability_judgments.json"


def _load_task(task_id: str) -> dict:
    with TASKS_PATH.open() as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            t = json.loads(line)
            if t["task_id"] == task_id:
                return t
    raise KeyError(f"task {task_id!r} not in tasks.jsonl")


def _load_record(architecture: str, task_id: str, run_index: int) -> dict:
    arch_file = SOURCE_RUN_DIR / f"architecture_{architecture}.json"
    with arch_file.open() as f:
        data = json.load(f)
    for r in data["runs"]:
        if r["task_id"] == task_id and r["run_index"] == run_index:
            return r
    raise KeyError(f"no record for {architecture}/{task_id}/run{run_index}")


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not set — re-enable the key in the Anthropic console first.",
              file=sys.stderr)
        return 2

    client = anthropic.Anthropic()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    results = {
        "test": "judge-stability-pol001-hybrid-vs-naive",
        "n_repeats": N_REPEATS,
        "judge_model": "claude-opus-4-7",
        "judge_temperature": "default (opus-4-7 rejects parameter)",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "targets": [],
    }

    total_input_tokens = 0
    total_output_tokens = 0
    total_cache_creation = 0
    total_cache_read = 0

    for target in TARGETS:
        task = _load_task(target["task_id"])
        record = _load_record(target["architecture"], target["task_id"], target["run_index"])

        per_target = {
            "task_id": target["task_id"],
            "architecture": target["architecture"],
            "run_index": target["run_index"],
            "original_verdict": target["original_verdict"],
            "original_scores": target["original_scores"],
            "judgments": [],
        }

        for i in range(N_REPEATS):
            print(f"  [{target['architecture']}/{target['task_id']}/run{target['run_index']}] "
                  f"repeat {i+1}/{N_REPEATS}...", flush=True)
            j = judge_one(client=client, task=task, record=record)
            per_target["judgments"].append({
                "repeat_index": i,
                "factual_correctness": j["factual_correctness"],
                "citation_accuracy": j["citation_accuracy"],
                "no_fabrication": j["no_fabrication"],
                "task_passed": j["task_passed"],
                "rationale": j["rationale"],
                "stop_reason": j.get("stop_reason"),
                "judge_usage": j.get("judge_usage"),
            })
            usage = j.get("judge_usage") or {}
            total_input_tokens += usage.get("input_tokens", 0)
            total_output_tokens += usage.get("output_tokens", 0)
            total_cache_creation += usage.get("cache_creation_input_tokens", 0) or 0
            total_cache_read += usage.get("cache_read_input_tokens", 0) or 0

        passes = sum(1 for j in per_target["judgments"] if j["task_passed"])
        per_target["pass_rate"] = f"{passes}/{N_REPEATS}"
        per_target["pass_count"] = passes
        results["targets"].append(per_target)

    results["completed_at"] = datetime.now(timezone.utc).isoformat()
    results["usage_totals"] = {
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "cache_creation_input_tokens": total_cache_creation,
        "cache_read_input_tokens": total_cache_read,
    }

    with OUTPUT_FILE.open("w") as f:
        json.dump(results, f, indent=2)

    print()
    print("=" * 70)
    print("Stability test complete")
    print("=" * 70)
    for t in results["targets"]:
        print(f"  {t['architecture']}/{t['task_id']}/run{t['run_index']} "
              f"(original {t['original_verdict']}): {t['pass_rate']} PASS")
    print(f"  Total usage: input={total_input_tokens:,}  "
          f"output={total_output_tokens:,}  "
          f"cache_w={total_cache_creation:,}  cache_r={total_cache_read:,}")
    print(f"  Output: {OUTPUT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
