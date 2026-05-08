from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

import lancedb

from codebase_search.db_paths import derive_db_paths
from codebase_search.graph.factory import create_graph_store
from codebase_search.index import TABLE_NAME


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Remove a deleted file's chunks from the vector store.")
    _env_repo = os.environ.get("CODEBASE_REPO")
    parser.add_argument("--repo", default=_env_repo, required=_env_repo is None,
                        help="Path to the repo root. Env: CODEBASE_REPO")
    parser.add_argument("file", help="Path to the removed file (absolute or relative to cwd).")
    return parser


def main() -> None:
    load_dotenv()
    args = build_parser().parse_args()
    repo = Path(args.repo).expanduser().resolve()
    db_path, graph_db_path = derive_db_paths(repo)
    removed = Path(args.file).expanduser().resolve()

    try:
        rel_path = removed.relative_to(repo).as_posix()
    except ValueError:
        raise SystemExit(f"File {removed} is not inside repo {repo}")

    db = lancedb.connect(db_path)
    if TABLE_NAME not in db.table_names():
        raise SystemExit(f"No table '{TABLE_NAME}' found in {db_path}. Has the repo been indexed?")

    db.open_table(TABLE_NAME).delete(f"file_path = '{rel_path}'")
    print(f"Removed vector chunks for '{rel_path}' from {db_path}/{TABLE_NAME}.")

    if graph_db_path.exists():
        graph_store = create_graph_store("kuzu", str(graph_db_path))
        graph_store.delete_file(rel_path)
        graph_store.close()
        print(f"Removed graph nodes for '{rel_path}' from {graph_db_path}.")


if __name__ == "__main__":
    main()
