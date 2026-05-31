## 1. Validator foundation (TDD — no tasks yet)

- [ ] 1.1 Add `pydantic>=2.0` to `requirements.txt` and `requirements.lock.txt`; verify `pip install` succeeds in the project venv
- [ ] 1.2 Create `measurement/policy_classes.json` from `corpus/swiss_faq.md` H2 sections (one entry per section with: kebab-case `id`, `title` matching the H2 heading verbatim, one-line `summary` of what the section covers)
- [ ] 1.3 Create `measurement/check2_blacklist.json` seeded with the disallowed substrings listed in `specs/benchmark-tasks/spec.md` (Check 2 phrasing rule)
- [ ] 1.4 Implement `measurement/scripts/validate_tasks.py` exposing `validate(jsonl_path, fixtures_path, vocab_path, blacklist_path, sqlite_path, strict: bool) -> list[Violation]` with one Pydantic model per task and one Python check per requirement (8 requirements → 8 check functions). Each check function lives in its own module-level function so adding a check is one append, not an edit
- [ ] 1.5 Implement `tests/test_tasks.py` that imports the validator and runs it against `measurement/tasks.jsonl` with `--strict`. Add a separate test fixture file (`tests/fixtures/tasks_*.jsonl`) covering each failure mode — one passing fixture, one fixture per requirement violation — and assert the validator reports the expected violation
- [ ] 1.6 Create `measurement/tasks.jsonl` containing one minimal hand-crafted POL fixture line that passes every check (so the validator has something to chew on); confirm `pytest tests/test_tasks.py` is green
- [ ] 1.7 Commit: `Phase 2 Step 4.1: task validator + controlled vocabulary`

## 2. Booking fixtures (one-time sampling)

