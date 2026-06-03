"""One-time script: chunk corpus, build BGE-M3 vector store + BM25 index.

Run once before the Hybrid RAG agent can query:

    python -m architectures.hybrid_rag.setup_indices

Idempotent — re-running rebuilds both indices from scratch. Both persist
under `architectures/hybrid_rag/vector_store/` (gitignored). Each clone
rebuilds.

Vector store mirrors Naive RAG's: BGE-M3 embeddings normalised to unit
length, cosine space in ChromaDB. The BM25 index is a sidecar pickle
(`bm25_index.pkl`) holding the tokenised corpus + chunk_ids + chunk
texts + section metadata; the `BM25Okapi` instance itself is rebuilt at
load time (cheap; the index build dominates).

The two indices MUST share chunk boundaries — otherwise the
vector-vs-BM25 comparison inside RRF would be confounded by chunking
differences. Both use `_shared/chunker.py::chunk_corpus` against the
same corpus + policy_classes.json.
"""
from __future__ import annotations

import pickle
import re
import shutil
import sys
from pathlib import Path


# Allow `python architectures/hybrid_rag/setup_indices.py` as well as
# `python -m architectures.hybrid_rag.setup_indices`.
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
BM25_INDEX_PATH = VECTOR_STORE_DIR / "bm25_index.pkl"
COLLECTION_NAME = "swiss_faq"
EMBEDDING_MODEL_NAME = "BAAI/bge-m3"
RERANKER_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"


# ---------------------------------------------------------------------------
# BM25 tokenisation
# ---------------------------------------------------------------------------

# Word-boundary split + lowercase. Standard for BM25 over English text —
# rank_bm25 is bag-of-words, so anything stronger (stemming, stopword
# removal) is a tuning knob, not a correctness requirement. Keeping it
# simple makes the retrieval behaviour reproducible across machines.
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def tokenize_for_bm25(text: str) -> list[str]:
    """Lowercase + word-boundary split. Exported so tools.py uses the
    SAME tokeniser at query time as setup_indices used at build time —
    drift here would silently degrade BM25 recall.
    """
    return [m.group(0).lower() for m in _TOKEN_RE.finditer(text)]


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
# Build
# ---------------------------------------------------------------------------


def build_indices(*, rebuild: bool = True) -> int:
    """Chunk corpus, embed → ChromaDB, tokenise → BM25 pickle. Returns
    chunk count. `rebuild=True` (default) drops any existing vector_store/
    and rebuilds.
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

    # --- Vector index ---
    embeddings = _embed_chunks(chunks)
    print(f"Embedded {len(embeddings)} chunks via {EMBEDDING_MODEL_NAME}")

    client = chromadb.PersistentClient(path=str(VECTOR_STORE_DIR))
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
    print(f"Persisted {collection.count()} vector records to {VECTOR_STORE_DIR}")

    # --- BM25 sidecar ---
    # Pickle the tokenised corpus + chunk metadata, NOT a BM25Okapi
    # instance — rebuilding BM25Okapi at load time is fast (microseconds)
    # and avoids tying the on-disk format to rank_bm25 internals.
    tokenised = [tokenize_for_bm25(chunk.text) for chunk in chunks]
    payload = {
        "version": 1,
        "tokenised_corpus": tokenised,
        "chunk_ids": [chunk.chunk_id for chunk in chunks],
        "chunk_texts": [chunk.text for chunk in chunks],
        "section_ids": [chunk.section_id for chunk in chunks],
        "section_titles": [chunk.section_title for chunk in chunks],
    }
    with open(BM25_INDEX_PATH, "wb") as f:
        pickle.dump(payload, f)
    print(f"Persisted BM25 index ({len(chunks)} chunks) to {BM25_INDEX_PATH}")

    return len(chunks)


def main() -> int:
    build_indices(rebuild=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
