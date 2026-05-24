# Architecture B — Bounded Tools

No vector store. Policy content is served through targeted lookup tools, each returning curated text for a specific policy class.

The bet: when the policy taxonomy is known in advance (as it usually is for customer support), structured retrieval is more efficient than semantic retrieval.

## Files

| File           | Purpose                                                       |
|----------------|---------------------------------------------------------------|
| `agent.py`     | Main agent loop. Loads tools, handles tool-call cycle.        |
| `tools.py`     | Tool definitions: policy lookup tools plus transactional tools. |
| `prompts.py`   | System prompt — tighter than Architecture A.                  |
| `policies/`    | Curated policy text, one file per policy class.              |

## Design choices

### Policy retrieval

The FAQ corpus is partitioned into named policy classes during a one-time setup step. Each class becomes a tool. Examples:

- `get_rebooking_policy()` → returns the rebooking policy text
- `get_refund_policy()` → returns the refund policy text
- `get_baggage_policy()` → returns the baggage policy text
- `get_check_in_policy()` → returns the check-in policy text
- (etc., one per policy class identified in the corpus)

The agent picks the appropriate tool by name based on the user's question. This is the model's normal tool-selection behavior — it doesn't require any special routing logic.

### Why this works

Semantic retrieval is most useful when:
1. The query and the relevant content don't share vocabulary
2. The taxonomy of content is unknown or open-ended
3. The same content might match multiple plausible queries

None of these hold strongly for customer support over a fixed policy corpus. Policy classes are well-defined, the agent's model has strong intent-classification ability, and the matching from question to policy class is mostly trivial. Vector search is solving a problem that mostly doesn't exist in this setting.

### Tools

The agent has access to:

- One policy lookup tool per policy class (4-8 tools depending on corpus partitioning)
- Same transactional tools as Architecture A (`get_booking_status`, `search_flights`, etc.)

### Prompts

System prompt should be tighter than Architecture A's. Target ~150–250 tokens. Include:

- Agent persona (brief)
- Tool usage instructions ("call the appropriate policy lookup tool when the customer asks about policy")
- Refusal/escalation behavior

The reason this can be shorter: with named policy tools, the model doesn't need extensive guidance on retrieval. The tool names themselves communicate intent.

## Build sequence

1. Partition `corpus/swiss_faq.md` into named policy files in `policies/`. Done as a one-time setup, not at runtime. This is curation work.
2. Implement one tool function per policy file in `tools.py`. Each is a simple file-read that returns the policy text. Add the transactional tools (copied from Architecture A).
3. Implement the agent loop in `agent.py`. Same structure as Architecture A's loop.
4. Instrument token counting identically to Architecture A.

## What "done" looks like for this implementation

- Successfully answers at least 4 of 5 pure-policy tasks (the bar is the same as Architecture A; if Architecture B sacrifices correctness for cost, the comparison is invalid).
- Successfully answers at least 4 of 5 pure-transactional tasks.
- All token measurements logged to `measurement/results/architecture_b.json`.
- Decomposition sums to total tokens reported by the API (within 2% rounding).

## Known limitations

- **Policy taxonomy is closed.** Architecture B can only answer questions that fall into a defined policy class. Questions about policies not yet curated will fall through. Architecture A would (theoretically) handle them via semantic search, though the retrieval may surface tangentially related content.
- **Manual curation burden.** Each new policy class requires a code change (adding a tool). Architecture A absorbs new policy via re-indexing.
- **Tool schema overhead.** Having 4-8 policy tools means 4-8 schema definitions in every request. This is a known cost; the bet is that the schema overhead is less than the average retrieved-context overhead in Architecture A.

## What this implementation is making concrete

The argument the article makes — that "RAG is a permission system wearing retrieval clothing" — is most visible here. In Architecture A, the vector store mediates between Support Content (who owns the FAQ corpus) and AI Engineering (who consumes it). In Architecture B, that mediation has to be re-invented: either AI Engineering takes ownership of the policy text (a boundary shift), or Support Content publishes a structured registry (a new artifact and a new ownership boundary), or some process glue is built (brittle).

The token measurement is what makes this architectural choice quantifiable. The boundary question is what makes it organizationally hard.
