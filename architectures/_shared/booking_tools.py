"""Booking Systems' transactional tools — identical across all measured
architectures.

Per CLAUDE.md (Architectural invariants):
    Transactional tools (get_booking_status, search_flights, search_hotels,
    search_cars) are identical across all measured architectures. If you
    change one, change them all — the comparison assumes the only difference
    is retrieval.

Per the modularity constraint (METHODOLOGY § "Modularity constraint"):
    AI Engineering's agent calls these tools; it never reads
    `data/travel.sqlite` directly. The tools themselves are conceptually
    owned by Booking Systems.

All SQL is parameterised. No string interpolation into queries.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# DB path resolution
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_DB_PATH = _REPO_ROOT / "data" / "travel.sqlite"


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    """Open a read-only connection to travel.sqlite.

    Returns a connection with row_factory set so tool responses are
    structured dicts.
    """
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    if not path.exists():
        raise FileNotFoundError(
            f"travel.sqlite not found at {path}. Run the Phase 1 Step 0 "
            f"fetch (see BUILD_PLAN.md)."
        )
    # URI form lets us open read-only — defends against accidental writes
    # from a tool that's supposed to be query-only.
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# get_booking_status
# ---------------------------------------------------------------------------


def get_booking_status(
    booking_id: str, *, db_path: Path | None = None
) -> dict[str, Any]:
    """Return the booking record and its itinerary.

    Shape:
        {
          "booking_id": "0002D8",
          "total_amount": 23600,
          "book_date": "...",
          "passenger_count": 1,
          "segments": [
              {"ticket_no": "...", "passenger_id": "...",
               "flight_no": "LX0136", "fare_conditions": "Economy",
               "departure_airport": "...", "arrival_airport": "...",
               "scheduled_departure": "...", "status": "Scheduled"},
              …
          ]
        }
        or {"booking_id": "...", "found": false} when no such booking.

    Tickets are listed per (ticket, flight) pair so multi-segment
    itineraries surface every segment.
    """
    if not isinstance(booking_id, str) or not booking_id:
        return {"booking_id": booking_id, "found": False, "error": "invalid booking_id"}

    with _connect(db_path) as conn:
        booking_row = conn.execute(
            "SELECT book_ref, book_date, total_amount FROM bookings WHERE book_ref = ?",
            (booking_id,),
        ).fetchone()
        if booking_row is None:
            return {"booking_id": booking_id, "found": False}

        passenger_rows = conn.execute(
            "SELECT DISTINCT passenger_id FROM tickets WHERE book_ref = ?",
            (booking_id,),
        ).fetchall()

        segment_rows = conn.execute(
            """
            SELECT
                t.ticket_no,
                t.passenger_id,
                tf.fare_conditions,
                f.flight_no,
                f.departure_airport,
                f.arrival_airport,
                f.scheduled_departure,
                f.status
            FROM tickets t
            JOIN ticket_flights tf ON tf.ticket_no = t.ticket_no
            JOIN flights f ON f.flight_id = tf.flight_id
            WHERE t.book_ref = ?
            ORDER BY t.ticket_no, f.scheduled_departure
            """,
            (booking_id,),
        ).fetchall()

    return {
        "booking_id": booking_row["book_ref"],
        "book_date": booking_row["book_date"],
        "total_amount": booking_row["total_amount"],
        "passenger_count": len(passenger_rows),
        "segments": _rows_to_dicts(segment_rows),
    }


# ---------------------------------------------------------------------------
# get_flight_status
# ---------------------------------------------------------------------------


def get_flight_status(
    flight_no: str, *, db_path: Path | None = None
) -> dict[str, Any]:
    """Return route-level status counts for a flight number.

    The LangGraph travel db is route-keyed: a flight_no recurs across
    many dates with different statuses. The tool returns:

        {
          "flight_no": "LX0000",
          "found": true,
          "instances": 61,
          "status_counts": {"Cancelled": 12, "Arrived": 40, …},
          "any_cancelled": true,
          "sample_instances": [{flight_id, scheduled_departure, status}, …]
        }

    Used by EDGE / MIX tasks that check "is this flight number ever
    cancelled" (per task_fixtures.json _meta on LX0000 loose coupling).
    """
    if not isinstance(flight_no, str) or not flight_no:
        return {"flight_no": flight_no, "found": False, "error": "invalid flight_no"}

    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT flight_id, scheduled_departure, status
            FROM flights
            WHERE flight_no = ?
            ORDER BY scheduled_departure
            """,
            (flight_no,),
        ).fetchall()

    if not rows:
        return {"flight_no": flight_no, "found": False}

    status_counts: dict[str, int] = {}
    for row in rows:
        status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1

    return {
        "flight_no": flight_no,
        "found": True,
        "instances": len(rows),
        "status_counts": status_counts,
        "any_cancelled": status_counts.get("Cancelled", 0) > 0,
        "sample_instances": _rows_to_dicts(rows[:5]),
    }


# ---------------------------------------------------------------------------
# search_flights
# ---------------------------------------------------------------------------


