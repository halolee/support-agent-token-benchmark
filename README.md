# support-agent-token-benchmark

A measurement framework for comparing retrieval architectures on customer-support agent workloads, with two reference implementations and a published comparison.

## What this project is

Two implementations of the same customer support agent, measured head-to-head on the same task set:

- **Architecture A — RAG + tool calls.** The canonical pattern. Vector store over FAQ corpus, agent retrieves top-K chunks per turn, tool calls for transactional lookups. Based on the LangGraph customer support tutorial.
- **Architecture B — bounded tools.** No vector store. Policy content lives in targeted lookup tools (`get_rebooking_policy`, `get_refund_policy`, etc.) returning curated text. Same transactional tools as Architecture A.

Both architectures answer the same benchmark task set. Token counts are measured per task, decomposed across five categories matching the methodology published by [Silicon Data](https://www.silicondata.com/blog/llm-cost-per-token):

1. System prompt
2. Retrieved/injected context
3. User message
4. Tool call overhead (schemas)
5. Response

Results are recorded in `measurement/results/comparison.md`.

## What this project is not

- Not a claim that one architecture is universally better. The comparison is on one task class (customer support over a finite policy taxonomy) with one model. The intent is to show *how to measure*, not to declare a winner.
- Not a production-ready agent. The implementations are minimum viable — enough to make token measurements honest, not enough to deploy.
- Not a benchmark suite. The task set is small (15–20 tasks). Statistically suggestive, not statistically authoritative.

## Why the comparison exists

The optimization corpus for LLM cost reduction focuses on per-call efficiency (prompt caching, model routing, batch APIs). What gets less attention is whether the *architecture* of the agent is the right one for the task. RAG and bounded-tools are both valid patterns, but they have different token profiles, different operational requirements, and different organizational dependencies. This project quantifies the token-profile dimension.

The broader argument — that the right architecture depends on which team owns which system — is developed in `HANDOVER.md`.

## Quick start

```bash
# Install dependencies
pip install -r requirements.txt

# Set your API key
export ANTHROPIC_API_KEY=sk-ant-...

# Run the benchmark on both architectures
python measurement/runner.py --architecture both --tasks measurement/tasks.jsonl

# Generate the comparison report
python measurement/runner.py --report
```

Expected runtime: ~5 minutes for 20 tasks across both architectures.

## Repository structure

```
.
├── README.md                          # You are here
├── HANDOVER.md                        # Cross-department artifact: what this project requires from other teams to ship
├── METHODOLOGY.md                     # How measurements are taken and what they exclude
├── corpus/
│   └── swiss_faq.md                   # FAQ corpus (forked from LangGraph tutorial)
├── data/
│   └── travel.sqlite                  # Booking/order data (forked from LangGraph tutorial)
├── architecture_a_rag/                # Reference implementation: RAG + tools
│   ├── README.md
│   ├── agent.py
│   ├── tools.py
│   └── prompts.py
├── architecture_b_bounded/            # Reference implementation: bounded tools, no vector store
│   ├── README.md
│   ├── agent.py
│   ├── tools.py
│   └── prompts.py
├── measurement/
│   ├── runner.py                      # Orchestrates measurement runs
│   ├── tokens.py                      # Token accounting
│   ├── tasks.jsonl                    # Benchmark task set
│   └── results/
│       ├── architecture_a.json        # Raw per-task measurements
│       ├── architecture_b.json
│       └── comparison.md              # Generated comparison report
└── notebooks/
    └── analysis.ipynb                 # Visualization and sanity checks
```

## Headline results

> _To be populated after measurement runs. The structure below indicates what will be reported._

| Metric                        | Architecture A (RAG) | Architecture B (Bounded) | Delta   |
|-------------------------------|----------------------|--------------------------|---------|
| Mean input tokens per task    | _TBD_                | _TBD_                    | _TBD_   |
| Mean output tokens per task   | _TBD_                | _TBD_                    | _TBD_   |
| Mean cost per task (Sonnet 4) | _TBD_                | _TBD_                    | _TBD_   |
| Task success rate             | _TBD_                | _TBD_                    | _TBD_   |
| Mean latency per task         | _TBD_                | _TBD_                    | _TBD_   |

Per-task-class breakdowns and the full discussion are in `measurement/results/comparison.md`.

## Methodology summary

- **Model:** Claude Sonnet 4 (`claude-sonnet-4-5`), single model across both architectures
- **Task set:** 15–20 tasks across four classes (pure policy, pure transactional, mixed, edge case)
- **Token counting:** Provider-reported usage from API response (input, output, cache reads where applicable)
- **Success criteria:** Per-task rubric, scored by LLM-as-judge with human spot-check
- **Excluded from cost:** Infrastructure costs (vector DB, hosting), one-time setup costs (embedding generation), developer time
- **Pre-publication adversarial review:** All findings undergo a documented review for tuning-effort asymmetry, task-set bias, and counterfactual reasoning before being published. See `METHODOLOGY.md` and the "Confidence and known biases" section in `comparison.md`.

Full details in `METHODOLOGY.md`.

## Related work

- [LangGraph customer support tutorial](https://github.com/langchain-ai/langgraph/blob/main/docs/docs/tutorials/customer-support/customer-support.ipynb) — Architecture A is closely modeled on this.
- [Silicon Data, _Understanding LLM Cost Per Token_](https://www.silicondata.com/blog/llm-cost-per-token) — Token decomposition methodology is taken from here.
- [SolDevelo, _A real-world test of RAG vs. Direct API calls_](https://soldevelo.com/blog/a-real-world-test-of-rag-vs-direct-api-calls/) — Independent comparison of RAG vs. full-context approaches; relevant precedent for measurement framing.

## Author

Hao Lee — building [OrbitBrain](https://orbitbrain.ai). Repo built as a companion to a published analysis of LLM cost architecture; see linked article in `HANDOVER.md`.

## License

MIT. Forked corpus and database from LangGraph examples (Apache 2.0); see `corpus/` and `data/` for upstream attribution.
