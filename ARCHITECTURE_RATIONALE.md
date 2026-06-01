# Architecture Rationale

This document explains why each measured architecture was chosen and why others were deferred or excluded. The selection was made against an explicit framework rather than by accumulation.

## The selection framework

For each candidate architecture, four questions:

1. **What's popular?** What enterprises actually deploy.
2. **What are the misconceptions?** Where the popular pattern is misapplied.
3. **What's the industry standard?** What "good" looks like, not what's most common.
4. **What's our assumption?** What we're implicitly treating as true that deserves measurement.

An architecture earns measurement if it surfaces a misconception, represents a real standard, or tests one of our assumptions. Architectures that fail all four filters get mentioned in the article but not measured.

## Architectures included in v1

### Naive RAG

Vector store, top-K=4 retrieval, LLM agent with tool calls.

- **Popular?** Yes — the default tutorial pattern.
- **Misconception?** Major: people conflate "naive top-K RAG" with "RAG" in general. They're different things with different cost profiles.
- **Industry standard?** No — naive RAG is the *starting point* that mature teams iterate away from.
- **Our assumption?** That A represents the canonical pattern. It does represent the canonical *tutorial* pattern, which is different from what production teams actually run.

**Why measure it:** It's what gets shipped at v1. It's what job postings describe. It's the floor of the comparison — every other architecture is competing against this.

**Article angle:** "This is what you're paying for if you let your team build straight from tutorials."

### Cached RAG

Same as Naive RAG. Anthropic prompt caching enabled on system prompt and stable retrieved chunks.

- **Popular?** Increasingly. Anthropic's 90% caching discount is now well-known.
- **Misconception?** That caching is a separate optimization layer added later. It's actually a property of prompt architecture — stable prefixes matter.
- **Industry standard?** For teams aware of it, yes. Many teams aren't aware.
- **Our assumption?** That measuring Naive RAG *without* caching gives a fair view of its real production cost. It doesn't — comparing Naive-RAG-without-caching to anything else overstates Naive RAG's cost relative to what production teams actually pay.

**Why measure it:** Without this baseline, the comparison is unfair to RAG. The result we expect — that caching collapses Naive RAG's cost dramatically — needs to be the published number, not an asterisk.

**Article angle:** "Before deciding RAG is expensive, check whether you've enabled prompt caching. It collapses the cost more than any architectural change."

### Grep search

A `grep`-style search tool (case-insensitive, with reasonable result truncation) exposed by Support Content. The LLM agent picks keywords and calls the tool; grep returns matching lines with context.

- **Popular?** No — almost nobody builds this as a "production AI pattern" because it sounds primitive.
- **Misconception?** That keyword search is obsolete for AI agents. It isn't — LLMs are excellent at picking the right keywords; they don't need vector search for that part.
- **Industry standard?** No, but arguably should be the starting point for many internal-facing agents.
- **Our assumption?** That grep "fails on tasks where semantic understanding matters." This may be less true than we assume — the LLM does the semantic understanding, grep just has to find the right document.

**Why measure it:** This is the article's contrarian heart. The "MCP/RAG vs. CLI/grep" argument lives or dies on whether C is actually competitive.

**Article angle:** "Your platform team is building a vector store for a problem grep would solve. Before accepting the vector store as a given, can you justify it against a grep baseline?"

### Hybrid RAG

Vector search + BM25 keyword search combined, with a reranking pass on the merged results.

- **Popular?** Among teams that have iterated past v1, yes.
- **Misconception?** That Naive RAG and production RAG (Hybrid RAG) are the same thing.
- **Industry standard?** Yes — this is what mature production RAG looks like in 2026.
- **Our assumption?** That comparing alternatives against Naive RAG is fair. It isn't, for teams who have moved past v1.

**Why measure it:** Without Hybrid RAG in the comparison, a sharp reader dismisses the article with "you compared against a strawman." Hybrid RAG is the actual standard the alternatives have to beat.

**Article angle:** "This is the real benchmark. Alternatives have to beat this, not the tutorial."

## Architectures deferred to v2

### Bounded tools

One tool per policy class. Curated text returned from each tool.

- **Why considered:** Tests the assumption that semantic retrieval is necessary when the policy taxonomy is closed.
- **Why deferred:** Conceptually close enough to E (hybrid RAG over a small, well-tagged corpus) that the distinct measurement value is unclear. The interesting question — "is your taxonomy closed enough to skip semantic retrieval?" — gets partially answered by comparing Hybrid RAG against Grep search.
- **When to add:** v2, if reviewers push back thatBounded tools and Hybrid RAGare meaningfully different in cost or success rate.

### Stuffed corpus

The entire FAQ corpus pasted into the system prompt. No retrieval logic.

- **Why considered:** SolDevelo's published finding suggests this sometimes beats RAG on TCO for small corpora.
- **Why deferred:** It's more of a sanity check than a real architectural choice. The qualitative point can be made in the article by citing SolDevelo directly without re-measuring.
- **When to add:** v2, if the v1 results suggest Naive RAG and Hybrid RAG are paying a lot for retrieval that the corpus size doesn't justify.

## Architectures mentioned in article but not measured

### Fine-tuned

Train a smaller model on the policy corpus. Inference does not require retrieval.

- **Why not measured:** Different cost structure (training cost upfront, inference cost down). Requires training infrastructure outside this experiment's scope.
- **Article treatment:** Named as an alternative with its own cost profile. Useful for stable, well-bounded domains. Not directly comparable to runtime-retrieval architectures.

### Deterministic routing

Classify the user question first (cheap model or rule-based router), then route to a deterministic SQL/file lookup with no LLM in the retrieval path, then format the response with the LLM. LLM at the edges, not in the middle.

- **Why not measured:** Different engineering effort (classifier or rule system). Closer to "traditional software with LLM glue" than to "AI architecture."
- **Article treatment:** Named as the pattern mature systems converge on for high-volume predictable queries. Reinforces the article's "do you need an LLM in the middle" point.

### No-LLM

Structured query, structured response. Just software.

- **Why not measured:** Self-evident baseline. The rhetorical zero point — "before you reach for AI, can a SQL query answer this?"
- **Article treatment:** Named once as the sanity check that should precede any AI architecture decision.

## What this rationale gives the reader

The article reader sees a spectrum, not a winner. The spectrum has six visible points (four measured, two deferred) and three further alternatives mentioned. The framework for choosing among them is task-class fit, corpus characteristics, and organizational authority — not "which has the lowest tokens."

The selection rationale itself demonstrates the skill the article is implicitly arguing for: knowing what to measure, knowing what to defer, knowing what to mention. This is the architect's job.
