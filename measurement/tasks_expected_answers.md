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

**Note on Check 2 grep affinity (intentional, do not "fix"):** This `user_message` contains several terms that appear verbatim or near-verbatim in the target section — "special invoice", "business" (corpus says "business purposes"), "receipt", "booking confirmation". The convergence is real customer language meeting real corpus authorship style, not architect leakage; per [[project-flexibility-over-restriction]] the benchmark preserves natural customer phrasing rather than engineer around it. **Measurement implication:** POL-002 may be a weaker Grep-search-vs-Naive-RAG/Hybrid-RAG discriminator than POL-001/POL-003 — grep is likely to find the right section easily. When interpreting comparison results, treat any Grep-search-side win on POL-002 alone as expected; significance should be assessed across the POL class, not on this single task.

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

---

## MIX-001

**Task:** Hi — I've got booking 002E3A with ticket 2350005432655688, and one segment in Business is operated by Turkish Airlines instead of SWISS. What should I expect from that compared to a Business segment on a SWISS flight?

**Expected behaviour:** The agent calls `get_booking_status('002E3A')`, resolves ticket `2350005432655688`'s segments, identifies the Business segment as `TK0065` (Turkish Airlines codeshare per fixture rationale — TK is the IATA code for Turkish Airlines), and retrieves the `## Frequently asked questions: European fare concept` section. The corpus addresses two things about codeshare Business: (1) Business CAN be booked on codeshare flights; (2) seats cannot be reserved on codeshare flights for the time being. The corpus is SILENT on amenity parity (lounge access, baggage allowance on codeshare, miles-accrual differences, meal service). A faithful response confirms Business applies on the TK leg, surfaces the seat-reservation caveat, and does NOT extrapolate amenity claims.

**Corpus support** — verbatim from `corpus/swiss_faq.md` `## Frequently asked questions: European fare concept`:

> Can the SWISS fares be booked on codeshare flights operated by other airlines? What happens when changing a flight from a SWISS-operated flight to a codeshare flight (e.g. Zurich-Lisbon with TAP Portugal)?
> The fares Economy Classic, Economy Flex and Business can be booked on codeshare flights. Economy Light can only be booked on flights operated by SWISS (airline code LX). For technical reasons, seats cannot be reserved on codeshare flights for the time being.

**SQL (derives the expected answer):**

```sql
-- Resolve ticket 2350005432655688's segments and fare classes via booking 002E3A
SELECT tf.ticket_no, f.flight_no, tf.fare_conditions, SUBSTR(f.flight_no, 1, 2) AS airline_code
FROM tickets t
JOIN ticket_flights tf ON t.ticket_no = tf.ticket_no
JOIN flights f ON tf.flight_id = f.flight_id
WHERE t.book_ref = '002E3A' AND t.ticket_no = '2350005432655688'
ORDER BY f.scheduled_departure;
-- → TK0065 Business (Turkish Airlines), TP0018 Economy, LX0082 Economy, KE0122 Economy
-- Confirms: one Business segment, on TK (non-LX codeshare), per fixture rationale.
```

**Failure modes to penalise:**
- Asserting that Business cannot be booked on codeshare — the corpus is explicit it can.
- Omitting the seat-reservation caveat — it is the one corpus-specific limitation about codeshare, and the customer's question ("what should I expect") naturally surfaces it.
- Inventing amenity parity claims not in the corpus: lounge access guarantees, specific baggage allowances on TK, miles-accrual differences, service quality, meal service.
- Citing `Booking Platform` (which addresses UI/device-specific upgrade and seating Qs, not codeshare fare rules) or `Pay per invoice`.
- Asserting the wrong segment is Business (the customer says "one segment" — the agent must identify which one via booking lookup; identifying e.g. LX0082 as Business is factually wrong).

**Note on multi-fare ticket phrasing (per design.md Decision 7 §"Practical implications"):** Ticket `2350005432655688` has one Business segment of four (the other three are Economy on TP0018/LX0082/KE0122). The customer's phrasing "one segment in Business" matches the segment-scoped pattern required for multi-fare fixture tickets — calling the whole ticket "my Business ticket" would fail referential checks against `ticket_flights × flights`.

**Note on Check 2 grep affinity:** Moderate. "Business", "operated by", and "SWISS" appear in the user message; "Business", "operated by SWISS" appear verbatim in the target section. "Turkish Airlines" does not appear in the corpus (only `TK` as the IATA code is implicit). The convergence reflects natural premium-traveller phrasing meeting natural FAQ-author phrasing, per the POL-002 precedent and [[project-flexibility-over-restriction]] — the benchmark preserves realistic customer language rather than engineer around it. Grep-search-side wins on MIX-001 should be assessed against the MIX class as a whole, not this task alone.

---

## MIX-002

**Task:** I already changed booking 0002D8 once last month — can I move my dates again, or is one change all I get?

**Expected behaviour:** The agent calls `get_booking_status('0002D8')`, retrieves both segments of ticket `7240005435767874` (per TXN-003 derivation: LX0136 Economy, CX0047 Economy), and identifies that **TWO independent rules** in `## Booking and Cancellation` apply to the customer's question:

