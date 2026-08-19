# Project evaluation

**Evaluated:** 2026-08-18  
**Baseline:** v1 / Phase 3 (`cached-rag-v1`)  
**Verdict:** strong research prototype and case study; not yet a general-purpose benchmark.

## Scorecard

| Area | Score | Assessment |
|---|---:|---|
| Research engineering | 8/10 | Clear methodology, retained raw evidence, explicit constraints, and unusually candid adversarial review. |
| Reproducibility | 6/10 | Dependencies and task inputs are pinned, but CI, Python-version metadata, safe report generation, and environment bootstrap are incomplete. |
| Benchmark validity | 5/10 | The cost case study is useful; comparative quality is contaminated by judge label leakage and known Hybrid RAG defects. |
| Production readiness | 3/10 | The repository explicitly implements minimum viable reference agents, not production services. |
| **Overall** | **6.5/10** | Credible evidence for this workload and configuration, with limited external validity. |

## Claims the evidence supports

The strongest defensible statement is:

> For this SWISS support workload, model, task set, and the measured configurations, retrieval payload size and prompt caching materially affect inference-token cost.

The project supports its v1 cost observations as a scoped case study. It does **not** yet support a general claim that Naive RAG is intrinsically cheaper or equally capable across customer-support systems. Cost excludes embedding compute, vector infrastructure, development effort, and operations, and each retrieval implementation uses a different context budget.

Quality results should remain preliminary. The current judge prompt exposes architecture identity, Cached RAG quality is inherited rather than measured, and Hybrid RAG has known retrieval defects. The repository already acknowledges these limitations; the next milestone should close them experimentally.

## Findings by project structure

### `measurement/` — benchmark validity and reporting

**Strengths**

- Provider-reported usage is retained alongside a documented token decomposition.
- Frozen tasks, expected answers, judgments, raw runs, and manifests make results auditable.
- The alternating run protocol and adversarial review address common benchmark failure modes.

**Gaps**

- `measurement/judge.py::_build_agent_suffix` exposes `architecture`, `run_index`, and `tools_called`. The documented C3 finding shows this can produce asymmetric scoring.
- Seventeen tasks in one domain, on one model family, with three runs are sufficient for a case study but not broad benchmarking claims.
- Cached RAG quality is assigned from Naive RAG rather than independently measured.
- `measurement/runner.py --report` can overwrite the hand-authored comparison narrative with a Phase 1 stub.
- Cost comparisons use architecture-specific retrieval sizes (`k=4`, `k=6`, and variable grep output), so payload policy is a confound as well as a real operational characteristic.

### `architectures/` — implementation parity

**Strengths**

- Shared booking, audit, chunking, and agent-loop components reduce accidental implementation drift.
- Each architecture preserves the stated organizational boundary through explicit tools.
- Per-architecture READMEs explain intended tuning and completion criteria.

**Gaps**

- Hybrid RAG has four acknowledged active retrieval defects: accent tokenization, vector-favored RRF tie-breaking, reranker truncation, and negative-IDF early termination.
- The primary comparison does not separate architecture choice from returned-context allowance. An equal-`k` or equal-token-budget sensitivity run is needed.
- Reference agents are intentionally minimal and should not be presented as production-ready implementations.

### `tests/` and environment — executable reproducibility

**Strengths**

- The suite contains 204 test functions covering task validation, measurement, shared tools, and all four architectures.
- All Python sources compiled successfully during this evaluation.

**Gaps**

- There is no checked-in CI workflow to prove the suite on a clean machine.
- There is no declared supported Python version or project metadata such as `pyproject.toml`.
- The local `.venv` observed during evaluation pointed to a missing Homebrew Python, and system Python did not have pytest, so the suite could not be executed without rebuilding the environment.
- `requirements.lock.txt` is a `pip freeze` snapshot rather than a platform-aware lock/bootstrap workflow.

### Root documentation and release artifacts

**Strengths**

- `README.md`, `METHODOLOGY.md`, `ROADMAP.md`, and the result manifests clearly distinguish measured facts from limitations.
- The cost-confidence versus quality-confidence split is prominent rather than buried.

**Gaps**

- `CLAUDE.md` still describes the repository as scaffolding with no Python implementation, which is materially stale and can misdirect the next worker.
- The README repository tree names `notebooks/analysis.ipynb`, while the tracked notebook is `notebooks/00_corpus_inventory.ipynb`.
- The README declares an MIT license, but no root `LICENSE` file is present.
- Documentation contains completed implementation task lists whose checkboxes were never reconciled, weakening them as handoff artifacts.

## Recommended sequence

1. **Restore trust in quality measurement.** Blind the judge, fix Hybrid RAG, run a complete alternating sweep, re-judge every measured architecture, and repeat the human review sample.
2. **Make the experiment safely reproducible.** Add CI, declare Python support, document clean environment creation, and make report generation non-destructive.
3. **Quantify configuration sensitivity.** Add equal-`k` and equal-retrieved-token-budget analyses alongside the operational-default comparison.
4. **Repair project-state documentation.** Update stale worker guidance, repository layout, licensing, and historical task status.
5. **Only then broaden external validity.** Add corpora, models, task volume, and multi-turn workloads before adopting general benchmark language.

Pickup-ready work is tracked in [`openspec/changes/address-project-evaluation/tasks.md`](openspec/changes/address-project-evaluation/tasks.md). Each workstream is independently reviewable; Workstream 1 is the only prerequisite for publishing comparative quality conclusions.
