from __future__ import annotations

import argparse
import math
import os
from pathlib import Path

from dotenv import load_dotenv

import lancedb

from codebase_search.cache import load_cached, save_cached
from codebase_search.chunking import CodeChunk, chunk_file, iter_source_files
from codebase_search.db_paths import derive_db_paths
from codebase_search.embed import DEFAULT_MODEL, embed_texts
from codebase_search.extractor import extract_file
from codebase_search.graph.factory import create_graph_store


TABLE_NAME = "chunks"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Index a repo into a local LanceDB vector store.")
    _env_repo = os.environ.get("CODEBASE_REPO")
    parser.add_argument("--repo", default=_env_repo, required=_env_repo is None,
                        help="Path to the codebase to index. Env: CODEBASE_REPO")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama embedding model. Default: {DEFAULT_MODEL}")
    parser.add_argument("--batch-size", type=int, default=16, help="Embedding batch size. Default: 16")
    return parser


def run_index(repo: Path, model: str = DEFAULT_MODEL, batch_size: int = 16) -> dict:
    """Index a repo into vector + graph DBs. Returns a summary dict."""
    if not repo.exists() or not repo.is_dir():
        raise ValueError(f"Repo path does not exist or is not a directory: {repo}")

    db_path, graph_db_path = derive_db_paths(repo)
    cache_dir = db_path / "cache"
    db_path.mkdir(parents=True, exist_ok=True)
    graph_db_path.mkdir(parents=True, exist_ok=True)

    graph_store = create_graph_store("kuzu", str(graph_db_path))
    graph_store.clear()

    _log(f"Scanning source files in {repo}")
    source_files = list(iter_source_files(repo))
    _log(f"Found {len(source_files)} supported source files.")

    all_records: list[dict] = []
    pending_files: list[tuple[Path, list[CodeChunk]]] = []

    for source_file in source_files:
        cached = load_cached(source_file, repo, cache_dir)
        if cached is not None:
            all_records.extend(cached)
        else:
            file_chunks = chunk_file(source_file, repo)
            if file_chunks:
                pending_files.append((source_file, file_chunks))

        result = extract_file(source_file, repo)
        graph_store.insert_nodes(result["nodes"])
        graph_store.insert_edges(result["edges"])

    cached_count = len(source_files) - len(pending_files)
    if cached_count:
        _log(f"Loaded {cached_count} files from cache.")

    if pending_files:
        pending_chunks = [chunk for _, chunks in pending_files for chunk in chunks]
        total_batches = math.ceil(len(pending_chunks) / batch_size)
        _log(f"Embedding {len(pending_chunks)} chunks from {len(pending_files)} changed files "
             f"with model '{model}' in {total_batches} batches.")

        vectors = iter(_embed_all(pending_chunks, batch_size, model, total_batches))
        for source_file, file_chunks in pending_files:
            file_records = [chunk.to_record(next(vectors)) for chunk in file_chunks]
            save_cached(source_file, file_records, repo, cache_dir)
            all_records.extend(file_records)

    graph_store.close()

    if not all_records:
        raise ValueError("No supported source files found.")

    _log(f"Writing {len(all_records)} records to {db_path}/{TABLE_NAME}.")
    db = lancedb.connect(db_path)
    if TABLE_NAME in db.table_names():
        _log(f"Dropping existing table '{TABLE_NAME}'.")
        db.drop_table(TABLE_NAME)
    db.create_table(TABLE_NAME, data=all_records)

    return {
        "repo": str(repo),
        "chunks": len(all_records),
        "files_indexed": len(pending_files),
        "files_cached": cached_count,
        "vector_db": str(db_path),
        "graph_db": str(graph_db_path),
    }


def main() -> None:
    load_dotenv()
    args = build_parser().parse_args()
    repo = Path(args.repo).expanduser().resolve()
    try:
        result = run_index(repo, model=args.model, batch_size=args.batch_size)
    except ValueError as e:
        raise SystemExit(str(e))
    print(f"Indexed {result['chunks']} chunks from {result['repo']}.")
    print(f"  vector -> {result['vector_db']}/{TABLE_NAME}")
    print(f"  graph  -> {result['graph_db']}")


def _embed_all(
    chunks: list[CodeChunk],
    batch_size: int,
    model: str,
    total_batches: int,
) -> list[list[float]]:
    all_vectors: list[list[float]] = []
    for batch_index, start in enumerate(range(0, len(chunks), batch_size), start=1):
        batch = chunks[start : start + batch_size]
        _log(f"Embedding batch {batch_index}/{total_batches} ({len(batch)} chunks)...")
        all_vectors.extend(embed_texts([_embedding_text(c) for c in batch], model=model))
    return all_vectors


def _embedding_text(chunk: CodeChunk) -> str:
    if chunk.symbol:
        prefix = f"{chunk.entity_type} " if chunk.entity_type else ""
        return f"{prefix}{chunk.symbol} in {chunk.file_path}\n{chunk.code}"
    return chunk.code


def _log(message: str) -> None:
    print(f"[index] {message}", flush=True)


if __name__ == "__main__":
    main()
