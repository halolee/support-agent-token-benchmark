# Tasks — expected answers (answer key)

This document is the human-derived answer key for `measurement/tasks.jsonl`. It exists separately from the JSONL so it stays editable for adjudication of LLM-as-judge disputes without polluting the frozen task schema. The validator enforces 1:1 parity between task IDs in `tasks.jsonl` and `## TASK-ID` headings here.

**Format per entry:**
- One `## TASK-ID` heading per task (heading must match exactly).
- Verbatim quote(s) from `corpus/swiss_faq.md` supporting any policy claim.
- SQL queries (if the task touches `data/travel.sqlite`) used to derive the expected transactional answer.
- Notes on adversarial intent (EDGE tasks) so future maintainers do not "fix" them as bugs.

---

## POL-001

**Task:** A friend told me I can pay for my flight after I take it instead of upfront — is that something I'd qualify for?

**Expected behaviour:** The agent recognises this as a pay-per-invoice question and surfaces the three eligibility conditions. Best-form responses ask qualifying follow-up questions (age, residence, route) before asserting eligibility, because the customer's user_message contains none of that information.

**Corpus support** — verbatim from `corpus/swiss_faq.md` `## Pay per invoice`:

> Who can use "Pay per invoice"?
> You must be over 18 years old and be a resident of Switzerland or the Principality of Liechtenstein. Furthermore, this payment option is only available for flights from Switzerland.

**Failure modes to penalise:**
- Asserting eligibility without checking the three conditions.
- Inventing additional eligibility criteria (e.g., credit score thresholds, frequent-flyer tier requirements) — these are not in the corpus.
- Citing the wrong section (e.g., `## Credit Cards` or `## Frequently asked questions: Payment`) instead of `## Pay per invoice`.

---

## POL-002

**Task:** I'm filing my taxes and need to submit a receipt for my flight as a business expense. Do I need to ask you for a special invoice, or does the booking confirmation work?

**Expected behaviour:** The agent recognises this as an "is the e-ticket sufficient for tax / business purposes" question and surfaces the two relevant facts from `## Ordering an invoice`: (1) the e-ticket confirmation is internationally recognised as a receipt in most countries and can be used for expense reimbursement and tax-return submission; (2) special invoices are only issued for flights originating in Greece, India, Italy, or Spain on request. Best-form responses surface both even though the customer didn't volunteer their country.

**Corpus support** — verbatim from `corpus/swiss_faq.md` `## Ordering an invoice`:

> If you need an invoice for personal or business purposes, most countries accept an e-ticket confirmation as an invoice. For countries with special requirements, an invoice can be ordered using forms that are available for this purpose.
>
> Using an e-ticket confirmation as an invoice
> Your e-ticket confirmation is internationally recognised as a receipt in most countries, including Switzerland, and it can be used for the reimbursement of expenses and for the submission of a tax return.
>
> […]
>
> Invoices for Greece, India, Italy or Spain
> For flights originating in Greece, India, Italy or Spain, we can issue special invoices on request. You can request an invoice in these countries if the information provided on your e-ticket is not deemed sufficient.

**Failure modes to penalise:**
- Asserting a special invoice is always required for business expenses (the corpus says e-ticket is sufficient in most countries).
- Inventing additional special-form jurisdictions beyond the four named.
- Inventing form names, processing times, or fees not stated in the corpus.
- Citing the wrong section (e.g., `## Invoice Questions` — relevant but its Q1 is about the re-issuance fee window, not the tax-receipt-sufficiency question; see note below).

**Note on Check 2 grep affinity (intentional, do not "fix"):** This `user_message` contains several terms that appear verbatim or near-verbatim in the target section — "special invoice", "business" (corpus says "business purposes"), "receipt", "booking confirmation". The convergence is real customer language meeting real corpus authorship style, not architect leakage; per [[project-flexibility-over-restriction]] the benchmark preserves natural customer phrasing rather than engineer around it. **Measurement implication:** POL-002 may be a weaker C-vs-A/E discriminator than POL-001/POL-003 — grep is likely to find the right section easily. When interpreting comparison results, treat any C-side win on POL-002 alone as expected; significance should be assessed across the POL class, not on this single task.

**Note on adjacent corpus content (do not exercise here):** `## Invoice Questions` Q1 (line 5) also discusses invoices but focuses on the free re-issuance window — and asserts **100 days**, while `## Ordering an invoice` asserts **90 days** for the same rule. POL-002 is framed around tax-receipt sufficiency, not re-issuance timing, so this inconsistency is deliberately not in scope. The conflict is recorded as a candidate EDGE-002 synthesis-with-conflict framing (see [[project-corpus-inconsistency-handling]] in memory; deferred to a separate design call when EDGE drafting begins).

---

## POL-003

**Task:** Quick question before I check out — does paying by credit card cost more than other methods?

