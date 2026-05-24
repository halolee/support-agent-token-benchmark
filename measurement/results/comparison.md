# Comparison Report

> **Status:** Template. Populated by `python measurement/runner.py --report` after benchmark runs complete.

## Run metadata

- **Date:** _TBD_
- **Model:** `claude-sonnet-4-5`
- **Task set version:** _TBD_ (hash of `tasks.jsonl`)
- **Architecture A commit:** _TBD_
- **Architecture B commit:** _TBD_
- **Runs per task:** 3
- **Total API calls:** _TBD_
- **Total measurement cost:** _TBD_

## Headline numbers

| Metric                          | Architecture A | Architecture B | Delta (B vs A)    |
|---------------------------------|----------------|----------------|-------------------|
| Mean input tokens per task      | _TBD_          | _TBD_          | _TBD_ (-X%)       |
| Mean output tokens per task     | _TBD_          | _TBD_          | _TBD_ (±X%)       |
| Mean total tokens per task      | _TBD_          | _TBD_          | _TBD_ (-X%)       |
| Mean cost per task              | $_TBD_         | $_TBD_         | -$_TBD_ (-X%)     |
| Cost per 10,000 tasks           | $_TBD_         | $_TBD_         | -$_TBD_           |
| Task success rate               | _TBD_%         | _TBD_%         | _TBD_ percentage points |
| Mean latency per task           | _TBD_s         | _TBD_s         | _TBD_             |

## Per-class breakdown

The interesting question is whether the architectures perform differently on different task classes. If Architecture B is uniformly cheaper, the architectural choice is straightforward. If Architecture A wins on some classes and B wins on others, the right answer depends on which class the production traffic actually contains.

### Pure policy tasks

| Metric                          | Architecture A | Architecture B |
|---------------------------------|----------------|----------------|
| Mean tokens per task            | _TBD_          | _TBD_          |
| Mean cost per task              | $_TBD_         | $_TBD_         |
| Success rate                    | _TBD_%         | _TBD_%         |

**Observation:** _TBD — does the architecture B advantage hold here, or does RAG's flexibility win?_

### Pure transactional tasks

| Metric                          | Architecture A | Architecture B |
|---------------------------------|----------------|----------------|
| Mean tokens per task            | _TBD_          | _TBD_          |
| Mean cost per task              | $_TBD_         | $_TBD_         |
| Success rate                    | _TBD_%         | _TBD_%         |

**Observation:** _TBD — both architectures should perform similarly here; if they don't, why?_

### Mixed tasks

| Metric                          | Architecture A | Architecture B |
|---------------------------------|----------------|----------------|
| Mean tokens per task            | _TBD_          | _TBD_          |
| Mean cost per task              | $_TBD_         | $_TBD_         |
| Success rate                    | _TBD_%         | _TBD_%         |

**Observation:** _TBD — this is where the comparison gets interesting._

### Edge case tasks

| Metric                          | Architecture A | Architecture B |
|---------------------------------|----------------|----------------|
| Mean tokens per task            | _TBD_          | _TBD_          |
| Mean cost per task              | $_TBD_         | $_TBD_         |
| Success rate                    | _TBD_%         | _TBD_%         |

**Observation:** _TBD — edge cases often expose failure modes that aggregate metrics hide._

## Token decomposition (Silicon Data methodology)

| Component                       | Arch A (mean) | Arch B (mean) | Notes |
|---------------------------------|---------------|---------------|-------|
| System prompt                   | _TBD_         | _TBD_         |       |
| Retrieved/injected context      | _TBD_         | _TBD_         | A: vector chunks. B: policy tool responses. |
| User message                    | _TBD_         | _TBD_         | Should be identical across architectures. |
| Tool call overhead (schemas)    | _TBD_         | _TBD_         | B has more tools, so schema overhead is higher per call. |
| Response                        | _TBD_         | _TBD_         | Should be similar; if not, why? |
| **Total**                       | _TBD_         | _TBD_         |       |

## Variance and reliability

- **Coefficient of variation across 3 runs:** _TBD_%
- **Tasks excluded due to API errors:** _TBD_
- **Tasks where architectures disagreed on success:** _TBD_

If the coefficient of variation exceeds 10%, results should be treated as exploratory. Re-run with more samples per task.

