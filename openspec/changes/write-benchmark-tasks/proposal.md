# Write benchmark task set

## Why

Phase 2 Step 4 of `BUILD_PLAN.md` requires `measurement/tasks.jsonl` — the 17 frozen tasks every architecture is measured against. No task set exists yet; without it, Phase 2's headline comparison cannot run. Once any task ID is published, it is permanently frozen (per architectural invariants), so getting this right on the first pass matters more than getting it done fast.

The seed task examples in `measurement/tasks.md` were drafted before corpus inventory and assume policy text (rebooking, baggage, frequent flyer) that mostly isn't in `corpus/swiss_faq.md`. The actual corpus is payments/billing/invoicing-heavy. Tasks must be re-grounded in what the corpus actually answers, or the benchmark measures fluency on absent policies rather than retrieval against present ones.

## What Changes

- Add a **task schema validator** (`tests/test_tasks.py`) that runs in CI and enforces: JSON-schema conformance, ID uniqueness and pattern, class distribution (3 POL / 3 TXN / 8 MIX / 3 EDGE), controlled vocabulary for `policy_classes_invoked`, Check 2 architect-phrase blacklist on `user_message`, and referential integrity of `book_ref` / `flight_no` mentions against `data/travel.sqlite`. Validator exists before any task is written.
- Add a **controlled vocabulary file** (`measurement/policy_classes.json`) listing the H2 sections actually present in `corpus/swiss_faq.md`. Separate file so future corpus changes don't require validator edits.
- Add a **booking fixtures file** (`measurement/task_fixtures.json`) recording the real `book_ref` / `flight_no` / `ticket_no` values sampled from `data/travel.sqlite`, with a one-time sampling script so the choice is reproducible.
- Write **`measurement/tasks.jsonl`** in class-by-class drafting order with user review between classes. Each class commits separately so regressions are bisectable.
- Write **`measurement/tasks_expected_answers.md`** — a separate human-readable document recording the manually-derived expected answer for each task, with corpus quotes. Not in `tasks.jsonl` (which stays frozen-schema); lives alongside as the answer key.
- **Decide and document the corpus-quirk question**: `swiss_faq.md` contains an injected-looking phone number ("877-5O7-7341") in its last H2 section. Decide whether to (a) treat it as known contamination noted in METHODOLOGY only, or (b) add an EDGE task specifically testing whether agents surface this number as authoritative. Decision recorded in `design.md`.
- Update `measurement/tasks.md` to deprecate the aspirational seed examples (clarify they were pre-inventory) and link to the actual frozen task set.

## Capabilities

### New Capabilities

- `benchmark-tasks`: the frozen task set, its schema, the controlled policy-class vocabulary, the booking fixtures, and the validator that gates changes to it. Captures the rules that govern task authoring (Check 2 phrasing, ID stability, distribution, referential integrity) as enforceable requirements rather than prose conventions.

### Modified Capabilities

None. No existing specs in `openspec/specs/`.

## Impact

- **New files:** `tests/test_tasks.py`, `measurement/tasks.jsonl`, `measurement/tasks_expected_answers.md`, `measurement/policy_classes.json`, `measurement/task_fixtures.json`, `measurement/scripts/sample_fixtures.py` (one-time use, kept for reproducibility).
- **Modified files:** `measurement/tasks.md` (deprecate seeds, link to frozen set), `requirements.txt` (add `jsonschema` or `pydantic` if not already pinned), possibly `.github/workflows/*` if CI exists (validator should run).
- **Depends on:** `corpus/swiss_faq.md` and `data/travel.sqlite` being present (Phase 1 Step 0 — already done).
- **Blocks:** Phase 2 Steps 5-10 (Naive RAG/C/E full runs, LLM-as-judge scoring, adversarial review) — all consume `tasks.jsonl`.
- **Frozen-on-merge constraint:** every `task_id` shipped in this change becomes immutable. Future edits require new IDs and a deprecation note. The validator is the safeguard.