def search_flights(
    *,
    origin: str | None = None,
    destination: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 10,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Search flights by origin / destination / date range.

    All filters optional but at least one must be provided (a bare query
    against ~30k flights would burn tokens with no useful result).
    """
    if not any([origin, destination, date_from, date_to]):
        return {"results": [], "error": "specify at least one filter"}

    where_parts: list[str] = []
    params: list[Any] = []
    if origin:
        where_parts.append("departure_airport = ?")
        params.append(origin)
    if destination:
        where_parts.append("arrival_airport = ?")
        params.append(destination)
    # Compare on date(scheduled_departure) so date-only inputs
    # ("2026-06-02") behave inclusively at both ends — a bare-date
    # date_to was previously string-compared against full timestamps
    # ("2026-06-02 14:30:00…"), excluding every flight later than
    # midnight that day. Timestamp inputs work too since date() truncates
    # before comparing.
    if date_from:
        where_parts.append("date(scheduled_departure) >= date(?)")
        params.append(date_from)
    if date_to:
        where_parts.append("date(scheduled_departure) <= date(?)")
        params.append(date_to)

    where_clause = " AND ".join(where_parts)
    bounded_limit = max(1, min(int(limit), 50))

    with _connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT flight_no, departure_airport, arrival_airport,
                   scheduled_departure, scheduled_arrival, status
            FROM flights
            WHERE {where_clause}
            ORDER BY scheduled_departure
            LIMIT ?
            """,
            (*params, bounded_limit),
        ).fetchall()

    return {"results": _rows_to_dicts(rows), "count": len(rows)}


# ---------------------------------------------------------------------------
# search_hotels
# ---------------------------------------------------------------------------


def search_hotels(
    *,
    location: str | None = None,
    price_tier: str | None = None,
    checkin_date: str | None = None,
    checkout_date: str | None = None,
    limit: int = 10,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Search hotels with optional filters."""
    where_parts: list[str] = []
    params: list[Any] = []
    if location:
        where_parts.append("location = ?")
        params.append(location)
    if price_tier:
        where_parts.append("price_tier = ?")
        params.append(price_tier)
    if checkin_date:
        where_parts.append("checkin_date >= ?")
        params.append(checkin_date)
    if checkout_date:
        where_parts.append("checkout_date <= ?")
        params.append(checkout_date)

    where_clause = " AND ".join(where_parts) if where_parts else "1=1"
    bounded_limit = max(1, min(int(limit), 50))

    with _connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT id, name, location, price_tier,
                   checkin_date, checkout_date, booked
            FROM hotels
            WHERE {where_clause}
            ORDER BY id
            LIMIT ?
            """,
            (*params, bounded_limit),
        ).fetchall()

    return {"results": _rows_to_dicts(rows), "count": len(rows)}


# ---------------------------------------------------------------------------
# search_cars
# ---------------------------------------------------------------------------


def search_cars(
    *,
    location: str | None = None,
    price_tier: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 10,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Search car rentals with optional filters."""
    where_parts: list[str] = []
    params: list[Any] = []
    if location:
        where_parts.append("location = ?")
        params.append(location)
    if price_tier:
        where_parts.append("price_tier = ?")
        params.append(price_tier)
    if start_date:
        where_parts.append("start_date >= ?")
        params.append(start_date)
    if end_date:
        where_parts.append("end_date <= ?")
        params.append(end_date)

    where_clause = " AND ".join(where_parts) if where_parts else "1=1"
    bounded_limit = max(1, min(int(limit), 50))

    with _connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT id, name, location, price_tier,
                   start_date, end_date, booked
            FROM car_rentals
            WHERE {where_clause}
            ORDER BY id
            LIMIT ?
            """,
            (*params, bounded_limit),
        ).fetchall()

    return {"results": _rows_to_dicts(rows), "count": len(rows)}


# ---------------------------------------------------------------------------
# Tool schema definitions (Anthropic format) — shared across architectures
# ---------------------------------------------------------------------------


BOOKING_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "get_booking_status",
        "description": (
            "Retrieve a booking and its full itinerary by booking reference. "
            "Returns passenger count, total amount, and per-segment details "
            "(flight_no, fare_conditions, departure/arrival airports, status). "
            "Use this when the customer references a specific booking ID."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "booking_id": {
                    "type": "string",
                    "description": "Booking reference (e.g., '0002D8').",
                }
            },
            "required": ["booking_id"],
        },
    },
    {
        "name": "get_flight_status",
        "description": (
            "Look up route-level status for a flight number across all its "
            "scheduled instances. Returns status counts and whether any "
            "instance is cancelled. Use this when the customer references a "
            "flight number that may not be tied to their booking."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "flight_no": {
                    "type": "string",
                    "description": "Flight designator (e.g., 'LX0000').",
                }
            },
            "required": ["flight_no"],
        },
    },
    {
        "name": "search_flights",
        "description": (
            "Search the flight schedule by origin, destination, and/or date "
            "range. At least one filter required. Use this for new-booking "
            "or availability questions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "origin": {"type": "string", "description": "Departure airport code."},
                "destination": {"type": "string", "description": "Arrival airport code."},
                "date_from": {"type": "string", "description": "Earliest departure (ISO date)."},
                "date_to": {"type": "string", "description": "Latest departure (ISO date)."},
                "limit": {"type": "integer", "description": "Max results (default 10, max 50)."},
            },
        },
    },
    {
        "name": "search_hotels",
        "description": (
            "Search hotel inventory by location, price tier, and/or stay dates."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "location": {"type": "string"},
                "price_tier": {"type": "string"},
                "checkin_date": {"type": "string"},
                "checkout_date": {"type": "string"},
                "limit": {"type": "integer"},
            },
        },
    },
    {
        "name": "search_cars",
        "description": (
            "Search car rental inventory by location, price tier, and/or "
            "rental dates."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "location": {"type": "string"},
                "price_tier": {"type": "string"},
                "start_date": {"type": "string"},
                "end_date": {"type": "string"},
                "limit": {"type": "integer"},
            },
        },
    },
]


BOOKING_TOOL_DISPATCH = {
    "get_booking_status": get_booking_status,
    "get_flight_status": get_flight_status,
    "search_flights": search_flights,
    "search_hotels": search_hotels,
    "search_cars": search_cars,
}
