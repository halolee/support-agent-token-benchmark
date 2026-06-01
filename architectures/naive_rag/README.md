# Naive RAG

The canonical tutorial pattern. Vector store, top-K retrieval, LLM agent with tool calls.

This implementation is intentionally faithful to the [LangGraph customer support tutorial](https://github.com/langchain-ai/langgraph/blob/main/docs/docs/tutorials/customer-support/customer-support.ipynb), simplified to remove dialog routing complexity that isn't relevant to the token comparison.

## Why this architecture is in the comparison

See `ARCHITECTURE_RATIONALE.md`. Brief: A is the popular default and the source of most misconceptions about "RAG." It's what gets shipped at v1, what job postings describe, and the baseline every other architecture has to be compared against.

## Files

| File           | Purpose                                                  |
|----------------|----------------------------------------------------------|
| `agent.py`     | Main agent loop. Loads tools, handles tool-call cycle.   |
| `tools.py`     | Tool definitions. Tools represent inter-team interfaces (see HANDOVER) |
| `prompts.py`   | System prompt and agent instructions.                    |
| `setup_vector_store.py` | One-time script to chunk corpus and build vector store |

## Modularity constraint compliance

Per METHODOLOGY, all architectures respect simulated team boundaries.

- **Support Content's interface:** `vector_search(query: str, k: int) -> list[Chunk]`. Implemented in `tools.py` but represents what Support Content publishes. AI Engineering's agent calls it; doesn't reach into the vector store directly.
- **Booking Systems' interface:** `get_booking_status`, `search_flights`, etc. Identical across all architectures.
- **Compliance interface:** `audit_log(event)`. Identical across all architectures.

The vector store itself (`vector_store/` directory) is conceptually owned by Support Content — its existence, configuration, and lifecycle are their concern. AI Engineering only sees the tool response.

## Design choices

### Retrieval

- **Embedding model:** `BAAI/bge-m3` (self-hosted, MIT-licensed) — the 2026 enterprise self-hosted default. See METHODOLOGY §"Model and configuration" for the reasoning behind self-hosted over API-based embedding
- **Chunking strategy:** Split FAQ corpus on H2 (`##`) headings, then further split chunks above 500 tokens at paragraph boundaries. Targets ~300-500 tokens per chunk
- **Top-K:** 4. Lower end of common defaults (4-8) to give A a fair shot — over-retrieval is a known waste pattern. Adversarial review verifies this is tuned, not just defaulted
- **Retrieval threshold:** None in v1 (always return K chunks). Documented limitation

### Tools

- `vector_search(query: str, k: int = 4)` — Support Content's retrieval interface
- `get_booking_status(booking_id: str)` — Booking Systems
- `search_flights(origin, destination, date_range)` — Booking Systems
- Additional Booking Systems tools as needed
- `audit_log(event_type, details)` — Compliance

All tool implementations use parameterized SQL queries; no string concatenation into database paths. Input validation is a code-quality requirement, addressed during Phase 2 implementation (see `openspec/changes/implement-architecture-a/tasks.md`).

### Prompts

System prompt targets ~500 tokens. Include agent persona, behavior guidelines (be helpful, concise, cite policy), tool usage instructions, refusal/escalation behavior.

Avoid few-shot examples in system prompt (inflates tokens) and repeated boilerplate.

## What "done" looks like

- Successfully answers at least 2 of 3 pure-policy tasks
- Successfully answers at least 2 of 3 pure-transactional tasks
- All token measurements logged to `measurement/results/architecture_a.json`
- Decomposition sums to total tokens reported by API (within 5%)

## Known limitations

- Embedding compute (BGE-M3 inference on CPU) excluded from per-task cost. Adds ~30-100ms of local CPU time per query — non-zero but not a token cost
- Vector store rebuilt from scratch on fresh clone
- No retrieval quality monitoring or drift detection
- BGE-M3 model weights (~2.3GB) must be downloaded once; subsequent runs use the local cache
