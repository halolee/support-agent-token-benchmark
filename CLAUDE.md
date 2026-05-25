# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A measurement framework, not a product. Four reference customer-support agents (A: Naive RAG, A+G: A with prompt caching, C: Grep, E: Hybrid RAG) are implemented against the *same* corpus, *same* tasks, and *same* model so per-task token usage can be compared head-to-head under enterprise-realistic constraints. The headline artifact is `measurement/results/comparison.md`. Two further architectures (B: bounded structured tools, D: full corpus stuffed) are scoped but deferred to v2; see `ROADMAP.md`.

## Read first

For full framing context, see `AGENT_HANDOVER_NOTE.md` — it's the orientation doc for any implementation work and explains the v3.1 framing (the comparison is "four retrieval architectures under enterprise constraints," not "MCP/RAG vs grep" or "RAG vs MCP").

## Current state

The repo is currently **docs and scaffolding only** — no Python implementation has landed yet. `BUILD_PLAN.md` is the authoritative sequencing guide: Phase 1 = foundation + token accounting, Phase 2 = A, C, E + adversarial review, Phase 3 = A+G (caching variant), Phase 4 = deferred B/D. Implement in that order — `measurement/tokens.py` is load-bearing for all architectures and must exist before any agent.

The commands documented in `README.md` (`python measurement/runner.py …`, `pip install -r requirements.txt`) describe the *intended* CLI; they will not work until the corresponding files are written.

## Architectural invariants

These constraints come from `METHODOLOGY.md` and `BUILD_PLAN.md`. Violating them invalidates the comparison.

- **Modularity constraint:** Hard, project-wide. Every cross-team data flow goes through an explicit tool call owned by the data-owning team. Agent code does not read `corpus/swiss_faq.md` or query `data/travel.sqlite` directly — it calls tools. See `METHODOLOGY.md` §"Modularity constraint" and per-architecture READMEs for how each implements it. This is the discipline most likely to get accidentally violated during implementation; treat it as load-bearing.
- **Agent model:** `claude-sonnet-4-6`, temperature `0.0`, `max_tokens=1024`, native Anthropic function calling. Same across all architectures.
- **Judge model:** `claude-opus-4-7` for LLM-as-judge scoring against per-task rubric.
- **Embedding model:** `BAAI/bge-m3` (MIT-licensed, self-hosted) for A, A+G, and E. No third-party embedding API. The choice eliminates data egress exposure; see `METHODOLOGY.md` §"API vs self-hosted choices."
- **Caching:** Disabled for A, C, E. Enabled for A+G (which exists specifically to measure the caching effect).
- **Transactional tools** (`get_booking_status`, `search_flights`, `search_hotels`, `search_cars`) are identical across all measured architectures. If you change one, change them all — the comparison assumes the only difference is retrieval.
- **Token decomposition** (Silicon Data 5-category) must sum to API-reported `input_tokens` within 5%. `measurement/runner.py` asserts this and flags discrepancies; do not silence the assertion.
- **System prompt token targets:** A ~500 tokens, C ~300-400 tokens, E ~500 tokens. These are part of the design, not accidental.
- **Task IDs in `measurement/tasks.jsonl` are frozen once published.** New tasks get new IDs. Edits create a new ID and deprecate the old one. Never mutate an existing task's content.
- **Runs:** Three runs per task per architecture, alternating (A, A+G, C, E, A, A+G, C, E, …) to control for API time-of-day variance. Report the median; record variance.
- **A task that an architecture fails is excluded from that architecture's cost comparison** — comparing cost on unsolved tasks is misleading.

## The adversarial review is non-negotiable

Per `METHODOLOGY.md` §"Pre-publication adversarial review" and `BUILD_PLAN.md` Step 10: before any number in `comparison.md` is treated as a finding, the three checks (equal tuning effort, task-set neutrality, counterfactual reasoning) plus steel-manning the null plus a net confidence statement must be filled in. A benchmark without this section is explicitly framed as a marketing artifact, not a measurement. Do not mark the project "shippable" or remove `_TBD_` placeholders from the headline tables without completing this section.

Specific bias to watch for when writing tasks: phrasings that map suspiciously cleanly to architect-style category names (e.g., "rebooking policy" → `get_rebooking_policy` for B in v2), or keyword-friendly phrasings that give grep (C) a free signal. Tasks should be in customer-style phrasing, not architect-style category names. See `measurement/tasks.md` "Critical rule" section.

## Cross-architecture parity rules

- All architectures share `corpus/swiss_faq.md` and `data/travel.sqlite` (sourced from the LangGraph customer-support tutorial; do not edit upstream content without re-attribution).
- All architectures access the corpus through Support Content's exposed tool (`vector_search` for A/A+G, `grep_corpus` for C, `hybrid_search` for E). None reads the corpus file directly.
- All agents implement the same loop shape: receive user message → call model with system prompt + tools → execute tool calls → feed results back → loop until model produces a no-tool-call response.
- Instrument token counting at **every** model call, not just the final one — multi-turn tool loops are where retrieved-context tokens accumulate.
- Audit log payload is uniform across architectures (`task_id`, `response`, `tools_called` only). Audit log token cost is excluded from per-task decomposition. See `METHODOLOGY.md` §"Audit log specification."

## Tooling

- **Package manager:** `pip` + `requirements.txt`. The parent workspace defaults to `uv` for other repos; this project intentionally uses plain pip for portability of the published artifact.
- **Vector store:** ChromaDB or FAISS, persisted under `architectures/a_naive_rag/vector_store/` and `architectures/e_hybrid_rag/vector_store/` (gitignored).
- **Embeddings:** `BAAI/bge-m3` via `sentence-transformers` or `FlagEmbedding`. Self-hosted; no API key required for embeddings.
- **Tokenizer for decomposition:** Anthropic's `client.beta.messages.count_tokens()` API. Do NOT use `tiktoken` (OpenAI's tokenizer; produces wrong counts for Anthropic models).
- **Reranker (E only):** `cross-encoder/ms-marco-MiniLM-L-6-v2`, self-hosted via `sentence-transformers`.

## What lives where

- `AGENT_HANDOVER_NOTE.md` — orientation doc for any implementation work; read first.
- `BUILD_PLAN.md` — phased implementation sequencing (Phase 1 → 4).
- `METHODOLOGY.md` — what gets counted, what doesn't, the modularity constraint spec, and the adversarial review checklist. The authority for measurement choices.
- `ARCHITECTURE_RATIONALE.md` — why these four architectures and not others; the selection framework.
- `ROADMAP.md` — v1 scope, v2 deferred items, future variants.
- `HANDOVER.md` — the *organizational* artifact: how each architecture respects the modularity constraint, cross-team dependencies, sign-off list.
- `measurement/tasks.md` — task schema, class composition (3/3/8/3), and the Check 2 rule for task phrasing.
- `architectures/{a_naive_rag,c_grep,e_hybrid_rag}/README.md` — per-architecture design choices and "done" criteria.
- `architectures_deferred/` — placeholders for B and D (v2).
- `measurement/results/comparison.md` — the headline output. Currently a template with `_TBD_` placeholders.

## Out of scope for v1

Caching variants for C and E, B/D architectures, multiple models, multi-turn dialogue, multi-language, production hardening, UI. Don't add these unless explicitly asked — they would expand the comparison surface in ways the methodology isn't designed to handle. See `ROADMAP.md` for what's deferred to v2 with trigger conditions.
