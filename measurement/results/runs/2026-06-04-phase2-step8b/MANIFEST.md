# §8 B paid run — 2026-06-04

Phase 2, BUILD_PLAN §8 B. First full paid sweep across the three v1 architectures.

## Provenance

- **Code commit:** `5a1a6e8` (`main`, post-#41 merge)
- **Command:** `python -m measurement.runner --architectures naive_rag,grep_search,hybrid_rag --tasks measurement/tasks.jsonl --runs 3`
- **Completed:** 2026-06-04T00:33 local (`config.completed_at` in each JSON for the precise UTC stamp)
- **Model:** `claude-sonnet-4-6`, `temperature=0.0`, `max_tokens=1024`, `MAX_TURNS=12`

## Headline counts

- **Dispatches:** 17 tasks × 3 archs × 3 runs = **153**
- **Errors:** 0
- **Retries:** 0
- **Max turns observed:** 9 (grep_search, EDGE-001) — well under the 12 ceiling
- **Decomposition drift:** within 5% on 150/153 records (3 grep_search records exceed; see below)

## Gate breaches (5% decomposition gate)

All three breaches are on `grep_search`, recorded with `gate_breach: true`:

| task | run | gate_ratio | status |
|------|-----|------------|--------|
| POL-001 | 1 | 5.6% | known watch item (issue #23) |
| POL-001 | 2 | 5.4% | known watch item (issue #23) |
| MIX-001 | 0 | 6.8% | **new — fold into #23** |

Per CLAUDE.md, breaches are flagged not silenced. Forensics belong in #23, not here.

## Not a finding yet

Input-token totals: naive 666K / grep 1.04M / hybrid 831K. These are **uncalibrated** — §9 (LLM-as-judge) must mark task-level pass/fail before any "exclude failed tasks from cost comparison" filter applies, and §10 (adversarial review) is non-negotiable before any number in `comparison.md` replaces a `_TBD_`.
