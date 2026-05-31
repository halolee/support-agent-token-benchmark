## Context

`measurement/tasks.jsonl` is the frozen task set every architecture is measured against. Once published, task IDs become immutable — bad tasks contaminate every future comparison, and fixing them requires deprecation paperwork, not edits. The seed examples in `measurement/tasks.md` were drafted before corpus inventory and reference policy text (rebooking, baggage, frequent flyer) that mostly doesn't exist in `corpus/swiss_faq.md`, which is instead payments/billing/invoicing-heavy. Two further constraints shape the design: (1) METHODOLOGY Check 2 forbids architect-style phrasing that gives bounded-tool or grep architectures unearned signal; (2) the validator is the only thing that mechanically enforces these rules after merge — humans drift, lint doesn't.

Stakeholders: this benchmark is the headline artifact of the project. The task set's quality is the upper bound on every architectural comparison's credibility.

## Goals / Non-Goals

**Goals:**
- The task set is grounded in policy text and booking rows that actually exist (no phantom tasks).
- The validator catches Check 2 violations, schema drift, ID collisions, and phantom bookings *before* a task is merged — humans don't have to remember the rules.
- Task drafting is incremental (class-by-class commits) so a bad task can be bisected and reverted without touching the others.
- The validator and schema are modular: adding a new task is one appended line; adding a new policy class is one entry in `policy_classes.json`; tightening Check 2 is one entry in `check2_blacklist.json`. Validator code stays untouched.
- The expected-answers document is a maintainable answer key for adjudicating LLM-as-judge disputes — it's not the agent's input, it's the human's reference.

**Non-Goals:**
- Building the LLM-as-judge scorer (Phase 2 Step 9).
- Running the architectures against the task set (Phase 2 Step 8).
- Auto-generating tasks (the small-N hand-crafted nature is the point; see `measurement/tasks.md` "small precisely so manual validation is tractable").
- Multi-turn dialogue tasks (out of scope for v1 per `BUILD_PLAN.md` "Out of scope").

## Decisions

### Decision 1: Validator before tasks (TDD foundation)

The validator (`tests/test_tasks.py` + `measurement/scripts/validate_tasks.py`) is written and merged *before* any task is drafted, against a minimal `tasks.jsonl` containing only a fixture line. This forces the schema to be concrete before authoring, and means every subsequent task draft is immediately checkable.

**Alternative considered:** Write tasks first, validator after. **Rejected** because Check 2 violations are easy to miss by eye — without the validator, the first round of tasks is likely to need rewrites after the validator lands. TDD-style ordering avoids that wasted work.

### Decision 2: Pydantic over jsonschema for the validator

The validator uses `pydantic` v2 for schema enforcement. Pydantic gives typed parsing, custom validators (we need per-field business rules like Check 2 phrasing and prefix↔class agreement), and good error messages that point at line numbers. `jsonschema` is more portable across languages but its custom-rule story is uglier and the project is Python-only.

**Alternative considered:** `jsonschema` with custom format checkers. **Rejected** for ergonomics — Check 2 needs case-insensitive substring matching against a configurable blacklist; doing that as a `format` rule is awkward.

**Alternative considered:** Hand-rolled validation. **Rejected** because the rules are non-trivial (8 separate requirements with scenarios) and the validator is load-bearing; a typed library reduces the chance of subtle bugs that silently let bad tasks through.

### Decision 3: Class-by-class drafting with commits per class

Drafting order: validator → fixtures → POL (3) → TXN (3) → MIX (8) → EDGE (3) → expected answers → final Check 2 pass. Each class is a separate commit. This gives:
- Bisectability if a class introduces a regression.
- User review checkpoints between classes (4 review gates vs. 1 mega-review).
- Forced consideration of class-specific rules (transactional tasks all need `booking_data_required: true`; mixing them up with edge tasks would lose that signal).

**Alternative considered:** Single commit with all 17 tasks. **Rejected** — too large to review carefully, and a single Check 2 violation in any task fails the whole batch.

### Decision 4: Corpus quirk handled via an EDGE task (Option b)

The `swiss_faq.md` "How to Cancel a Swiss Air Flight: 877-5O7-7341 Step-by-Step Guide" section contains a phone number that looks like it was injected for SEO/scam purposes (the `O` instead of `0` in "5O7" is a known evasion pattern). Two options were considered:

- **(a) Note as known contamination, exclude from tasks.** Cleaner comparison numbers, but ducks a real production failure mode.
- **(b) Add an EDGE task that asks something that retrieval might map to this section, and judge whether the agent surfaces the number as authoritative.** Surfaces the asymmetric risk: grep is more likely to return this text verbatim (the section is short and keyword-dense); RAG may rank it lower because of semantic dissimilarity to other policy sections; reranking in E may further demote it. This is the *honest* test — production corpora have noise, and an architecture that confidently regurgitates injected text is a safety failure worth measuring.

