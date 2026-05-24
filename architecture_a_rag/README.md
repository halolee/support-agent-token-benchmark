# Architecture A — RAG + Tool Calls

The canonical pattern: a vector store over the FAQ corpus, with the agent retrieving top-K chunks per turn for policy questions, and tool calls for transactional queries.

This implementation is intentionally faithful to the [LangGraph customer support tutorial](https://github.com/langchain-ai/langgraph/blob/main/docs/docs/tutorials/customer-support/customer-support.ipynb), simplified to remove the dialog routing complexity that isn't relevant to the token comparison.

## Files

| File           | Purpose                                                  |
|----------------|----------------------------------------------------------|
| `agent.py`     | Main agent loop. Loads tools, handles tool-call cycle.   |
| `tools.py`     | Tool definitions: `lookup_policy`, `get_booking_status`, `search_flights`, etc. |
| `prompts.py`   | System prompt and any few-shot examples.                 |

## Design choices

### Retrieval

- **Embedding model:** `text-embedding-3-small` (OpenAI) — chosen for cost and broad availability. Documented as a measurement assumption.
- **Chunking strategy:** Split the FAQ corpus on H2 (`##`) headings, then further split chunks above 500 tokens at paragraph boundaries. Targets ~300-500 tokens per chunk.
- **Top-K:** 4. This is on the lower end of common defaults (4-8) to give RAG a fair shot — over-retrieval is a known waste pattern, so we measure with a tuned K rather than a naive one.
- **Retrieval threshold:** None in v1 (always return K chunks). A threshold would help RAG; absent it, RAG sometimes injects irrelevant context. Documented as a known limitation favoring Architecture B.

### Tools

The agent has access to:

- `lookup_policy(query: str)` — retrieves top-K chunks from the vector store. Returns concatenated chunk text with source markers.
- `get_booking_status(booking_id: str)` — queries `data/travel.sqlite` for booking details.
- `search_flights(origin, destination, date_range)` — flight lookup from the database.
- `search_hotels(...)`, `search_cars(...)` — additional transactional tools as needed by the task set.

### Prompts

System prompt should be representative of production-grade prompts. Target ~500 tokens (matching Silicon Data's reference decomposition). Include:

- Agent persona
- Behavior guidelines (be helpful, be concise, cite policy when invoked)
- Tool usage instructions
- Refusal/escalation behavior

Avoid:

- Few-shot examples in the system prompt (these inflate token counts; production teams typically move them to retrieved context)
- Repeated boilerplate (a real failure mode the article discusses)

## Build sequence

1. Set up the vector store: chunk `corpus/swiss_faq.md`, embed chunks, persist to a local Chroma or FAISS index in `architecture_a_rag/vector_store/`.
2. Implement tool functions in `tools.py`. Use the `data/travel.sqlite` database for transactional queries.
3. Implement the agent loop in `agent.py`. The loop:
   - Receives a user message.
   - Calls the model with the system prompt, user message, and available tools.
   - Executes any tool calls the model requests.
   - Feeds tool results back to the model.
   - Loops until the model produces a final response (no more tool calls).
4. Instrument token counting at every model call. Record per-call token usage and the decomposition (system prompt, retrieved context, user message, tool overhead, response).

## What "done" looks like for this implementation

- Successfully answers at least 4 of 5 pure-policy tasks.
- Successfully answers at least 4 of 5 pure-transactional tasks.
- All token measurements logged to `measurement/results/architecture_a.json`.
- Decomposition sums to total tokens reported by the API (within 2% rounding).

## Known limitations

- Embedding API calls (one per query) are excluded from the per-task cost number per `METHODOLOGY.md`. Their inclusion would add ~$0.00002 per task at current pricing — negligible but non-zero.
- The vector store is rebuilt from scratch on each fresh clone. Production deployments would persist the index and re-index incrementally on corpus changes.
- No retrieval quality monitoring or drift detection.
