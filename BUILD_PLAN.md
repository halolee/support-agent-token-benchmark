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

**Step 11 implementation shape — DECIDED 2026-06-04: Option A (clean separation).**
- **Option A (chosen) — Copy `architectures/naive_rag/` to `architectures/cached_rag/`.** Methodology framing favors this: Cached RAG is a separately-named architecture in METHODOLOGY and `comparison.md`, not a config flag. Code duplication is the cost; clean divergence on caching-specific tuning is the benefit.
- Option B (rejected) — `--cached` flag on the existing Naive RAG agent. Would conflate two architectures behind one identity in the judge and analysis paths.

**Step 12 sweep protocol — DECIDED 2026-06-04: Option Y (cost-only, no re-judge).**
- **Option Y (chosen) — Cached RAG alone (51 dispatches), append-only, agent-side cost measurement only.** No judge re-run. Quality is asserted equivalent to Naive RAG by construction: prompt caching changes input-token *pricing*, not the tokens the model sees, and Sonnet 4.6 at `temperature=0.0` is deterministic on identical inputs. A 3-task spot-check (bit-identical responses to Naive RAG) is sufficient to validate the equivalence claim before reporting cost numbers. Estimated cost: ~$1.50 (agent sweep only; no $5 judge sweep).
- Option X (rejected for this phase) — full 4-arch re-sweep with re-judging. Saves the methodology asterisk on the alternating-runs protocol, but the v2 quality re-measurement series is going to re-sweep with a *blinded* judge anyway (Finding C3). Doing a non-blinded re-judge now would burn ~$5 and produce numbers that get superseded by v2. Deferred to v2 when C1–C3 loose ends are tightened — the re-sweep then carries both the caching variant AND the blinded judge in a single methodology-clean run.

**Implication to document in `comparison.md`:** Phase 3 reports Cached RAG cost columns and explicitly carries forward Naive RAG's quality numbers (with a footnote: "Quality assumed equivalent to Naive RAG; bit-identical-response spot-check confirms determinism. Re-judging deferred to v2 quality series."). The cache matrix table notes Cached RAG quality as `= Naive RAG (by construction)` rather than as an independent measurement.

