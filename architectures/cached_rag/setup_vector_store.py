"""One-time script: chunk `corpus/swiss_faq.md` and build the vector store.

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

import shutil
import sys
from pathlib import Path


# Allow `python architectures/naive_rag/setup_vector_store.py` as well as
# `python -m architectures.naive_rag.setup_vector_store`.
if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from architectures._shared.chunker import Chunk, chunk_corpus


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_PATH = _REPO_ROOT / "corpus" / "swiss_faq.md"
POLICY_CLASSES_PATH = _REPO_ROOT / "measurement" / "policy_classes.json"
VECTOR_STORE_DIR = Path(__file__).resolve().parent / "vector_store"
COLLECTION_NAME = "swiss_faq"
EMBEDDING_MODEL_NAME = "BAAI/bge-m3"


# ---------------------------------------------------------------------------
# Embedding model
# ---------------------------------------------------------------------------


def _load_embedding_model():
    """Lazily import sentence_transformers so the chunker stays importable
    in environments without the heavy ML deps installed (e.g., chunker
    unit tests).
    """
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(EMBEDDING_MODEL_NAME)


def _embed_chunks(chunks: list[Chunk]):
    model = _load_embedding_model()
    texts = [chunk.text for chunk in chunks]
    embeddings = model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=True,
    )
    return embeddings.tolist()


# ---------------------------------------------------------------------------
# Vector store build
# ---------------------------------------------------------------------------


def build_vector_store(*, rebuild: bool = True) -> int:
    """Chunk corpus, embed, and persist to ChromaDB. Returns chunk count.

    `rebuild=True` (default) drops any existing vector_store/ and rebuilds.
    """
    import chromadb

    chunks = chunk_corpus(
        corpus_path=CORPUS_PATH,
        policy_classes_path=POLICY_CLASSES_PATH,
    )
    print(f"Chunked corpus: {len(chunks)} chunks across "
          f"{len({c.section_id for c in chunks})} sections")

    if rebuild and VECTOR_STORE_DIR.exists():
        shutil.rmtree(VECTOR_STORE_DIR)
    VECTOR_STORE_DIR.mkdir(parents=True, exist_ok=True)

    embeddings = _embed_chunks(chunks)
    print(f"Embedded {len(embeddings)} chunks via {EMBEDDING_MODEL_NAME}")

    client = chromadb.PersistentClient(path=str(VECTOR_STORE_DIR))
    # Cosine space; embeddings are already L2-normalised, so cosine ≡
    # inner product, but specifying it explicitly documents the contract.
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )

    collection.add(
        ids=[chunk.chunk_id for chunk in chunks],
        embeddings=embeddings,
        documents=[chunk.text for chunk in chunks],
        metadatas=[chunk.to_metadata() for chunk in chunks],
    )
    print(f"Persisted {collection.count()} records to {VECTOR_STORE_DIR}")
    return len(chunks)


def main() -> int:
    build_vector_store(rebuild=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
