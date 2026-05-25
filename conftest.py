"""Pytest configuration shared across all tests.

Auto-skips `requires_api_key` tests when ANTHROPIC_API_KEY is missing,
so the test suite stays green in development sessions without a key.
The integration tests run automatically once a key is set in `.env`
or the environment.
"""
from __future__ import annotations

import os

import pytest

try:
    # Load .env if python-dotenv is available (it is, per requirements.txt).
    # This makes the requires_api_key gate work transparently when devs
    # have a key in .env, without needing to manually `source` it.
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


def pytest_collection_modifyitems(config, items):
    """Auto-skip API-dependent tests when no key is available."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return  # key present — run everything
    skip = pytest.mark.skip(reason="ANTHROPIC_API_KEY not set (see .env.example)")
    for item in items:
        if "requires_api_key" in item.keywords:
            item.add_marker(skip)
