"""Environment smoke tests for Phase 1 Step 1.

These tests are the SPEC of a correctly-configured development environment.
They are written before `pip install` succeeds — the red→green transition
is the completion signal for Step 1.

What's verified:
- All declared dependencies are importable
- Anthropic SDK is instantiable (no network call)
- BGE-M3 self-hosted embedding model loads and produces correct dimensions
- Phase 1 Step 0 artifacts are present (corpus + DB)
- SQLite DB has the expected schema

If any test fails, Phase 1 Step 1 is not complete.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent


# ---------- Dependency imports ----------


def test_anthropic_importable():
    import anthropic  # noqa: F401


def test_chromadb_importable():
    import chromadb  # noqa: F401


def test_sentence_transformers_importable():
    import sentence_transformers  # noqa: F401


def test_rank_bm25_importable():
    from rank_bm25 import BM25Okapi  # noqa: F401


def test_dotenv_importable():
    from dotenv import load_dotenv  # noqa: F401


def test_tabulate_importable():
    from tabulate import tabulate  # noqa: F401


# ---------- Anthropic client (no network call) ----------


def test_anthropic_client_instantiable():
    """The client constructor should not require a real key."""
    import anthropic

    client = anthropic.Anthropic(api_key="sk-ant-dummy-for-test")
    assert client is not None


# ---------- Phase 1 Step 0 artifacts ----------


def test_corpus_present():
    """`corpus/swiss_faq.md` must exist (download via Phase 1 Step 0)."""
    corpus = PROJECT_ROOT / "corpus" / "swiss_faq.md"
    assert corpus.exists(), "Corpus missing — see BUILD_PLAN Step 0"
    assert corpus.stat().st_size > 1000, "Corpus suspiciously small"


def test_corpus_sha256_matches_inventory():
    """Hash must match what the inventory notebook records."""
    import hashlib

    corpus = PROJECT_ROOT / "corpus" / "swiss_faq.md"
    actual = hashlib.sha256(corpus.read_bytes()).hexdigest()
    expected = "864c718edfcf80ef46575a16180210ecb41c354a891bf397a0b29dcb96f585f1"
    assert actual == expected, (
        f"Corpus hash drift: got {actual}, expected {expected}. "
        f"The bucket content may have changed; re-run Step 0 inventory."
    )


def test_database_present():
    db = PROJECT_ROOT / "data" / "travel.sqlite"
    assert db.exists(), "Database missing — see BUILD_PLAN Step 0"
    assert db.stat().st_size > 1_000_000, "Database suspiciously small"


def test_database_has_expected_tables():
    """All 11 expected tables (8 aviation + 3 travel-extension) must exist."""
    db = PROJECT_ROOT / "data" / "travel.sqlite"
    conn = sqlite3.connect(str(db))
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    finally:
        conn.close()
    expected = {
        "aircrafts_data",
        "airports_data",
        "boarding_passes",
        "bookings",
        "flights",
        "seats",
        "ticket_flights",
        "tickets",
        "car_rentals",
        "hotels",
        "trip_recommendations",
    }
    missing = expected - tables
    assert not missing, f"Missing tables: {missing}"


# ---------- BGE-M3 (the heavy one) ----------


@pytest.mark.slow
def test_bge_m3_loads_and_embeds():
    """BGE-M3 model must be cached locally and produce 1024-dim embeddings.

    Marked `slow` so it can be skipped via `pytest -m 'not slow'` during
    rapid iteration. The full Phase 1 Step 1 verification requires this
    test to pass.
    """
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer("BAAI/bge-m3")
    vec = model.encode("How do I rebook my flight?")
    assert vec.shape == (1024,), f"Unexpected embedding shape: {vec.shape}"
    # Sanity: embedding should not be all zeros or all NaN
    assert vec.any(), "Embedding is all zeros"
    assert not (vec != vec).any(), "Embedding contains NaN"
