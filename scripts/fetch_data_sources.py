#!/usr/bin/env python3
"""Fetch and verify the LangGraph reference data sources.

Tries the GitHub release mirror (durable for this repo's lifetime) first, then
falls back to the upstream langchain-ai GCS bucket. Verifies SHA-256 against
pinned constants before writing; refuses to keep mismatched bytes.

Run idempotently:
    python scripts/fetch_data_sources.py            # skip files whose hash already matches
    python scripts/fetch_data_sources.py --force    # re-download even if hashes match

Background: see issue #19. The pinned hashes below are the bytes the experiment
was calibrated against; changing them invalidates the frozen task fixtures,
rubrics, and any published numbers.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MIRROR_TAG = "data-mirror-v1"
MIRROR_BASE = f"https://github.com/halolee/support-agent-token-benchmark/releases/download/{MIRROR_TAG}"
UPSTREAM_BASE = "https://storage.googleapis.com/benchmarks-artifacts/travel-db"


@dataclass(frozen=True)
class Source:
    rel_path: str
    sha256: str
    size: int
    mirror_name: str    # asset filename in the GitHub release
    upstream_name: str  # filename in the langchain-ai GCS bucket

    @property
    def dest(self) -> Path:
        return PROJECT_ROOT / self.rel_path

    @property
    def mirror_url(self) -> str:
        return f"{MIRROR_BASE}/{self.mirror_name}"

    @property
    def upstream_url(self) -> str:
        return f"{UPSTREAM_BASE}/{self.upstream_name}"


SOURCES = [
    Source(
        rel_path="corpus/swiss_faq.md",
        sha256="864c718edfcf80ef46575a16180210ecb41c354a891bf397a0b29dcb96f585f1",
        size=35_061,
        mirror_name="swiss_faq.md",
        upstream_name="swiss_faq.md",
    ),
    Source(
        rel_path="data/travel.sqlite",
        sha256="7646259e80230dc9bd92914466e13874bba82f461473d6a66552e819898eb66b",
        size=114_442_240,
        mirror_name="travel.sqlite",
        upstream_name="travel2.sqlite",  # upstream is travel2.sqlite; mirror normalises the name
    ),
]


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _atomic_download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=dest.parent, prefix=f".{dest.name}.", suffix=".part")
    tmp_path = Path(tmp_name)
    os.close(fd)
    try:
        # Default urllib UA gets 403'd by some hosts; identify ourselves.
        req = urllib.request.Request(
            url, headers={"User-Agent": "support-agent-token-benchmark-fetcher/1"}
        )
        with urllib.request.urlopen(req, timeout=60) as r, tmp_path.open("wb") as out:
            shutil.copyfileobj(r, out, length=1024 * 1024)
        tmp_path.replace(dest)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def fetch_one(src: Source, *, force: bool) -> bool:
    """Returns True on success, False on failure."""
    rel = src.rel_path
    if src.dest.exists() and not force:
        actual = sha256_of(src.dest)
        if actual == src.sha256:
            print(f"OK    {rel} — hash matches pinned value; skipping download.")
            return True
        print(
            f"WARN  {rel} — local hash {actual[:12]}… != pinned {src.sha256[:12]}…; "
            f"re-downloading."
        )

    for label, url in (("mirror", src.mirror_url), ("upstream GCS", src.upstream_url)):
        print(f"...   {rel} — fetching from {label} ({url})")
        try:
            _atomic_download(url, src.dest)
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            reason = getattr(e, "reason", e)
            print(f"FAIL  {rel} — {label} unreachable: {reason}")
            continue
        actual = sha256_of(src.dest)
        if actual != src.sha256:
            print(
                f"FAIL  {rel} — {label} returned hash {actual[:12]}… "
                f"(expected {src.sha256[:12]}…); refusing to keep."
            )
            src.dest.unlink(missing_ok=True)
            continue
        print(f"OK    {rel} — {label} verified ({src.size:,} bytes).")
        return True

    print(f"ERROR {rel} — both mirror and upstream failed. See issue #19.")
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch and verify reference data sources.")
    parser.add_argument(
        "--force", action="store_true",
        help="Re-download even if the local hash matches the pinned value.",
    )
    args = parser.parse_args(argv)
    results = [fetch_one(s, force=args.force) for s in SOURCES]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
