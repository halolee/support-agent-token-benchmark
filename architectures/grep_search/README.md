# Grep search

Keyword search exposed as a tool. The agent picks search terms; grep returns matching lines with context.

## Why this architecture is in the comparison

See `ARCHITECTURE_RATIONALE.md`. Brief: C is the contrarian heart of the experiment. The "MCP/RAG vs. CLI/grep" argument lives or dies on whether keyword search, wrapped as a tool the LLM calls, is actually competitive with semantic retrieval for this class of task.

The bet: LLMs are excellent at picking keywords. They don't need vector search to do that. For a corpus the size of a typical FAQ, a well-implemented grep tool may match or beat semantic retrieval on cost while providing comparable success rates.

## Files

| File           | Purpose                                                  |
|----------------|----------------------------------------------------------|
| `agent.py`     | Main agent loop                                          |
| `tools.py`     | Tool definitions including the grep tool                 |
| `prompts.py`   | System prompt instructing the agent to pick keywords     |

## Modularity constraint compliance

Per METHODOLOGY, all architectures respect simulated team boundaries. This matters especially for Grep search because naive "grep" implies file system access, which would violate the boundary.

- **Support Content's interface:** `grep_corpus(keywords: list[str], max_results: int = 10) -> list[Match]`. Implemented as a tool exposed by Support Content. AI Engineering's agent does NOT shell out to grep directly on the corpus file — it calls the tool, which performs the search inside Support Content's owned code path.
- **Booking Systems' interface:** Identical to Naive RAG
- **Compliance interface:** Identical to Naive RAG

The grep tool is structured to feel like grep — case-insensitive substring matching, returns matching lines with N lines of context, truncates results — but it's exposed as a structured tool with a defined contract, not as raw shell access.

## Design choices

### Grep tool implementation

- **Case-insensitive matching** (default; can be toggled per call)
- **Context window:** ±2 lines around each match
- **Result truncation:** max 10 matches by default to bound response size
- **Multi-keyword support:** when multiple keywords passed, returns matches for each, deduplicated
- **No regex by default** to keep the tool predictable for the LLM (regex available as optional parameter, but not encouraged)

This is grep done thoughtfully — not raw `grep -i` from a shell, but the moral equivalent exposed safely as a tool. The point is to test whether keyword retrieval is sufficient, not to test whether the cheapest possible implementation wins.

### Tools

- `grep_corpus(keywords: list[str], max_results: int = 10, context_lines: int = 2)` — Support Content's keyword retrieval
- All Booking Systems tools (identical to A)
- `audit_log` (identical to A)

All tool implementations use parameterized SQL queries; the grep tool's optional regex parameter is character-bounded (≤64 chars by default) to prevent ReDoS. Input validation is a code-quality requirement, addressed during Phase 2 implementation (see `openspec/changes/implement-architecture-c/tasks.md`).

### Prompts

System prompt should:
- Instruct the agent to extract search keywords from the user's question
- Encourage iterative search if first attempt returns too few or irrelevant results
- Explain how to interpret grep results (matching lines with context, not full document sections)

Target ~300-400 tokens. The prompt can be tighter than Naive RAG's because there's less retrieval orchestration to explain.

## What "done" looks like

- Successfully answers at least 2 of 3 pure-policy tasks (this is where C's success rate matters most — if grep can find the right policy, the comparison is fair)
- Successfully answers at least 2 of 3 pure-transactional tasks
- All token measurements logged to `measurement/results/architecture_c.json`
- Decomposition sums correctly

## Known limitations

- Grep depends on the LLM picking the right keywords. Failure mode: vague query → vague keywords → poor matches → bad answer. Documented in adversarial review.
- No fuzzy matching, no stemming, no synonym handling in v1. Production grep tools often add these; v1 keeps it pure to test the baseline claim.
- Result truncation may discard relevant matches when corpus has many references to the search term. Tuning required.

## What this architecture demonstrates

If C performs competitively on cost AND success rate, the article's contrarian claim is validated: vector search may be over-engineering for tasks where the LLM can pick keywords. If C performs competitively on cost but loses on success rate, the article's claim becomes more nuanced: there's a cost/competence frontier, and the right point depends on what you're willing to sacrifice. If C performs poorly on both, the article's claim is falsified — semantic retrieval is doing real work even for this class of task. All three outcomes are publishable findings.
