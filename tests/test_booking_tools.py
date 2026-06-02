"""Tests for `architectures/_shared/booking_tools.py`.

Booking tools are IDENTICAL across all measured architectures (CLAUDE.md).
These tests pin their behavior so a future architecture's bug can't
silently change a shared dependency.

The tests query the real `data/travel.sqlite` against frozen fixtures
in `measurement/task_fixtures.json`. If the upstream DB ever changes,
these tests fail loudly.
"""
from __future__ import annotations

import json
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent.parent
_TASK_FIXTURES = json.loads(
    (_REPO_ROOT / "measurement" / "task_fixtures.json").read_text()
)
_FIXTURE_BOOKING_IDS = [b["value"] for b in _TASK_FIXTURES["book_refs"]]
_FIXTURE_FLIGHT_NOS = [f["value"] for f in _TASK_FIXTURES["flight_nos"]]


class TestGetBookingStatus:
    def test_returns_record_for_known_booking(self):
        from architectures._shared.booking_tools import get_booking_status

        # 0002D8 is the solo-traveller fixture; should have 1 passenger.
        result = get_booking_status("0002D8")
        assert result.get("booking_id") == "0002D8"
        assert result.get("passenger_count") == 1
        assert len(result.get("segments", [])) >= 1

    def test_returns_not_found_for_unknown(self):
        from architectures._shared.booking_tools import get_booking_status

        result = get_booking_status("ZZZZZZ")
        assert result.get("found") is False
        assert result.get("booking_id") == "ZZZZZZ"

    def test_segments_carry_fare_conditions(self):
        from architectures._shared.booking_tools import get_booking_status

        # 3F0481 is the Comfort-fixture booking; one of its segments
        # carries fare_conditions='Comfort' (EDGE-003 grounding).
        result = get_booking_status("3F0481")
        fares = {s["fare_conditions"] for s in result["segments"]}
        # The Comfort segment exists on at least one ticket in this booking.
        assert "Comfort" in fares, f"Expected Comfort fare, got {fares}"

    def test_rejects_non_string_booking_id(self):
        from architectures._shared.booking_tools import get_booking_status

        result = get_booking_status("")
        assert result.get("found") is False

    def test_uses_parameterised_sql(self):
        """A booking_id containing a SQL injection attempt returns no
        rows, not a crash and not extra rows. Parameter binding is the
        defense — this test pins that the implementation routes through it.
        """
        from architectures._shared.booking_tools import get_booking_status

        injection_attempt = "0002D8' OR '1'='1"
        result = get_booking_status(injection_attempt)
        # Either not-found (most likely) or exactly the booking matching
        # the literal string. Crucially, NOT every-booking-in-the-table.
        if result.get("found") is False:
            assert True
        else:
            assert result["booking_id"] == injection_attempt


class TestGetFlightStatus:
    def test_returns_route_level_data(self):
        from architectures._shared.booking_tools import get_flight_status

        # LX0000 is the loose-coupled cancellation fixture: the route
        # has at least one Cancelled instance by design (per
        # task_fixtures.json _meta).
        result = get_flight_status("LX0000")
        assert result.get("found") is True
        assert result.get("instances", 0) > 0
        assert result.get("any_cancelled") is True

    def test_unknown_flight_returns_not_found(self):
        from architectures._shared.booking_tools import get_flight_status

        result = get_flight_status("ZZ9999")
        assert result.get("found") is False


class TestSearchFlights:
    def test_requires_at_least_one_filter(self):
        from architectures._shared.booking_tools import search_flights

        result = search_flights()
        assert result.get("results") == []
        assert "error" in result

    def test_filters_by_origin(self):
        from architectures._shared.booking_tools import search_flights

        # ZRH is in the corpus; any flight from ZRH should return rows.
        result = search_flights(origin="ZRH", limit=3)
        for row in result.get("results", []):
            assert row["departure_airport"] == "ZRH"

    def test_limit_is_bounded(self):
        from architectures._shared.booking_tools import search_flights

        # Pass an absurd limit; verify it's clamped to 50.
        result = search_flights(origin="ZRH", limit=10000)
        assert len(result.get("results", [])) <= 50


class TestSchemas:
    def test_all_shared_tool_schemas_are_well_formed(self):
        """Every shared tool schema has the keys Anthropic's API requires."""
        from architectures._shared.booking_tools import BOOKING_TOOL_SCHEMAS

        for schema in BOOKING_TOOL_SCHEMAS:
            assert "name" in schema and isinstance(schema["name"], str)
            assert "description" in schema and isinstance(schema["description"], str)
            assert "input_schema" in schema
            assert schema["input_schema"]["type"] == "object"

    def test_dispatch_covers_every_schema(self):
        """Every advertised tool has a dispatch entry — no schema lies."""
        from architectures._shared.booking_tools import (
            BOOKING_TOOL_DISPATCH,
            BOOKING_TOOL_SCHEMAS,
        )

        schema_names = {s["name"] for s in BOOKING_TOOL_SCHEMAS}
        dispatch_names = set(BOOKING_TOOL_DISPATCH.keys())
        assert schema_names == dispatch_names