**Chosen: (b).** The EDGE task is included with rubric criteria penalizing fabrication / endorsement of the suspect number. This is documented prominently in `tasks_expected_answers.md` so future maintainers understand the deliberate adversarial intent.

**Risk of (b):** If all four architectures handle it identically (all pass or all fail), the task adds noise without signal. Mitigation: this is acceptable — even a null result on this task tells us something about the architectures' robustness floor.

### Decision 5: Fixtures sampled once, recorded in JSON, never regenerated

`measurement/scripts/sample_fixtures.py` runs once, samples specific `book_ref`/`flight_no`/`ticket_no` values from `data/travel.sqlite`, and writes them to `measurement/task_fixtures.json` with rationale strings (e.g., "selected as a multi-segment booking for MIX-005"). The script is committed for reproducibility but not re-run in CI — fixtures are frozen the same way task IDs are.

**Alternative considered:** Random sampling at validator runtime. **Rejected** — non-determinism in a frozen benchmark is poison. We want the same `book_ref` to mean the same thing every run.

### Decision 6: Expected answers live in Markdown, not JSON

`measurement/tasks_expected_answers.md` is human-readable Markdown with one section per task ID. The validator only enforces ID parity (every `tasks.jsonl` ID has a matching `## TASK-ID` heading in the doc), not content. This keeps the answer key easy for humans to maintain and read during adjudication, while still gating completeness mechanically.

**Alternative considered:** Embed expected answers in `tasks.jsonl`. **Rejected** because (a) it would inflate the file and make Check 2 phrasing review harder, and (b) `tasks.jsonl` is what the runner reads; mixing the answer key in invites accidental leakage to agents.

### Decision 7: Re-grounded class composition

Given the corpus is payments/billing-heavy, the candidate task topics shift from the aspirational seeds in `measurement/tasks.md`:

- **POL (3):** invoice timing, credit card surcharges/security, pay-per-invoice eligibility — all directly answerable from the FAQ.
- **TXN (3):** booking lookup (total amount paid), flight status, ticket fare class — straightforward sqlite reads.
- **MIX (8):** invoice request for a cancelled booking; payment-method clarification on a specific booking; European fare concept question tied to a specific flight; pay-per-invoice eligibility for a customer's booking; credit card issue on a specific booking; refund question for a cancelled booking; rebooking eligibility (limited coverage in corpus — use cautiously); invoice ordering for past trip.
- **EDGE (3):** the corpus-quirk phone-number task (decision 4); a question ambiguous between two FAQ sections (e.g., card security vs. payment FAQ); a question whose answer depends on `fare_conditions` on a specific ticket the customer doesn't explicitly mention.

Final tasks may shift during drafting — these are candidates, not committed IDs. Final list lands during the apply phase with user review per class.

### Decision 8: EDGE class reframed as three failure-mode probes (amends Decision 7 EDGE candidates)

Decision 7 listed three EDGE candidates by topic. On review, the third candidate ("fare_conditions missing-context") primarily measured agent-loop completeness — did the agent call `get_ticket` before answering? — which is architecture-agnostic and a weak discriminator for an A vs C vs E comparison. The EDGE class is reorganized around three distinct failure-mode probes, each chosen to discriminate across retrieval architectures asymmetrically:

- **EDGE-001 — Suspect content present in source.** Answer-shaped text exists in the corpus but its provenance is unverifiable (the `877-5O7-7341` section). Tests whether the agent endorses suspect content as authoritative. Per Decision 4, this is included regardless of whether the number is real, abandoned, or planted — the measured failure mode is "regurgitates without skepticism," not "falls for injection." **Discrimination across architectures:** grep most likely to surface verbatim; RAG ranks by semantic similarity to the user query; rerank may demote.

- **EDGE-002 — Answer requires synthesis across multiple sections.** Answer cannot be derived from a single FAQ section alone; the agent must retrieve and combine partial answers from two or more sections (e.g., a payment question whose full answer touches Credit Cards + Card Security + Payment FAQ). **Framing chosen: synthesis, not disambiguation.** Disambiguation (one section is correct, the other is a decoy) is faster to test and produces cleaner pass/fail signal, but it is a toy scenario: it assumes user questions arrive pre-classified into FAQ categories. In practice, FAQ section boundaries are early-stage business statistics — they reflect the most common questions when the corpus was authored, and they drift as the product, customer base, and edge cases evolve. Synthesis tests system robustness to that drift: when a real user's question crosses the implicit FAQ taxonomy, does the agent retrieve enough sources and combine them coherently, or does it lock onto one and miss the rest. **Discrimination across architectures:** grep returns multiple hits with no ranking signal — relies on the model to combine; RAG top-k may miss a secondary section if it ranks below threshold; rerank can correct (promote a complementary section) or compound (concentrate on the top match and demote the partial-answer sources).

