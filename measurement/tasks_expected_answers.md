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

**Note on adjacent corpus content (do not exercise here):** `## Invoice Questions` Q1 (line 5) also discusses invoices but focuses on the free re-issuance window — and asserts **100 days**, while `## Ordering an invoice` asserts **90 days** for the same rule. POL-002 is framed around tax-receipt sufficiency, not re-issuance timing, so this inconsistency is deliberately not in scope. The conflict is recorded as a candidate EDGE-002 synthesis-with-conflict framing (see [[project-corpus-inconsistency-handling]] in memory; deferred to a separate design call when EDGE drafting begins).

---

## POL-003

**Task:** Quick question before I check out — does paying by credit card cost more than other methods?

**Expected behaviour:** The agent recognises this as a "credit-card surcharge" question and surfaces both relevant facts from `## Frequently asked questions: Payment` Q4: (1) SWISS itself does not add credit-card surcharges; (2) some banks may charge additional fees in individual cases over which SWISS has no influence. Best-form responses surface both — a blanket "no extra fees" is incomplete because it omits the bank-side caveat.

**Corpus support** — verbatim from `corpus/swiss_faq.md` `## Frequently asked questions: Payment`:

> Will there be any other credit card charges?
> Some banks might charge additional fees in individual cases. SWISS has no influence over these charges.

**Failure modes to penalise:**
- Claiming a blanket "no, credit card is free" without the bank-side caveat.
- Inventing specific surcharge percentages (e.g., "2.5%") or named third-party processors.
- Conflating with currency-conversion fees (Q1–3 in the same section) unless the customer asked about foreign currency — those are a separate topic and asserting them here is over-answering.
- Citing the wrong section (e.g., `## Credit Cards`, which covers CVV location, not surcharges).
