# Build Plan

Phased execution plan. Each phase produces a working, independently-shippable artifact. Phases can run with gaps between them, supporting parallel execution with other work.

---

## Phase 1 — Foundation

**Goal:** Project is set up, corpus and data are in place, measurement infrastructure works on a smoke test.

**Estimated effort:** 1 day

### Step 0: Explore the LangGraph reference (required first action)

Before designing anything, read what's already there.

- [ ] Open `https://github.com/langchain-ai/langgraph/blob/main/docs/docs/tutorials/customer-support/customer-support.ipynb`
- [ ] **Important — corpus and database are NOT downloadable as standalone files.** The tutorial builds them inside notebook cells: the FAQ corpus is embedded as a Python string in a setup cell; `travel.sqlite` is created and populated by SQL in another setup cell.
- [ ] To extract them: clone the LangGraph repo locally, run the notebook's setup cells, then export the FAQ text to `corpus/swiss_faq.md` and copy the generated `travel.sqlite` to `data/`
- [ ] Note the actual structure of the tutorial's agent — what tools it defines, what dialog routing it uses
- [ ] Read `swiss_faq.md` to inventory the actual policy classes present (count them, note vocabulary)
- [ ] Inspect `travel.sqlite` schema (tables, columns, row counts, sample data)
- [ ] Document findings in a brief `notebooks/00_corpus_inventory.ipynb` — what we're working with

This step exists because we've been treating the LangGraph tutorial as a placeholder. Reading and extracting it first surfaces design constraints we haven't anticipated and confirms what we're actually measuring against.

### Step 1: Project setup

- [ ] Create Python virtual environment
- [ ] Initialize `requirements.txt` with: `anthropic`, `chromadb` (or `faiss-cpu`), `rank-bm25`, `python-dotenv`, `tabulate`, `pytest` (for sanity tests)
- [ ] **Do not include `tiktoken`** — it's OpenAI's tokenizer and will produce wrong counts for Anthropic models
- [ ] Set up `.env.example` with `ANTHROPIC_API_KEY` placeholder
- [ ] Verify corpus and database loaded correctly

### Step 2: Token counting infrastructure

This is the load-bearing measurement code. Build it before any architecture, because all architectures depend on it.

- [ ] Implement `measurement/tokens.py` with:
  - `count_tokens(text: str) -> int` using Anthropic's `client.beta.messages.count_tokens()` API
  - `decompose_request(system, messages, tools) -> dict` returning the 5-category breakdown
  - `record_run(architecture, task_id, decomposition, api_usage, response) -> dict` for structured logging
- [ ] Unit test the decomposition: sum of categories should equal API-reported `input_tokens` within 5%

### Step 3: Runner skeleton

- [ ] Implement `measurement/runner.py` with:
  - `--architectures <list>` argument (e.g., `a,a_cached,c,e`)
  - `--tasks <path>` argument
  - `--runs <int>` argument (default 3)
  - Output to `measurement/results/architecture_<id>.json`
  - `--report` flag that generates `measurement/results/comparison.md` from the JSON files
- [ ] Add a `--smoke` mode that runs a single trivial task to verify wiring

### Phase 1 deliverable

A repo where `pip install -r requirements.txt && python measurement/runner.py --smoke` runs end-to-end without errors, and the token decomposition is correct on the smoke test.

---

## Phase 2 — Core comparison (A, C, E)

**Goal:** Three architectures implemented, full task set run, adversarial review complete, comparison report populated.

**Estimated effort:** 2 days

### Step 4: Write the task set

- [ ] Write ~17 tasks in `measurement/tasks.jsonl` per the schema in `measurement/tasks.md`
- [ ] Distribution: 3 pure policy, 3 pure transactional, 8 mixed, 3 edge case
- [ ] **Critical:** Use customer-style phrasing, not architect-style category names. A task that says "rebooking policy" maps too cleanly to architecture-friendly tool names. See METHODOLOGY Check 2.
- [ ] Manually answer each task yourself to confirm it's well-defined
- [ ] Document expected_citations for each task

### Step 5: Architecture A — Naive RAG

Follow `architectures/a_naive_rag/README.md` design choices:
- [ ] Chunk `corpus/swiss_faq.md` (Support Content team's process, conceptually)
- [ ] Set up vector store (Chroma or FAISS, in `architectures/a_naive_rag/vector_store/`)
- [ ] Implement Support Content's tool: `vector_search(query, k=4)` returning chunks
- [ ] Implement Booking Systems' tools: `get_booking_status`, `search_flights`, etc.
- [ ] Implement system prompt (~500 tokens, comparable in care to other architectures)
- [ ] Implement agent loop in `architectures/a_naive_rag/agent.py`
- [ ] Smoke test with 2-3 tasks

### Step 6: Architecture C — Grep

Follow `architectures/c_grep/README.md` design choices:
- [ ] Implement Support Content's tool: `grep_corpus(keywords, max_results=10)` — case-insensitive, returns matching lines with surrounding context
- [ ] Reuse Booking Systems' tools from A (they're identical across architectures)
- [ ] Implement system prompt — instruct agent to pick search keywords and call grep
- [ ] Implement agent loop
- [ ] Smoke test with 2-3 tasks

### Step 7: Architecture E — Hybrid RAG

Follow `architectures/e_hybrid_rag/README.md` design choices:
- [ ] Implement Support Content's tool: `hybrid_search(query, k=6)` combining BM25 + vector retrieval with reranking
- [ ] Reuse Booking Systems' tools
- [ ] Implement system prompt
- [ ] Implement agent loop
- [ ] Smoke test with 2-3 tasks

