"""One-time script: chunk `corpus/swiss_faq.md` and build Naive RAG's vector store.

Thin wrapper around `architectures._shared.vector_store_builder`. The
chunk/embed/persist pipeline is shared with other RAG architectures;
this module only pins Naive RAG's destination directory + collection
name + embedding model.

Run once before the Naive RAG agent can query:

    python -m architectures.naive_rag.setup_vector_store

Idempotent — re-running rebuilds from scratch (the persistent ChromaDB
directory under `architectures/naive_rag/vector_store/` is dropped and
recreated). The vector store directory is gitignored; each clone rebuilds.

Embedding model: `BAAI/bge-m3` self-hosted, normalised to unit length so
cosine similarity is equivalent to inner product. Downloading the model
on first run takes a few minutes (~2.3GB); BUILD_PLAN Step 1 prefetches
it to avoid the first-run latency during measurement.
"""
from __future__ import annotations

import sys
from pathlib import Path


# Allow `python architectures/naive_rag/setup_vector_store.py` as well as
# `python -m architectures.naive_rag.setup_vector_store`.
if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from architectures._shared.vector_store_builder import build_vector_store


# Per-architecture paths and identifiers. Kept at module level because
# `architectures/naive_rag/tools.py` and tests import them directly to
# locate the persisted collection — see test_naive_rag.py and tools.py.
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