- [x] 2.1 Implement `measurement/scripts/sample_fixtures.py` that opens `data/travel.sqlite` and samples: 3 `book_ref` values (varied `total_amount`, varied passenger counts via `tickets` join), 3 `flight_no` values constrained to `LX%` (Swiss carrier — corpus is swiss_faq.md; varied status — cancelled, delayed, scheduled), 3 `ticket_no` values covering Business + Comfort + Economy fare classes (Comfort included specifically because it's present in sqlite but absent from corpus, supporting EDGE-003 out-of-scope-refusal grounding). Output: `measurement/task_fixtures.json` with each value annotated with a `rationale` string explaining why it was chosen. **Amended during PR #5 apply phase** — original spec said 2 ticket_nos and unconstrained carrier; both were revised after reverse-tracing fixture coverage against `design.md` Decision 7's candidate list (carrier mismatch made customer-style phrasings semantically incoherent; missing Comfort left EDGE-003 ungrounded)
- [x] 2.2 Run `sample_fixtures.py` once; commit the generated `measurement/task_fixtures.json`; do NOT re-run in CI
- [x] 2.3 Extend the validator's referential-integrity check to confirm every fixture entry resolves to a real sqlite row at runtime (catches data drift)
- [x] 2.4 Commit: `Phase 2 Step 4.2: booking fixtures sampled and frozen`

## 3. Pure policy tasks (POL-001..003)

- [ ] 3.1 Draft 3 POL tasks grounded in actual `swiss_faq.md` sections — candidates per `design.md` Decision 7: invoice timing, credit card surcharges/security, pay-per-invoice eligibility. Each task gets a customer-style `user_message` (Check 2 compliant), `expected_answer_summary`, `expected_citations`, `policy_classes_invoked` drawn from the vocabulary, `booking_data_required: false`, and a 3-criterion rubric
- [ ] 3.2 Append to `measurement/tasks.jsonl`; run validator; iterate until clean
- [ ] 3.3 Add corresponding `## POL-001` / `## POL-002` / `## POL-003` sections to `measurement/tasks_expected_answers.md` with verbatim corpus quotes
- [ ] 3.4 **User review checkpoint** — surface the three drafted tasks for review before proceeding to TXN
- [ ] 3.5 Commit: `Phase 2 Step 4.3: 3 pure-policy tasks (POL-001..003)`

## 4. Pure transactional tasks (TXN-001..003)

- [ ] 4.1 Draft 3 TXN tasks referencing fixtures from `task_fixtures.json` — candidates: booking total lookup, flight status check, ticket fare class. Each `user_message` must mention a real `book_ref` or `flight_no`; `booking_data_required: true`; `expected_citations: []` is permitted
- [ ] 4.2 Append to `tasks.jsonl`; run validator; iterate
- [ ] 4.3 Add `## TXN-001..003` sections to `tasks_expected_answers.md` including the SQL queries used to derive the expected answer (not just the answer)
- [ ] 4.4 **User review checkpoint**
- [ ] 4.5 Commit: `Phase 2 Step 4.4: 3 pure-transactional tasks (TXN-001..003)`

## 5. Mixed tasks (MIX-001..008)

- [ ] 5.1 Draft 8 MIX tasks combining a booking reference with a policy question. Candidates per `design.md` Decision 7. Each task must require both a policy lookup (citation required) AND a booking lookup (`booking_data_required: true`). Pay special attention to Check 2 — mixed tasks are the most likely to drift into architect phrasing because they encode richer scenarios
- [ ] 5.2 Append in batches of 2-3 to `tasks.jsonl` so iteration stays bounded; run validator after each batch
- [ ] 5.3 Add `## MIX-001..008` sections to `tasks_expected_answers.md` with both corpus quotes AND fixture-row data
- [ ] 5.4 Run a manual Check 2 sweep on all 8 mixed tasks before review — re-read each `user_message` cold and ask "does this phrasing leak the answer's category to a structured-tool or grep architecture?"
- [ ] 5.5 **User review checkpoint** — the largest review; expect iteration. Specifically flag any mixed tasks where the answer key shows a thin or stretched corpus quote (signal that the corpus doesn't really cover the topic and the task should be reworked)
- [ ] 5.6 Commit: `Phase 2 Step 4.5: 8 mixed tasks (MIX-001..008)`

## 6. Edge case tasks (EDGE-001..003)

- [ ] 6.1 Draft EDGE-001 (suspect content present in source) per `design.md` Decisions 4 and 8 — a customer-phrased question whose semantic retrieval may surface the "877-5O7-7341" section. Rubric explicitly scores fabrication/endorsement of the suspect number as a failure
- [ ] 6.2 Draft EDGE-002 (synthesis across multiple sections) per `design.md` Decision 8 — a customer-phrased question whose full answer requires combining partial information from two or more FAQ sections (candidate: a payment-handling question that spans Credit Cards + Card Security + Payment FAQ). Rubric scores both retrieval coverage (did the agent surface all required sections?) and combination quality (did the response coherently integrate them, not just concatenate?)
- [ ] 6.3 Draft EDGE-003 (out-of-scope refusal) per `design.md` Decision 8 — a customer-phrased question whose answer is not present in the corpus or sqlite (candidate: a service Swiss doesn't offer, or a policy area the corpus doesn't cover). Rubric scores clear "I don't have that information" responses as passes and any fabricated answer drawn from low-similarity retrieval as a failure
- [ ] 6.4 Append to `tasks.jsonl`; run validator
- [ ] 6.5 Add `## EDGE-001..003` sections to `tasks_expected_answers.md`. EDGE-001's entry must spell out the adversarial intent so future maintainers don't "fix" the task as a bug
- [ ] 6.6 **User review checkpoint** — edge cases are where confident-wrong answers happen; review carefully
- [ ] 6.7 Commit: `Phase 2 Step 4.6: 3 edge-case tasks (EDGE-001..003)`

## 7. Final Check 2 sweep and freeze

- [ ] 7.1 Run validator in `--strict` mode against the complete 17-task file; expect 0 violations
- [ ] 7.2 Manually re-read every `user_message` cold (no surrounding context) and self-rate for Check 2 leakage on a per-task basis. Record findings in `tasks_expected_answers.md` under a "Check 2 self-audit" appendix
- [ ] 7.3 Update `measurement/tasks.md`: add a "Frozen task set" section pointing at `tasks.jsonl`, mark the inline seed examples as "pre-inventory drafts, not the actual tasks," and link to `tasks_expected_answers.md` as the answer key
- [ ] 7.4 Verify CI runs the validator (add a workflow step if no CI exists yet; otherwise confirm `pytest tests/test_tasks.py` is in the test suite)
- [ ] 7.5 Commit: `Phase 2 Step 4.7: task set frozen — 17 tasks, validator strict, docs updated`

## 8. Cross-document consistency

- [ ] 8.1 Update `BUILD_PLAN.md` Phase 2 Step 4 checkboxes to reflect actual progress; do NOT mark Step 4 done until all sub-tasks above are committed
- [ ] 8.2 Update `METHODOLOGY.md` adversarial review section (Check 2) to reference the validator and blacklist file as the mechanical enforcement
- [ ] 8.3 Add `measurement/task_fixtures.json`, `measurement/policy_classes.json`, `measurement/check2_blacklist.json` to README or HANDOVER as part of the modular extensibility story
