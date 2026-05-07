from __future__ import annotations

import argparse
import math
from pathlib import Path

import lancedb

from codebase_search.chunking import chunk_file, iter_source_files
from codebase_search.embed import DEFAULT_MODEL, embed_texts


TABLE_NAME = "chunks"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Index a repo into a local LanceDB vector store.")
    parser.add_argument("--repo", required=True, help="Path to the codebase to index.")
    parser.add_argument("--db", required=True, help="Path to the LanceDB directory.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama embedding model. Default: {DEFAULT_MODEL}")
    parser.add_argument("--batch-size", type=int, default=16, help="Embedding batch size. Default: 16")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    repo = Path(args.repo).expanduser().resolve()
    db_path = Path(args.db).expanduser()

    if not repo.exists() or not repo.is_dir():
        raise SystemExit(f"Repo path does not exist or is not a directory: {repo}")

    _log(f"Scanning source files in {repo}")
    chunks = []
    source_files = list(iter_source_files(repo))
    _log(f"Found {len(source_files)} supported source files.")

    for index, source_file in enumerate(source_files, start=1):
        file_chunks = chunk_file(source_file, repo)
        chunks.extend(file_chunks)
        _log(
            f"Chunked {index}/{len(source_files)} files: "
            f"{source_file.relative_to(repo).as_posix()} ({len(file_chunks)} chunks)"
        )

    if not chunks:
        raise SystemExit("No supported source files found.")

    total_batches = math.ceil(len(chunks) / args.batch_size)
    _log(f"Embedding {len(chunks)} chunks with model '{args.model}' in {total_batches} batches.")

    records = []
    for batch_index, start in enumerate(range(0, len(chunks), args.batch_size), start=1):
        batch = chunks[start : start + args.batch_size]
        _log(f"Embedding batch {batch_index}/{total_batches} ({len(batch)} chunks)...")
        vectors = embed_texts([chunk.code for chunk in batch], model=args.model)
        records.extend(chunk.to_record(vector) for chunk, vector in zip(batch, vectors, strict=True))
        _log(f"Embedded {min(start + len(batch), len(chunks))}/{len(chunks)} chunks.")

    _log(f"Writing {len(records)} records to {db_path}/{TABLE_NAME}.")
    db = lancedb.connect(db_path)
    if TABLE_NAME in db.table_names():
        _log(f"Dropping existing table '{TABLE_NAME}'.")
        db.drop_table(TABLE_NAME)
    db.create_table(TABLE_NAME, data=records)

    print(f"Indexed {len(records)} chunks from {repo} into {db_path}/{TABLE_NAME}.")


def _log(message: str) -> None:
    print(f"[index] {message}", flush=True)


if __name__ == "__main__":
    main()