**Expected behaviour:** The agent recognises this as a credit-card-fees question and surfaces what the corpus actually says: some banks may charge additional fees in individual cases, and SWISS has no influence over those bank-side charges. The corpus does **not** explicitly state whether SWISS itself adds a credit-card-specific surcharge — it only addresses the bank side of the question (framed as "*other* credit card charges"). A corpus-faithful agent surfaces the bank-fee caveat and does not invent a definitive SWISS-side claim (neither "SWISS surcharges credit cards" nor "SWISS does not surcharge credit cards" appears in the source).

**Corpus support** — verbatim from `corpus/swiss_faq.md` `## Frequently asked questions: Payment`:

> Will there be any other credit card charges?
> Some banks might charge additional fees in individual cases. SWISS has no influence over these charges.

**Failure modes to penalise:**
- Asserting "SWISS does not add a credit-card surcharge" as a fact — this is an inference from the section's framing ("*other* charges") but is not stated by the corpus. A corpus-faithful agent acknowledges that the source addresses only bank-side fees and is silent on SWISS-side pricing.
- Asserting "SWISS does add a credit-card surcharge" as a fact — same reason, counterfactual direction.
- Omitting the bank-side caveat entirely (the one thing the corpus *does* explicitly say).
- Inventing specific surcharge percentages (e.g., "2.5%") or named third-party processors.
- Conflating with currency-conversion fees (Q1–3 in the same section) unless the customer asked about foreign currency — those are a separate topic and asserting them here is over-answering.
- Citing the wrong section (e.g., `## Credit Cards`, which covers CVV location, not surcharges).

**Note on PR-review revision (Codex feedback, 2026-05-31):** This task's `expected_answer_summary` and rubric originally required the agent to state "SWISS does not add credit-card surcharges" as a positive fact. That phrasing was an inference from the section's framing rather than a corpus quote, and put the rubric in tension with its own `no_fabrication` criterion. Revised to require only the supported bank-side caveat and to score over-assertion in either direction as fabrication. The corrected framing is also a more interesting POL probe: the agent is tested on faithful quoting under partial-coverage corpus, not on agreement with a synthesized expected answer.

---

## TXN-001

**Task:** Doing my expense report and I can't find the receipt for booking 002E3A. Can you tell me what I paid in total?

**Expected behaviour:** The agent calls the booking-lookup tool for `002E3A` and reports the row's `total_amount`. No corpus citation is needed — this is a pure transactional lookup. Best-form responses either report the raw number (`393000`) or contextualize it with a reasonable currency interpretation (e.g., `CHF 3,930.00` or `CHF 393,000`); the schema does not annotate currency, so interpretation is downstream of the lookup and any of these forms passes factual correctness.

**SQL (derives the expected answer):**

```sql
SELECT total_amount FROM bookings WHERE book_ref = '002E3A';
-- → 393000
```

**Failure modes to penalise:**
- Reporting a different number (e.g., the per-passenger total, a sum of `ticket_flights.amount`, or an invented figure). The customer asked for what's on the booking row.
- Citing `corpus/swiss_faq.md` — no policy is invoked; a citation here is fabrication.
- Inventing fields not in `bookings` (payment method, refund status, passenger names) — those would require extra tool calls the customer did not ask for.

**Note on currency-unit ambiguity:** The `bookings.total_amount` column in `data/travel.sqlite` is an integer with no documented unit. Real SWISS pricing for two Business-cabin tickets would more plausibly be ~3,930 CHF than 393,000 CHF (the latter would imply ~$440K USD for a round-trip), suggesting the column stores minor units (cents). But the schema is silent and the corpus does not annotate this either, so the rubric accepts both interpretations rather than locking in an inference. This is deliberate per [[project-flexibility-over-restriction]]: the TXN probe measures whether the agent reads the sqlite row correctly, not whether it guesses the right currency convention.

---

## TXN-002

**Task:** Quick check — did my LX0086 leg on booking 3F0481 land OK? Trying to figure out if my next connection is going to work.

**Expected behaviour:** The agent resolves booking `3F0481`'s itinerary (the agent's `get_booking_status` tool returns all segments), identifies the LX0086 segment as `flight_id=11472` (the unique LX0086 instance on this booking — `flight_no` alone is ambiguous across 61 rows in `flights`), and reports `status='Arrived'`. Surfacing `actual_departure` / `actual_arrival` to address the connection-timing concern is a plus. The agent must not pick a different LX0086 instance (e.g., a Cancelled or future-Scheduled one from a different date) — only the one on this customer's booking is relevant.

**SQL (derives the expected answer):**

