# Build Plan

This document is the sequencing guide for building the project. It's written for the developer (or coding assistant) executing the work, not for an external reader.

## Day 1 — Foundation and Architecture A

### Step 1: Project setup (~30 min)

- [ ] Create Python virtual environment
- [ ] Initialize `requirements.txt` with: `anthropic`, `openai` (for embeddings), `chromadb` (or `faiss-cpu`), `tiktoken`, `python-dotenv`, `tabulate`
- [ ] Set up `.env.example` with `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` placeholders
- [ ] Verify `corpus/swiss_faq.md` and `data/travel.sqlite` are downloaded from the LangGraph tutorial sources

### Step 2: Token counting infrastructure (~1 hour)

- [ ] Implement `measurement/tokens.py` with:
  - `count_tokens(text: str, model: str) -> int` using the appropriate tokenizer
  - `decompose_request(system, messages, tools) -> dict` returning the 5-category breakdown
  - `record_run(architecture, task_id, decomposition, api_usage, response) -> dict` for structured logging

This is the load-bearing measurement code. Get it right before building either architecture, because both architectures call into it.

### Step 3: Architecture A implementation (~3 hours)

Follow `architecture_a_rag/README.md` design choices:

- [ ] Implement chunking of `corpus/swiss_faq.md` into ~300-500 token chunks at H2 boundaries
- [ ] Embed chunks with `text-embedding-3-small`, persist to ChromaDB or FAISS in `architecture_a_rag/vector_store/`
- [ ] Implement tools in `tools.py`:
  - `lookup_policy(query)` — top-4 retrieval from vector store
  - `get_booking_status(booking_id)` — SQLite query
  - `search_flights(...)`, `search_hotels(...)`, `search_cars(...)` — additional SQLite queries based on what tasks need
- [ ] Write system prompt in `prompts.py`, target ~500 tokens
- [ ] Implement agent loop in `agent.py`: loop until model produces a non-tool-call response
- [ ] Smoke-test with 2-3 hand-written queries to confirm it runs end-to-end

### Step 4: First measurements (~30 min)

- [ ] Write 3-5 placeholder tasks in `measurement/tasks.jsonl` (use the schema in `measurement/tasks.md`)
- [ ] Run Architecture A on these tasks
- [ ] Verify the token decomposition sums correctly (input categories add up to API-reported `input_tokens`)
- [ ] Verify the JSON output to `measurement/results/architecture_a.json` is well-formed

## Day 2 — Architecture B and full task set

### Step 5: Partition the FAQ corpus (~1 hour)

- [ ] Read `corpus/swiss_faq.md` carefully
- [ ] Identify the policy classes present (rebooking, refund, baggage, check-in, etc.)
- [ ] Create one file per class in `architecture_b_bounded/policies/`
- [ ] Verify the partitioning is complete (every paragraph of the FAQ belongs to exactly one policy file)

### Step 6: Architecture B implementation (~2 hours)

