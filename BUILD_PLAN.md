# Build Plan

Phased execution plan. Each phase produces a working, independently-shippable artifact. Phases can run with gaps between them, supporting parallel execution with other work.

---

## Phase 1 — Foundation

**Goal:** Project is set up, corpus and data are in place, measurement infrastructure works on a smoke test.

**Estimated effort:** 1 day

### Step 0: Extract the LangGraph reference assets (required first action)

Before designing anything, get the corpus and database in place and inventory what's there.

- [ ] **Corpus and database are fetched via `scripts/fetch_data_sources.py`.** The script tries this repo's `data-mirror-v1` GitHub release first (durable for this repo's lifetime) and falls back to the upstream langchain-ai GCS bucket, verifying SHA-256 against pinned constants before writing. It's idempotent — skip the download if the local hashes match.
  - `python scripts/fetch_data_sources.py`
  - Sources: `corpus/swiss_faq.md` (35,061 B) and `data/travel.sqlite` (114,442,240 B — upstream is `travel2.sqlite`, normalised). Pinned hashes are in the script's `SOURCES` constant. Mirror provenance is recorded in the release notes; see issue #19.
- [ ] For tutorial context, see the current LangGraph docs at `https://docs.langchain.com/oss/python/langgraph/overview`. The original customer-support notebook path (`langchain-ai/langgraph` → `docs/docs/tutorials/customer-support/customer-support.ipynb`) was deprecated when the docs were restructured and now returns 404; the original notebook is preserved in git history at that path.
- [ ] Read `swiss_faq.md` to inventory the actual policy classes present (count them, note vocabulary). This affects task design (Phase 2 Step 4) and implementation choices for Naive RAG, Grep search, and Hybrid RAG.
- [ ] Inspect `travel.sqlite` schema (tables, columns, row counts, sample data)
- [ ] Document findings in a brief `notebooks/00_corpus_inventory.ipynb` — what we're working with. Record the source URLs verbatim so future reproducers have a fixed starting point.

This step exists because we've been treating the LangGraph tutorial as a placeholder. Extracting the actual artifacts surfaces design constraints we haven't anticipated and confirms what we're actually measuring against.

If both the `data-mirror-v1` release and the upstream GCS bucket become unavailable, the canonical source is the LangGraph tutorial notebook's `db.py` setup cell (preserved in git history at the deprecated path above), which encodes both the URL pattern and the underlying SQL fallback.

### Step 1: Project setup

