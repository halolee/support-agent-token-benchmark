# Measurement Methodology

This document specifies how token measurements are taken, what is counted, what is excluded, and what the measurements can and cannot support as claims.

## Why this document exists

Measurement-based comparisons of LLM architectures are easy to manipulate, intentionally or not. Different teams measuring "tokens per request" can produce 5× different numbers depending on what they count. This document fixes the methodology in advance so the comparison is defensible.

If you disagree with any choice below, the right move is to fork the methodology and re-measure. The results in this repo are valid only under the methodology specified here.

## Model and configuration

- **Model:** Claude Sonnet 4 (`claude-sonnet-4-5`)
- **Temperature:** 0.0 (for reproducibility; production deployments would typically use 0.3–0.7)
- **Max tokens:** 1024 (response cap)
- **Tools:** Native Anthropic function calling
- **Cache:** Disabled for v1 measurements. The cache discount is a real production lever, but enabling it during measurement introduces variability that obscures the architectural comparison. A follow-up measurement with caching enabled is in scope for v2.

## What gets counted

For each task run, the following are recorded from the API response:

| Field                          | Source                                      |
|--------------------------------|---------------------------------------------|
| `input_tokens`                 | API usage object (provider-reported)        |
| `output_tokens`                | API usage object (provider-reported)        |
| `cache_creation_input_tokens`  | API usage object (zero in v1, cache off)    |
| `cache_read_input_tokens`      | API usage object (zero in v1, cache off)    |

