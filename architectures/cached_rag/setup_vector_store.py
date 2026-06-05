"""One-time script: chunk `corpus/swiss_faq.md` and build Cached RAG's vector store.

Thin wrapper around `architectures._shared.vector_store_builder`. Cached
RAG uses an independent vector store from Naive RAG (rather than
sharing) to keep Option A's clean architectural separation; the
chunking + embedding logic is intentionally shared via the builder, so
the resulting indexes are byte-equivalent given identical
sentence-transformers / BGE-M3 versions. See `cached_rag/README.md` for
the parity rationale.

Run once before the Cached RAG agent can query:

    python -m architectures.cached_rag.setup_vector_store

Idempotent — re-running rebuilds from scratch (the persistent ChromaDB
directory under `architectures/cached_rag/vector_store/` is dropped and
recreated). The vector store directory is gitignored; each clone rebuilds.

Embedding model: `BAAI/bge-m3` self-hosted, normalised to unit length so
cosine similarity is equivalent to inner product. Downloading the model
on first run takes a few minutes (~2.3GB); BUILD_PLAN Step 1 prefetches
it to avoid the first-run latency during measurement.
"""
from __future__ import annotations

import sys
from pathlib import Path


# Allow `python architectures/cached_rag/setup_vector_store.py` as well as
# `python -m architectures.cached_rag.setup_vector_store`.
if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from architectures._shared.vector_store_builder import build_vector_store


# Per-architecture paths and identifiers. Kept at module level because
# `architectures/cached_rag/tools.py` imports them directly to locate
# the persisted collection — see tools.py.
VECTOR_STORE_DIR = Path(__file__).resolve().parent / "vector_store"
COLLECTION_NAME = "swiss_faq"
EMBEDDING_MODEL_NAME = "BAAI/bge-m3"


def main() -> int:
    build_vector_store(
        vector_store_dir=VECTOR_STORE_DIR,
        collection_name=COLLECTION_NAME,
        embedding_model_name=EMBEDDING_MODEL_NAME,
        rebuild=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
