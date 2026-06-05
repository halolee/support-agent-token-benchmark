"""Shared chunk-and-embed-and-persist pipeline for ChromaDB-backed RAG.

Used by Naive RAG and Cached RAG (and future caching variants) so the
chunk/embed/persist step is a single code path. Each architecture
wraps this with its own destination directory + collection name; the
chunking and embedding contract is intentionally shared.

Keeping this separate from per-architecture setup scripts means a
caching variant doesn't need to copy ~50 lines of embedding boilerplate
to get its own ChromaDB — it imports `build_vector_store` and passes
its own paths.

The corpus and policy-classes paths default to the repo's canonical
locations; callers can override for fixtures or alternate corpora.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from architectures._shared.chunker import Chunk, chunk_corpus


# Repo-shared inputs: the corpus and per-section class metadata describe
# the customer-facing FAQ, not architecture-specific storage. Resolved
# relative to this file so resolution doesn't depend on caller CWD.
_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CORPUS_PATH = _REPO_ROOT / "corpus" / "swiss_faq.md"
DEFAULT_POLICY_CLASSES_PATH = _REPO_ROOT / "measurement" / "policy_classes.json"


def _load_embedding_model(name: str):
    """Lazily import sentence_transformers so importers that don't need
    embeddings (e.g., chunker unit tests) don't pay the heavy-deps cost.
    """
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(name)


def _embed_chunks(
    chunks: list[Chunk],
    *,
    embedding_model_name: str,
) -> list[list[float]]:
    model = _load_embedding_model(embedding_model_name)
    embeddings = model.encode(
        [chunk.text for chunk in chunks],
        normalize_embeddings=True,
        show_progress_bar=True,
    )
    return embeddings.tolist()


def build_vector_store(
    *,
    vector_store_dir: Path,
    collection_name: str,
    embedding_model_name: str,
    corpus_path: Path = DEFAULT_CORPUS_PATH,
    policy_classes_path: Path = DEFAULT_POLICY_CLASSES_PATH,
    rebuild: bool = True,
) -> int:
    """Chunk corpus, embed, persist to a ChromaDB collection. Returns chunk count.

    `rebuild=True` drops any existing `vector_store_dir` and rebuilds
    from scratch. Embeddings are L2-normalised so cosine similarity is
    equivalent to inner product; the collection is created with
    `hnsw:space=cosine` to make the contract explicit.
    """
    import chromadb

    chunks = chunk_corpus(
        corpus_path=corpus_path,
        policy_classes_path=policy_classes_path,
    )
    print(
        f"Chunked corpus: {len(chunks)} chunks across "
        f"{len({c.section_id for c in chunks})} sections"
    )

    if rebuild and vector_store_dir.exists():
        shutil.rmtree(vector_store_dir)
    vector_store_dir.mkdir(parents=True, exist_ok=True)

    embeddings = _embed_chunks(chunks, embedding_model_name=embedding_model_name)
    print(f"Embedded {len(embeddings)} chunks via {embedding_model_name}")

    client = chromadb.PersistentClient(path=str(vector_store_dir))
    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )

    collection.add(
        ids=[chunk.chunk_id for chunk in chunks],
        embeddings=embeddings,
        documents=[chunk.text for chunk in chunks],
        metadatas=[chunk.to_metadata() for chunk in chunks],
    )
    print(f"Persisted {collection.count()} records to {vector_store_dir}")
    return len(chunks)
