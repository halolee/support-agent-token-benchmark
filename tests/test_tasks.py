"""Tests for the task-set validator.

One test per spec requirement (openspec/changes/write-benchmark-tasks/specs/
benchmark-tasks/spec.md), exercising both the pass and fail paths. Most tests
build inline JSONL via tmp_path; a canonical good fixture lives at
tests/fixtures/tasks_passing.jsonl for round-tripping.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from measurement.scripts.validate_tasks import (
    DEFAULT_SQLITE,
    Violation,
    validate,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PASSING_FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "tasks_passing.jsonl"


def _good_task(**overrides) -> dict:
    """A task that passes every check. Tests mutate this to trigger violations."""
    base = {
        "task_id": "POL-001",
        "class": "policy",
        "user_message": "Just got back from my trip and realized I never grabbed an invoice — is there still a window for that?",
        "expected_answer_summary": "E-ticket as invoice; 90-day free window; CHF 30 fee after.",
        "expected_citations": ["ordering-an-invoice"],
        "policy_classes_invoked": ["ordering-an-invoice"],
        "booking_data_required": False,
        "rubric": {
            "factual_correctness": "States 90-day window and CHF 30 fee.",
            "citation_accuracy": "Cites ordering-an-invoice.",
            "no_fabrication": "No invented policy.",
        },
    }
    base.update(overrides)
    return base


def _run(tmp_path: Path, lines, *, strict: bool = False, fixtures: dict | None = None,
         answers: str | bool | None = True) -> list[Violation]:
    """Wrapper around validate() that wires tmp_path-based inputs.

    `lines` is a list of dicts (JSON-encoded) or raw strings (passed through).
    `answers=True` auto-generates matching `## TASK-ID` headings so the parity
    check stays quiet unless the test is specifically about parity.
    """
    tasks_path = tmp_path / "tasks.jsonl"
    encoded = []
    for item in lines:
        encoded.append(json.dumps(item) if isinstance(item, dict) else item)
    tasks_path.write_text("\n".join(encoded) + "\n")

    fixtures_path = tmp_path / "task_fixtures.json"
    if fixtures is not None:
        fixtures_path.write_text(json.dumps(fixtures))

    answers_path = tmp_path / "answers.md"
    if answers is True:
        ids = [t["task_id"] for t in lines if isinstance(t, dict) and "task_id" in t]
        answers_path.write_text("\n".join(f"## {tid}\nbody" for tid in ids) + "\n")
    elif isinstance(answers, str):
        answers_path.write_text(answers)

    return validate(
        jsonl_path=tasks_path,
        fixtures_path=fixtures_path,
        sqlite_path=DEFAULT_SQLITE,
        answers_path=answers_path,
        strict=strict,
    )


def _errors(violations: list[Violation]) -> list[Violation]:
    return [v for v in violations if v.severity == "ERROR"]


def _has(violations: list[Violation], requirement: str) -> bool:
    return any(v.requirement == requirement for v in violations)


# ---------- Pass paths ----------

def test_passing_fixture_file_validates_clean(tmp_path):
    """tests/fixtures/tasks_passing.jsonl must validate with zero errors."""
    answers_path = tmp_path / "answers.md"
    # Mirror the passing fixture's IDs in the answers file so parity stays clean.
    for line in PASSING_FIXTURE.read_text().splitlines():
        if line.strip() and not line.strip().startswith("#"):
            tid = json.loads(line)["task_id"]
            answers_path.write_text(answers_path.read_text() if answers_path.exists() else "" +
                                    f"## {tid}\nbody\n")
    violations = validate(
        jsonl_path=PASSING_FIXTURE,
        fixtures_path=tmp_path / "nonexistent_fixtures.json",
        sqlite_path=DEFAULT_SQLITE,
        answers_path=answers_path,
        strict=False,
    )
    assert _errors(violations) == [], f"unexpected errors: {[str(v) for v in violations]}"


def test_minimal_inline_task_passes(tmp_path):
    violations = _run(tmp_path, [_good_task()])
    assert _errors(violations) == [], f"unexpected: {[str(v) for v in violations]}"


# ---------- Requirement: Task schema conformance ----------

def test_missing_required_field_rejected(tmp_path):
    t = _good_task()
    del t["expected_answer_summary"]
    violations = _run(tmp_path, [t])
    assert _has(violations, "schema-conformance")


def test_unknown_field_rejected(tmp_path):
    t = _good_task()
    t["bonus"] = "extra"
    violations = _run(tmp_path, [t])
    assert _has(violations, "schema-conformance"), "extra='forbid' must reject unknown fields"


def test_invalid_json_line_rejected(tmp_path):
    violations = _run(tmp_path, ['{"task_id": "POL-001", broken'])
    assert _has(violations, "schema-conformance")


def test_rubric_missing_dimension_rejected(tmp_path):
    t = _good_task()
    del t["rubric"]["no_fabrication"]
    violations = _run(tmp_path, [t])
    assert _has(violations, "schema-conformance")


# ---------- Requirement: Task ID stability and uniqueness ----------

def test_duplicate_task_id_rejected(tmp_path):
    violations = _run(tmp_path, [_good_task(), _good_task()])
    assert any(v.requirement == "task-id-uniqueness" for v in violations)


def test_malformed_task_id_rejected(tmp_path):
    violations = _run(tmp_path, [_good_task(task_id="POL-1")])
    assert _has(violations, "schema-conformance")  # pydantic Field(pattern=...) catches it


def test_prefix_class_mismatch_rejected(tmp_path):
    t = _good_task(task_id="MIX-001")  # MIX prefix but class still "policy"
    violations = _run(tmp_path, [t])
    assert _has(violations, "task-id-prefix-class-agreement")


# ---------- Requirement: Class distribution ----------

def test_distribution_not_enforced_when_not_strict(tmp_path):
    """A 1-task file in non-strict mode should not trigger distribution failure."""
    violations = _run(tmp_path, [_good_task()], strict=False)
    assert not _has(violations, "class-distribution")


def test_distribution_enforced_when_strict(tmp_path):
    """Strict mode against a 1-task file triggers distribution failure."""
    violations = _run(tmp_path, [_good_task()], strict=True)
    assert _has(violations, "class-distribution")


def test_distribution_enforced_via_complete_marker(tmp_path):
    """A `# COMPLETE` line triggers distribution check without --strict."""
    lines = [_good_task(), "# COMPLETE"]
    violations = _run(tmp_path, lines, strict=False)
    assert _has(violations, "class-distribution")


# ---------- Requirement: Controlled vocabulary ----------

def test_unknown_policy_class_rejected(tmp_path):
    t = _good_task(policy_classes_invoked=["not-a-real-section"])
    violations = _run(tmp_path, [t])
    assert _has(violations, "controlled-vocabulary")


def test_unknown_citation_rejected(tmp_path):
    t = _good_task(expected_citations=["not-a-real-section"])
    violations = _run(tmp_path, [t])
    assert _has(violations, "controlled-vocabulary")


# ---------- Requirement: Check 2 phrasing ----------

def test_architect_phrasing_rejected(tmp_path):
    t = _good_task(user_message="What's your policy on rebooking one-way tickets?")
    violations = _run(tmp_path, [t])
    assert _has(violations, "check2-phrasing")


def test_customer_phrasing_passes(tmp_path):
    t = _good_task(user_message="I need to push my departure back a couple of days — what can I do?")
    violations = _run(tmp_path, [t])
    assert not _has(violations, "check2-phrasing")


# ---------- Requirement: Referential integrity ----------

def test_phantom_book_ref_rejected(tmp_path):
    # FFFFFF is hex-shaped (matches the book_ref regex) but verified absent from data/travel.sqlite.
    t = _good_task(
        task_id="MIX-001",
        user_message="My booking FFFFFF is acting up — can you help me sort it out?",
        booking_data_required=True,
    )
    t["class"] = "mixed"
    violations = _run(tmp_path, [t])
    assert _has(violations, "referential-integrity")


def test_real_book_ref_passes(tmp_path):
    """06B046 is a real book_ref in data/travel.sqlite (sampled from initial inspection)."""
    t = _good_task(
        task_id="MIX-001",
        user_message="Can you check what I paid on booking 06B046?",
        booking_data_required=True,
    )
    t["class"] = "mixed"
    violations = _run(tmp_path, [t])
    # Real booking exists → no phantom error. Warning about not-in-fixtures is fine.
    assert not any(v.requirement == "referential-integrity" and v.severity == "ERROR"
                   for v in violations)


# ---------- Requirement: Booking data flag ----------

def test_transactional_without_booking_flag_rejected(tmp_path):
    t = _good_task(
        task_id="TXN-001",
        user_message="What time does my flight leave tomorrow?",
        booking_data_required=False,
        expected_citations=[],
    )
    t["class"] = "transactional"
    violations = _run(tmp_path, [t])
    assert _has(violations, "booking-data-flag")


def test_policy_with_booking_reference_rejected(tmp_path):
    t = _good_task(user_message="I'm asking about booking 06B046 — what's the invoice window?")
    violations = _run(tmp_path, [t])
    assert _has(violations, "booking-data-flag")


def test_mixed_with_ref_but_flag_false_rejected(tmp_path):
    """A MIX task that mentions a real booking but sets booking_data_required=false
    must be flagged — the data path the prompt needs would not be provisioned."""
    t = _good_task(
        task_id="MIX-001",
        user_message="On booking 06B046, when does the invoice typically arrive?",
        booking_data_required=False,
    )
    t["class"] = "mixed"
    violations = _run(tmp_path, [t])
    flag_errs = [v for v in violations
                 if v.requirement == "booking-data-flag" and "booking_data_required=false" in v.message]
    assert flag_errs, f"expected booking-data-flag violation for the false-flag case; got {[str(v) for v in violations]}"


# ---------- Requirement: Expected citations match class ----------

def test_policy_with_empty_citations_rejected(tmp_path):
    t = _good_task(expected_citations=[])
    violations = _run(tmp_path, [t])
    assert _has(violations, "citations-match-class")


def test_transactional_with_empty_citations_passes(tmp_path):
    t = _good_task(
        task_id="TXN-001",
        user_message="What time does my flight 06B046 leave?",  # 06B046 is a real book_ref but used as filler
        booking_data_required=True,
        expected_citations=[],
        policy_classes_invoked=[],
    )
    t["class"] = "transactional"
    # 06B046 matches book_ref regex; real, so no error. Use a real flight_no to be cleaner:
    t["user_message"] = "What time does my flight QR0051 leave?"
    violations = _run(tmp_path, [t])
    assert not _has(violations, "citations-match-class")


# ---------- Requirement: Expected answers documented separately ----------

def test_missing_answer_entry_rejected(tmp_path):
    violations = _run(tmp_path, [_good_task()], answers="# empty answer key\n")
    assert _has(violations, "expected-answers-parity")


def test_orphaned_answer_entry_rejected(tmp_path):
    answers_content = "## POL-001\nbody\n\n## MIX-099\norphan body\n"
    violations = _run(tmp_path, [_good_task()], answers=answers_content)
    parity = [v for v in violations if v.requirement == "expected-answers-parity"]
    assert any("orphan" in v.message.lower() or "MIX-099" in v.message for v in parity)


# ---------- Production file integration (gates task 1.6 → 1.7) ----------

def test_production_tasks_jsonl_validates(tmp_path):
    """The actual measurement/tasks.jsonl must pass non-strict validation
    once task 1.6 lands. Until then this test will fail — that's the green
    signal that the validator foundation is complete."""
    tasks_path = PROJECT_ROOT / "measurement" / "tasks.jsonl"
    if not tasks_path.exists():
        pytest.skip("measurement/tasks.jsonl not yet created (blocked by task 1.6)")
    violations = validate(strict=False)
    errs = [v for v in violations if v.severity == "ERROR"]
    assert errs == [], f"production tasks.jsonl has errors: {[str(v) for v in errs]}"
