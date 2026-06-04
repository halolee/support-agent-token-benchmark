# §9 LLM-as-judge summary — 2026-06-04 sweep

**Source dataset:** `measurement/results/runs/2026-06-04-phase2-step8b/` (153 dispatches, frozen at commit `1dda831`)  
**Judge model:** `claude-opus-4-7` (temperature default — opus rejects the parameter; see judge.py and PR #45)  
**Generated:** 2026-06-04T05:16:55.390497+00:00  
**Judgments:** 153/153 successful, 0 errors, 0 score drift, 0 judge self-inconsistencies.  
**Cost:** ~$6.50 (320,156 input + 31,260 output tokens; caching helped only on EDGE-001's 9 calls).

> **This is not a publishable finding yet.** Per `BUILD_PLAN.md` §10 and `CLAUDE.md`, the adversarial review (equal-tuning, task-neutrality, counterfactual, steel-man-the-null, confidence statement) must complete before any number here replaces a `_TBD_` in `comparison.md`. Numbers below are raw judge output for the §10 reviewer to scrutinize, not headline claims.

## Headline pass rates

| Architecture | Tasks passed (n/153) | Mean fc | Mean cite | Mean nofab |
|---|---|---|---|---|
| `naive_rag` | 22/51 (43%) | 0.75 | 0.88 | 0.71 |
| `grep_search` | 21/51 (41%) | 0.76 | 0.87 | 0.67 |
| `hybrid_rag` | 20/51 (39%) | 0.83 | 0.91 | 0.68 |

All three architectures converge in the 39–43% range — a narrow spread that should itself be a §10 talking point. The factual_correctness and citation_accuracy dimensions are similar across architectures (0.75–0.83 fc, 0.87–0.91 cite); `no_fabrication` is the tightest cluster (0.67–0.71) and is where most failures concentrate.

## Per-class pass rates

| Architecture | Policy (n/9) | Transactional (n/9) | Mixed (n/24) | Edge (n/9) |
|---|---|---|---|---|
| `naive_rag` | 3/9 | 6/9 | 9/24 | 4/9 |
| `grep_search` | 3/9 | 5/9 | 10/24 | 3/9 |
| `hybrid_rag` | 1/9 | 4/9 | 12/24 | 3/9 |

- **Mixed is where `hybrid_rag` leads** (12/24 vs 9–10 for the others). Consistent with hybrid's design intent: BM25+vector reranking helps disambiguate multi-section queries.
- **Transactional favours `naive_rag`** (6/9 vs 4–5). Surprising — the booking tools are identical across architectures, so the difference reflects how the agent interprets tool results, not retrieval.
- **Policy is universally weak** (1–3/9). The 3 POL tasks are dominated by POL-003 (silent corpus) and POL-002 (multi-jurisdiction nuance) where all archs fail.
- **Edge favours `naive_rag` slightly** (4/9 vs 3/9) — driven by EDGE-002 (universal pass) and a partial EDGE-003 win that the other archs miss.

## Per-task matrix (majority of 3 runs)

| task_id | class | naive_rag | grep_search | hybrid_rag |
|---|---|---|---|---|
| POL-001 | policy | 2/3 ✅ | 3/3 ✅ | 1/3 ❌ |
| POL-002 | policy | 1/3 ❌ | 0/3 ❌ | 0/3 ❌ |
| POL-003 | policy | 0/3 ❌ | 0/3 ❌ | 0/3 ❌ |
| TXN-001 | transactional | 0/3 ❌ | 0/3 ❌ | 0/3 ❌ |
| TXN-002 | transactional | 3/3 ✅ | 3/3 ✅ | 3/3 ✅ |
| TXN-003 | transactional | 3/3 ✅ | 2/3 ✅ | 1/3 ❌ |
| MIX-001 | mixed | 0/3 ❌ | 0/3 ❌ | 1/3 ❌ |
| MIX-002 | mixed | 0/3 ❌ | 0/3 ❌ | 1/3 ❌ |
| MIX-003 | mixed | 3/3 ✅ | 3/3 ✅ | 2/3 ✅ |
| MIX-004 | mixed | 2/3 ✅ | 3/3 ✅ | 2/3 ✅ |
| MIX-005 | mixed | 0/3 ❌ | 0/3 ❌ | 0/3 ❌ |
| MIX-006 | mixed | 0/3 ❌ | 1/3 ❌ | 2/3 ✅ |
| MIX-007 | mixed | 1/3 ❌ | 0/3 ❌ | 1/3 ❌ |
| MIX-008 | mixed | 3/3 ✅ | 3/3 ✅ | 3/3 ✅ |
| EDGE-001 | edge | 0/3 ❌ | 0/3 ❌ | 0/3 ❌ |
| EDGE-002 | edge | 3/3 ✅ | 3/3 ✅ | 3/3 ✅ |
| EDGE-003 | edge | 1/3 ❌ | 0/3 ❌ | 0/3 ❌ |

### Tasks NO architecture passed (4)

- **POL-002** (policy): I'm filing my taxes and need to submit a receipt for my flight as a business expense. Do I need to ask you for a special…
- **POL-003** (policy): Quick question before I check out — does paying by credit card cost more than other methods?… — corpus is partial-silent on SWISS-side credit-card surcharge. Likely a rubric-vs-judge calibration question: agents that say 'SWISS does not surcharge' get penalised because the corpus doesn't literally state that, even though it's the most natural inference.
- **TXN-001** (transactional): Doing my expense report and I can't find the receipt for booking 002E3A. Can you tell me what I paid in total?… — booking total report with no documented currency. The rubric accepts 'raw 393000' or 'CHF 3,930.00' or 'CHF 393,000', so universal failure here is suspicious. **Investigate in §10.**
- **MIX-001** (mixed): Hi — I've got booking 002E3A with ticket 2350005432655688, and one segment in Business is operated by Turkish Airlines i…
- **MIX-002** (mixed): I already changed booking 0002D8 once last month — can I move my dates again, or is one change all I get?…
- **MIX-005** (mixed): I'm a Swiss resident and want to use the pay-later option for booking 002E3A — am I good to go?… — Swiss-resident pay-later eligibility with conditional resolution. Per `[[project-mix-condition-resolution-pattern]]` agents should ask for age (18+) before confirming. Universal failure suggests agents are either over-confirming or denying on routing grounds.
- **MIX-007** (mixed): Quick question on booking 0002D8 — if I need to change my flight later and there's a fare difference, can I pay that in …
- **EDGE-001** (edge): I need to cancel my upcoming flight on booking 0002D8 — what's the process? Can I just do it online or do I need to call… — **design-as-intended.** EDGE-001 is the safety-floor probe (`877-5O7-7341` suspect phone number). Universal failure here is the methodology gate, not an architecture flaw.
- **EDGE-003** (edge): I've got a Comfort segment on ticket 1050005434344662 (booking 3F0481) — what does that get me compared to Economy?…

### Tasks ALL architectures passed (4)

- **TXN-002** (transactional): Quick check — did my LX0086 leg on booking 3F0481 land OK? Trying to figure out if my next connection is going to work.…
- **MIX-003** (mixed): On booking 002E3A — my partner wants to change their flight to a different date but I want to keep mine. Can we split it…
- **MIX-004** (mixed): Need to push my flight on booking 002E3A back by a week — can I do that online or do I have to call?…
- **MIX-008** (mixed): Got booking 002E3A with ticket 2350005432655688 — for the Turkish Airlines segment, can I pick my seat in advance like I…
- **EDGE-002** (edge): I lost my booking confirmation from a SWISS flight a few months back and need a new copy — am I past the free window or …

## Cost comparison (excluding failed-majority cells)

Per METHODOLOGY: *'A task that an architecture fails is excluded from that architecture's cost comparison for that task.'* Failure here = majority (≥2 of 3 runs) of the (task, arch) cell scored `task_passed: false`. Median is over the 3 runs of each included cell, then aggregated across included tasks.

| Architecture | Included tasks | Total input tok | Median per task | Mean per task |
|---|---|---|---|---|
| `naive_rag` | 7/17 | 84,002 | 12,505 | 12,000 |
| `grep_search` | 7/17 | 97,211 | 14,687 | 13,887 |
| `hybrid_rag` | 6/17 | 84,879 | 14,056 | 14,146 |

- `naive_rag` is the cheapest **per included task** (median 12,505 input tok) AND has the highest pass rate. This contradicts the intuition that hybrid_rag's reranking should compensate for cost with quality. **Worth a steel-man-the-null pass in §10:** maybe POL/TXN tasks favouring naive's larger top-K accidentally inflate hybrid's failure rate, or maybe BGE-M3 + the 5% gate behaviour mis-attributes tokens.
- The 8B raw totals were naive 666K / grep 1.04M / hybrid 831K. After the pass filter, both naive and grep drop to ~7 tasks; hybrid to 6 tasks. The relative ordering between archs flips post-filter for hybrid vs grep.

## Forensics — what the side-car records show

- **0 judgments** had a coerced or off-grid score → judge emitted clean `{0.0, 0.5, 1.0}` on every call.
- **0 judgments** had a `task_passed_raw` disagreeing with the recomputed value → no self-inconsistency.
- **0 sweep errors** → no transient API failures or parse breakages.
- **Gate breach propagation** worked as intended: 2× POL-001/grep_search records (the known #23 gate-breach watchlist) carried `gate_breach=true` into the judgment side-car; both PASSED the judge. Confirms #23 is decomposition drift, not response-quality drift.
- **Caching**: triggered only on EDGE-001 (cache_w=2,305 once + cache_r=2,305 × 8). All other (task, run_index) prefixes were below Opus's ~1024-token breakpoint. Net savings ~$0.30 on this sweep.

## Manual review sample (stratified 10%, seed=20260604)

Per METHODOLOGY §'LLM-as-judge scoring': *'A 10% random sample of judgments is manually reviewed to detect judge-model bias.'* Sample weighted: POL=2, TXN=2, MIX=6, EDGE=5 + up to 5 borderline (any-dim=0.5). Stratification reflects the task-class distribution (3/3/8/3) and oversamples EDGE because those are the calibration probes.

| # | class | task_id | architecture | run | verdict | fc | cite | nofab | reviewer's call |
|---|---|---|---|---|---|---|---|---|---|
| 1 | edge | EDGE-001 | `grep_search` | 0 | FAIL | 0.5 | 0.5 | 0.0 | _TBD_ |
| 2 | edge | EDGE-001 | `grep_search` | 1 | FAIL | 0.5 | 0.5 | 0.0 | _TBD_ |
| 3 | edge | EDGE-001 | `naive_rag` | 1 | FAIL | 0.0 | 0.0 | 0.0 | _TBD_ |
| 4 | edge | EDGE-002 | `naive_rag` | 0 | PASS | 1.0 | 1.0 | 1.0 | _TBD_ |
| 5 | edge | EDGE-003 | `grep_search` | 0 | FAIL | 1.0 | 0.5 | 1.0 | _TBD_ |
| 6 | edge | EDGE-003 | `grep_search` | 1 | FAIL | 1.0 | 0.5 | 1.0 | _TBD_ |
| 7 | mixed | MIX-001 | `grep_search` | 2 | FAIL | 0.5 | 1.0 | 1.0 | _TBD_ |
| 8 | mixed | MIX-001 | `hybrid_rag` | 2 | FAIL | 1.0 | 1.0 | 0.5 | _TBD_ |
| 9 | mixed | MIX-002 | `naive_rag` | 0 | FAIL | 0.0 | 0.5 | 0.5 | _TBD_ |
| 10 | mixed | MIX-002 | `naive_rag` | 2 | FAIL | 0.5 | 1.0 | 1.0 | _TBD_ |
| 11 | mixed | MIX-003 | `grep_search` | 0 | PASS | 1.0 | 1.0 | 1.0 | _TBD_ |
| 12 | mixed | MIX-006 | `grep_search` | 2 | FAIL | 1.0 | 0.5 | 1.0 | _TBD_ |
| 13 | mixed | MIX-008 | `grep_search` | 1 | PASS | 1.0 | 1.0 | 1.0 | _TBD_ |
| 14 | mixed | MIX-008 | `hybrid_rag` | 1 | PASS | 1.0 | 1.0 | 1.0 | _TBD_ |
| 15 | policy | POL-001 | `grep_search` | 2 | PASS | 1.0 | 1.0 | 1.0 | _TBD_ |
| 16 | policy | POL-001 | `hybrid_rag` | 0 | FAIL | 1.0 | 1.0 | 0.5 | _TBD_ |
| 17 | policy | POL-001 | `naive_rag` | 2 | PASS | 1.0 | 1.0 | 1.0 | _TBD_ |
| 18 | transactional | TXN-001 | `grep_search` | 0 | FAIL | 1.0 | 1.0 | 0.5 | _TBD_ |
| 19 | transactional | TXN-002 | `grep_search` | 0 | PASS | 1.0 | 1.0 | 1.0 | _TBD_ |
| 20 | transactional | TXN-002 | `naive_rag` | 0 | PASS | 1.0 | 1.0 | 1.0 | _TBD_ |

Reviewer reads each judgment's `rationale` field from the corresponding `judgments_{arch}.json` and either confirms the judge or flags disagreement in the final column. Disagreement rate on this sample is the calibration signal feeding §10 Check 1.

## Open questions for §10 adversarial review

1. **Why does `naive_rag` win on cost AND pass rate?** Steel-man the null: is the comparison accidentally biased by retrieval-relevant rephrasing? `[[feedback-frozen-artifact-coverage]]` applies — re-trace the task set for grep-vs-vector signal.
2. **TXN-001 universal failure** is the highest-priority anomaly. The rubric explicitly accepts multiple correct answers; check whether the judge is reading the multi-answer clause correctly.
3. **POL-003 corpus-silent calibration:** is the rubric's 'no positive surcharge claim' criterion too strict? An agent that says 'I don't have specific surcharge info; banks may add fees' should arguably PASS but the judge may interpret 'no fabrication' as 'no positive claim either way.'
4. **MIX-005 conditional resolution:** are agents over-confirming Swiss-resident pay-later eligibility without asking about age? This is the `[[project-mix-condition-resolution-pattern]]` test case; if all archs fail, the task is doing its job, but it's worth confirming the judge isn't penalising the right behaviour.
5. **Hybrid RAG's weak policy performance** (1/9) is counterintuitive given its design. §10 should rule out: (a) reranker dropping the right chunk, (b) BM25 token-mangling on em-dashes in policy section names, (c) RRF tie-break asymmetry per #30.
6. **Judge non-determinism** (no `temperature=0`): within-cell variance is real (e.g. `naive_rag/POL-001` was PASS/FAIL/PASS across the 3 runs). The 10% manual review sample is the calibration tool. If variance is high, §10 should consider re-judging the borderline records with N≥3 and reporting agreement rate.

## Next blockers

- §10 adversarial review per `BUILD_PLAN.md` Step 10 — non-negotiable before `_TBD_` replacements in `comparison.md`.
- §11 template-driven `comparison.md` renderer per issue #42 (current `--report` clobbers the human-authored template).
- Manual review of the 15-record sample above; record disagreement rate in §10 Check 1.
