# Implement Grep search

## Why

Grep search is the contrarian heart of the experiment. Per `ARCHITECTURE_RATIONALE.md`, the "MCP/RAG vs CLI/grep" framing lives or dies on whether keyword search, wrapped as an LLM-callable tool, is actually competitive with semantic retrieval for this task class.

The bet Grep search tests: LLMs are excellent at picking keywords. They don't need vector search to do that part. For a corpus the size of a typical FAQ, a well-implemented grep tool may match or beat semantic retrieval on cost while providing comparable success rates.

Three outcomes are publishable:
- Grep search wins on cost AND success → vector search is over-engineering for this task class
- Grep search wins on cost but loses on success → cost/competence frontier exists, position depends on use case
- Grep search loses on both → semantic retrieval does real work, the contrarian claim falsified

## What changes

- Implement Support Content's `grep_corpus(keywords, max_results, context_lines)` tool — case-insensitive substring matching with surrounding context, result truncation, no regex by default
- Reuse Booking Systems' transactional tools and Compliance's `audit_log` (identical across architectures)
- Implement agent loop in `architectures/grep_search/agent.py` with a system prompt that instructs keyword extraction
- Smoke-test with 2-3 hand-written queries

## Impact

- **New code:** `architectures/grep_search/agent.py`, `tools.py`, `prompts.py`
- **No persisted artifacts:** the grep tool reads `corpus/swiss_faq.md` at query time inside Support Content's owned code path; no vector store or indices
- **Modifies:** nothing existing
- **Depends on:** `measurement/tokens.py` and `corpus/swiss_faq.md` being in place. Ideally implemented after Naive RAG so the Booking Systems tools are reusable rather than re-implemented.

## Modularity constraint compliance — critical for Grep search

This rule matters MORE for Grep search than for Naive RAG or Hybrid RAG because naive "grep" implies shell access. The agent code in this change must NOT shell out to `grep` or read `corpus/swiss_faq.md` directly. The grep functionality is implemented inside Support Content's `grep_corpus()` tool body — it happens to do substring matching, but the agent only sees the tool's structured response.

If you find yourself writing `subprocess.run(["grep", ...])` from the agent, that's the modularity violation.

## Adversarial review hooks

Per METHODOLOGY's Check 1 (equal tuning effort) and Check 2 (task set neutrality):

- The grep tool implementation must be polished — case-insensitive matching, sensible context window, result truncation — not a strawman version
- Task phrasings must not use keyword vocabulary that matches policy text verbatim. If a task says "rebooking" and the policy text says "rebooking," grep gets a free signal that doesn't reflect production conditions. See `measurement/tasks.md` "Critical rule" section.