**(A) Online-rebooking eligibility (Q1-Q2 — same logic as MIX-004):** The booking contains segment `CX0047` (Cathay Pacific, non-LX codeshare), which disqualifies it from online rebooking per Q2: "Bookings containing flight segments with other airlines" cannot be rebooked online — **regardless of fare condition or change history**. The customer must contact SWISS service center to change dates on this booking.

**(B) Multi-change rule (Q5):** Even via service-center channel, whether the customer can change *again* depends on the fare condition — "If the fare condition allows it, it is possible to make multiple changes to the itinerary." The booking's stored `'Economy'` is less granular than the corpus's three-way Economy split in the European fare concept section (Economy Light's "fare itself cannot be changed"; Classic and Flex are less restricted), and the database does not expose the sub-fare.

A faithful response per [[project-mix-condition-resolution-pattern]] surfaces **both independently-determining facts**:
1. This booking can't be changed online due to the codeshare segment — call SWISS service center.
2. When calling: multiple changes are conditional on the sub-fare. The customer should check their e-ticket for the specific Economy sub-fare (Light blocks further changes; Classic and Flex don't).

The agent's role is to RESOLVE the customer's problem. An answer that addresses only the sub-fare conditional, without flagging the codeshare blocker, **implicitly tells the customer to try the change online** — which would fail at the rebooking page. An answer that flags only the codeshare blocker without the sub-fare conditional answers the channel question but misses Q5 (the customer's primary "is one change all I get" constraint).

**Corpus support** — verbatim from `corpus/swiss_faq.md` `## Booking and Cancellation` Q5:

> After I have made changes to the itinerary online, can I make another change?
> If the fare condition allows it, it is possible to make multiple changes to the itinerary.

And from `## Frequently asked questions: European fare concept` (corroborating the sub-fare distinction):

> The additional options cannot be rebooked with Economy Light because the fare itself cannot be changed.

**SQL (derives the expected answer):**

```sql
-- Resolve booking 0002D8's fare classes (same derivation as TXN-003)
SELECT t.ticket_no, f.flight_no, tf.fare_conditions
FROM tickets t
JOIN ticket_flights tf ON t.ticket_no = tf.ticket_no
JOIN flights f ON tf.flight_id = f.flight_id
WHERE t.book_ref = '0002D8';
-- → ticket 7240005435767874: LX0136 Economy, CX0047 Economy
-- Both segments stored as 'Economy' — ambiguous across corpus's Light/Classic/Flex.
```

**Failure modes to penalise:**
- **Missing the codeshare blocker (Codex P2 catch, PR #15).** Booking 0002D8 contains segment `CX0047` (Cathay Pacific, non-LX), which independently disqualifies online rebooking per Q2 — regardless of fare condition or change history. An agent that answers only the multi-change-conditional-on-sub-fare question, without surfacing that this booking can't be changed online at all, gives the customer a **wrong actionable next step** (they'd try the online rebooking page and fail). Per [[project-mix-condition-resolution-pattern]], faithful behavior is to drive toward resolution — and the resolution path here requires calling SWISS, not online.
- Asserting "yes you can change again, just do it online" — wrong on the channel (codeshare blocker) even if conditionally right on the fare.
- Asserting "yes you can change again" without the fare-condition caveat — Q5 is conditional.
- Asserting "no you can't" — the corpus does not say one change is the limit; additional changes depend on fare conditions.
- Inventing specific limits ("you get 3 changes", "one change per month") not in the corpus.
- Confidently classifying the booking's `'Economy'` as Economy Classic / Flex / Light without basis — the database doesn't expose sub-fare.
- Inventing change fees — the corpus does not state any specific fee structure for itinerary changes (only for post-booking invoice re-issuance, which is a different topic).
- Citing only Booking and Cancellation without surfacing the sub-fare granularity issue is incomplete — the answer is materially weakened by not acknowledging that `'Economy'` in the data is ambiguous across three corpus categories with different change rules.
- **Surfacing the conditional but failing to identify the specific missing info or how the customer can obtain it** (e.g., "depends on your fare conditions, sorry" with no follow-through). Per [[project-mix-condition-resolution-pattern]], the agent's faithful behavior is to ASK for the sub-fare or point at where it can be found, not to merely describe the ambiguity. Treating the customer as a developer debugging the retrieval rather than a customer needing an answer.
- Inventing a specific service-center phone number for the call-SWISS instruction. The corpus does not provide one in `## Booking and Cancellation` — surfacing `877-5O7-7341` from the Cancel Flight Guide section is EDGE-001 fabrication territory and a fail here.

**Note on data-corpus granularity mismatch (intentional design):** The benchmark's `data/travel.sqlite` stores `fare_conditions` as `'Economy'`/`'Business'`/`'Comfort'` — single-word labels — while `corpus/swiss_faq.md` distinguishes Economy Light, Economy Classic, Economy Flex with materially different rules. MIX-002 exercises this asymmetry on purpose: a faithful agent (a) surfaces the conditional rule and (b) drives toward resolution by **asking for the specific sub-fare info** — not by passively educating the customer about corpus structure. Per [[project-mix-condition-resolution-pattern]], conditional answers must be paired with actionable info-gathering. This is distinct from EDGE-003 (Comfort in data, absent from corpus → refusal); MIX-002 is "data less specific than corpus → ask for the missing specificity." Per [[project-flexibility-over-restriction]], real production data is often coarser than policy text — the benchmark preserves the asymmetry rather than papering over it.

**Note on Check 2 grep affinity:** Moderate. "Change" / "changed" / "dates" map to corpus verbatim — "changes" and "travel dates" appear throughout `## Booking and Cancellation`. The customer's phrasing is unavoidable for a rebooking-related question; alternatives like "modify" would be less natural and not significantly less grep-friendly. Per [[project-flexibility-over-restriction]] the benchmark preserves natural customer language. **B&C cluster member:** part of the Booking & Cancellation cluster with MIX-003 and MIX-004; all three target this section. Grep retrieval will reliably hit B&C for all three — the differentiator is *which sub-Q within B&C* the agent applies. **Measurement implication:** the B&C cluster should be analyzed as a group rather than as three independent data points when reporting grep vs Naive RAG performance; individual-task wins in this cluster are less informative than cluster-level performance.

---

## MIX-003

**Task:** On booking 002E3A — my partner wants to change their flight to a different date but I want to keep mine. Can we split it?

**Expected behaviour:** The agent calls `get_booking_status('002E3A')`, confirms the booking has 2 passenger records (2 ticket rows: `2350005432655688` and `2350005432655689`, each with a distinct `passenger_id`), and retrieves the `## Booking and Cancellation` section Q7. The corpus is explicit: "The changes will always be applied to all passengers travelling together. Changes to the passenger name or number of passengers is not possible online." A faithful response per [[project-mix-condition-resolution-pattern]]:
1. Confirms the booking has multiple passengers (the customer's premise — "my partner and I" — is valid against the data).
2. Clearly states that online changes apply to all travelling-together passengers as a group; individual per-passenger splits are NOT supported online.
3. Directs the customer to contact SWISS service center for per-passenger handling (the corpus does not provide a specific phone number in this section — agent should not invent one).

Asserting that the partner can change their flight independently online is factually wrong. The agent's booking lookup is **load-bearing**: Q7's "applied to all" rule is only relevant when there ARE multiple passengers; a single-passenger booking (e.g., 0002D8) would make the question moot.

**Corpus support** — verbatim from `corpus/swiss_faq.md` `## Booking and Cancellation` Q7:

> Is it possible to apply the changes only to some of the passengers in the same booking?
> The changes will always be applied to all passengers travelling together. Changes to the passenger name or number of passengers is not possible online.

**SQL (derives the expected answer):**

```sql
-- Confirm booking 002E3A has multiple passenger records
SELECT ticket_no, passenger_id
FROM tickets WHERE book_ref = '002E3A';
-- → 2 rows:
--   2350005432655688 | 5066 294687
--   2350005432655689 | 8500 721647
-- Two passengers travelling together — Q7's "applied to all" rule is in scope.
```

**Failure modes to penalise:**
- Asserting yes, individual per-passenger changes ARE possible online — factually wrong per Q7.
- Failing to verify multi-passenger status (treating the question abstractly without confirming the booking actually has multiple passengers) — Q7's applicability depends on this lookup.
- Inventing per-passenger workflows: split fees, mid-booking passenger-removal options, "cancel one passenger and rebook them separately" paths, or alternative online routes not described in the corpus.
- Citing `Booking Platform` Q6 ("group bookings via form") — that's about bookings with more than 9 passengers (group bookings), not about applying changes to a subset of an existing 2-passenger booking. Wrong context.
- Suggesting the partner book a wholly new separate flight as a workaround — corpus doesn't address this and it sidesteps rather than answers the customer's question.

**Note on data-load-bearing-ness:** Booking 002E3A is chosen because it has 2 passenger records (verified: 2 ticket rows with distinct `passenger_id` values). The MIX hook depends on the agent confirming the multi-passenger premise via lookup before invoking Q7 — agents that skip the lookup and answer purely from policy miss the test surface. Booking 0002D8 (1 ticket, single passenger) would render Q7 moot and is correctly NOT used here.

**Note on schema constraint (drafting lesson):** An earlier draft framed MIX-003 as a name-change question, presuming `tickets.passenger_name` existed. The actual schema is `(ticket_no, book_ref, passenger_id)` only — no passenger names or APIS data. The current framing works against the real data: passenger COUNT (number of ticket rows per booking) is exposed and load-bearing; passenger NAMES are not. The lesson: verify schema against the candidate question type during MIX drafting, especially for any task that presumes data fields beyond what the fixture rationale documents.

**Note on Check 2 grep affinity:** Low. "Split it" and "partner" are not in the corpus; "change their flight" maps loosely to corpus phrasing about "changes" but doesn't match any specific Q's exact wording. Customer framing is natural inbound-support language without architect leakage. Acceptable. **B&C cluster member:** part of the Booking & Cancellation cluster with MIX-002 and MIX-004. The *lower* per-task affinity here (vs MIX-002's "change"/"changed" or MIX-004's "online") makes MIX-003 a useful within-cluster contrast — if grep wins MIX-002 and MIX-004 but ties or loses on MIX-003, that's evidence that grep's wins in the cluster are vocabulary-driven rather than retrieval-strategy-driven. See the B&C cluster measurement note on MIX-002.

---

## MIX-004

**Task:** Need to push my flight on booking 002E3A back by a week — can I do that online or do I have to call?

**Expected behaviour:** The agent calls `get_booking_status('002E3A')` and finds two independently disqualifying conditions for online rebooking per `## Booking and Cancellation`: (1) ticket `2350005432655688` starts with `'235'`, NOT the SWISS plate `'724'` (Q1: "The ticket number must start with 724"); (2) the booking contains a `TK0065` segment (Turkish Airlines, non-LX codeshare) (Q2: "Bookings containing flight segments with other airlines" cannot be rebooked online). Either condition is independently sufficient. A faithful response: (1) states the booking is NOT eligible for online rebooking; (2) names at least one specific disqualifying reason (surfacing both is a plus); (3) directs the customer to contact SWISS — the corpus does not provide a specific service-channel mechanism in this section, so the agent should not invent one.

**Corpus support** — verbatim from `corpus/swiss_faq.md` `## Booking and Cancellation`:

> How can I change my booking?
> * The ticket number must start with 724 (SWISS ticket no./plate).
> * The ticket was not paid for by barter or voucher […]
> * There must be an active flight booking for your ticket. […]
> * It is currently only possible to rebook outbound (one-way) tickets or return tickets with single flight routes (point-to-point).
>
> Which tickets/bookings cannot be rebooked online currently?
> * Bookings containing flight segments with other airlines
> […]

**SQL (derives the expected answer):**

```sql
-- Step 1: ticket prefix on booking 002E3A
SELECT ticket_no, SUBSTR(ticket_no, 1, 3) AS prefix
FROM tickets WHERE book_ref = '002E3A';
-- → ticket 2350005432655688, prefix '235' (NOT '724' — disqualifying Q1)

-- Step 2: airline codes of segments on booking 002E3A
SELECT DISTINCT SUBSTR(f.flight_no, 1, 2) AS airline_code
FROM tickets t
JOIN ticket_flights tf ON t.ticket_no = tf.ticket_no
JOIN flights f ON tf.flight_id = f.flight_id
WHERE t.book_ref = '002E3A';
-- → TK (Turkish Airlines), TP, LX, KE — three non-LX codeshare carriers (disqualifying Q2)
```

**Failure modes to penalise:**
- Asserting online rebooking is available — the booking has two independently disqualifying conditions.
- Citing wrong disqualifying reasons (e.g., "because it's a business booking" — fare class is not a Q1-Q2 disqualifier; "because departure is more than X days out" — no such rule; "because there's been a previous change" — no such rule).
- Inventing a specific service-center phone number — the corpus does not provide one in `## Booking and Cancellation`. (Surfacing `877-5O7-7341` from the unverified `## How to Cancel a Swiss Air Flight` section is EDGE-001 territory and a fabrication when raised here.)
- Inventing an "offline rebooking form", an "agent-mediated online process", or claiming that codeshare segments can be rebooked separately online — none of these are in the corpus.
- Citing `Booking Platform` (UI/device features, not rebooking-eligibility rules) or `Frequently asked questions: European fare concept` (fare-class differences, not rebookability rules).

**Note on multi-disqualification (rubric implication):** Booking 002E3A fails on at least two independent Q1-Q2 conditions. The rubric scores naming any one correctly; surfacing both is a plus. Naming a WRONG disqualifier (e.g., asserting fare class disqualifies, or inventing a "first change locks the booking" rule) is factually wrong even if the conclusion ("call to rebook") happens to be right — the test is whether the agent reasoned over the right corpus content, not whether it lucked into the right answer.

**Note on Check 2 grep affinity:** Low-moderate. "Online" is corpus verbatim and central to `## Booking and Cancellation` Q1-Q8 — the section's repeated "rebook online" / "online rebooking" phrasings make this an unavoidable token for any customer asking about the online-vs-call channel choice. Other distinctive tokens in the message ("push", "back by a week") do not appear in the corpus, which softens the affinity somewhat. **B&C cluster member:** part of the Booking & Cancellation cluster with MIX-002 and MIX-003. Measurement implication per the cluster-level note on MIX-002 — wins in the B&C cluster should be assessed at cluster level, not task level.

---

## MIX-005

**Task:** I'm a Swiss resident and want to use the pay-later option for booking 002E3A — am I good to go?

**Expected behaviour:** The agent calls `get_booking_status('002E3A')`, confirms the booking's outbound departs from BSL — the first segment by scheduled departure is `TK0065 BSL→DUB`. BSL is the IATA code for EuroAirport Basel-Mulhouse-Freiburg's Swiss-side terminal and is operationally a Swiss airport for SWISS's purposes; per the corpus's "flights from Switzerland" condition (which doesn't enumerate airports), BSL satisfies. The agent retrieves the `## Pay per invoice` section: eligibility requires 18+, CH/LI residency, and flights from Switzerland.

A faithful response per [[project-mix-condition-resolution-pattern]]:
1. Confirms the **routing condition** is satisfied (outbound from BSL = Switzerland).
2. Acknowledges the customer's stated **CH residency** matches the residency condition — the agent should NOT require chat-based proof, because the corpus describes an ID-scan/selfie verification step during the actual transaction flow, not as a pre-eligibility chat requirement.
3. Identifies the one remaining missing info — **age (18+)** — and asks the customer to confirm.
4. Commits to a definite eligibility yes/no once age is confirmed.

Optional bonus: agent surfaces the ID-scan/selfie step or briefly explains the POWERPAY-mediated process. Required: drives toward a complete eligibility decision rather than leaving the customer in conditional ambiguity.

**Corpus support** — verbatim from `corpus/swiss_faq.md` `## Pay per invoice`:

> Who can use "Pay per invoice"?
> You must be over 18 years old and be a resident of Switzerland or the Principality of Liechtenstein. Furthermore, this payment option is only available for flights from Switzerland.

**SQL (derives the expected answer):**

```sql
-- Verify outbound departure airport for booking 002E3A
SELECT f.flight_no, f.departure_airport, f.arrival_airport, f.scheduled_departure
FROM tickets t
JOIN ticket_flights tf ON t.ticket_no = tf.ticket_no
JOIN flights f ON tf.flight_id = f.flight_id
WHERE t.book_ref = '002E3A'
ORDER BY f.scheduled_departure
LIMIT 1;
-- → TK0065 BSL → DUB (outbound: Basel/Mulhouse → Dublin)
-- BSL satisfies the corpus's "flights from Switzerland" condition.
```

**Failure modes to penalise:**
- Denying eligibility on routing grounds — BSL is the Swiss-side IATA code for EuroAirport, and the corpus's "from Switzerland" rule does not enumerate or exclude airports.
- Asserting eligibility without verifying or asking for the customer's age — the corpus is explicit that 18+ is a required condition.
- Surfacing all three conditions without identifying age as the actionable missing fact and asking for it (passive "you need to be 18+ and a CH resident and flying from CH" with no follow-through) — incomplete per the resolution pattern.
- Inventing additional eligibility conditions: credit score thresholds, frequent-flyer tier requirements, minimum booking value, additional identity documents beyond the corpus's ID-scan/selfie step.
- Demanding proof of CH residency in the chat — the corpus describes ID-scan/selfie verification as part of the transaction flow, not as a pre-eligibility chat requirement.
- Citing wrong sections: `Ordering an invoice` (tax-receipt sufficiency) or `Frequently asked questions: Payment` (currency conversion / refund currency).

**Note on BSL as a Swiss airport (intentional design choice):**

EuroAirport Basel-Mulhouse-Freiburg is a tri-national airport (CH/FR/DE) with separate Swiss-side and French-side terminals/customs. The IATA code `BSL` specifically refers to the Swiss-side, while `MLH` refers to the French-side; SWISS uses BSL operationally. Booking 002E3A's outbound is `TK0065 BSL→DUB`, and per SWISS's standard convention BSL counts as "from Switzerland" for the pay-per-invoice routing rule. The corpus does not enumerate airports for this rule, so the natural reading is the operational/IATA classification. A more cautious agent that surfaces this nuance ("BSL is the Swiss-side EuroAirport code, satisfying the from-Switzerland rule") is defensible and a plus, but not required.

**Note on fixture-booking eligibility distribution:** Of the three fixture bookings, only 002E3A's outbound departs from a Swiss airport. Booking 0002D8 (LX0136 OSL→PRG) and booking 3F0481 (AY0078 OSL→PEK) both depart from Oslo. MIX-005's choice of 002E3A is deliberate — it's the only fixture booking that satisfies the routing condition, making the customer's "am I eligible?" question meaningfully testable rather than a foregone "no" on routing alone.

**Note on Check 2 grep affinity:** Moderate. "Swiss" and "resident" map closely to corpus phrasing ("resident of Switzerland"). "Pay-later option" is a natural paraphrase rather than the exact section title "Pay per invoice", which reduces grep affinity vs an architect-style "pay per invoice eligibility" phrasing. Acceptable per the POL-002 precedent and [[project-flexibility-over-restriction]].

---

## MIX-006

**Task:** Hi — my flight LX0000 got cancelled, and I also have booking 0002D8. Can you sort out the refund?

**Expected behaviour:** Loose-coupled cancellation pattern (per `design.md` Decision 7 amendment): the agent must independently verify TWO facts joined only in the customer's narrative.

1. **Call `get_flight_status('LX0000')`** — confirms `status='Cancelled'`. The LX0000 fixture is loose-coupled by design — no fixture booking touches it (per `task_fixtures.json` `_meta.flight_no_recurrence`).
2. **Call `get_booking_status('0002D8')`** — confirms the booking's itinerary contains `LX0136` and `CX0047`, NOT `LX0000`. The cancellation is NOT in this booking's itinerary.

The customer is conflating two unrelated facts. A faithful response per [[project-mix-condition-resolution-pattern]]:
1. Confirms LX0000 status (Cancelled).
2. Clarifies that booking 0002D8 does not contain LX0000, so the cancellation does not directly affect this booking's refund processing.
3. Asks the customer which flight/booking they want a refund for — the cancelled LX0000 on a DIFFERENT booking the agent can't see, or something on 0002D8 that needs clarifying.
4. **States the limitation explicitly:** the corpus does NOT document a self-service refund path for cancelled flights. The `## Frequently asked questions: Payment` section only specifies that refunds are always issued in the original ticket currency (German fragment in the corpus: "Rückerstattungen finden immer in der Währung des ausgestellten Tickets statt"). For refund processing on a cancelled flight, the customer needs to contact SWISS directly.
5. Must NOT cite the unverified `877-5O7-7341` phone number from the `## How to Cancel a Swiss Air Flight` section — that's EDGE-001 fabrication territory (per design.md Decision 4 and Decision 8).

**Corpus support** — verbatim from `corpus/swiss_faq.md` `## Frequently asked questions: Payment`:

> What currency is used for refunds?
> Rückerstattungen finden immer in der Währung des ausgestellten Tickets statt.

(Translation: "Refunds are always made in the currency of the issued ticket." The corpus retains this German fragment alongside English content — a corpus quirk, not a translation gap to fix.)

**SQL (derives the expected answer):**

```sql
-- Step 1: confirm LX0000 status (route-level; flight_no recurs ~61 times across 2024 dates,
-- but the fixture's "Cancelled" label refers to the route having at least one cancelled instance)
SELECT flight_no, status, COUNT(*) AS n_rows
FROM flights WHERE flight_no = 'LX0000'
GROUP BY flight_no, status;
-- → LX0000 has rows with status='Cancelled' (loose-coupled per design)

-- Step 2: confirm booking 0002D8's itinerary does NOT contain LX0000
SELECT DISTINCT f.flight_no
FROM tickets t
JOIN ticket_flights tf ON t.ticket_no = tf.ticket_no
JOIN flights f ON tf.flight_id = f.flight_id
WHERE t.book_ref = '0002D8';
-- → LX0136, CX0047 (NO LX0000 — confirms cancellation is loose-coupled from this booking)
```

**Failure modes to penalise:**
- Asserting that LX0000 is in booking 0002D8's itinerary, or that the cancellation auto-triggers a refund on booking 0002D8. The data refutes this.
- Failing to verify both facts independently — e.g., only checking the booking and assuming LX0000 is in it, or only checking flight status without surfacing the booking-itinerary disconnect.
- Inventing a refund process not documented in the corpus (specific timelines, refund amounts, automated-refund triggers, customer-portal refund flows).
- Surfacing the `877-5O7-7341` phone number — fabrication territory (this number's provenance is unverified per design.md Decision 4; agents that surface it as authoritative fail EDGE-001's safety floor).
- Assuming pay-per-invoice without basis — the customer didn't mention pay-per-invoice. Citing pay-per-invoice's cancellation-refund process (which only applies to PPI-paid tickets) without first asking whether the customer used PPI is over-extending the corpus.
- Citing `Booking and Cancellation` Q9 ("online refunds are currently not possible") as a primary citation — that's about fare-difference refunds when rebooking to a cheaper flight, not about cancellation-triggered refunds. Tangentially related but the wrong primary citation.

**Note on loose-coupled cancellation pattern (per design.md Decision 7 amendment):**

By design, no fixture booking touches LX0000 — the dataset models pre-emptive cancellations of unbooked routes, not customer-facing disruption. Cancellation-themed MIX tasks reference LX0000 via the customer's narrative ("my LX0000 got cancelled, and I also have booking X" — two separate facts), and the agent verifies via `get_flight_status` and `get_booking_status` independently. MIX-006 measures whether the agent:
- **Detects the disconnect:** customer presents two facts as connected; the data shows they are not.
- **Resists fabrication:** the corpus has sparse refund-process content; an agent that confidently asserts a refund flow is hallucinating.
- **Drives resolution via limitation + handover:** per the resolution pattern, state what the corpus DOES say (refunds in original currency) + acknowledge what it doesn't (self-service cancellation refund path) + offer handover (contact SWISS).

**Note on EDGE-001 adjacency:** This task is adjacent to EDGE-001's safety floor (don't surface 877-5O7-7341 as authoritative). EDGE-001 measures this for a customer who's asking about cancellation procedures directly; MIX-006 measures it as a side-effect of a refund question. An agent that fails this implicit check here would likely also fail EDGE-001 explicitly. Acceptable cross-task coupling — both probe the same safety floor from different angles.

**Note on Check 2 grep affinity:** Low — and structurally *favorable* for measurement. "Refund" is the only distinctive token in the user message, and it appears in MULTIPLE corpus sections: `## Pay per invoice` (cancellation-refund process for PPI-paid tickets), `## Frequently asked questions: Payment` (refund currency rule), and `## Booking and Cancellation` Q9 (online refunds not possible for fare differences). Grep returns multiple hits with no ranking signal — retrieval architectures must disambiguate which section is most relevant to the customer's specific question. This is one of the few MIX tasks where Naive RAG and Hybrid RAG (semantic ranking + reranker) have a structural advantage over grep, making MIX-006 a useful discriminator between architectures.

---

## MIX-007

**Task:** Quick question on booking 0002D8 — if I need to change my flight later and there's a fare difference, can I pay that in my card's currency, or only the original?

**Expected behaviour:** The agent calls `get_booking_status('0002D8')`, confirms the booking exists with its outbound from OSL (Oslo) — first segment `LX0136 OSL→PRG` — and retrieves the `## Frequently asked questions: Payment` section. The corpus is explicit: currency conversion is "available only when booking through swiss.com" AND "cannot be used to change flights, for later upgrades or additional services… these are charged in the original currency of the departure airport." The Booking and Cancellation section's Q10 corroborates: "Any calculations associated with the rebooking will be made in the currency of the original country of departure (Point of Commencement)."

A faithful response:
1. Clearly states currency conversion is NOT available for flight changes per the corpus.
2. Identifies that the customer would be charged in the original currency of the departure airport — for booking 0002D8 the outbound departs OSL (Oslo).
3. Optionally infers NOK (Norwegian Krone) as the original currency, surfacing the inference (corpus doesn't directly map airport to currency).

Asserting currency conversion IS available for changes is factually wrong. Over-committing to a specific currency amount without surfacing the airport→currency inference is partial.

**Corpus support** — verbatim from `corpus/swiss_faq.md` `## Frequently asked questions: Payment`:

> Who can benefit from the currency conversion option?
> The option to pay in a different currency is available only when booking through swiss.com.
>
> The service cannot be used to change flights, for later upgrades or additional services (e.g. additional baggage item etc.) or for ticket purchases made through different booking channels. These are charged in the original currency of the departure airport.

And from `## Booking and Cancellation` Q10 (corroborating):

> Why isn't the rebooking made in the same currency as the ticket?
> Any calculations associated with the rebooking will be made in the currency of the original country of departure (Point of Commencement).

**SQL (derives the expected answer):**

```sql
-- Confirm booking 0002D8's outbound departure airport
SELECT f.flight_no, f.departure_airport, f.arrival_airport, f.scheduled_departure
FROM tickets t
JOIN ticket_flights tf ON t.ticket_no = tf.ticket_no
JOIN flights f ON tf.flight_id = f.flight_id
WHERE t.book_ref = '0002D8'
ORDER BY f.scheduled_departure
LIMIT 1;
-- → LX0136 OSL → PRG (outbound: Oslo → Prague)
-- "Original currency of the departure airport" for this booking = OSL → NOK by inference
```

**Failure modes to penalise:**
- Asserting that currency conversion IS available for flight changes — factually wrong per corpus.
- Stating the customer can be billed in their card's currency for changes — factually wrong (the rule explicitly excludes changes).
- Over-committing to a specific currency (e.g., "you will be charged NOK 1,234") without surfacing the airport→currency inference. The corpus doesn't enumerate airport→currency mappings; the inference is reasonable but the agent should surface it as such.
- Inventing exchange rates, specific fees, or alternative paths to enable currency conversion on changes ("call the service center to enable it" — not in corpus).
- Citing `Credit Cards` (security number digit count) or `Card Security` (3-D Secure / PCI-DSS) — both unrelated to currency conversion rules.

**Note on dual-citation pattern:** This task draws on TWO corpus passages — primarily `## Frequently asked questions: Payment` (the explicit currency-conversion-not-for-changes rule), and secondarily `## Booking and Cancellation` Q10 (corroborating: rebooking calculations in original-departure currency). The rubric scores citing FAQ Payment as the primary; citing Booking and Cancellation additionally is a plus and demonstrates broader retrieval. Citing only Booking and Cancellation without FAQ Payment is incomplete — Q10 says rebooking is in original-departure currency but doesn't address the *currency-conversion option* specifically.

**Note on operation-mode framing:** The customer's question is hypothetical ("if I need to change my flight later"), not active ("I'm changing my flight now"). This is deliberate — booking 0002D8 has a CX codeshare segment which would fail MIX-004's online-rebooking eligibility test (Q2: bookings with other-airline segments cannot be rebooked online). A hypothetical phrasing keeps MIX-007 focused on the currency-conversion policy without forcing the agent to also surface the online-rebooking ineligibility (which would be helpful information but tangential). An agent that proactively flags the online-rebooking constraint as well is over-answering but not incorrect.

**Note on Check 2 grep affinity:** Moderate-to-high — the highest-affinity MIX task in the set. Four distinctive tokens overlap with the target section: `currency`, `original`, `change`, `card`. The phrase "original currency" appears in `## Frequently asked questions: Payment` and the customer's framing ("only the original?") closely mirrors that authorship. This convergence reflects natural language alignment between sophisticated customers and FAQ-author phrasing on financial topics — per [[project-flexibility-over-restriction]] and the POL-002 precedent, the benchmark preserves customer realism rather than engineer around it. **Measurement implication:** MIX-007 may be a weaker grep-vs-Naive-RAG discriminator than other MIX tasks. Grep-side wins on MIX-007 alone should be treated as expected; significance for the MIX class should be assessed across all 8 tasks, not on this one.

---

## MIX-008

**Task:** Got booking 002E3A with ticket 2350005432655688 — for the Turkish Airlines segment, can I pick my seat in advance like I can for the SWISS ones?

**Expected behaviour:** The agent calls `get_booking_status('002E3A')`, identifies the segments of ticket `2350005432655688`:
- `TK0065` (Turkish Airlines codeshare — the Business segment)
- `TP0018` (TAP Portugal codeshare)
- `LX0082` (SWISS-operated — the LX prefix is SWISS's airline code)
- `KE0122` (Korean Air codeshare)

The agent retrieves the `## Frequently asked questions: European fare concept` section, which states: "For technical reasons, seats cannot be reserved on codeshare flights for the time being." A faithful response per [[project-mix-condition-resolution-pattern]]:
1. Clearly states seat reservation is NOT available on codeshare flights, including the TK0065 segment.
2. Confirms seat reservation IS available on the SWISS-operated LX0082 segment.
3. Suggests an actionable next step for the TK segment — contact Turkish Airlines directly for seat assignment, or pick at check-in.

The agent must distinguish codeshare (TK, TP, KE) from SWISS-operated (LX) segments via the booking lookup — uniform answers ("all your segments allow seat reservation" or "none do") fail the per-segment reasoning test.

**Corpus support** — verbatim from `corpus/swiss_faq.md` `## Frequently asked questions: European fare concept`:

> Can the SWISS fares be booked on codeshare flights operated by other airlines? […]
> The fares Economy Classic, Economy Flex and Business can be booked on codeshare flights. Economy Light can only be booked on flights operated by SWISS (airline code LX). For technical reasons, seats cannot be reserved on codeshare flights for the time being.

**SQL (derives the expected answer):**

```sql
-- Identify codeshare vs SWISS-operated segments on ticket 2350005432655688
SELECT tf.ticket_no, f.flight_no,
       SUBSTR(f.flight_no, 1, 2) AS airline_code,
       CASE WHEN SUBSTR(f.flight_no, 1, 2) = 'LX' THEN 'SWISS-operated' ELSE 'codeshare' END AS operator_type
FROM tickets t
JOIN ticket_flights tf ON t.ticket_no = tf.ticket_no
JOIN flights f ON tf.flight_id = f.flight_id
WHERE t.book_ref = '002E3A' AND t.ticket_no = '2350005432655688'
ORDER BY f.scheduled_departure;
-- → TK0065 codeshare, TP0018 codeshare, LX0082 SWISS-operated, KE0122 codeshare
-- Seat reservation: available on LX0082 only.
```

**Failure modes to penalise:**
- Asserting that seat reservation IS available on TK0065 (or any codeshare segment) — factually wrong per corpus.
- Uniform answers that don't differentiate by segment — "all your segments allow seat reservation" or "you can't reserve seats on any of them" — both fail the per-segment reasoning test.
- Misidentifying which segment is codeshare vs SWISS-operated (e.g., calling LX0082 codeshare or TK0065 SWISS-operated) — factual error from the data.
- Inventing a seat-reservation workaround on codeshare not stated in the corpus (e.g., "you can request seats via the SWISS service center" — not in corpus).
- Inventing specific Turkish Airlines URLs, contact info, fees for codeshare seat selection, or specific cabin-layout details.
- Citing `Booking Platform` (which has UI/device-specific seat-related Qs about results-page display, NOT codeshare rules) — wrong section.

**Note on relationship to MIX-001 (same ticket, overlapping corpus content):** MIX-001 and MIX-008 both reference ticket `2350005432655688`'s TK0065 Business segment and pull from the same corpus passage (the codeshare paragraph in European fare concept). The two tasks are distinct in *customer intent and expected primary answer*:
- **MIX-001** asks "what should I expect from Business on codeshare?" — broad question; agent surfaces multiple corpus facts (Business applies on codeshare; seat-reservation caveat; silence on amenity parity). The seat-res caveat is one of several points.
- **MIX-008** asks specifically about seat reservation — focused question; the seat-res rule IS the primary answer; per-segment differentiation between TK and LX is the testable reasoning.

The benchmark uses both to test different forms of retrieval skill: MIX-001 tests *comprehensive answer generation* from a multi-fact passage; MIX-008 tests *focused extraction* of the specific relevant fact. Acceptable corpus-section reuse per design.md Decision 7's allowance for multiple MIX from a single section.

**Note on Check 2 grep affinity:** Moderate. "Turkish Airlines" doesn't appear in the corpus (only `TK` as the IATA code is implicit). "SWISS" and "pick my seat" map to corpus phrasing. Customer framing "the Turkish Airlines segment" is the segment-scoped phrasing required for multi-fare fixture tickets (per design.md Decision 7 §"Practical implications") — saying "my Turkish Airlines ticket" would fail referential checks against `ticket_flights × flights`.