- [ ] Create Python virtual environment
- [ ] Initialize `requirements.txt` with: `anthropic`, `chromadb` (or `faiss-cpu`), `sentence-transformers` or `FlagEmbedding` (for BGE-M3), `rank-bm25`, `python-dotenv`, `tabulate`, `pytest` (for sanity tests)
- [ ] **Do not include `tiktoken`** — it's OpenAI's tokenizer and will produce wrong counts for Anthropic models
- [ ] **Do not include `openai`** — the project is scoped to Anthropic for inference and self-hosted BGE-M3 for embeddings; no third-party embedding API
- [ ] Set up `.env.example` with `ANTHROPIC_API_KEY` placeholder only (no OPENAI_API_KEY needed)
- [ ] Verify corpus and database loaded correctly
- [ ] Pre-download BGE-M3 model weights to avoid first-run delay during measurement: `python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-m3')"` (or equivalent via FlagEmbedding) — caches the model to disk for offline use
- [ ] **Pin specific versions in `requirements.txt`** (e.g., `anthropic==X.Y.Z`). After install, run `pip freeze > requirements.lock.txt` and commit. Reproducibility (per METHODOLOGY's expected-variance claims) requires pinned versions, not version ranges. BGE-M3 download integrity relies on HuggingFace TLS — accepted risk for v1, would need hash verification for production (see HANDOVER §"Security and governance scope")

### Step 2: Token counting infrastructure

This is the load-bearing measurement code. Build it before any architecture, because all architectures depend on it.

- [ ] Implement `measurement/tokens.py` with:
  - `count_tokens(text: str) -> int` using Anthropic's `client.beta.messages.count_tokens()` API
  - `decompose_request(system, messages, tools) -> dict` returning the 6-category breakdown (the original Silicon Data five plus `agent_intermediate` for multi-turn loops — see METHODOLOGY §"Multi-turn extension")
  - `record_run(architecture, task_id, decomposition, api_usage, response) -> dict` for structured logging
- [ ] Unit test the decomposition: sum of categories should equal API-reported `input_tokens` within 5%

### Step 3: Runner skeleton

- [ ] Implement `measurement/runner.py` with:
  - `--architectures <list>` argument (e.g., `naive_rag,cached_rag,grep_search,hybrid_rag`)
  - `--tasks <path>` argument
  - `--runs <int>` argument (default 3)
  - Output to `measurement/results/architecture_<id>.json`
  - `--report` flag that generates `measurement/results/comparison.md` from the JSON files
- [ ] Add a `--smoke` mode that runs a single trivial task to verify wiring

### Phase 1 deliverable

A repo where `pip install -r requirements.txt && python measurement/runner.py --smoke` runs end-to-end without errors, and the token decomposition is correct on the smoke test.

---

## Phase 2 — Core comparison (Naive RAG, Grep search, Hybrid RAG)

**Goal:** Three architectures implemented, full task set run, adversarial review complete, comparison report populated.

**Estimated effort:** 2 days

### Step 4: Write the task set

- [ ] Write ~17 tasks in `measurement/tasks.jsonl` per the schema in `measurement/tasks.md`
- [ ] Distribution: 3 pure policy, 3 pure transactional, 8 mixed, 3 edge case
- [ ] **Critical:** Use customer-style phrasing, not architect-style category names. A task that says "rebooking policy" maps too cleanly to architecture-friendly tool names. See METHODOLOGY Check 2.
- [ ] Manually answer each task yourself to confirm it's well-defined
- [ ] Document expected_citations for each task

### Step 5: Naive RAG

Follow `architectures/naive_rag/README.md` design choices:
- [ ] Chunk `corpus/swiss_faq.md` (Support Content team's process, conceptually)
- [ ] Set up vector store (Chroma or FAISS, in `architectures/naive_rag/vector_store/`)
- [ ] Implement Support Content's tool: `vector_search(query, k=4)` returning chunks
- [ ] Implement Booking Systems' tools: `get_booking_status`, `search_flights`, etc.
- [ ] Implement system prompt (~500 tokens, comparable in care to other architectures)
- [ ] Implement agent loop in `architectures/naive_rag/agent.py`
- [ ] Smoke test with 2-3 tasks

### Step 6: Grep search

Follow `architectures/grep_search/README.md` design choices:
- [ ] Implement Support Content's tool: `grep_corpus(keywords, max_results=10)` — case-insensitive, returns matching lines with surrounding context
- [ ] Reuse Booking Systems' tools from Naive RAG (they're identical across architectures)
- [ ] Implement system prompt — instruct agent to pick search keywords and call grep
- [ ] Implement agent loop
- [ ] Smoke test with 2-3 tasks

### Step 7: Hybrid RAG

Follow `architectures/hybrid_rag/README.md` design choices:
- [ ] Implement Support Content's tool: `hybrid_search(query, k=6)` combining BM25 + vector retrieval with reranking
- [ ] Reuse Booking Systems' tools
- [ ] Implement system prompt
- [ ] Implement agent loop
- [ ] Smoke test with 2-3 tasks

### Step 8: Full run

- [ ] Run `python measurement/runner.py --architectures naive_rag,grep_search,hybrid_rag --runs 3`
- [ ] Inspect results for sanity (no architecture should have 0% success; tokens should be in expected order of magnitude)
- [ ] Fix any bugs the run surfaces

### Step 9: LLM-as-judge scoring

- [ ] Implement scoring in runner using `claude-opus-4-7` as judge against per-task rubrics
- [ ] Manually review a 10% random sample of judgments
- [ ] Adjust rubric prompts if judge bias is detected

### Step 10: Adversarial review for Phase 2 (do not skip)

Per METHODOLOGY §"Pre-publication adversarial review."

- [ ] **Check 1 — Equal tuning effort.** Naive RAG's top-K tuned? Hybrid RAG's hybrid weighting tuned? Grep search's grep polished? All system prompts equivalently sized? Document in `comparison.md` tuning effort table.
- [ ] **Check 2 — Task set neutrality.** Re-read every task. Do phrasings favor any architecture? Document findings.
- [ ] **Check 3 — Counterfactual reasoning.** For each headline finding, articulate what would have to be true for it to reverse. Fill in counterfactual section.
- [ ] **Steel-man the null.** Write out the strongest "this shows nothing meaningful" argument. Address it.
- [ ] **Confidence statement.** State net confidence (high/medium/low/preliminary) and scope of validity.

### Phase 2 deliverable

Three architectures measured, comparison report populated with real numbers, adversarial review complete. Repo is shippable as-is at this point — Phase 3 and 4 add to it but aren't required for v1 to be useful.

---

## Phase 3 — Caching variant (Cached RAG)

**Goal:** Measure Naive RAG with Anthropic prompt caching enabled. Quantify how much caching collapses Naive RAG's cost.

**Estimated effort:** 0.5 day

### Handover from v1 ship (2026-06-04) — read before starting

**Starting state:** v1 shipped at tag `measurement-v1`. Three architectures measured (Naive RAG, Grep search, Hybrid RAG). Cost ordering settled HIGH-confidence. Quality numbers LOW-confidence pending Finding C3 fix (v2 series, queued separately in `ROADMAP.md`). Phase 3 is sequenced **ahead of** the v2 quality re-measurement series because the v1 headline goal is *token cost*, and caching is the obvious cost optimization on the cheapest measured architecture — quantifying it answers the headline question directly. The v2 quality re-measurement settles a calibration question that does not affect the cost story; it stays scheduled but waits.

**Read first, in order:**
1. This Phase 3 spec below (Step 11–12).
2. `measurement/results/comparison.md` §"Scope of measurement: the cache matrix" — the 4-of-6 cells v1 fills, and which v2 cells caching opens up.
3. `architectures/naive_rag/README.md` — what Cached RAG extends.
4. `METHODOLOGY.md` §"Model and configuration" — caching is enabled for Cached RAG only; disabled for the v1 measured three.

**Key design choice for Step 11 (decide before implementing):**
- **Option A — Copy `architectures/naive_rag/` to `architectures/cached_rag/`.** Methodology framing favors this: Cached RAG is a separately-named architecture in METHODOLOGY and `comparison.md`, not a config flag. Code duplication is the cost; clean divergence on caching-specific tuning is the benefit.
- **Option B — Add a `--cached` flag to `architectures/naive_rag/agent.py`.** One code path; branching logic at run time. Lighter footprint.
- **Recommendation: Option A.** Aligns with the methodology framing and keeps the v2 quality re-judging cleaner (the judge sees `architecture: cached_rag` as a distinct identity).

**Sweep protocol — the consequential decision for Step 12:**

METHODOLOGY §"Run protocol" requires *all measured architectures execute the full task set in a single alternating run* to control time-of-day variance. Phase 3 has two paths:
- **Option X (recommended) — full re-sweep of all four architectures (Naive RAG, Cached RAG, Grep search, Hybrid RAG) in a new alternating run.** Protocol-clean; produces a fresh dated dir with 204 dispatches (51 per arch × 4 archs). Drops `runs/2026-06-04-phase2-step8b/` as the v1 frozen reference (it stays as the v1 historical record; the new sweep is the v1+Phase 3 canonical). Estimated cost: ~$9 (agent re-sweep ~$4 + judge ~$5).
- **Option Y — Cached RAG alone (51 dispatches) appended to the v1 sweep's analysis.** Breaks the alternating protocol; defensible only if the time-of-day variance is documented as a known scope limit on the Cached RAG measurement. Cheaper (~$4 total).

**Recommendation: Option X.** Methodology-clean, and at the same scale of paid spend that v1 itself cost (~$6.50 judge + agent sweep). Option Y saves ~$5 at the cost of a methodology asterisk on the headline finding.

**Process gotchas (carried forward from v1):**
- `[[feedback-runner-report-clobbers-comparison]]` — do NOT run `python -m measurement.runner --report` until §11 template renderer ships (issue #42). Hand-edit `comparison.md`.
- Frozen artifact rule: `architecture_*.json` and `judgments_*.json` under existing `runs/*/` dirs are read-only. Phase 3 output lands in a new dated dir.
- `[[reference-anthropic-console]]` — API key disabled by default; re-enable before paid runs, disable after.
- Finding C3 (judge architecture-label leak) is NOT fixed yet. Cached RAG's quality numbers will inherit the same calibration limit as v1; this is acceptable because Phase 3's headline is cost, not quality. The v2 series remains the canonical quality settlement work.

**Hypothesis worth pre-registering** (so the article narrative has a frame either way):

> Anthropic's prompt caching collapses cached-prefix input-token cost by ~90% on the cached portion (cache reads priced at ~$0.30/M vs $3/M list for Sonnet 4.6). Naive RAG's measured ① system prompt (1,693 mean) + ④ tool overhead (4,746 mean) — ~6,400 tokens — is the natural cache target. If retrieved chunks are stable for a non-trivial fraction of queries, ② retrieved_context (5,041 mean) joins the cacheable prefix. Expected outcome: Cached RAG median input cost drops 50–80% vs Naive RAG, depending on cache hit rate. If the drop is <30%, that's a methodology finding about prefix variability under realistic agent loops; publishable either way.

**Exit criteria for Phase 3:**
- Cached RAG measured with the chosen sweep protocol (Option X recommended).
- `comparison.md` headline + per-class + decomposition tables populated for the Cached RAG column (currently marked "Phase 3 — not measured").
- §"Confidence and known biases" Check 1 row for Cached RAG: confirm caching is configured to maximize stable-prefix reuse (not just enabled with defaults).
- New tag `cached-rag-v1` on the Phase 3 ship commit, parallel to `measurement-v1`. Tag annotation includes the sweep dir provenance.
- `README.md` headline table updated; `HANDOVER.md` §6 + §9 amended; `ROADMAP.md` decision log entry added.

**v2 quality re-measurement series stays queued** in `ROADMAP.md` §"Quality re-measurement series." After Phase 3 ships, v2 is the natural next move — it would re-judge BOTH the v1 sweep AND the Phase 3 Cached RAG sweep with the blinded judge prompt, settling the architecture-quality story once.

### Step 11: Implement Cached RAG

- [ ] Copy `architectures/naive_rag/` to `architectures/naive_rag_cached/` (or add a `--cached` flag to the existing Naive RAG agent)
- [ ] Enable prompt caching on the system prompt (always cacheable)
- [ ] Enable caching on retrieved chunks when stable (this requires thinking about what "stable" means — chunks retrieved with same query are cacheable; different queries are not)
- [ ] Document the caching configuration explicitly in the architecture README

### Step 12: Run and integrate

- [ ] Run Cached RAG on the full task set, 3 runs
- [ ] Add Cached RAG column to comparison report
- [ ] Update adversarial review to cover Cached RAG (Check 1: is caching configured to maximize stable-prefix reuse?)

### Phase 3 deliverable

Four architectures measured. Comparison report shows caching effect quantified. Article can now honestly claim "Naive RAG vs. Grep search, but here's what Naive RAG looks like with the obvious optimization enabled."

---

## Phase 4 — Deferred architectures (Bounded tools, Stuffed corpus) — optional, not v1

Per ROADMAP, Bounded tools and Stuffed corpus are deferred. Build only if Phase 2-3 results suggest they'd add to the picture, or if reviewers push back.

- [ ] **Bounded tools** — ~1 day if added
- [ ] **Stuffed corpus** — ~0.5 day if added

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

- **Chunk size for Naive RAG and Hybrid RAG.** The README suggests 300-500 tokens. Actual best value depends on corpus structure (discovered in Phase 1).
- **Top-K for Naive RAG.** Default is 4. Tune based on Phase 2 smoke tests.
- **Hybrid weighting for Hybrid RAG.** BM25 vs vector weighting needs tuning per corpus.
- **Reranking model for Hybrid RAG.** Cross-encoder choice affects cost and quality.
- **Grep result truncation for Grep search.** Too short loses information; too long wastes tokens. Tune in Phase 2.
- **Judge model behavior.** If `claude-opus-4-7` systematically rates one architecture higher despite manual review disagreeing, document and consider alternative judges.

## Out of scope for v1

These are explicitly deferred (also in ROADMAP):

- Multi-turn dialogue (single-turn only)
- Multiple agent models (single-model comparison)
- Bounded tools, Stuffed corpus, Fine-tuned, Deterministic routing, No-LLM (mentioned in article, not measured)
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