These raw numbers are then decomposed into five categories matching the [Silicon Data methodology](https://www.silicondata.com/blog/llm-cost-per-token):

1. **System prompt tokens** — counted by tokenizing the system prompt string with the model's tokenizer before sending.
2. **Retrieved/injected context tokens** — for Architecture A, this is the concatenated text of retrieved chunks. For Architecture B, this is the concatenated text of tool responses returning policy content.
3. **User message tokens** — the customer inquiry string.
4. **Tool call overhead tokens** — the tool schema JSON sent in every request (constant per architecture, varies per task only if available tools change mid-conversation).
5. **Response tokens** — the model's output (assistant message + any structured tool call requests).

The sum of categories 1–4 should equal `input_tokens` reported by the API, within tokenizer-rounding variance. The runner asserts this equality and flags discrepancies above 2%.

## What does not get counted

The following are deliberately excluded from the per-task cost number:

- **Vector store infrastructure cost.** Hosting, embedding generation, re-indexing on policy updates. These are real costs but they amortize differently than per-call token costs.
- **Embedding API calls for retrieval.** Architecture A makes one embedding call per query (embedding the user message to compare against the indexed chunks). At current pricing this is sub-cent per query and an order of magnitude below the inference cost, but it is not zero. Excluded from v1; flagged in `comparison.md`.
- **Development cost.** Building Architecture A took longer than Architecture B (because of the embedding pipeline). Building Architecture B's policy lookup tools required curating policy text, which takes content team time. Both are real costs; neither is captured in per-task token measurements.
- **Operational costs.** Monitoring, evaluation harnesses, on-call burden. Not measured.

The headline claim of this project is about *per-call token cost only*. Total cost of ownership is discussed qualitatively in `HANDOVER.md` and the companion article, but is not part of the measured comparison.

## Success criteria

Each task in `tasks.jsonl` has an expected answer and a rubric. After both architectures produce responses, an LLM-as-judge (Claude Opus 4) scores each response on three dimensions:

1. **Factual correctness** — does the response state the right policy / data?
2. **Citation accuracy** — when policy is invoked, is the cited source correct?
3. **No fabrication** — does the response avoid stating policy not present in the source corpus?

Each dimension is scored 0 (fail), 0.5 (partial), or 1 (pass). Task success requires 1.0 on all three.

A 10% random sample of judgments is manually reviewed to detect judge-model bias.

A task that one architecture fails is excluded from the cost comparison for that architecture — comparing cost on tasks the architecture didn't actually solve would be misleading.

## Task set composition

15–20 tasks total, distributed across four classes:

- **Pure policy** (5 tasks) — answer is entirely in the FAQ corpus, no booking data needed
- **Pure transactional** (5 tasks) — answer requires booking data only, no policy lookup
- **Mixed** (5 tasks) — requires both policy and booking data
- **Edge case** (3–5 tasks) — requires conditional logic, policy-with-exceptions, or unusual booking states

Task IDs are stable across runs. New tasks are appended, never edited, to preserve historical comparability.

## Run protocol

1. Both architectures execute the full task set in a single run, alternating tasks (A, B, A, B, …) to control for any time-of-day API latency variance.
2. Each task is run **three times** per architecture. The reported value is the median of the three runs. Variance is reported in `comparison.md`.
3. If any run produces an API error, that run is retried up to twice. If it still fails, the task is flagged and excluded from that run's reported numbers.

## Reproducibility

To reproduce these results:

```bash
git clone <repo>
cd support-agent-token-benchmark
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
python measurement/runner.py --architecture both --tasks measurement/tasks.jsonl --runs 3
python measurement/runner.py --report
```

Expected variance across independent runs of the full task set: under 5% on mean token counts, under 2% on cost (since cost is dominated by stable-prompt tokens, not output variability).

If your results differ from those published in `comparison.md` by more than the stated variance, possible causes include:

- Model version drift (provider has updated the model under the same identifier)
- Tokenizer changes
- Task set has been edited locally
- Different temperature or max_tokens setting

## What this measurement supports

Defensible claims:

- "Under this task set, Architecture A consumes X% more input tokens than Architecture B per task."
- "Per-task cost differs by $Y at Claude Sonnet 4 pricing."
- "Architecture A succeeds on Z% of tasks; Architecture B succeeds on W%."

Claims this measurement does **not** support:

- "Bounded tools are always cheaper than RAG." (Sample size, task class scope, single model.)
- "RAG is wasteful." (Cost-per-token is one input to total cost; not measured here.)
- "Architecture B is production-ready." (No production hardening assessed.)
- "These results generalize to other domains." (Single domain — airline customer support.)

Honest framing of what the measurement is for: a *worked example* of how to compare two architectural patterns on the same task, with results that are suggestive for this domain and method-transferable to others.

## Pre-publication adversarial review

Before any measurement result is published as a finding, it must pass an adversarial review designed to catch the non-obvious setup errors that "I checked the setup and it looks fine" reviews miss. The goal is to actively try to invalidate the comparison with the same energy that would otherwise go into defending it.

### Why this exists

Measurement-based comparisons fail in subtle ways. The obvious failures (broken token counting, wrong API parameters, off-by-one errors) usually get caught by smoke testing. The subtle ones — choices that biased the comparison without being visibly wrong — survive into published results and produce findings that don't reproduce. This section is the discipline that catches the second category.

The principle: a finding is publishable when I have honestly tried to make the *losing* architecture win, and reported what it would have taken.

### Required checks before publishing any result

**Check 1 — Equal tuning effort.**

Both architectures must have received their reasonable best showing. If Architecture A is at default settings and Architecture B is hand-curated, the comparison is asymmetric in ways that don't reflect production reality.

Specifically required to verify:

- [ ] Architecture A's retrieval is tuned (top-K, chunk size, threshold) — not running with defaults that may be suboptimal for the corpus
- [ ] Architecture A's system prompt is comparable in care to Architecture B's policy curation
- [ ] If Architecture B's policy text was curated, document how much effort went into curation. Architecture A should receive comparable effort on something — corpus cleaning, prompt tuning, or chunking strategy
- [ ] Document the effort asymmetry honestly if one cannot be removed

**Check 2 — Task set neutrality.**

The task set must not favor one architecture by accident of how tasks were written.

Specifically required to verify:

- [ ] Task phrasings do not map suspiciously cleanly to Architecture B's policy tool names. If a task says "rebooking policy" and Architecture B has a tool named `get_rebooking_policy`, the tool selection is trivial in a way that wouldn't hold in production. Tasks should be written in customer-style phrasings, not architect-style category names.
- [ ] The class distribution (pure policy / pure transactional / mixed / edge case) reflects realistic production traffic, not a distribution chosen to favor one architecture
- [ ] Edge cases include scenarios that stress *both* architectures' weak spots, not just one's

**Check 3 — Counterfactual reasoning.**

For each headline finding, articulate what would have to be true for the result to reverse.

Specifically required to verify:

- [ ] If Architecture B is cheaper, document under what conditions Architecture A would close the gap or win (larger corpus, more policy classes, open-ended question taxonomy, multi-turn dialogue, different model)
- [ ] If Architecture A is cheaper, document under what conditions Architecture B would close the gap or win (more concise policy curation, fewer policy classes, tighter task scope)
- [ ] If success rates differ, document what failure modes drove the difference and whether they are addressable in each architecture

These counterfactuals are the scope-of-validity boundaries of the result. They are part of the published finding, not an asterisk on it.

### What happens if a check fails

If any check reveals a problem, three options in order of preference:

1. **Fix it.** Re-tune the under-tuned architecture, rebalance the task set, re-run.
2. **Document it as a measurement limitation.** Add it to "Limitations acknowledged" below, and clearly state which direction the bias likely runs.
3. **Reframe the finding to match what was actually measured.** If the measurement actually shows "B wins under these specific conditions" rather than "B wins generally," publish the narrower claim.

The disposition: I would rather publish a narrow defensible finding than a broad one I have to retract.

### Steel-manning the null

In addition to the three checks above, write out the strongest version of "this measurement shows nothing meaningful" before publishing. What is the most compelling argument that the observed differences are artifacts of choices rather than genuine architectural properties? Include this argument in the published finding and address it. If it cannot be addressed, the finding is not yet ready.

## Limitations acknowledged

These are limitations of the measurement as designed, separate from the adversarial review above. Both sections should be read together.

1. **Single model.** Results may differ on smaller/cheaper models that are more sensitive to context length, or on reasoning models where thinking tokens dominate.
2. **Single domain.** Airline customer support has a particular policy structure (finite, well-defined classes). Domains with open-ended policy taxonomies may favor RAG more.
3. **Small task set.** 15–20 tasks is enough to be suggestive, not enough to be authoritative.
4. **No multi-turn evaluation.** All tasks are single-turn. Multi-turn dialogue would change the comparison significantly.
5. **No production load testing.** Latency under load, rate limit interactions, and concurrent request handling are not measured.
