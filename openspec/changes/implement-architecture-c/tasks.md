# Tasks for implement-architecture-c

## 1. Inter-team grep tool (modularity constraint)

- [ ] 1.1 Implement `grep_corpus(keywords: list[str], max_results: int = 10, context_lines: int = 2)` in `tools.py` as Support Content's interface
- [ ] 1.2 Case-insensitive substring matching by default; ±2 lines of surrounding context per match
- [ ] 1.3 Result truncation to bound response size; deduplicate matches when multiple keywords overlap
- [ ] 1.4 Optional regex parameter available but not encouraged in the system prompt; default behavior is plain substring
- [ ] 1.5 The tool reads `corpus/swiss_faq.md` inside its own code path (Support Content's perimeter). Agent code does NOT shell out, does NOT read the file directly, and does NOT use `subprocess` for grep. This is the modularity check.
- [ ] 1.6 If the optional regex parameter is implemented, character-bound it (≤64 chars by default) and reject patterns containing nested quantifiers or known ReDoS-prone constructs. Use Python's `re` with a timeout if available, or pre-validate. Code-quality requirement per architecture README.
- [ ] 1.7 All SQL queries (Booking Systems tools) use parameterized statements; no string concatenation of user-derived input.

## 2. Reuse shared tools

- [ ] 2.1 Wire in Booking Systems tools (identical to Naive RAG — extract to shared module if Naive RAG is already done)
- [ ] 2.2 Wire in Compliance's `audit_log` per the uniform payload spec

## 3. Agent loop

- [ ] 3.1 Write system prompt in `prompts.py` targeting ~300-400 tokens. Instruct agent to extract search keywords from the user's question and call `grep_corpus`. Encourage iterative search if first attempt returns too few or irrelevant results. Explain how to interpret grep results (matching lines with context, not full document sections).
- [ ] 3.2 Implement agent loop — same shape as Naive RAG
- [ ] 3.3 Instrument token counting at every model call

## 4. Smoke test

- [ ] 4.1 Run agent on 2-3 hand-written tasks; verify completion
- [ ] 4.2 Verify token decomposition sums within 5% tolerance
- [ ] 4.3 Output to `measurement/results/architecture_grep_search.json` is well-formed JSON

## 5. "Done" criteria from architecture README

- [ ] 5.1 Successfully answers ≥2 of 3 pure-policy tasks (this is where Grep search's success rate matters most — if grep can find the right policy, the comparison is fair to all parties)
- [ ] 5.2 Successfully answers ≥2 of 3 pure-transactional tasks
- [ ] 5.3 Token decomposition is correct (5% tolerance) on all full-run tasks
