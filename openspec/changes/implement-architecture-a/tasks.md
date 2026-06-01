# Tasks for implement-architecture-a

## 1. Vector store setup

- [ ] 1.1 Implement `setup_vector_store.py` to chunk `corpus/swiss_faq.md` per the chunking strategy in `architectures/naive_rag/README.md` (H2 boundaries, ~300-500 tokens, paragraph-split for overflow chunks above 500 tokens)
- [ ] 1.2 Embed chunks with BGE-M3 via `sentence-transformers` or `FlagEmbedding` and persist to ChromaDB (or FAISS) in `architectures/naive_rag/vector_store/`
- [ ] 1.3 Confirm chunk count matches expectation from Phase 1 Step 0 corpus inventory; embedding dimensions match BGE-M3 (1024)

## 2. Inter-team tools (modularity constraint)

- [ ] 2.1 Implement `vector_search(query: str, k: int = 4)` in `tools.py` as Support Content's interface; returns list of chunks with source markers
- [ ] 2.2 Wire in shared Booking Systems tools (`get_booking_status`, `search_flights`, `search_hotels`, `search_cars`) — these may live in a shared module if extracted later, but Naive RAG is responsible for getting them working first
- [ ] 2.3 Wire in Compliance's `audit_log(task_id, response, tools_called)` per the uniform payload spec in METHODOLOGY §"Audit log specification"
- [ ] 2.4 Verify agent code does NOT read `corpus/swiss_faq.md` or query `data/travel.sqlite` directly — only through the tools above. This is the modularity constraint check.
- [ ] 2.5 Tool implementations use parameterized SQL queries throughout (`?` placeholders in SQLite); no f-string or `%` concatenation of user input into queries. Code-quality requirement per architecture README.

## 3. Agent loop

- [ ] 3.1 Write system prompt in `prompts.py` targeting ~500 tokens. Include: agent persona, behavior guidelines (be helpful, concise, cite policy), tool usage instructions, refusal/escalation behavior. Avoid few-shot examples and repeated boilerplate.
- [ ] 3.2 Implement agent loop in `agent.py`: receive user message → call model with system prompt + tools → execute tool calls → feed results back → loop until no-tool-call response
- [ ] 3.3 Instrument token counting at every model call by calling into `measurement/tokens.py`

## 4. Smoke test

- [ ] 4.1 Run agent on 2-3 hand-written tasks; verify it completes end-to-end
- [ ] 4.2 Verify token decomposition sums to API-reported `input_tokens` within 5% (per METHODOLOGY's tolerance)
- [ ] 4.3 Output to `measurement/results/architecture_naive_rag.json` is well-formed JSON

## 5. "Done" criteria from architecture README

- [ ] 5.1 Successfully answers ≥2 of 3 pure-policy tasks (when the full task set is run)
- [ ] 5.2 Successfully answers ≥2 of 3 pure-transactional tasks
- [ ] 5.3 Token decomposition is correct (5% tolerance) on all full-run tasks
