# Benchmark Task Set

Specification for `tasks.jsonl`, the benchmark task set used to evaluate all architectures.

## File format

`tasks.jsonl` is JSON Lines — one task per line, each a complete JSON object.

## Task schema

```json
{
  "task_id": "MIX-001",
  "class": "mixed",
  "user_message": "I bought a one-way ticket to Zurich last month and need to push my departure back by two days — what are my options here?",
  "expected_answer_summary": "The agent should look up the user's booking, check ticket type and eligibility, then apply the rebooking policy. One-way rebooking is allowed under conditions: ticket must be active, must not be voucher-paid (with exceptions), must have segments with the same airline. Response should cite the relevant policy section.",
  "expected_citations": ["rebooking"],
  "policy_classes_invoked": ["rebooking"],
  "booking_data_required": true,
  "rubric": {
    "factual_correctness": "Response correctly identifies whether the user's ticket is eligible for rebooking and states the conditions.",
    "citation_accuracy": "Response cites the rebooking policy.",
    "no_fabrication": "Response does not invent policy clauses not in the source."
  }
}
```

## Critical rule: task phrasing must not favor any architecture

This is the most important rule for task authors. Per METHODOLOGY §"Check 2," task phrasings must use customer-style language, not architect-style category names.

**Wrong (favors structured-tool architectures):**
```json
"user_message": "What's your policy on rebooking one-way tickets?"
```
This phrasing uses the exact category name a structured-tool architecture might expose as a tool (`get_rebooking_policy`). A real customer would not phrase it this way. Using this phrasing in the benchmark gives bounded-tool architectures a free signal that doesn't reflect production conditions.

**Right (customer-style phrasing):**
```json
"user_message": "I bought a one-way ticket to Zurich last month and need to push my departure back by two days — what are my options here?"
```
This phrasing forces the agent to *figure out* that this is a rebooking question. The architecture's retrieval mechanism has to do real work.

The rule extends to grep-friendly vocabulary too. A task phrased to use the exact keywords that appear in the policy text gives grep an unfair advantage. Customer language is colloquial, often imprecise, and rarely matches the formal policy vocabulary directly.

The `policy_classes_invoked` and `booking_data_required` fields are metadata for analysis (what *should* the agent retrieve), not for the architecture to read. The agent only sees `user_message`.

## Task classes

The canonical 17-task frozen set lives in `measurement/tasks.jsonl` (marked `# COMPLETE`); expected answers are in `measurement/tasks_expected_answers.md`. The class descriptions below define what each class *is* — for the actual phrasings and rubrics, read the JSONL.

### Pure policy (3 tasks)

Questions answerable entirely from the FAQ corpus, no booking data required.

### Pure transactional (3 tasks)

Questions requiring booking data only, no policy lookup. Control class — all architectures should perform similarly.

### Mixed (8 tasks)

Questions requiring both policy and booking data. This is where production traffic actually lives, and where architectural differences become most visible. Weighted heavily for realistic distribution.

### Edge case (3 tasks)

Tests conditional policy logic, exceptions, ambiguous routing. Often expose failure modes that aggregate metrics hide.

## Why these classes and this distribution

The four classes expose where architectural choice actually matters:

- **Pure policy** is the case where RAG is theoretically strongest — semantic search over unstructured text. If grep matches RAG here, the bet is validated.
- **Pure transactional** is a control — neither architecture's policy retrieval is exercised, so differences should be small and attributable to system prompt size only.
- **Mixed** is where production traffic actually lives. Weighted heavily (8 of ~17) because the comparison should reflect real distribution.
- **Edge case** is where confident-sounding wrong answers happen. Important for safety; often the deciding factor for whether an agent ships.

The mixed-heavy distribution is deliberate. Real customer support traffic is overwhelmingly mixed; pure-class questions are minority cases.

## MIX section coverage — intentional gaps

The MIX class exercises 4 of the 9 candidate corpus sections (per `measurement/policy_classes.json`): `faq-european-fare-concept`, `booking-and-cancellation`, `pay-per-invoice`, `faq-payment`. Three sections are **uncovered by MIX by design** because the corpus rules in those sections do not vary with booking attributes — a MIX task drawing on them would have a decorative-only booking lookup, violating the class definition (per `openspec/changes/write-benchmark-tasks/design.md` Decision 7: MIX requires both policy AND booking data to be load-bearing):

- `booking-platform` — UI/device feature gaps (smartphone vs desktop, third-party bookings via app). Rules apply universally regardless of which booking is being viewed.
- `credit-cards` — card security number digit count by brand (Amex 4-digit front, others 3-digit back). Rule is the same for any booking being paid for.
- `card-security` — 3-D Secure for EEA cards, PCI-DSS storage standards. Applies regardless of the specific booking.

`invoice-questions` is also untouched in MIX — it shares the 90-vs-100-day re-issuance-window conflict with `ordering-an-invoice` (issue [#14](https://github.com/halolee/support-agent-token-benchmark/issues/14)) and is reserved as a candidate EDGE-002 synthesis-with-conflict framing.

These coverage gaps are limitations of the *class definition* (MIX requires booking-data-load-bearing rules), not of the corpus itself. POL covers some of the same sections (`pay-per-invoice` via POL-001, `ordering-an-invoice` via POL-002, `faq-payment` via POL-003). v2 architectures (Bounded tools, Stuffed corpus — deferred per `ROADMAP.md`) may exercise the booking-data-thin sections through different testing surfaces.

## Rubric scoring

Each task is scored on three dimensions by an LLM-as-judge (`claude-opus-4-7`):

| Dimension              | 0 (fail)                                          | 0.5 (partial)                                    | 1 (pass)                                          |
|------------------------|---------------------------------------------------|--------------------------------------------------|---------------------------------------------------|
| Factual correctness    | States wrong information                          | States correct information with significant omissions | States correct information completely        |
| Citation accuracy      | Cites wrong source, or fabricates citation        | Cites partially correct source                   | Cites correct source                              |
| No fabrication         | Invents policy not in source                      | Embellishes source policy with non-source content | All policy content traceable to source           |

A task is **successful** only if it scores 1.0 on all three dimensions.

A 10% random sample of judge decisions is manually reviewed to detect judge bias.

## Task IDs are stable

Once a task ID is published in a release, the task content is frozen. New tasks get new IDs. Edits create a new ID and deprecate the old one. This preserves comparability across versions.

## Adding new tasks after the freeze

The 17-task set in `measurement/tasks.jsonl` is frozen. Per CLAUDE.md invariants, new tasks get new IDs (e.g., `MIX-009`); edits to an existing row create a new ID and deprecate the old one. The original authoring process — read `corpus/swiss_faq.md`, identify real policy classes against `data/travel.sqlite`, write in customer voice, manually answer, re-read against Check 2 — applies equally to any addition. The validator (`measurement/scripts/validate_tasks.py`) gates all of the above; run it before committing.