## Comparison to published baselines

The Silicon Data piece reports a reference workload of 3,150 input tokens + 400 output tokens per ticket. This corresponds to a particular RAG configuration (system prompt 500 + retrieved chunks 2,500 + user message 150 + response 400).

Our Architecture A configuration: _TBD — compare to reference._
Our Architecture B configuration: _TBD — compare to reference._

The Silicon Data piece does not include tool call overhead or measure a bounded-tools alternative, so direct comparison is limited to the input/output totals.

## Limitations of this measurement

(See `METHODOLOGY.md` for the full discussion.)

- Single model. Results may shift on smaller or reasoning models.
- Small task set (15–20 tasks). Suggestive, not authoritative.
- Single domain (airline customer support, English only).
- No multi-turn dialogue measurement.
- Excludes infrastructure cost, embedding cost, developer cost.

## Confidence and known biases

This section documents the adversarial review (per `METHODOLOGY.md`) of the published findings. It is mandatory before any number above is treated as a finding worth sharing.

### Tuning effort review

| Architecture     | Tuning applied                                                | Effort level | Honest assessment |
|------------------|---------------------------------------------------------------|--------------|-------------------|
| Architecture A   | _TBD: top-K choice, chunk strategy, threshold (if any)_       | _TBD_        | _TBD: was this comparable to the effort spent on Architecture B's curation?_ |
| Architecture B   | _TBD: policy partitioning approach, tool naming, system prompt tightening_ | _TBD_ | _TBD: was this comparable to the effort spent on Architecture A's retrieval tuning?_ |

If the effort levels differ meaningfully, document the direction of the resulting bias here: _TBD_

### Task set bias review

- **Do task phrasings map suspiciously to Architecture B tool names?** _TBD: yes / no, with examples_
- **Does the class distribution reflect realistic production traffic?** _TBD: discussion_
- **Do edge cases stress both architectures or just one?** _TBD: discussion_

### Counterfactual reasoning

For the headline finding (whichever direction it points), what would have to be true for it to reverse?

**If Architecture B is cheaper:**
- A larger corpus with hundreds of policy classes would _TBD_
- An open-ended question taxonomy (questions not anticipated during curation) would _TBD_
- Multi-turn dialogue would _TBD_
- A model with weaker tool-selection ability would _TBD_

**If Architecture A is cheaper:**
- A more concise policy curation in B would _TBD_
- A tighter task scope mapping to fewer policy classes would _TBD_
- Prompt caching enabled (which favors A's stable system prompt structure) would _TBD_

**If success rates differ:**
- The failure modes driving the gap are: _TBD_
- Whether they are addressable in each architecture: _TBD_

### Steel-manning the null

The strongest argument that this measurement shows nothing meaningful:

> _TBD: write out the most compelling case that observed differences are artifacts of methodology choices, not genuine architectural properties. Then address it._

If this argument cannot be addressed, the finding is not yet ready for publication.

### Net confidence statement

Based on the review above, the confidence level of the headline findings is: _TBD: high / medium / low / preliminary_

The scope of validity is: _TBD: the conditions under which the result holds_

## What this measurement supports

Defensible claims based on these numbers:

- Under the specified configuration and task set, Architecture B uses _TBD_% fewer input tokens than Architecture A.
- The cost difference per task is $_TBD_, or $_TBD_ at the scale of 10,000 tasks.
- Task success rates differ by _TBD_ percentage points; whether this difference is meaningful depends on the application's tolerance for the failure modes observed.

Claims this measurement does **not** support:

- That one architecture is universally better.
- That these numbers will hold in other domains.
- That production deployments will see exactly these results (variability in real prompts, retrieval tuning, and tool implementations will shift the absolute numbers).

## What I'd want to measure next

> _Populated after v1 results are in._

Candidate v2 measurements:

1. With prompt caching enabled.
2. With a cheaper model (Haiku 4.5 or GPT-4o-mini) to test whether the architectural advantage interacts with model choice.
3. With a larger task set (50-100 tasks) to tighten statistical confidence.
4. Multi-turn dialog measurement (the architectural cost difference may compound across turns).
5. With retrieval threshold tuning on Architecture A to give it the best possible showing.