```sql
-- Step 1: resolve the unique LX0086 instance on booking 3F0481
SELECT tf.flight_id
FROM ticket_flights tf
JOIN tickets t ON tf.ticket_no = t.ticket_no
JOIN flights f ON tf.flight_id = f.flight_id
WHERE t.book_ref = '3F0481' AND f.flight_no = 'LX0086';
-- → flight_id 11472

-- Step 2: look up status for that flight_id
SELECT status, scheduled_departure, scheduled_arrival, actual_departure, actual_arrival
FROM flights WHERE flight_id = 11472;
-- → status='Arrived'; actual_departure and actual_arrival populated
```

**Failure modes to penalise:**
- Reporting a different status (e.g., `Cancelled` or `Scheduled`) for the LX0086 instance on this booking.
- Looking up `flight_no='LX0086'` without disambiguating via the booking, then reporting the status of an arbitrary row (the data has 61 LX0086 rows across 2024 dates with varying statuses — this would surface a status not relevant to the customer).
- Citing `corpus/swiss_faq.md` — flight status is sourced from booking + flight data, not policy text.
- Inventing gate numbers, baggage carousel info, or weather context not present in the `flights` row.
- Asserting whether the next connection is or isn't viable without actually inspecting the rest of the itinerary (the customer raised the concern but didn't supply the connection details; the agent should either inspect or decline rather than guess).

**Note on flight_no ambiguity (structural property of `data/travel.sqlite`):** `flight_no` is a route designator, not a unique flight identifier — each LX route recurs on many dates, so `flights` has 61 rows for LX0086 across the dataset's 2024 window. The fixture rationale's "Scheduled"/"Arrived" labels refer to the *specific instance linked to a fixture booking* (LX0086→11472→Arrived on 3F0481), not to LX0086 in general. TXN-002 is phrased to force disambiguation via the booking join; an agent that ignores the booking context and queries `flight_no` alone will get a non-unique result and may pick the wrong row. This is realistic — the customer says "my LX0086 leg" because in their mental model there's one specific instance, and the agent has to map that to the right `flight_id`.

---

## TXN-003

**Task:** Got an email about an upgrade offer for ticket 7240005435767874 on booking 0002D8 — what class am I currently flying?

**Expected behaviour:** The agent calls `get_booking_status('0002D8')`, which returns the booking's itinerary including ticket `7240005435767874` and its segment fares. Both segments (LX0136, CX0047) are `Economy`, so the answer is `Economy` (uniform across the ticket's itinerary — no need to enumerate per-segment unless the agent wants to be explicit, which is also fine). The agent should not extrapolate about upgrade eligibility, pricing, or process — the customer asked one question (what class) and the upgrade offer is mentioned only as the reason for asking.

**SQL (derives the expected answer):**

The shared transactional tool surface is booking-keyed (`get_booking_status(booking_id)`), so the tool's underlying query joins `bookings → tickets → ticket_flights → flights` for the given booking. The agent then filters the returned itinerary to the customer-named ticket.

```sql
-- The data the tool returns for booking 0002D8 (booking → tickets → fares)
SELECT t.ticket_no, f.flight_no, tf.fare_conditions
FROM tickets t
JOIN ticket_flights tf ON t.ticket_no = tf.ticket_no
JOIN flights f ON tf.flight_id = f.flight_id
WHERE t.book_ref = '0002D8';
-- → ticket 7240005435767874: LX0136 Economy, CX0047 Economy
```

**Failure modes to penalise:**
- Reporting a different fare class.
- Citing a `corpus/swiss_faq.md` section about Economy fare conditions or upgrade policy — the customer asked what class they're in (transactional), not what the class entails or how to upgrade (which would be MIX). Citing here is over-answering.
- Asserting upgrade eligibility, upgrade pricing, or upgrade availability. These require tool calls the agent does not have in scope; making confident claims is fabrication.
- Inventing per-segment fare differences (e.g., "Economy on one segment, Premium Economy on the other") — both segments are Economy in sqlite.

**Note on fixture choice:** Ticket `7240005435767874` is the only one of the three fixture tickets with a uniform fare class across its segments (both Economy). The other two have mixed fares (one segment of the named class, others Economy), which makes them better suited to MIX scenarios where the rubric can score per-segment reasoning. TXN-003 stays pure by using the uniform-fare ticket — the agent's answer is a single class, not a per-segment breakdown.

**Note on PR-review revision (Codex feedback, 2026-05-31):** The original draft asked about ticket `7240005435767874` *without* naming the booking. The shared transactional interface across all measured architectures (per `CLAUDE.md` and `architectures/naive_rag/README.md`) is `get_booking_status(booking_id: str)` — there is no `get_ticket` tool. With only a ticket number in the user message, the agent had no documented tool path to reach `fare_conditions`, which would have made TXN-003 unreachable as a control task rather than a fair transactional probe. Revised to include booking `0002D8` in the customer's message (natural phrasing for an upgrade-email scenario — the email would name both) so the agent can call `get_booking_status('0002D8')` and find the ticket inside the returned itinerary. The SQL above reflects the booking-first lookup path the agent's tool actually executes.
