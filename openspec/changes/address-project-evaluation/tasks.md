# Tasks for addressing the project evaluation

## 1. Measurement validity — P0, owner: `measurement/`

- [ ] 1.1 Remove `architecture`, `run_index`, and `tools_called` from the judge-visible suffix while preserving them in judgment metadata for auditability.
- [ ] 1.2 Add a regression test that builds judge inputs for equivalent records from two architectures and asserts the model-visible content is identical.
- [ ] 1.3 Define and record the blinded-judge calibration protocol, including a fresh 10% human sample and disagreement reporting.
- [ ] 1.4 Decide whether Cached RAG is independently judged or explicitly excluded from comparative quality tables; do not inherit a numeric quality result without an experimental label.
- [ ] 1.5 Create a new dated run directory and manifest; never edit the frozen v1 result snapshots.
- [ ] 1.6 Run all measured architectures in one alternating sweep after Workstream 2 is complete.
- [ ] 1.7 Re-judge the full dispatch grid with the blinded prompt and update `comparison.md`, README headline results, confidence labels, and the adversarial review.
- [ ] 1.8 Acceptance: no architecture identifier or architecture-specific trace reaches the judge, dispatch coverage is complete, and the manual review result is documented.

## 2. Hybrid RAG correctness — P0, owner: `architectures/hybrid_rag/`

- [ ] 2.1 Fix BM25 tokenization for accented terms such as Zürich and add focused retrieval tests.
- [ ] 2.2 Replace vector-favored RRF tie-breaking with an explicitly neutral and deterministic rule; test tied rankings.
- [ ] 2.3 Handle reranker inputs beyond 512 tokens explicitly through chunk sizing, windowing, or documented truncation; test the chosen behavior.
- [ ] 2.4 Remove the negative-IDF early termination behavior and test a corpus where useful matches have negative scores.
- [ ] 2.5 Audit Chroma parallel-array handling for the preventive zip-truncation risk and either fix it or close it with a regression test.
- [ ] 2.6 Re-run architecture smoke tests and token-decomposition gates before the paid sweep.
- [ ] 2.7 Acceptance: every active Hybrid RAG defect listed in `ROADMAP.md` has a regression test and documented disposition.

## 3. Configuration sensitivity — P1, owner: `measurement/` + `architectures/`

- [ ] 3.1 Preserve the current operational-default comparison (`k=4`, `k=6`, variable grep output) as one explicitly named experiment.
- [ ] 3.2 Add an equal-`k` comparison where applicable and document why grep is or is not directly compatible.
- [ ] 3.3 Add an equal retrieved-token-budget comparison, truncating at tool boundaries without changing frozen task content.
- [ ] 3.4 Report success, input tokens, output tokens, tool turns, and truncation rate for both sensitivity protocols.
- [ ] 3.5 Update claims to distinguish architecture effects from payload-budget effects.
- [ ] 3.6 Acceptance: the report shows whether the Naive < Hybrid < Grep cost ordering persists under controlled context budgets.

## 4. Test and environment reproducibility — P1, owner: root + `tests/`

- [ ] 4.1 Declare supported Python version(s) in project metadata and the README.
- [ ] 4.2 Add a clean bootstrap command that creates a virtual environment and installs the locked dependencies without relying on a committed local `.venv`.
- [ ] 4.3 Add CI for offline tests, task validation, and Python compilation; keep paid API and model-download tests behind explicit markers.
- [ ] 4.4 Verify all 204 current test functions on the supported Python version and record the result in the PR.
- [ ] 4.5 Review whether `requirements.lock.txt` is portable across supported platforms; document or replace the freeze workflow.
- [ ] 4.6 Acceptance: a clean checkout passes the offline suite in CI with no API key and no pre-existing model cache.

## 5. Safe reporting — P1, owner: `measurement/runner.py`

- [ ] 5.1 Change `--report` so its default output cannot overwrite the curated `measurement/results/comparison.md`.
- [ ] 5.2 Add an explicit opt-in flag for replacement, or implement a template renderer that preserves human-authored sections.
- [ ] 5.3 Add tests for default output, overwrite refusal, empty input, and preservation of curated narrative.
- [ ] 5.4 Remove the README's “Do NOT run” warning only after the safe behavior ships.
- [ ] 5.5 Acceptance: an ordinary report command cannot destroy publication narrative.

## 6. Documentation and release hygiene — P1, owner: root docs

- [ ] 6.1 Rewrite `CLAUDE.md` current-state and tooling sections to reflect the implemented v1/Phase 3 repository.
- [ ] 6.2 Reconcile completed OpenSpec and build-plan checkboxes or clearly mark them as historical plans.
- [ ] 6.3 Correct the README notebook tree entry to `notebooks/00_corpus_inventory.ipynb`.
- [ ] 6.4 Add the MIT `LICENSE` file promised by the README and verify upstream data attribution remains clear.
- [ ] 6.5 Link `PROJECT_EVALUATION.md` from README and ROADMAP while remediation is active.
- [ ] 6.6 Acceptance: a new worker can identify current state, supported commands, open limitations, and the next task without consulting git history.

## 7. Future benchmark expansion — P2, owner: roadmap

- [ ] 7.1 Define the minimum task count and class balance needed before using general “benchmark” language.
- [ ] 7.2 Pre-register a second support corpus/domain and its licensing/provenance requirements.
- [ ] 7.3 Pre-register a second model family and a policy for price/version updates.
- [ ] 7.4 Add multi-turn workload design only after the corrected single-turn baseline is frozen.
- [ ] 7.5 Acceptance: expansion has a pre-registered protocol and does not retroactively alter v1 artifacts.