- [ ] Implement one tool per policy file in `tools.py` (each is a simple file read)
- [ ] Copy transactional tools from Architecture A (they're identical)
- [ ] Write system prompt in `prompts.py`, target ~150-250 tokens
- [ ] Implement agent loop in `agent.py` — same structure as Architecture A
- [ ] Smoke-test with the same hand-written queries from Day 1

### Step 7: Full task set (~2 hours)

- [ ] Write all 15-20 tasks in `tasks.jsonl` per the schema in `measurement/tasks.md`
- [ ] Manually answer each task yourself to confirm it's well-defined
- [ ] Document expected_citations and expected_tool_calls for each task

### Step 8: Implement the runner (~2 hours)

- [ ] Build `measurement/runner.py` with:
  - `--architecture {a,b,both}` argument
  - `--tasks <path>` argument
  - `--runs <int>` argument (default 3)
  - Output to `measurement/results/architecture_{a,b}.json`
  - `--report` flag that generates `measurement/results/comparison.md` from the JSON files

### Step 9: First full run (~30 min)

- [ ] Run `python measurement/runner.py --architecture both --runs 3`
- [ ] Inspect results for sanity (no architecture should have 0% success; tokens should be in the expected order of magnitude)
- [ ] Fix any bugs the run surfaces

## Day 3 — Analysis and documentation

### Step 10: LLM-as-judge scoring (~2 hours)

- [ ] Implement scoring in `measurement/runner.py` using Claude Opus 4 as judge against the rubric in each task
- [ ] Manually review a 10% random sample of judgments
- [ ] If judge bias is detected, adjust the rubric prompts and re-run

### Step 11: Generate the comparison report (~1 hour)

- [ ] Run `--report` to populate `measurement/results/comparison.md`
- [ ] Manually review the report for any anomalies
- [ ] Add a written interpretation section discussing what the numbers actually show

### Step 12: Notebook for visualization (~1 hour)

- [ ] Build `notebooks/analysis.ipynb` with:
  - Bar chart of mean tokens per task by architecture and class
  - Distribution plot of token usage (to show variance, not just means)
  - Cost projection chart (per-1K, per-10K, per-100K tasks)
- [ ] Export key charts as PNGs that can be embedded in the article

### Step 13: Adversarial review (~2 hours, do not skip)

This is the discipline that separates "I ran a benchmark" from "I produced a defensible finding." Per `METHODOLOGY.md`, all three checks below are required before publishing any number as a finding.

- [ ] **Check 1 — Equal tuning effort.** Did Architecture A receive tuning effort comparable to Architecture B's curation effort? If not, either tune A further or document the asymmetry honestly. Fill in the tuning effort review table in `comparison.md`.
- [ ] **Check 2 — Task set neutrality.** Re-read every task in `tasks.jsonl`. Does any task phrasing map suspiciously cleanly to Architecture B tool names? Is the class distribution realistic? Document findings in `comparison.md`.
- [ ] **Check 3 — Counterfactual reasoning.** For each headline finding, articulate what would have to be true for it to reverse. Fill in the counterfactual section of `comparison.md`. If you cannot articulate a credible counterfactual, you have not thought hard enough about the failure modes — return to the data and try again.
- [ ] **Steel-man the null.** Write out the strongest argument that the measurement shows nothing meaningful. Address it. If it cannot be addressed, the finding is not yet ready.
- [ ] **Confidence statement.** State a net confidence level (high / medium / low / preliminary) and define the scope of validity.

If any check reveals a problem that can be fixed by re-running with better tuning or task balance, fix it before proceeding. If the problem cannot be fixed, reframe the finding to match what was actually measured rather than what you hoped to measure.

### Step 14: Final pass on documentation (~1 hour)

- [ ] Update `README.md` headline table with real numbers
- [ ] Update `HANDOVER.md` recommendation section with the architecture choice the measurements support, honestly reflecting the confidence level from Step 13
- [ ] Add any newly-discovered limitations to `METHODOLOGY.md`
- [ ] Verify all links in all `.md` files resolve

## Decision points along the way

The build will surface decisions that aren't pre-specified. Document each in `notebooks/analysis.ipynb` or as a separate ADR. Likely ones:

- **Chunk size for Architecture A.** The README suggests 300-500 tokens. The actual best value depends on the corpus. If chunks are consistently above or below, document the adjustment.
- **Top-K for Architecture A.** Default is 4. If recall is poor on policy tasks, document a tuned value.
- **Tool count for Architecture B.** Partitioning the corpus may yield more or fewer policy classes than expected. Document the actual count.
- **Judge model behavior.** If Claude Opus 4 systematically rates one architecture higher despite manual review disagreeing, consider GPT-4 as judge or use a different rubric structure.

## Out of scope for v1

These are explicitly deferred:

- Prompt caching (per `METHODOLOGY.md`, v1 measures with caching disabled)
- Multiple models (single-model comparison only)
- Multi-turn dialogue (single-turn only)
- Production hardening (no rate limit handling, no retry logic beyond what's already in the SDK)
- Multi-language (English only)
- Frontend / UI (CLI only)

## What "shippable" looks like

The repo is shippable for portfolio + article-companion purposes when:

1. Both architectures run end-to-end on the full task set
2. The comparison report has real numbers (no remaining `_TBD_` in the headline table)
3. **The adversarial review is complete** — `comparison.md` has the Confidence and Known Biases section populated, with an honest confidence level and scope of validity
4. The HANDOVER.md recommendation section is filled in based on the measured results, with the confidence level honestly reflected
5. Someone could clone the repo, install dependencies, and reproduce the headline numbers within 5%
6. The README clearly states what the project is and what it isn't (no overclaiming)

A future iteration can add caching, multiple models, larger task sets, etc. None of those is required for v1 to be useful. But the adversarial review is non-negotiable — a benchmark without it is a marketing artifact, not a measurement.
