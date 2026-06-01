"""Orchestration CLI for the support-agent-token-benchmark project.

Three modes:

  --smoke         Single trivial task end-to-end (Phase 1 verification).
                  Makes one real API call, asserts the 5% methodology
                  gate, exits 0/1. Cost: ~$0.01.

  --architectures Run measurement across listed architectures × tasks ×
                  runs. Writes per-architecture JSON to
                  measurement/results/architecture_<id>.json.
                  (Phase 2 — requires architectures to be registered.)

  --report        Aggregate the per-architecture JSON files into
                  measurement/results/comparison.md.

Architectures register themselves into ARCHITECTURE_REGISTRY when their
modules are imported. Phase 1 ships only the built-in smoke "architecture"
(a single direct API call, not a real architecture); A/C/E register in
Phase 2 when their agent.py modules land.
"""
from __future__ import annotations

import argparse
import json
import sys
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

from measurement.tokens import AGENT_MODEL, decompose_request, record_run


# ---------------------------------------------------------------------------
# Architecture registry (Phase 2 populates this)
# ---------------------------------------------------------------------------


ARCHITECTURE_REGISTRY: dict[str, Callable] = {}


def register_architecture(name: str, agent_fn: Callable) -> None:
    """Register an architecture's agent function. Called from each
    `architectures/<arch>/agent.py` module at import time.
    """
    ARCHITECTURE_REGISTRY[name] = agent_fn


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
            "Per the [Silicon Data 5-category model](https://www.silicondata.com/blog/llm-cost-per-token), "
            "every model call's token cost is the sum of four input categories and one output category. "
            "The runner asserts that categories ①–④ sum to API-reported `input_tokens` "
            "within 5%; discrepancies are flagged, not silenced "
            "(see `METHODOLOGY.md` §\"What gets counted\").",
            "",
            "```mermaid",
            "flowchart LR",
            "    Q[User query] -->|\"③ User message<br/>identical across architectures\"| API[Model call]",
            "    SP[\"① System prompt<br/>~300–500 tokens<br/>architecture-set, ~constant per arch\"] -->|added per call| API",
            "    TS[\"④ Tool call overhead<br/>tool schema JSON<br/>architecture-set, ~constant per arch\"] -->|added per call| API",
            "    CTX[\"② Retrieved/injected context<br/>retrieval architecture sets the size<br/>where the comparison lives\"] -->|added per call| API",
            "    API -->|\"⑤ Response<br/>agent-set, varies per task\"| Out[Agent response]",
            "",
            "    API ==> Assert{{\"input_tokens ≈ ① + ② + ③ + ④<br/>within 5% tolerance\"}}",
            "```",
            "",
            "The architecture comparison lives in category ②. Categories ①, ③, ④ are "
            "approximately constant within an architecture; category ⑤ is bounded by the agent's "
            "`max_tokens` and varies with task. Architecture differences in mean tokens per task are "
            "driven primarily by ② (retrieved/injected context).",
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
        help="Comma-separated architecture names (e.g., a,c,e).",
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

    if args.architectures and args.tasks:
        print(
            "Full measurement runs land in Phase 2 (architectures must be "
            "registered first). See BUILD_PLAN.md.",
            file=sys.stderr,
        )
        return 1

    print(
        "Usage: runner.py --smoke | --report | --architectures a,c,e --tasks tasks.jsonl",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
