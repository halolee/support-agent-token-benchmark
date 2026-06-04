# Phase 3 Step 12 paid run — 2026-06-04

Phase 3, BUILD_PLAN §12. Cached RAG sweep via Option Y (cost-only, no re-judge; quality inherited from Naive RAG by construction).

## Provenance

- **Code commit:** `f32ffe3` (`main`, post-Step 11.5 caching-aware gate)
- **Command:** `python -m measurement.runner --architectures cached_rag --runs 3 --results-dir measurement/results/runs/2026-06-04-phase3-step12-cached-only` (originally launched into `runs/` at repo root; moved to canonical `measurement/results/runs/` immediately post-sweep)
- **Completed:** 2026-06-04 (see `architecture_cached_rag.json` `config.completed_at` for precise UTC)
- **Model:** `claude-sonnet-4-6`, `temperature=0.0`, `max_tokens=1024`, `MAX_TURNS=12`
- **Sweep protocol:** single-architecture, no alternation (Option Y asterisk — see `comparison.md` §"Confidence and known biases")

## Headline counts

- **Dispatches:** 17 tasks × 1 arch × 3 runs = **51**
- **Errors:** 0
- **Retries:** 0
- **Gate breaches (caching-aware 5% gate):** 0 (mean gate ratio 1.9%, max 2.9% — well under tolerance)
- **Caching fired:** 51/51 dispatches (`cache_read_input_tokens > 0` on every run)
- **Max turns observed:** 5 (MIX-001) — under the 12 ceiling

## Caching telemetry (mean across 51 dispatches)

| Counter | Mean tokens / run | Share of total input |
|---|---:|---:|
| `api_input_tokens` (standard-priced, $3/MTok) | 6,651 | 48.2% |
| `cache_creation_input_tokens` ($3.75/MTok) | 1,329 | 7.6% |
| `cache_read_input_tokens` ($0.30/MTok) | 5,882 | 44.2% |
| `api_output_tokens` ($15/MTok) | 1,100 | — |

## Cost

| | Mean / run | Total (51 runs) |
|---|---:|---:|
| Naive RAG (reference, from v1 sweep) | $0.0548 | $2.79 |
| Cached RAG (this sweep) | **$0.0432** | **$2.20** |
| Savings | $0.0116 (−21.1%) | $0.59 |

Input-side savings: 32%. Output cost unchanged (caching does not affect output pricing). Article-worthy finding: caching shifts cost *shape*, not magnitude — see `comparison.md` §"Caching effect on cost" and §"Cached RAG cost-shape shift."

## Quality

Inherited from Naive RAG by construction (Option Y). No judge sweep was run on this dispatch set. Caching-fires spot-check (3 tasks pre-sweep) confirmed:
1. `cache_read_input_tokens > 0` on turn 2+ (caching wired correctly)
2. Tool-call sequences match Naive RAG on the same tasks
3. Responses semantically equivalent to Naive RAG's

Re-judging deferred to v2 quality re-measurement series (will run blinded judge + Hybrid RAG bug fixes + caching variants for Grep / Hybrid all together).

## Files

- `architecture_cached_rag.json` — per-dispatch records (token counts, decomposition, cache counters, tool sequences, response text, gate ratio)
- `sweep.log` — runner stdout/stderr for forensics
- `MANIFEST.md` — this file