**Process gotchas (carried forward from v1):**
- `[[feedback-runner-report-clobbers-comparison]]` — do NOT run `python -m measurement.runner --report` until §11 template renderer ships (issue #42). Hand-edit `comparison.md`.
- Frozen artifact rule: `architecture_*.json` and `judgments_*.json` under existing `runs/*/` dirs are read-only. Phase 3 output lands in a new dated dir.
- `[[reference-anthropic-console]]` — API key disabled by default; re-enable before paid runs, disable after.
- Finding C3 (judge architecture-label leak) is NOT fixed yet. Cached RAG's quality numbers will inherit the same calibration limit as v1; this is acceptable because Phase 3's headline is cost, not quality. The v2 series remains the canonical quality settlement work.

**Hypothesis worth pre-registering** (so the article narrative has a frame either way):

> Anthropic's prompt caching collapses cached-prefix input-token cost by ~90% on the cached portion (cache reads priced at ~$0.30/M vs $3/M list for Sonnet 4.6). Naive RAG's measured ① system prompt (1,693 mean) + ④ tool overhead (4,746 mean) — ~6,400 tokens — is the natural cache target. If retrieved chunks are stable for a non-trivial fraction of queries, ② retrieved_context (5,041 mean) joins the cacheable prefix. Expected outcome: Cached RAG median input cost drops 50–80% vs Naive RAG, depending on cache hit rate. If the drop is <30%, that's a methodology finding about prefix variability under realistic agent loops; publishable either way.

**Exit criteria for Phase 3:**
- Cached RAG cost measured via Option Y (append-only, 51 dispatches, no re-judge).
- Caching-fires spot-check on ≥3 tasks: `cache_read_input_tokens > 0` on turn 2+, tool-call sequence matches Naive RAG, response semantically equivalent. (Not bit-identical — temp=0 server-side FP non-determinism makes byte-identical an unreliable bar; v1's 3-runs-and-median protocol exists for the same reason.)
- `comparison.md` headline + per-class + decomposition tables populated for the Cached RAG cost columns; quality columns carry Naive RAG numbers with a `= Naive RAG (by construction)` footnote.
- §"Confidence and known biases" Check 1 row for Cached RAG: confirm caching is configured to maximize stable-prefix reuse (not just enabled with defaults).
- New tag `cached-rag-v1` on the Phase 3 ship commit, parallel to `measurement-v1`. Tag annotation includes the sweep dir provenance and notes "cost-only; quality carried over from Naive RAG."
- `README.md` headline table updated; `HANDOVER.md` §6 + §9 amended; `ROADMAP.md` decision log entry added (record both the Y choice and the deferred X re-sweep).

**v2 quality re-measurement series stays queued** in `ROADMAP.md` §"Quality re-measurement series." After Phase 3 ships, v2 is the natural next move — it would re-sweep with the blinded judge across all four architectures (Naive RAG, Cached RAG, Grep search, Hybrid RAG) in a single alternating run, settling both the architecture-quality story AND the methodology-clean protocol for Cached RAG in one pass. That is where the deferred Option X re-sweep lands.

### Step 11: Implement Cached RAG (Option A — clean separation)

- [ ] Copy `architectures/naive_rag/` to `architectures/cached_rag/` (full directory, including README, agent.py, system prompt, vector_store path)
- [ ] Enable prompt caching on the system prompt (always cacheable — stable across all 51 tasks)
- [ ] Enable caching on the tool definitions block (stable; ~4,746 mean tokens of overhead in v1 → high-leverage target)
- [ ] Evaluate caching on retrieved chunks: chunks change per query, so the standard prefix-caching model does *not* cache them. Document this in the README as "retrieved_context is NOT cached; only the stable system prompt + tool definitions prefix is."
- [ ] Update `architectures/cached_rag/README.md` to describe (a) what was copied from Naive RAG, (b) the caching configuration, (c) what is and isn't cached and why
- [ ] Register `cached_rag` in `measurement/runner.py`'s architecture dispatch
- [ ] Caching-fires spot-check (3 tasks, one each EASY/MID/EDGE) — proves caching is wired correctly, NOT bit-identical equivalence (agent runs at temp=0.0 but server-side FP non-determinism means temp=0 is close-but-not-byte-identical run-to-run; that's why v1 uses 3 runs + median). Pass criteria:
   1. `cache_read_input_tokens > 0` on turn 2+ (caching fired)
   2. Tool-call sequence matches Naive RAG's sequence on the same task (tool selection is much more stable than free-text output)
   3. Response text reads as semantically equivalent to Naive RAG's response on the same task (sanity check by human review; rigorous quality settlement is v2's job)
  If any of these fail, investigate before Step 12.

### Step 12: Run and integrate (Option Y — cost-only, append-only)

- [ ] Run Cached RAG on the full 51-task set, 3 runs (153 dispatches total) — single architecture, no alternation
- [ ] Output lands in a new dated run dir (e.g., `runs/2026-MM-DD-phase3-step12-cached-only/`); v1 frozen dir is untouched
- [ ] Skip judge sweep — quality columns inherit Naive RAG numbers
- [ ] Add Cached RAG cost columns to `comparison.md` headline + per-class + decomposition tables; quality cells get `= Naive RAG` footnote
- [ ] Update adversarial review to cover Cached RAG (Check 1: is caching configured to maximize stable-prefix reuse?)
- [ ] Document the Option Y protocol asterisk in §"Confidence and known biases": single-architecture sweep, no alternation; time-of-day variance is a known limit on the Cached RAG cost numbers but does not affect the Naive RAG↔Cached RAG cost *delta* if it's large (>>variance)

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