### Step 8: Full run

- [ ] Run `python measurement/runner.py --architectures a,c,e --runs 3`
- [ ] Inspect results for sanity (no architecture should have 0% success; tokens should be in expected order of magnitude)
- [ ] Fix any bugs the run surfaces

### Step 9: LLM-as-judge scoring

- [ ] Implement scoring in runner using `claude-opus-4-7` as judge against per-task rubrics
- [ ] Manually review a 10% random sample of judgments
- [ ] Adjust rubric prompts if judge bias is detected

### Step 10: Adversarial review for Phase 2 (do not skip)

Per METHODOLOGY §"Pre-publication adversarial review."

- [ ] **Check 1 — Equal tuning effort.** A's top-K tuned? E's hybrid weighting tuned? C's grep polished? All system prompts equivalently sized? Document in `comparison.md` tuning effort table.
- [ ] **Check 2 — Task set neutrality.** Re-read every task. Do phrasings favor any architecture? Document findings.
- [ ] **Check 3 — Counterfactual reasoning.** For each headline finding, articulate what would have to be true for it to reverse. Fill in counterfactual section.
- [ ] **Steel-man the null.** Write out the strongest "this shows nothing meaningful" argument. Address it.
- [ ] **Confidence statement.** State net confidence (high/medium/low/preliminary) and scope of validity.

### Phase 2 deliverable

Three architectures measured, comparison report populated with real numbers, adversarial review complete. Repo is shippable as-is at this point — Phase 3 and 4 add to it but aren't required for v1 to be useful.

---

## Phase 3 — Caching variant (A+G)

**Goal:** Measure A with Anthropic prompt caching enabled. Quantify how much caching collapses A's cost.

**Estimated effort:** 0.5 day

### Step 11: Implement A+G

- [ ] Copy `architectures/a_naive_rag/` to `architectures/a_naive_rag_cached/` (or add a `--cached` flag to the existing A agent)
- [ ] Enable prompt caching on the system prompt (always cacheable)
- [ ] Enable caching on retrieved chunks when stable (this requires thinking about what "stable" means — chunks retrieved with same query are cacheable; different queries are not)
- [ ] Document the caching configuration explicitly in the architecture README

### Step 12: Run and integrate

- [ ] Run A+G on the full task set, 3 runs
- [ ] Add A+G column to comparison report
- [ ] Update adversarial review to cover A+G (Check 1: is caching configured to maximize stable-prefix reuse?)

### Phase 3 deliverable

Four architectures measured. Comparison report shows caching effect quantified. Article can now honestly claim "A vs. C, but here's what A looks like with the obvious optimization enabled."

---

## Phase 4 — Deferred architectures (B, D) — optional, not v1

Per ROADMAP, B and D are deferred. Build only if Phase 2-3 results suggest they'd add to the picture, or if reviewers push back.

- [ ] **Architecture B — Bounded structured tools** — ~1 day if added
- [ ] **Architecture D — Full corpus stuffed** — ~0.5 day if added

If skipping, ensure the article and HANDOVER document explicitly note these were considered and why deferred.

---

## Final documentation pass (after each phase that ships)

- [ ] Update `README.md` headline table with real numbers
- [ ] Update `HANDOVER.md` recommendation section based on measured results, honestly reflecting confidence level
- [ ] Add any newly-discovered limitations to `METHODOLOGY.md`
- [ ] Verify all links in all `.md` files resolve
- [ ] Update `ROADMAP.md` decision log if any scope changed

---

## Decision points along the way

The build will surface decisions that aren't pre-specified. Document each in `notebooks/` or as a brief ADR. Likely ones:

- **Chunk size for A and E.** The README suggests 300-500 tokens. Actual best value depends on corpus structure (discovered in Phase 1).
- **Top-K for A.** Default is 4. Tune based on Phase 2 smoke tests.
- **Hybrid weighting for E.** BM25 vs vector weighting needs tuning per corpus.
- **Reranking model for E.** Cross-encoder choice affects cost and quality.
- **Grep result truncation for C.** Too short loses information; too long wastes tokens. Tune in Phase 2.
- **Judge model behavior.** If `claude-opus-4-7` systematically rates one architecture higher despite manual review disagreeing, document and consider alternative judges.

## Out of scope for v1

These are explicitly deferred (also in ROADMAP):

- Multi-turn dialogue (single-turn only)
- Multiple agent models (single-model comparison)
- Architectures B, D, F, H, I (mentioned in article, not measured)
- Production hardening (no rate limit handling beyond SDK defaults)
- Multi-language (English only)
- Frontend / UI (CLI only)

## What "shippable" looks like

The repo is shippable for portfolio + article-companion purposes when:

1. Phase 1 and 2 complete (foundation + core comparison)
2. The comparison report has real numbers (no remaining `_TBD_` in the headline table for measured architectures)
3. **The adversarial review is complete** — `comparison.md` "Confidence and known biases" populated with honest confidence level and scope of validity
4. The HANDOVER.md recommendation section is filled in based on measured results, with confidence honestly reflected
5. Someone could clone the repo, install dependencies, and reproduce headline numbers within 5%
6. The README clearly states what the project is and isn't (no overclaiming)
7. ROADMAP.md decision log is current

Phase 3 (caching) makes the comparison more defensible but isn't strictly required for v1.

The adversarial review is non-negotiable — a benchmark without it is a marketing artifact, not a measurement.
