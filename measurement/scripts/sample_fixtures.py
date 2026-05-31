"""One-time sampler for measurement/task_fixtures.json.

Picks specific book_ref / flight_no / ticket_no values from data/travel.sqlite
along with rationale strings explaining why each was chosen. Per
openspec/changes/write-benchmark-tasks/design.md Decision 5, this script is
run ONCE and the output is frozen — do not re-run in CI. The frozen fixtures
file becomes the sanctioned source of booking-data references for the task
set; the validator emits a warning if a task references a sqlite row that
isn't in the fixtures.

The queries are deterministic (ORDER BY <stable column> LIMIT 1) so re-running
on the same sqlite snapshot produces the same output. If the database changes
upstream, the fixture choices may change too — the validator's referential-
integrity check is the safety net that surfaces drift.

Usage:
    python measurement/scripts/sample_fixtures.py
    python measurement/scripts/sample_fixtures.py --output PATH
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_SQLITE = PROJECT_ROOT / "data" / "travel.sqlite"
DEFAULT_OUTPUT = PROJECT_ROOT / "measurement" / "task_fixtures.json"


@dataclass
class FixtureRow:
    value: str
    rationale: str

    def to_dict(self) -> dict:
        return {"value": self.value, "rationale": self.rationale}


def sample_book_refs(con: sqlite3.Connection) -> list[FixtureRow]:
    """Three book_refs spanning total_amount range and passenger count."""
    out: list[FixtureRow] = []

    # 1. Highest-value multi-passenger booking — useful for "what did our group pay" MIX tasks.
    row = con.execute("""
        SELECT b.book_ref, b.total_amount, COUNT(t.ticket_no) AS passengers
        FROM bookings b JOIN tickets t ON t.book_ref = b.book_ref
        GROUP BY b.book_ref
        HAVING passengers >= 3
        ORDER BY b.total_amount DESC, b.book_ref ASC
        LIMIT 1
    """).fetchone()
    out.append(FixtureRow(
        value=row[0],
        rationale=f"high-value multi-passenger booking (total_amount={row[1]}, "
                  f"{row[2]} tickets) — exercises group/family-booking phrasings",
    ))

    # 2. Mid-value two-passenger booking — useful for couples/co-travellers tasks.
    row = con.execute("""
        SELECT b.book_ref, b.total_amount, COUNT(t.ticket_no) AS passengers
        FROM bookings b JOIN tickets t ON t.book_ref = b.book_ref
        GROUP BY b.book_ref
        HAVING passengers = 2
        ORDER BY b.book_ref ASC
        LIMIT 1
    """).fetchone()
    out.append(FixtureRow(
        value=row[0],
        rationale=f"mid-range two-passenger booking (total_amount={row[1]}) — "
                  f"exercises couples/co-travellers phrasings",
    ))

    # 3. Low-value single-passenger booking — useful for solo-traveller TXN tasks.
    row = con.execute("""
        SELECT b.book_ref, b.total_amount, COUNT(t.ticket_no) AS passengers
        FROM bookings b JOIN tickets t ON t.book_ref = b.book_ref
        GROUP BY b.book_ref
        HAVING passengers = 1 AND b.total_amount BETWEEN 30000 AND 60000
        ORDER BY b.book_ref ASC
        LIMIT 1
    """).fetchone()
    out.append(FixtureRow(
        value=row[0],
        rationale=f"low-value solo booking (total_amount={row[1]}, 1 ticket) — "
                  f"baseline single-passenger reference",
    ))
    return out


def sample_flight_nos(con: sqlite3.Connection) -> list[FixtureRow]:
    """Three flight_nos spanning status variety, restricted to LX (Swiss) carrier.

    Carrier restriction matters: corpus is swiss_faq.md (Swiss Air Lines = LX).
    Picking flight_nos from other carriers (e.g. AA) makes customer-style
    phrasings semantically incoherent ("I'm a Swiss customer asking about AA…").
    """
    out: list[FixtureRow] = []

    def pick(status: str, note: str) -> None:
        row = con.execute(
            "SELECT flight_no FROM flights "
            "WHERE status = ? AND flight_no LIKE 'LX%' "
            "AND flight_no NOT IN (SELECT value FROM picked) "
            "ORDER BY flight_no ASC LIMIT 1",
            (status,),
        ).fetchone()
        if row is None:
            raise RuntimeError(f"no LX flight with status={status!r} available")
        out.append(FixtureRow(value=row[0], rationale=f"LX flight with status={status!r} — {note}"))
        con.execute("INSERT INTO picked(value) VALUES (?)", (row[0],))

    con.execute("CREATE TEMP TABLE picked(value TEXT PRIMARY KEY)")
    try:
        pick("Cancelled", "disruption reference for MIX 'my flight was cancelled' tasks "
                         "and EDGE 'cancelled booking' loose-coupling pattern (see design.md "
                         "Decision 7 amendment — no booking in this corpus actually has a "
                         "cancelled flight in its itinerary, so cancellation is referenced "
                         "via flight_no, not book_ref)")
        pick("Delayed", "exercises status-check TXN and disruption-handling MIX tasks")
        pick("Scheduled", "baseline upcoming-flight reference for routine TXN lookups")
    finally:
        con.execute("DROP TABLE picked")
    return out


def sample_ticket_nos(con: sqlite3.Connection) -> list[FixtureRow]:
    """Three ticket_nos covering Business, Comfort, Economy fare classes.

    Expanded from 2 → 3 during PR #5 review (see OpenSpec tasks.md §2.1).
    Comfort is included because it is a real fare class in travel.sqlite
    (17k+ tickets) but is NOT covered in swiss_faq.md — this asymmetry makes
    it the ideal grounding for EDGE-003 (out-of-scope refusal): a customer
    asking Comfort-specific policy questions should be answered "I don't
    have that information," not fabricated from low-similarity retrieval.
    """
    out: list[FixtureRow] = []

    # Business — premium fare class, exercises European-fare-concept questions
    row = con.execute("""
        SELECT ticket_no, fare_conditions FROM ticket_flights
        WHERE fare_conditions = 'Business'
        ORDER BY ticket_no ASC LIMIT 1
    """).fetchone()
    out.append(FixtureRow(
        value=row[0],
        rationale="Business fare ticket — premium fare class covered by "
                  "swiss_faq.md European fare concept section; supports "
                  "policy-grounded MIX tasks tying a fare class to FAQ rules",
    ))

    # Comfort — present in sqlite but NOT in corpus → EDGE-003 grounding
    row = con.execute("""
        SELECT ticket_no, fare_conditions FROM ticket_flights
        WHERE fare_conditions = 'Comfort'
        ORDER BY ticket_no ASC LIMIT 1
    """).fetchone()
    out.append(FixtureRow(
        value=row[0],
        rationale="Comfort fare ticket — present in travel.sqlite but NOT "
                  "discussed in swiss_faq.md; supports EDGE-003 out-of-scope "
                  "refusal grounding (agent should decline rather than "
                  "fabricate from low-similarity retrieval)",
    ))

    # Economy — most common fare class, baseline TXN
    row = con.execute("""
        SELECT ticket_no, fare_conditions FROM ticket_flights
        WHERE fare_conditions = 'Economy'
        ORDER BY ticket_no ASC LIMIT 1
    """).fetchone()
    out.append(FixtureRow(
        value=row[0],
        rationale="Economy fare ticket — most common fare class, baseline "
                  "reference for routine fare-conditions TXN tasks and "
                  "Economy Light/Classic/Flex policy questions",
    ))
    return out


def build_fixtures(sqlite_path: Path) -> dict:
    if not sqlite_path.exists():
        raise FileNotFoundError(f"sqlite database not found at {sqlite_path}")
    con = sqlite3.connect(sqlite_path)
    try:
        return {
            "_meta": {
                "source": str(sqlite_path.relative_to(PROJECT_ROOT)),
                "sampler": "measurement/scripts/sample_fixtures.py",
                "frozen": True,
                "note": "Generated once via sampler. Do not re-run in CI. "
                        "If the upstream sqlite changes, the validator's "
                        "fixture-resolution check will catch drift.",
            },
            "book_refs": [r.to_dict() for r in sample_book_refs(con)],
            "flight_nos": [r.to_dict() for r in sample_flight_nos(con)],
            "ticket_nos": [r.to_dict() for r in sample_ticket_nos(con)],
        }
    finally:
        con.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sample booking fixtures from travel.sqlite (one-time).")
    parser.add_argument("--sqlite", type=Path, default=DEFAULT_SQLITE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--print", action="store_true", help="Print JSON to stdout instead of writing")
    args = parser.parse_args(argv)

    fixtures = build_fixtures(args.sqlite)
    rendered = json.dumps(fixtures, indent=2, ensure_ascii=False) + "\n"

    if args.print:
        sys.stdout.write(rendered)
        return 0

    args.output.write_text(rendered)
    print(f"Wrote {args.output.relative_to(PROJECT_ROOT)}")
    print(f"  book_refs: {[r['value'] for r in fixtures['book_refs']]}")
    print(f"  flight_nos: {[r['value'] for r in fixtures['flight_nos']]}")
    print(f"  ticket_nos: {[r['value'] for r in fixtures['ticket_nos']]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
