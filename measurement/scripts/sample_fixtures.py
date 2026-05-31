"""One-time sampler for measurement/task_fixtures.json.

Picks specific book_ref / flight_no / ticket_no values from data/travel.sqlite
along with rationale strings explaining why each was chosen. Per
openspec/changes/write-benchmark-tasks/design.md Decision 5, this script is
run ONCE and the output is frozen — do not re-run in CI. The frozen fixtures
file becomes the sanctioned source of booking-data references for the task
set; the validator emits a warning if a task references a sqlite row that
isn't in the fixtures.

Design (hybrid linkage, per PR #5 Option F):
- All book_refs MUST touch at least one LX (Swiss Air Lines) flight. Corpus
  is swiss_faq.md; a "Swiss customer" booking with no Swiss flights is
  semantically incoherent.
- All ticket_nos MUST belong to one of the fixture book_refs. Tickets
  sampled independently from bookings produce false intra-data claims like
  "ticket X on my booking Y" — the agent's get_booking/get_ticket calls
  would return inconsistent results.
- flight_nos: 2 of 3 drawn from fixture bookings' LX itineraries (Scheduled
  + Arrived, for upcoming and past-trip tasks). The 3rd is Cancelled —
  intentionally loose-coupled because the data is structurally incapable
  of representing a customer-booked cancelled flight (414 Cancelled rows
  exist in `flights`, zero tickets are sold against any of them). See
  design.md Decision 7 amendment for the loose-coupling pattern.

The queries are deterministic (ORDER BY <stable column> ASC LIMIT 1) so
re-running on the same sqlite snapshot produces the same output.

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


# Reusable subquery: book_refs whose itinerary includes at least one LX flight.
LX_TOUCHING_SUBQUERY = """
    SELECT DISTINCT t2.book_ref FROM tickets t2
    JOIN ticket_flights tf2 ON tf2.ticket_no = t2.ticket_no
    JOIN flights f2 ON f2.flight_id = tf2.flight_id
    WHERE f2.flight_no LIKE 'LX%'
