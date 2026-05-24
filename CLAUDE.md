# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A measurement framework, not a product. Two reference customer-support agents (Architecture A: RAG + tool calls; Architecture B: bounded policy lookup tools) are implemented against the *same* corpus, *same* tasks, and *same* model so per-task token usage can be compared head-to-head. The headline artifact is `measurement/results/comparison.md`.

## Current state

The repo is currently **docs and scaffolding only** — no Python implementation has landed yet. `architecture_a_rag/`, `architecture_b_bounded/`, `measurement/`, `corpus/`, and `data/` exist but contain READMEs/specs, not code. `BUILD_PLAN.md` is the authoritative sequencing guide: Day 1 = Architecture A + token accounting, Day 2 = Architecture B + full task set + runner, Day 3 = LLM-as-judge + adversarial review + report. Implement in that order — `measurement/tokens.py` is load-bearing for both architectures and must exist before either agent.

The commands documented in `README.md` (`python measurement/runner.py …`, `pip install -r requirements.txt`) describe the *intended* CLI; they will not work until the corresponding files are written.

## Architectural invariants

These constraints come from `METHODOLOGY.md` and `BUILD_PLAN.md`. Violating them invalidates the comparison.

- **Model:** `claude-sonnet-4-5`, temperature `0.0`, `max_tokens=1024`, native Anthropic function calling. Same across both architectures.
- **Caching:** Disabled for v1. `cache_creation_input_tokens` and `cache_read_input_tokens` must be zero. A v2 measurement with caching is out of scope for now.
- **Transactional tools (`get_booking_status`, `search_flights`, `search_hotels`, `search_cars`) are identical between A and B.** If you change one, change the other — the comparison assumes the only difference is policy retrieval.
- **Token decomposition (Silicon Data 5-category) must sum to API-reported `input_tokens` within 2%.** `measurement/runner.py` asserts this and flags discrepancies; do not silence the assertion.
- **System prompt token targets:** Architecture A ~500 tokens, Architecture B ~150–250 tokens. These are part of the design, not accidental.
- **Task IDs in `measurement/tasks.jsonl` are frozen once published.** New tasks get new IDs (POL-006, MIX-006, …); edits create a new ID and deprecate the old one. Never mutate an existing task's content.
- **Runs:** Three runs per task per architecture, alternating A/B/A/B to control for API time-of-day variance. Report the median; record variance.
- **A task that one architecture fails is excluded from that architecture's cost comparison** — comparing cost on unsolved tasks is misleading.

## The adversarial review is non-negotiable

Per `METHODOLOGY.md` §"Pre-publication adversarial review" and `BUILD_PLAN.md` Step 13: before any number in `comparison.md` is treated as a finding, the three checks (equal tuning effort, task-set neutrality, counterfactual reasoning) plus steel-manning the null plus a net confidence statement must be filled in. A benchmark without this section is explicitly framed as a marketing artifact, not a measurement. Do not mark the project "shippable" or remove `_TBD_` placeholders from the headline tables without completing this section.

Specific bias to watch for when writing tasks: phrasings like "what is your rebooking policy" map suspiciously cleanly to Architecture B's `get_rebooking_policy` tool. Tasks should be in customer-style phrasing, not architect-style category names.

## Cross-architecture parity rules

- Both architectures share `corpus/swiss_faq.md` and `data/travel.sqlite` (forked from the LangGraph customer-support tutorial; do not edit upstream content without re-attribution).
- Architecture B's `policies/` files must be a complete partition of `corpus/swiss_faq.md` — every paragraph belongs to exactly one policy file. Verify completeness when partitioning.
- Both agents implement the same loop shape: receive user message → call model with system prompt + tools → execute tool calls → feed results back → loop until model produces a no-tool-call response.
- Instrument token counting at **every** model call, not just the final one — multi-turn tool loops are where retrieved-context tokens accumulate.

## Tooling

- **Package manager:** `pip` + `requirements.txt` (per `BUILD_PLAN.md` Step 1). The parent workspace defaults to `uv` for other repos, but this project intentionally uses plain pip for portability of the published artifact.
- **Vector store:** ChromaDB or FAISS, persisted under `architecture_a_rag/vector_store/` (gitignored).
- **Embeddings:** `text-embedding-3-small` (OpenAI). Embedding API calls are excluded from per-task cost per methodology.
- **Judge model:** Claude Opus 4 for LLM-as-judge scoring against the per-task rubric. Manually review a 10% random sample to detect judge bias.

## What lives where

- `BUILD_PLAN.md` — implementation sequencing (read this before writing code).
- `METHODOLOGY.md` — what gets counted, what doesn't, and the adversarial review checklist. The authority for measurement choices.
- `HANDOVER.md` — the *organizational* argument the project exists to make (RAG vs. bounded tools as a team-boundary question, not just a cost question). The "Recommended path forward" section gets filled in only after measurements land.
- `measurement/tasks.md` — task schema, class composition (5 pure-policy / 5 pure-transactional / 5 mixed / 3–5 edge), and rubric scoring rules.
- `architecture_{a,b}/README.md` — per-architecture design choices and "done" criteria.
- `measurement/results/comparison.md` — the headline output. Currently a template with `_TBD_` placeholders.

## Out of scope for v1

Caching, multiple models, multi-turn dialogue, multi-language, production hardening, UI. Don't add these unless explicitly asked — they would expand the comparison surface in ways the methodology isn't designed to handle.
