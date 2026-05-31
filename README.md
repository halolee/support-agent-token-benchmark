# support-agent-token-benchmark

A measurement framework for comparing retrieval architectures used in LLM-based customer support agents, under realistic enterprise constraints. Built as the empirical foundation for a companion LinkedIn article on AI architecture trade-offs.

## What this project is

Four implementations of the same customer support task, measured head-to-head with the same task set, the same model, and the same cross-team modularity constraints:

- **Naive RAG (A).** Vector store + top-K retrieval + LLM agent with tool calls. The pattern most tutorials show and most v1 deployments ship.
- **Cached RAG (A+G).** Same as Naive RAG, with Anthropic's prompt caching enabled. The "have you tried the obvious optimization first" baseline.
- **Grep search (C).** A `grep`-style keyword search exposed as a single tool. The "traditional retrieval still works" alternative.
- **Hybrid RAG (E).** Vector + BM25 combined with reranking. The production-standard pattern mature teams converge on.

Two further architectures are scoped but deferred to v2:
- **Bounded tools (B)** — one tool per policy class
- **Stuffed corpus (D)** — full corpus in context, no retrieval

Three more are mentioned in the companion article but not measured: fine-tuned (F), deterministic routing with LLM at the edges (H), and no-LLM-at-all (I).

> _Naming note:_ this README uses descriptive names with the article taxonomy letter in parentheses (e.g., "Naive RAG (A)"). Deeper docs (`METHODOLOGY.md`, `ARCHITECTURE_RATIONALE.md`, etc.) still use the letter labels directly while the broader rename is deferred — see issue #4.

## Architecture comparison at a glance

The four measured architectures all start from the same user query and end at the same agent response. What changes is the retrieval path in the middle — and that path is where most of the token cost accumulates.

```mermaid
flowchart LR
    Q([User query])
    R([Agent response])

    Q --> A1
    Q --> AG1
    Q --> C1
    Q --> E1

    subgraph A_lane["Naive RAG (A)"]
      direction LR
      A1[Embed query] --> A2[Vector store<br/>top-K] --> A3[Inject chunks<br/>into context]
    end

    subgraph AG_lane["Cached RAG (A+G)"]
      direction LR
      AG1[Embed query] --> AG2[Vector store<br/>top-K] --> AG3[Inject chunks<br/>cached prefix reused]
    end

    subgraph C_lane["Grep search (C)"]
      direction LR
      C1[Extract keywords] --> C2[Grep corpus] --> C3[Inject matches<br/>into context]
    end

    subgraph E_lane["Hybrid RAG (E)"]
      direction LR
      E1[Embed query<br/>+ keywords] --> E2[Vector + BM25<br/>union] --> E3[Cross-encoder<br/>rerank] --> E4[Inject top-K<br/>into context]
    end

    A3 --> R
    AG3 --> R
    C3 --> R
    E4 --> R
```

Same destination, four different paths. Token cost per task is dominated by what each lane injects into context — measured per-architecture in `measurement/results/comparison.md`.

## What this project is not

- Not a claim that one architecture is universally better. The point is to map the spectrum.
- Not a production-ready agent. Implementations are minimum viable — enough for honest token measurement, not enough for deployment.
- Not a benchmark suite. The task set is small (~17 tasks). Suggestive, not authoritative.

## The modularity constraint

All architectures must respect the same simulated department boundaries:

- The FAQ corpus is owned by **Support Content**. Any access goes through a tool exposed by them.
- The booking database is owned by **Booking Systems**. Same rule.
- The audit log is owned by **Compliance**. Same rule.
- AI Engineering owns the agent loop, system prompts, and tool orchestration only.

Every cross-team data flow must be an explicit tool call. No architecture is allowed to "win" by collapsing boundaries the org chart has set. This simulates the enterprise context the article is targeting — the context where the architecture decision is constrained by who owns what.

See `METHODOLOGY.md` §"Modularity constraint" for the full specification and `HANDOVER.md` for how each architecture implements the constraint.

## Why these architectures

The four measured architectures were chosen against an explicit framework: what is *popular*, what are the *misconceptions*, what is *industry standard*, and what are *our assumptions worth testing*. The full rationale is in `ARCHITECTURE_RATIONALE.md`. Brief summary:

- **Naive RAG (A)** is the popular default and the source of most misconceptions about "RAG."
- **Cached RAG (A+G)** is the obvious optimization production teams should try before any architectural change.
- **Grep search (C)** tests the assumption that semantic retrieval is necessary for LLM agents.
- **Hybrid RAG (E)** is the production-standard pattern; any alternative has to beat this, not the naive baseline.

