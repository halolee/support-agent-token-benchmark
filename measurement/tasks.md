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

### Pure policy (3 tasks)

Questions answerable entirely from the FAQ corpus, no booking data required.

Examples (customer-phrased):
- POL-001: "If my flight is cancelled by the airline, do I just get my money back automatically or do I need to ask?"
- POL-002: "I'm bringing a stroller and a car seat for my baby — does that count against my baggage allowance?"
- POL-003: "How long before takeoff do I need to be at the gate? Some airlines say 30 minutes, some say 45 — what's yours?"

### Pure transactional (3 tasks)

Questions requiring booking data only, no policy lookup. Control class — all architectures should perform similarly.

Examples:
- TXN-001: "Can you check what time my flight ABC123 leaves tomorrow?"
- TXN-002: "I'm looking at flights from Zurich to New York on December 15 — what's available?"
- TXN-003: "How much did I end up paying total for booking XYZ?"

### Mixed (8 tasks)

Questions requiring both policy and booking data. This is where production traffic actually lives, and where architectural differences become most visible. Weighted heavily for realistic distribution.

Examples (customer-phrased, avoid mapping to category names):
- MIX-001: "I bought a one-way ticket to Zurich last month and need to push my departure back by two days — what are my options here?"
- MIX-002: "My flight got cancelled, the one I had on booking ABC. Am I going to get my money back or do they put me on a different flight?"
- MIX-003: "I'm flying economy on flight XYZ next week — can I bring a guitar as carry-on or does that have to go below?"
- MIX-004: "I want to cancel my trip entirely and rebook for next month — is that a thing I can do or do I lose the money?"
- MIX-005: "I paid for booking DEF with a voucher from a previous cancelled flight — can I still change the date online or do I need to call someone?"
- MIX-006: "I have a connecting flight in Frankfurt with only 45 minutes between landing and takeoff — is that going to be a problem if the first leg is delayed?"
- MIX-007: "My daughter is 16 and traveling alone next month on booking GHI — is there anything I need to set up or sign?"
- MIX-008: "I need to add my frequent flyer number to my existing booking JKL — can I do that online or is it too late?"

### Edge case (3 tasks)

Tests conditional policy logic, exceptions, ambiguous routing. Often expose failure modes that aggregate metrics hide.

Examples:
- EDGE-001: A question whose answer depends on conditions in the booking data that aren't explicitly asked about (tests whether agent retrieves enough context)
- EDGE-002: A question whose policy answer has an exception the agent must surface (tests handling of conditional clauses)
- EDGE-003: A question that's ambiguous between two policy classes (tests how each architecture's retrieval handles ambiguity)

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

## Building the actual task set

The examples above are seed phrasings. The actual tasks need to be written by:

1. Reading `corpus/swiss_faq.md` (after Phase 1 corpus inventory) and identifying real policy classes
2. Reading `data/travel.sqlite` schema and identifying real bookings to reference (or designing tasks that work against the actual data)
3. Writing tasks in customer-style language — the kind of phrasing that would actually arrive in a support inbox
4. Validating each task by manually answering it yourself before adding to the set
5. Re-reading each task with Check 2 in mind: does this phrasing favor any architecture?

The task set is small (~17 tasks) precisely so this manual validation is tractable.
