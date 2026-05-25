"""Pytest configuration shared across all tests.

Two markers gate API-related tests:

  requires_api_key — auto-skipped when ANTHROPIC_API_KEY is missing.
                     Used for tests that need a real key but are otherwise
                     safe to run automatically (e.g., loading the SDK).

  live_api         — opt-in only via --run-live-api. Used for tests that
                     hit the real Anthropic API and cost real money
                     (cassette recording, end-to-end smoke runs).
                     Both this AND requires_api_key must be passed for
                     a test to actually run.

The combination protects against accidental API spend: even when a key
is present in the environment, `live_api` tests stay skipped unless
the user explicitly opts in.
"""
from __future__ import annotations

import os

import pytest

try:
    # Make a .env-stored ANTHROPIC_API_KEY visible to the tests.
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


def pytest_addoption(parser):
    parser.addoption(
        "--run-live-api",
        action="store_true",
        default=False,
        help=(
            "Run tests marked `live_api` (real Anthropic API calls — costs "
            "real money; see BUDGET.md for tier policy)"
        ),
    )


def pytest_collection_modifyitems(config, items):
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    run_live = config.getoption("--run-live-api")

    skip_no_key = pytest.mark.skip(
        reason="ANTHROPIC_API_KEY not set (see .env.example)"
    )
    skip_no_live = pytest.mark.skip(
        reason="live_api tests skip unless --run-live-api is passed (costs money)"
    )

    for item in items:
        if "requires_api_key" in item.keywords and not has_key:
            item.add_marker(skip_no_key)
        if "live_api" in item.keywords and not run_live:
            item.add_marker(skip_no_live)
