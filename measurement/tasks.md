# Benchmark Task Set

This document specifies the structure and contents of `tasks.jsonl`, the benchmark task set used to evaluate both architectures.

## File format

`tasks.jsonl` is JSON Lines — one task per line, each a complete JSON object.

## Task schema

```json
{
  "task_id": "POL-001",
  "class": "pure_policy",
  "user_message": "What's your policy on rebooking one-way tickets?",
  "expected_answer_summary": "Rebooking one-way tickets is allowed under specific conditions: ticket must be active, must not be barter/voucher-paid (with exceptions), must have flight segments with the same airline.",
  "expected_citations": ["swiss_faq.md#rebooking"],
  "expected_tool_calls": {
    "architecture_a": ["lookup_policy"],
    "architecture_b": ["get_rebooking_policy"]
  },
  "rubric": {
    "factual_correctness": "Response correctly states the conditions for one-way ticket rebooking.",
    "citation_accuracy": "Response cites the rebooking policy from the FAQ.",
    "no_fabrication": "Response does not invent policy not present in the source."
  }
}
```

## Task classes

### Pure policy (5 tasks)

Questions answerable entirely from the FAQ corpus, no booking data required. Architecture A retrieves chunks; Architecture B calls a single policy tool.

Examples to write:

- POL-001: One-way ticket rebooking policy
- POL-002: Refund eligibility for cancelled flights
- POL-003: Baggage allowance for economy fare
- POL-004: Check-in cutoff times
- POL-005: Voucher policy and exceptions

### Pure transactional (5 tasks)

Questions requiring booking data lookup only, no policy. Both architectures should perform similarly; this class is a control.

Examples to write:

- TXN-001: Status of a specific booking
- TXN-002: Flights available between two airports on a date
- TXN-003: Hotels available in a city for a date range
- TXN-004: Cars available at an airport
- TXN-005: Total cost of a specific booking

### Mixed (5 tasks)

Questions requiring both policy and booking data. The model must determine that it needs to look up booking state AND apply policy. This is where the architectures' differences become most visible.

Examples to write:

- MIX-001: "Can I rebook my flight ABC123?" — needs booking state plus rebooking policy
- MIX-002: "Am I eligible for a refund on booking XYZ?" — needs booking state plus refund policy
- MIX-003: "Does my baggage fit the allowance for my flight?" — needs booking class plus baggage policy
- MIX-004: "Can I cancel and rebook to a different date?" — needs booking state plus cancellation + rebooking policy
- MIX-005: "Is my voucher-paid booking eligible for online rebooking?" — needs booking payment method plus policy with exception

### Edge case (3–5 tasks)

Questions that test conditional policy logic, policy-with-exceptions, or unusual booking states. These often expose failure modes that aggregate metrics hide.

Examples to write:

- EDGE-001: Customer asks about a policy that has changed recently (tests both architectures' handling of stale content)
- EDGE-002: Customer asks about a booking that doesn't exist (tests error handling)
- EDGE-003: Customer asks about a policy with multiple conditional clauses (tests reasoning over policy text)
- EDGE-004: Customer asks a question outside the agent's scope (tests refusal behavior)
- EDGE-005: Customer asks in a way that's ambiguous between two policy classes (tests Architecture B's tool selection)

## Task IDs are stable

Once a task ID is published in a release, the task content is frozen. New tasks get new IDs (POL-006, MIX-006, etc.). Edits create a new task ID and deprecate the old one. This preserves comparability across versions.

## Rubric scoring

Each task is scored on three dimensions by an LLM-as-judge (Claude Opus 4):

| Dimension              | 0 (fail)                                          | 0.5 (partial)                                    | 1 (pass)                                          |
|------------------------|---------------------------------------------------|--------------------------------------------------|---------------------------------------------------|
| Factual correctness    | States wrong information                          | States correct information with significant omissions | States correct information completely        |
| Citation accuracy      | Cites wrong source, or fabricates citation        | Cites partially correct source                   | Cites correct source                              |
| No fabrication         | Invents policy not in source                      | Embellishes source policy with non-source content | All policy content traceable to source           |

A task is **successful** only if it scores 1.0 on all three dimensions.

A 10% random sample of judge decisions is manually reviewed to detect judge bias.

## Why these classes

The four classes are chosen to expose where the architectural choice actually matters:

- **Pure policy** is the case where RAG is theoretically strongest — semantic search over unstructured text. If Architecture B wins here, the bet (that the policy taxonomy is closed enough for structured retrieval to work) is validated.
- **Pure transactional** is a control — neither architecture's policy-retrieval design is exercised, so token differences should be small and attributable to system prompt size only.
- **Mixed** is where production traffic actually lives. Real customers rarely ask pure policy or pure transactional questions; they ask "can I do X with my booking Y" which requires both.
- **Edge case** is where confident-sounding wrong answers happen. Important for safety, often the deciding factor for whether an agent ships at all.

The class distribution matches roughly what customer support data tends to look like in practice — heavy on mixed, lighter on pure policy or pure transactional.

## Building the actual task set

The placeholders above are skeletons. The actual tasks need to be written by:

1. Reading `corpus/swiss_faq.md` and identifying real policy classes
2. Reading `data/travel.sqlite` schema and identifying real bookings to reference
3. Writing tasks that are answerable, unambiguous, and have clear success criteria
4. Validating each task by manually answering it yourself before adding to the set

The task set is small (15-20 tasks) precisely so this manual validation is tractable.
