"""Validator for measurement/tasks.jsonl.

One check function per spec requirement (openspec/changes/write-benchmark-tasks/
specs/benchmark-tasks/spec.md). Adding a new check is one append to CHECKS.

Usage (standalone):
    python measurement/scripts/validate_tasks.py [--strict] [--tasks PATH] ...

Usage (programmatic):
    from measurement.scripts.validate_tasks import validate
    violations = validate(strict=True)
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

DEFAULT_TASKS = PROJECT_ROOT / "measurement" / "tasks.jsonl"
DEFAULT_VOCAB = PROJECT_ROOT / "measurement" / "policy_classes.json"
DEFAULT_BLACKLIST = PROJECT_ROOT / "measurement" / "check2_blacklist.json"
DEFAULT_FIXTURES = PROJECT_ROOT / "measurement" / "task_fixtures.json"
DEFAULT_SQLITE = PROJECT_ROOT / "data" / "travel.sqlite"
DEFAULT_ANSWERS = PROJECT_ROOT / "measurement" / "tasks_expected_answers.md"

PREFIX_TO_CLASS = {"POL": "policy", "TXN": "transactional", "MIX": "mixed", "EDGE": "edge"}
EXPECTED_DISTRIBUTION = {"policy": 3, "transactional": 3, "mixed": 8, "edge": 3}

# Reference detection — derived from data/travel.sqlite schema:
#   bookings.book_ref:    6 chars uppercase hex-ish (e.g. "06B046")
#   flights.flight_no:    2 uppercase letters + 4 digits (e.g. "QR0051")
#   tickets.ticket_no:    13-16 digits (e.g. "9880005432000987")
BOOK_REF_RE = re.compile(r"\b[0-9A-F]{6}\b")
FLIGHT_NO_RE = re.compile(r"\b[A-Z]{2}\d{4}\b")
TICKET_NO_RE = re.compile(r"\b\d{13,16}\b")

COMPLETE_MARKER_RE = re.compile(r"^\s*#\s*COMPLETE\b", re.IGNORECASE)


class Rubric(BaseModel):
    model_config = ConfigDict(extra="forbid")
    factual_correctness: str
    citation_accuracy: str
    no_fabrication: str


class Task(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    task_id: str = Field(pattern=r"^(POL|TXN|MIX|EDGE)-\d{3}$")
    class_: Literal["policy", "transactional", "mixed", "edge"] = Field(alias="class")
    user_message: str
    expected_answer_summary: str
    expected_citations: list[str]
    policy_classes_invoked: list[str]
    booking_data_required: bool
    rubric: Rubric


@dataclass
class Violation:
    requirement: str
    message: str
    line: int | None = None
    task_id: str | None = None
    severity: str = "ERROR"

    def __str__(self) -> str:
        loc = f"line {self.line}" if self.line is not None else "<file>"
        tid = f" [{self.task_id}]" if self.task_id else ""
        return f"{self.severity:5} {self.requirement:30} {loc}{tid}: {self.message}"


@dataclass
class ParsedTask:
    line: int
    raw: dict
    model: Task | None = None
    parse_errors: list[str] = field(default_factory=list)


@dataclass
class Context:
    vocab: set[str]
    blacklist: list[str]
    fixtures: set[str]
    fixtures_by_kind: dict[str, list[str]]
    fixtures_path: Path
    sqlite_path: Path
    answers_path: Path
    complete_marker: bool


# ---------- Loaders ----------

def load_vocab(path: Path) -> set[str]:
    with path.open() as f:
        return {entry["id"] for entry in json.load(f)}


def load_blacklist(path: Path) -> list[str]:
    with path.open() as f:
        return [s.lower() for s in json.load(f)]


def load_fixtures(path: Path) -> set[str]:
    """Returns the set of all sanctioned reference values (flattened across kinds)."""
    if not path.exists():
        return set()
    with path.open() as f:
        data = json.load(f)
    out: set[str] = set()
    for key in ("book_refs", "flight_nos", "ticket_nos"):
        for item in data.get(key, []):
            if isinstance(item, str):
                out.add(item)
            elif isinstance(item, dict) and "value" in item:
                out.add(item["value"])
    return out


def load_fixtures_by_kind(path: Path) -> dict[str, list[str]]:
    """Returns fixtures grouped by kind (book_refs / flight_nos / ticket_nos).

    Used by check_fixtures_resolve to look up each value in the right table.
    Returns empty dict if the fixtures file is absent — the resolution check
    skips silently in that case (validator may be running before §2 lands).
    """
    if not path.exists():
        return {}
    with path.open() as f:
        data = json.load(f)
    out: dict[str, list[str]] = {}
    for key in ("book_refs", "flight_nos", "ticket_nos"):
        values: list[str] = []
        for item in data.get(key, []):
            if isinstance(item, str):
                values.append(item)
            elif isinstance(item, dict) and "value" in item:
                values.append(item["value"])
        out[key] = values
    return out


def parse_tasks_jsonl(path: Path) -> tuple[list[ParsedTask], bool]:
    """Parse JSONL. Comment lines starting with '#' are skipped; a '# COMPLETE'
    line anywhere flips the complete_marker flag."""
    tasks: list[ParsedTask] = []
    complete = False
    if not path.exists():
        return tasks, complete
    for i, raw_line in enumerate(path.read_text().splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            if COMPLETE_MARKER_RE.match(stripped):
                complete = True
            continue
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError as e:
            tasks.append(ParsedTask(line=i, raw={}, parse_errors=[f"invalid JSON: {e.msg}"]))
            continue
        pt = ParsedTask(line=i, raw=obj)
        try:
            pt.model = Task.model_validate(obj)
        except ValidationError as e:
            pt.parse_errors = [
                f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors()
            ]
        tasks.append(pt)
    return tasks, complete


# ---------- Check functions (one per spec requirement) ----------

def check_schema_conformance(tasks: list[ParsedTask], ctx: Context) -> list[Violation]:
    out: list[Violation] = []
    for t in tasks:
        for err in t.parse_errors:
            out.append(Violation("schema-conformance", err, line=t.line,
                                 task_id=t.raw.get("task_id")))
    return out


def check_task_id_format_and_uniqueness(tasks: list[ParsedTask], ctx: Context) -> list[Violation]:
    out: list[Violation] = []
    first_seen: dict[str, int] = {}
    for t in tasks:
        if t.model is None:
            continue
        tid = t.model.task_id
        if tid in first_seen:
            out.append(Violation("task-id-uniqueness",
                                 f"duplicate task_id (first seen at line {first_seen[tid]})",
                                 line=t.line, task_id=tid))
        else:
            first_seen[tid] = t.line
        prefix = tid.split("-")[0]
        expected = PREFIX_TO_CLASS[prefix]
        if t.model.class_ != expected:
            out.append(Violation("task-id-prefix-class-agreement",
                                 f"prefix {prefix} requires class={expected!r}, got {t.model.class_!r}",
                                 line=t.line, task_id=tid))
    return out


def check_class_distribution(tasks: list[ParsedTask], ctx: Context, strict: bool) -> list[Violation]:
    if not (strict or ctx.complete_marker):
        return []
    counts: Counter[str] = Counter(t.model.class_ for t in tasks if t.model is not None)
    out: list[Violation] = []
    for cls, expected in EXPECTED_DISTRIBUTION.items():
        got = counts.get(cls, 0)
        if got != expected:
            out.append(Violation("class-distribution",
                                 f"expected {expected} {cls!r} tasks, got {got}"))
    return out


def check_controlled_vocabulary(tasks: list[ParsedTask], ctx: Context) -> list[Violation]:
    out: list[Violation] = []
    for t in tasks:
        if t.model is None:
            continue
        for field_name in ("policy_classes_invoked", "expected_citations"):
            for v in getattr(t.model, field_name):
                if v not in ctx.vocab:
                    nearest = _closest_vocab(v, ctx.vocab)
                    hint = f" (closest: {', '.join(nearest)})" if nearest else ""
                    out.append(Violation("controlled-vocabulary",
                                         f"{field_name} value {v!r} not in policy_classes.json{hint}",
                                         line=t.line, task_id=t.model.task_id))
    return out


def check_phrasing(tasks: list[ParsedTask], ctx: Context) -> list[Violation]:
    out: list[Violation] = []
    for t in tasks:
        if t.model is None:
            continue
        lowered = t.model.user_message.lower()
        for bad in ctx.blacklist:
            if bad in lowered:
                out.append(Violation("check2-phrasing",
                                     f"contains architect-style phrase {bad!r} — rewrite in customer voice",
                                     line=t.line, task_id=t.model.task_id))
    return out


def check_referential_integrity(tasks: list[ParsedTask], ctx: Context) -> list[Violation]:
    """For each book_ref/flight_no/ticket_no in user_message: must resolve in sqlite;
    warns if it resolves but is not in task_fixtures.json."""
    out: list[Violation] = []
    if not ctx.sqlite_path.exists():
        out.append(Violation("referential-integrity",
                             f"sqlite db not found at {ctx.sqlite_path}", severity="WARN"))
        return out
    con = sqlite3.connect(ctx.sqlite_path)
    try:
        for t in tasks:
            if t.model is None:
                continue
            msg = t.model.user_message
            for kind, regex, table, column in (
                ("book_ref", BOOK_REF_RE, "bookings", "book_ref"),
                ("flight_no", FLIGHT_NO_RE, "flights", "flight_no"),
                ("ticket_no", TICKET_NO_RE, "tickets", "ticket_no"),
            ):
                for match in regex.findall(msg):
                    row = con.execute(
                        f"SELECT 1 FROM {table} WHERE {column} = ? LIMIT 1", (match,)
                    ).fetchone()
                    if row is None:
                        out.append(Violation("referential-integrity",
                                             f"phantom {kind} {match!r} — no row in {table}",
                                             line=t.line, task_id=t.model.task_id))
                    elif ctx.fixtures and match not in ctx.fixtures:
                        out.append(Violation("referential-integrity",
                                             f"{kind} {match!r} resolves in sqlite but is not in task_fixtures.json",
                                             line=t.line, task_id=t.model.task_id,
                                             severity="WARN"))
    finally:
        con.close()
    return out


def check_booking_data_flag(tasks: list[ParsedTask], ctx: Context) -> list[Violation]:
    out: list[Violation] = []
    for t in tasks:
        if t.model is None:
            continue
        if t.model.class_ == "transactional" and not t.model.booking_data_required:
            out.append(Violation("booking-data-flag",
                                 "transactional task must have booking_data_required=true",
                                 line=t.line, task_id=t.model.task_id))
        has_ref = bool(
            BOOK_REF_RE.search(t.model.user_message)
            or FLIGHT_NO_RE.search(t.model.user_message)
            or TICKET_NO_RE.search(t.model.user_message)
        )
        if has_ref and not t.model.booking_data_required:
            out.append(Violation("booking-data-flag",
                                 "user_message references a booking/flight/ticket but booking_data_required=false — agent will not be given the data path the prompt needs",
                                 line=t.line, task_id=t.model.task_id))
        if t.model.class_ == "policy" and has_ref:
            out.append(Violation("booking-data-flag",
                                 "policy task references a booking — reclassify as mixed",
                                 line=t.line, task_id=t.model.task_id))
    return out


def check_citations_match_class(tasks: list[ParsedTask], ctx: Context) -> list[Violation]:
    out: list[Violation] = []
    for t in tasks:
        if t.model is None:
            continue
        if t.model.class_ in ("policy", "mixed", "edge") and not t.model.expected_citations:
            out.append(Violation("citations-match-class",
                                 f"{t.model.class_} task must have non-empty expected_citations",
                                 line=t.line, task_id=t.model.task_id))
    return out


def check_fixtures_resolve(tasks: list[ParsedTask], ctx: Context) -> list[Violation]:
    """Every entry in task_fixtures.json SHALL resolve to a real row in sqlite.

    Catches upstream data drift even when no task yet references the fixture.
    Skipped silently if the fixtures file is absent (e.g., pre-§2 state).
    """
    out: list[Violation] = []
    if not ctx.fixtures_by_kind:
        return out
    if not ctx.sqlite_path.exists():
        # ERROR not WARN: a silent skip here would defeat the drift gate's
        # only job. If fixtures are committed but the db is unreachable in
        # CI (path misconfig, missing mount), the green-pass is a lie.
        out.append(Violation("fixtures-resolve",
                             f"sqlite db not found at {ctx.sqlite_path} — drift gate cannot run; "
                             f"either restore data/travel.sqlite or remove task_fixtures.json"))
        return out

    kind_to_query = {
        "book_refs": ("bookings", "book_ref"),
        "flight_nos": ("flights", "flight_no"),
        "ticket_nos": ("tickets", "ticket_no"),
    }
    con = sqlite3.connect(ctx.sqlite_path)
    try:
        for kind, values in ctx.fixtures_by_kind.items():
            table, column = kind_to_query[kind]
            for value in values:
                row = con.execute(
                    f"SELECT 1 FROM {table} WHERE {column} = ? LIMIT 1", (value,)
                ).fetchone()
                if row is None:
                    out.append(Violation("fixtures-resolve",
                                         f"fixture {kind[:-1]} {value!r} not found in {table} — "
                                         f"data drift; re-run measurement/scripts/sample_fixtures.py "
                                         f"and update {ctx.fixtures_path.name}"))
    finally:
        con.close()
    return out


def check_expected_answers_parity(tasks: list[ParsedTask], ctx: Context) -> list[Violation]:
    """Every task_id has a `## TASK-ID` heading in tasks_expected_answers.md.
    Orphaned answer entries (heading without a task) also fail."""
    out: list[Violation] = []
    task_ids = {t.model.task_id for t in tasks if t.model is not None}
    if not ctx.answers_path.exists():
        if task_ids:
            out.append(Violation("expected-answers-parity",
                                 f"tasks_expected_answers.md missing at {ctx.answers_path}"))
        return out
    headings = set(re.findall(r"^##\s+([A-Z]+-\d{3})", ctx.answers_path.read_text(), re.MULTILINE))
    for tid in sorted(task_ids - headings):
        out.append(Violation("expected-answers-parity",
                             f"no `## {tid}` heading in tasks_expected_answers.md",
                             task_id=tid))
    for tid in sorted(headings - task_ids):
        out.append(Violation("expected-answers-parity",
                             f"orphaned answer entry `## {tid}` — no matching task in tasks.jsonl",
                             task_id=tid))
    return out


# Append-only registry. New check → append here, no other edits.
CHECKS = [
    check_schema_conformance,
    check_task_id_format_and_uniqueness,
    check_controlled_vocabulary,
    check_phrasing,
    check_referential_integrity,
    check_booking_data_flag,
    check_citations_match_class,
    check_fixtures_resolve,
    check_expected_answers_parity,
]


def _closest_vocab(value: str, vocab: set[str], limit: int = 3) -> list[str]:
    import difflib
    return difflib.get_close_matches(value, vocab, n=limit, cutoff=0.5)


# ---------- Public API ----------

def validate(
    jsonl_path: Path = DEFAULT_TASKS,
    fixtures_path: Path = DEFAULT_FIXTURES,
    vocab_path: Path = DEFAULT_VOCAB,
    blacklist_path: Path = DEFAULT_BLACKLIST,
    sqlite_path: Path = DEFAULT_SQLITE,
    answers_path: Path = DEFAULT_ANSWERS,
    strict: bool = False,
) -> list[Violation]:
    tasks, complete_marker = parse_tasks_jsonl(jsonl_path)
    ctx = Context(
        vocab=load_vocab(vocab_path),
        blacklist=load_blacklist(blacklist_path),
        fixtures=load_fixtures(fixtures_path),
        fixtures_by_kind=load_fixtures_by_kind(fixtures_path),
        fixtures_path=fixtures_path,
        sqlite_path=sqlite_path,
        answers_path=answers_path,
        complete_marker=complete_marker,
    )
    violations: list[Violation] = []
    for check in CHECKS:
        violations.extend(check(tasks, ctx))
    violations.extend(check_class_distribution(tasks, ctx, strict))
    return violations


# ---------- CLI ----------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate measurement/tasks.jsonl")
    parser.add_argument("--strict", action="store_true",
                        help="Enforce 3/3/8/3 class distribution (CI mode)")
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--vocab", type=Path, default=DEFAULT_VOCAB)
    parser.add_argument("--blacklist", type=Path, default=DEFAULT_BLACKLIST)
    parser.add_argument("--sqlite", type=Path, default=DEFAULT_SQLITE)
    parser.add_argument("--answers", type=Path, default=DEFAULT_ANSWERS)
    args = parser.parse_args(argv)

    violations = validate(
        jsonl_path=args.tasks,
        fixtures_path=args.fixtures,
        vocab_path=args.vocab,
        blacklist_path=args.blacklist,
        sqlite_path=args.sqlite,
        answers_path=args.answers,
        strict=args.strict,
    )
    errors = [v for v in violations if v.severity == "ERROR"]
    warns = [v for v in violations if v.severity == "WARN"]
    for v in violations:
        print(v)
    print(f"\n{len(errors)} error(s), {len(warns)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
