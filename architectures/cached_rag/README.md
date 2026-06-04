# Cached RAG

Naive RAG with Anthropic prompt caching enabled on the two stable-prefix blocks (system prompt + tool definitions). The retrieval logic, vector store, chunking strategy, top-K, and tool implementations are byte-identical to Naive RAG; the only differences are:

1. `prompts.py` exports `SYSTEM_PROMPT` as a list of typed Anthropic blocks with `cache_control={"type": "ephemeral"}` instead of a plain string.
2. `tools.py` attaches `cache_control={"type": "ephemeral"}` to a Cached-RAG-only copy of `AUDIT_TOOL_SCHEMA` placed at the end of `TOOL_SCHEMAS`. The shared schema (used by Naive RAG, Grep search, Hybrid RAG) is not mutated.
3. `agent.py` registers under `"cached_rag"` instead of `"naive_rag"`.

The shared agent loop (`architectures/_shared/agent_loop.py`) is unchanged — it already tracks `cache_creation_input_tokens` and `cache_read_input_tokens` on every `client.messages.create()` response.

## Why this architecture is in the comparison

See `ARCHITECTURE_RATIONALE.md`. Brief: Cached RAG quantifies the headline cost optimization Anthropic and OpenAI both publicize. The v1 Naive RAG measurement shows ~1.7K tokens of system prompt + ~4.7K tokens of tool overhead per call. Both are stable across all 51 tasks and across multi-turn loops within a task — that's the cacheable prefix. Without measuring caching, the Naive RAG cost number is the un-optimized baseline.

## What's cached vs. what isn't

| Token category | Stability | Cached? | Why |
|----------------|-----------|---------|-----|
| ① System prompt (~1,693 tokens, v1 Naive RAG mean) | Stable across all tasks and turns | YES — `cache_control` on the system block | Stable cacheable prefix |
| ④ Tool definitions (~4,746 tokens, v1 Naive RAG mean) | Stable across all tasks and turns | YES — `cache_control` on the last tool entry | Stable cacheable prefix |
| ② Retrieved context (~5,041 tokens, v1 Naive RAG mean) | **Varies per query** | NO | Different queries retrieve different chunks; no stable prefix |
| ③ User message | Varies per task | NO | Different per task by definition |
| ⑤ Agent intermediate (multi-turn accumulator) | Varies per task and turn | NO | Tool-use blocks and assistant text differ per task |

The two cached blocks consume two of Anthropic's four available cache breakpoints per request, leaving headroom for future experiments.

## Hypothesis

Per `BUILD_PLAN.md` Phase 3 §"Hypothesis worth pre-registering": Cached RAG median input cost expected to drop **50–80%** vs Naive RAG, contingent on cache hit rate within the 5-minute ephemeral TTL. The cacheable prefix is ~6,440 tokens (① + ④); standard input is $3/MTok, cache read is ~$0.30/MTok — so each cache hit on the prefix saves ~$0.0174 per turn. A 51-task × 3-runs × ~3-turns/task sweep is ~459 model calls; if 80% of those hit cache, savings are ~$6.4 vs Naive RAG's full-price baseline.

If the observed drop is <30%, that's a finding about cache-hit rate under realistic loops (e.g., TTL expires between tasks faster than expected). Either result is publishable.

## Files

| File           | Purpose                                                  |
|----------------|----------------------------------------------------------|
| `agent.py`     | Thin wrapper. Identical to Naive RAG's agent.py except `architecture="cached_rag"`. |
| `tools.py`     | Tool definitions. Identical retrieval/booking/audit logic; one cache_control marker on a copy of AUDIT_TOOL_SCHEMA. |
| `prompts.py`   | System prompt. Identical text; exported as a typed-block list with cache_control instead of a string. |
| `setup_vector_store.py` | Identical to Naive RAG's. Builds the same BGE-M3 ChromaDB collection from `corpus/swiss_faq.md`. |

## Modularity constraint compliance

Identical to Naive RAG. Caching is a wire-format concern, not a team-boundary concern. Support Content still publishes `vector_search`; AI Engineering still calls it without reaching into the vector store directly.

## Design choices

### Cache breakpoint placement

Two breakpoints, on the two stable-prefix blocks. We do NOT cache retrieved chunks because:

- Each `vector_search` call produces a fresh set of chunks based on the query embedding.
- The same task across runs *might* produce identical chunks (deterministic embeddings + same corpus), but cross-task chunks differ.
- Prefix caching requires byte-identical prefixes; per-query chunks break the prefix immediately.

A future architecture variant (Bounded tools with stable categorical retrieval) might cache retrieved content; that's scoped for v2 in `ROADMAP.md`.

### Cache TTL

Ephemeral (5-minute) cache breakpoints. The 1-hour extended cache TTL (requires `extended-cache-ttl-2025-04-11` beta header) would be useful for very long sweep durations, but our 51-task sweep finishes well within 5 minutes per run, so ephemeral is sufficient.

## What "done" looks like

- Caching-fires spot-check passes (3 tasks): `cache_read_input_tokens > 0` on turn 2+, tool-call sequences match Naive RAG, responses read as semantically equivalent.
- Full 51-task sweep run, 3 runs each (cost-only; quality assumed equivalent to Naive RAG by construction — see `BUILD_PLAN.md` Phase 3 Step 12 Option Y).
- `cache_read_input_tokens` populated on every response after the first turn.
- All token measurements logged to `measurement/results/architecture_cached_rag.json` (or equivalent dated dir).
- Decomposition sums to total tokens reported by API (within 5%) — same gate as Naive RAG. Caching changes pricing, not token counts.

## Known limitations

- Cache hits depend on the 5-minute ephemeral TTL. If the sweep is paused or rate-limited mid-run, the cache may expire and subsequent reads pay full price. Document any expiry events in the run dir.
- Caching pricing for `claude-sonnet-4-6`: cache write is 1.25x input price, cache read is ~10% of input price. Documented in METHODOLOGY § "Cached RAG cost model."
- Quality is not independently re-judged in Phase 3 — Cached RAG inherits Naive RAG's quality numbers under the "caching is server-side optimization; model sees identical input tokens" argument. The v2 quality re-measurement series will re-judge both architectures with the blinded judge prompt; see `ROADMAP.md`.