"""


def _first_lx_touching_booking(con: sqlite3.Connection, pax: int, classes_filter: str) -> tuple:
    """Return the alphabetically-first LX-touching book_ref matching constraints.

    `pax` is the exact passenger count required; `classes_filter` is a HAVING
    fragment over the GROUP_CONCAT of fare classes (e.g., "= 'Economy'" for
    pure-Economy, "LIKE '%Business%'" for any Business presence).
    """
    row = con.execute(f"""
        SELECT t.book_ref, b.total_amount, COUNT(DISTINCT t.ticket_no) AS pax,
               GROUP_CONCAT(DISTINCT tf.fare_conditions) AS classes
        FROM tickets t JOIN bookings b ON b.book_ref = t.book_ref
        JOIN ticket_flights tf ON tf.ticket_no = t.ticket_no
        WHERE t.book_ref IN ({LX_TOUCHING_SUBQUERY})
        GROUP BY t.book_ref
        HAVING pax = ? AND classes {classes_filter}
        ORDER BY t.book_ref ASC LIMIT 1
    """, (pax,)).fetchone()
    if row is None:
        raise RuntimeError(
            f"no LX-touching booking with pax={pax} and classes {classes_filter}"
        )
    return row


def sample_book_refs(con: sqlite3.Connection) -> list[FixtureRow]:
    """Three LX-touching book_refs spanning passenger count + fare-class variety.

    The 1/2/3-pax constraints are deliberate: they let the three fixture
    tickets (Economy / Business / Comfort) each live in a different fixture
    booking, demonstrating distinct customer scenarios.
    """
    out: list[FixtureRow] = []

    # Solo traveller, pure Economy — baseline single-passenger TXN reference.
    row = _first_lx_touching_booking(con, pax=1, classes_filter="= 'Economy'")
    out.append(FixtureRow(
        value=row[0],
        rationale=f"solo LX-touching booking, Economy-only "
                  f"(total_amount={row[1]}, 1 ticket) — baseline single-passenger "
                  f"reference and host for the Economy fixture ticket",
    ))

    # Couple/co-travellers with at least one Business ticket — premium spread.
    row = _first_lx_touching_booking(con, pax=2, classes_filter="LIKE '%Business%'")
    out.append(FixtureRow(
        value=row[0],
        rationale=f"two-passenger LX-touching booking with Business class present "
                  f"(total_amount={row[1]}) — couples/co-travellers premium scenario "
                  f"and host for the Business fixture ticket",
    ))

    # Group/family with all three fare classes — richest scenario coverage.
    row = _first_lx_touching_booking(
        con, pax=3,
        classes_filter="LIKE '%Business%' AND classes LIKE '%Comfort%' AND classes LIKE '%Economy%'",
    )
    out.append(FixtureRow(
        value=row[0],
        rationale=f"three-passenger LX-touching booking spanning Business + Comfort + "
                  f"Economy (total_amount={row[1]}) — group/family scenario and host "
                  f"for the Comfort fixture ticket (Comfort is in sqlite but absent "
                  f"from corpus → EDGE-003 grounding)",
    ))
    return out


def sample_flight_nos(con: sqlite3.Connection, book_refs: list[str]) -> list[FixtureRow]:
    """Three LX flight_nos: cancelled (loose-coupled), scheduled (linked), arrived (linked).

    The Cancelled flight is sampled independently because no booking in this
    corpus touches a cancelled flight — see design.md Decision 7 amendment.
    The Scheduled + Arrived flights are drawn from fixture bookings' LX
    itineraries so customer-style messages can naturally tie the flight to
    the booking ("on my booking X, the LX flight Y…").
    """
    out: list[FixtureRow] = []
    placeholders = ",".join("?" for _ in book_refs)

    # Cancelled LX — loose-coupled. Sampled across all LX flights regardless of bookings.
    row = con.execute("""
        SELECT flight_no FROM flights
        WHERE status = 'Cancelled' AND flight_no LIKE 'LX%'
        ORDER BY flight_no ASC LIMIT 1
    """).fetchone()
    if row is None:
        raise RuntimeError("no cancelled LX flight in the corpus")
    out.append(FixtureRow(
        value=row[0],
        rationale="LX flight with status='Cancelled' — LOOSE-COUPLED to fixture "
                  "book_refs (no booking in this corpus has a cancelled flight in "
                  "its itinerary; this is a structural property of travel.sqlite, "
                  "see design.md Decision 7 amendment). Used for cancellation-themed "
                  "MIX tasks via the customer's narrative join.",
    ))

    # Scheduled LX from inside one of the fixture bookings — tightly linked.
    row = con.execute(f"""
        SELECT DISTINCT f.flight_no FROM tickets t
        JOIN ticket_flights tf ON tf.ticket_no = t.ticket_no
        JOIN flights f ON f.flight_id = tf.flight_id
        WHERE t.book_ref IN ({placeholders})
          AND f.flight_no LIKE 'LX%' AND f.status = 'Scheduled'
        ORDER BY f.flight_no ASC LIMIT 1
    """, book_refs).fetchone()
    if row is None:
        raise RuntimeError("no scheduled LX flight inside any fixture booking")
    out.append(FixtureRow(
        value=row[0],
        rationale=f"LX flight with status='Scheduled', linked to a fixture booking — "
                  f"customer-style 'my upcoming flight on booking X' phrasings ground "
                  f"naturally because the flight is actually in the booking's itinerary",
    ))

    # Arrived LX from inside a fixture booking — past-trip framing.
    row = con.execute(f"""
        SELECT DISTINCT f.flight_no FROM tickets t
        JOIN ticket_flights tf ON tf.ticket_no = t.ticket_no
        JOIN flights f ON f.flight_id = tf.flight_id
        WHERE t.book_ref IN ({placeholders})
          AND f.flight_no LIKE 'LX%' AND f.status = 'Arrived'
        ORDER BY f.flight_no ASC LIMIT 1
    """, book_refs).fetchone()
    if row is None:
        raise RuntimeError("no arrived LX flight inside any fixture booking")
    out.append(FixtureRow(
        value=row[0],
        rationale=f"LX flight with status='Arrived', linked to a fixture booking — "
                  f"supports 'past trip' MIX tasks (e.g. invoice ordering, Decision 7 #8) "
                  f"where the customer references a completed Swiss flight from their booking",
    ))
    return out


def sample_ticket_nos(con: sqlite3.Connection, book_refs: list[str]) -> list[FixtureRow]:
    """Three ticket_nos drawn from inside fixture bookings, covering Business + Comfort + Economy.

    Each ticket lives in a different fixture booking (per sample_book_refs'
    construction). This is the core of Option F: tight intra-data linkage
    so customer-style phrasings like "on my booking X, ticket Y" hold true
    against the data.
    """
    out: list[FixtureRow] = []

    def pick(book_ref: str, fare_class: str, rationale: str) -> None:
        # Prefer tickets where the named fare class is the only class on the ticket,
        # so the framing is unambiguous; fall back to mixed-class tickets if needed.
        row = con.execute("""
            SELECT t.ticket_no FROM tickets t
            JOIN ticket_flights tf ON tf.ticket_no = t.ticket_no
            WHERE t.book_ref = ?
            GROUP BY t.ticket_no
            HAVING GROUP_CONCAT(DISTINCT tf.fare_conditions) = ?
            ORDER BY t.ticket_no ASC LIMIT 1
        """, (book_ref, fare_class)).fetchone()
        if row is None:
            # Fall back: any ticket in the booking that has this fare class on at least one leg.
            row = con.execute("""
                SELECT t.ticket_no FROM tickets t
                JOIN ticket_flights tf ON tf.ticket_no = t.ticket_no
                WHERE t.book_ref = ? AND tf.fare_conditions = ?
                ORDER BY t.ticket_no ASC LIMIT 1
            """, (book_ref, fare_class)).fetchone()
        if row is None:
            raise RuntimeError(f"no {fare_class} ticket in booking {book_ref}")
        out.append(FixtureRow(value=row[0], rationale=rationale))

    # Booking[0] is the solo Economy-only — Economy fixture lives here.
    pick(book_refs[0], "Economy",
         f"Economy ticket inside fixture booking {book_refs[0]} (solo traveller) — "
         f"baseline routine TXN reference; tight linkage means 'on my booking X, ticket Y' "
         f"phrasings ground true against the data")

    # Booking[1] is the 2-pax with Business — Business fixture lives here.
    pick(book_refs[1], "Business",
         f"Ticket with Business fare in fixture booking {book_refs[1]} (couple/co-travellers) — "
         f"exercises swiss_faq.md European fare concept policy questions on a Business cabin")

    # Booking[2] is the 3-pax with Comfort — Comfort fixture lives here.
    pick(book_refs[2], "Comfort",
         f"Ticket with Comfort fare in fixture booking {book_refs[2]} (group/family) — "
         f"Comfort is present in travel.sqlite but absent from swiss_faq.md, making this "
         f"ticket the EDGE-003 (out-of-scope refusal) grounding")
    return out


def build_fixtures(sqlite_path: Path) -> dict:
    if not sqlite_path.exists():
        raise FileNotFoundError(f"sqlite database not found at {sqlite_path}")
    con = sqlite3.connect(sqlite_path)
    try:
        book_rows = sample_book_refs(con)
        book_refs = [r.value for r in book_rows]
        return {
            "_meta": {
                "source": str(sqlite_path.relative_to(PROJECT_ROOT)),
                "sampler": "measurement/scripts/sample_fixtures.py",
                "frozen": True,
                "linkage": "hybrid (PR #5 Option F): book_refs touch LX; "
                           "Scheduled+Arrived flight_nos drawn from fixture bookings' "
                           "itineraries; Cancelled flight_no is loose-coupled because the "
                           "corpus has no booked cancellations (design.md Decision 7 amendment); "
                           "ticket_nos drawn from inside fixture bookings",
                "note": "Generated once via sampler. Do not re-run in CI. "
                        "If the upstream sqlite changes, the validator's "
                        "fixture-resolution check will catch drift.",
            },
            "book_refs": [r.to_dict() for r in book_rows],
            "flight_nos": [r.to_dict() for r in sample_flight_nos(con, book_refs)],
            "ticket_nos": [r.to_dict() for r in sample_ticket_nos(con, book_refs)],
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