Bounded tools (B) and Stuffed corpus (D) were considered and deferred. Cutting scope to ship the load-bearing comparison first is itself a deliberate decision; see `ROADMAP.md` for v2 scope.

## Quick start

```bash
# Install dependencies
pip install -r requirements.txt

# Set your API key
export ANTHROPIC_API_KEY=sk-ant-...

# Run the benchmark on all v1 architectures
python measurement/runner.py --architectures a,a_cached,c,e --tasks measurement/tasks.jsonl

# Generate the comparison report
python measurement/runner.py --report
```

Expected runtime: ~8–10 minutes for the full task set across all four architectures.

## Repository structure

```
.
├── README.md                          # You are here
├── ARCHITECTURE_RATIONALE.md          # Why these architectures, why not others
├── ROADMAP.md                         # v1 scope, v2 deferred items, future variants
├── HANDOVER.md                        # Cross-department artifact — how each architecture respects the modularity constraint
├── METHODOLOGY.md                     # How measurements are taken, including adversarial review discipline
├── BUILD_PLAN.md                      # Phased execution plan
├── corpus/
│   └── swiss_faq.md                   # FAQ corpus (sourced from LangGraph tutorial)
├── data/
│   └── travel.sqlite                  # Booking data (sourced from LangGraph tutorial)
├── architectures/
│   ├── a_naive_rag/                   # Vector store + top-K retrieval
│   ├── c_grep/                        # Keyword search as a tool
│   └── e_hybrid_rag/                  # Vector + BM25 + reranking
├── architectures_deferred/            # Placeholders for B and D (v2)
├── measurement/
│   ├── runner.py                      # Orchestrates measurement runs
│   ├── tokens.py                      # Token accounting
│   ├── tasks.jsonl                    # Benchmark task set
│   └── results/
│       ├── architecture_<id>.json     # Per-architecture raw measurements
│       └── comparison.md              # Generated comparison report
└── notebooks/
    └── analysis.ipynb                 # Visualization, distribution plots
```

## Headline results

> _To be populated after measurement runs. Structure below indicates what will be reported._

| Architecture       | Mean tokens / task | Cost / task | Success rate | Mean latency |
|--------------------|--------------------|-------------|--------------|--------------|
| Naive RAG (A)      | _TBD_              | _TBD_       | _TBD_        | _TBD_        |
| Cached RAG (A+G)   | _TBD_              | _TBD_       | _TBD_        | _TBD_        |
| Grep search (C)    | _TBD_              | _TBD_       | _TBD_        | _TBD_        |
| Hybrid RAG (E)     | _TBD_              | _TBD_       | _TBD_        | _TBD_        |

Per-task-class breakdowns and the full discussion are in `measurement/results/comparison.md`.

## Methodology summary

- **Agent model:** `claude-sonnet-4-6` (Sonnet 4.6 dateless ID; current mid-tier production default)
- **Judge model:** `claude-opus-4-7` (Opus 4.7 dateless ID; strongest current model, used for LLM-as-judge scoring)
- **Task set:** ~17 tasks across four classes, weighted to reflect realistic production traffic (mixed-heavy, see `measurement/tasks.md`)
- **Token counting:** Provider-reported `usage` from API response; decomposition via Anthropic's `client.beta.messages.count_tokens()` API (not `tiktoken`, which is OpenAI's)
- **Latency:** Single-request wall-clock time, no concurrency, no load testing
- **Success criteria:** Per-task rubric scored by LLM-as-judge, 10% human spot-check
- **Excluded from cost:** Vector store hosting, embedding API calls, developer time
- **Pre-publication adversarial review:** All findings undergo a documented review for tuning-effort asymmetry, task-set bias, and counterfactual reasoning before publication. See `METHODOLOGY.md` and the "Confidence and known biases" section in `comparison.md`.

Full details in `METHODOLOGY.md`.

## Related work

- [LangGraph customer support tutorial](https://github.com/langchain-ai/langgraph/blob/main/docs/docs/tutorials/customer-support/customer-support.ipynb) — Naive RAG (A) is closely modeled on this; corpus and database forked from here.
- [Silicon Data, _Understanding LLM Cost Per Token_](https://www.silicondata.com/blog/llm-cost-per-token) — Token decomposition methodology.
- [SolDevelo, _A real-world test of RAG vs. Direct API calls_](https://soldevelo.com/blog/a-real-world-test-of-rag-vs-direct-api-calls/) — Independent measurement; relevant precedent.

## Author

Hao Li — building [OrbitBrain](https://orbitbrain.ai). Repo built as companion to a published analysis of LLM cost architecture; article link will appear in `HANDOVER.md` when ready.

## License

MIT. Forked corpus and database from LangGraph examples (per their license); see `corpus/` and `data/` for upstream attribution.