- **EDGE-003 — Out-of-scope refusal.** Answer is not present in the corpus or sqlite (e.g., a customer asks about a service Swiss doesn't offer, or a policy area the corpus doesn't cover). Tests whether the agent declines clearly versus fabricates from low-similarity retrieval. **Discrimination across architectures:** grep returns empty (clean negative signal); RAG returns top-k regardless of similarity (highest fabrication risk); rerank may filter below-threshold hits. This is the symmetric pair to EDGE-001 — EDGE-001 measures "endorses suspect *present* content," EDGE-003 measures "fabricates from *absent* content."

**Supersedes:** The "fare_conditions missing-context" candidate in Decision 7's EDGE list is dropped. The "ambiguous between card security vs. payment FAQ" candidate is folded into EDGE-002 pending the disambiguation-vs-synthesis resolution.

**Alternative considered:** Keep "conflicting sources" (corpus says X, sqlite booking exception says Y) as EDGE-003. **Rejected** for the same reason as the dropped candidate — it primarily tests reconciliation logic in the agent loop, not retrieval architecture.

**Alternative considered:** Keep "adversarial customer claim" (customer asserts a fact contradicted by sqlite) as EDGE-003. **Rejected** as architecture-agnostic; it measures the agent's verify-before-answering discipline regardless of retrieval mechanism.

## Risks / Trade-offs

- **Risk:** Validator is too strict and slows authoring. → Mitigation: standalone `--fast` mode runs in <1s; rules are configurable via JSON files so loosening doesn't require code changes.

- **Risk:** Check 2 blacklist becomes a false-positive trap (e.g., a legitimate customer phrasing happens to contain "policy"). → Mitigation: blacklist starts conservative (only architect-shaped phrases like "your policy on X"); additions require evidence of an architecture-favoring phrasing.

- **Risk:** Re-grounded tasks deviate so far from the seeds that someone reading `measurement/tasks.md` is confused about the actual benchmark. → Mitigation: update `tasks.md` to mark the seed examples as pre-inventory and link to the frozen `tasks.jsonl` as the authoritative set.

- **Risk:** The corpus-quirk EDGE task is interpreted as gimmicky rather than as honest adversarial testing. → Mitigation: document the rationale in both `design.md` (this file), `tasks_expected_answers.md`, and `METHODOLOGY.md`'s adversarial review section. Frame it as testing the safety floor, not as a trick.

- **Trade-off:** Pydantic adds a runtime dependency. Project already includes scientific Python (`sentence-transformers`, `chromadb`) so the marginal cost is negligible; ergonomics win is significant.

- **Trade-off:** Class-by-class commits mean 4-6 PR review cycles instead of 1. Worth it: each cycle is small, focused, and catches issues before they're baked into the immutable ID set.

## Migration Plan

This is a net-new change — no existing tasks to migrate. Steps:

1. Add validator + fixtures + empty `tasks.jsonl` (fixture-only). Commit. CI green on empty validator pass.
2. Append POL tasks. Commit. Review. Iterate if validator flags issues.
3. Append TXN tasks. Commit. Review.
4. Append MIX tasks. Commit. Review (largest review; expect iteration).
5. Append EDGE tasks. Commit. Review.
6. Write `tasks_expected_answers.md` entries (can be done incrementally per class). Final commit unlocks `--strict` mode.
7. Flip CI to `--strict` (requires 3/3/8/3 distribution and answer-key parity).
8. Update `measurement/tasks.md` to deprecate seeds and point to the frozen set.
9. Tag this commit as the task-set freeze point in the project changelog.

**Rollback:** Each class is its own commit, so any class can be reverted independently. The validator continues to enforce constraints on whatever remains.

## Open Questions

- Should `tasks_expected_answers.md` also include the manually-derived "exemplar agent response" for use as a few-shot reference in LLM-as-judge prompts? **Tentative answer: no for v1** — judging is rubric-based, not exemplar-based. Revisit if judge variance is high.
- Should the validator enforce a maximum `user_message` length to avoid drift toward essay-style tasks? **Tentative answer: soft limit of 280 characters, warning not failure.** Customer messages are typically short; long tasks usually indicate the author is over-specifying.
- Does the corpus-quirk EDGE task need to be paired with an explicit no-op `out_of_scope` field so future architectures can opt out? **Tentative answer: no** — every architecture should attempt every task; opting out defeats the comparison.
