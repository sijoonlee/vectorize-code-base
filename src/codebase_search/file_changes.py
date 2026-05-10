from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

import lancedb

from codebase_search.chunking import chunk_file
from codebase_search.db_paths import derive_db_paths
from codebase_search.embed import DEFAULT_MODEL, embed_texts
from codebase_search.extractor import extract_file
from codebase_search.graph.factory import create_graph_store
from codebase_search.index import TABLE_NAME, _embedding_text


VALID_EVENTS = {"created", "updated", "removed"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Report a source file creation, update, or removal.")
    _env_repo = os.environ.get("CODEBASE_REPO")
    parser.add_argument("--repo", default=_env_repo, required=_env_repo is None,
                        help="Path to the repo root. Env: CODEBASE_REPO")
    parser.add_argument("--event", required=True, choices=sorted(VALID_EVENTS),
                        help="File change event to report.")
    parser.add_argument("file", help="Path to the changed file, absolute or relative to repo root.")
    return parser


def report_file_change(repo: Path, file_path: str | Path, event: str) -> dict:
    if event not in VALID_EVENTS:
        raise ValueError(f"Unknown file change event: {event!r}")
    repo = repo.expanduser().resolve()
    if not repo.exists() or not repo.is_dir():
        raise ValueError(f"Repo path does not exist or is not a directory: {repo}")

    rel_path = _repo_relative_path(repo, file_path)
    db_path, graph_db_path = derive_db_paths(repo)
    state_path = _state_path(db_path)

    cleanup = {"vector_deleted": False, "graph_deleted": False}
    if event == "removed":
        cleanup = _delete_index_records(db_path, graph_db_path, rel_path)

    status = "removed" if event == "removed" else "stale"
    record = {
        "event": event,
        "status": status,
        "reported_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    state = _load_state(state_path)
    state[rel_path] = record
    _save_state(state_path, state)

    return {
        "repo": str(repo),
        "file_path": rel_path,
        "state_path": str(state_path),
        **record,
        **cleanup,
    }


def process_pending_file_changes(repo: Path, model: str = DEFAULT_MODEL) -> dict:
    """Apply pending file changes for the repo's current branch before a query."""
    repo = repo.expanduser().resolve()
    db_path, graph_db_path = derive_db_paths(repo)
    state_path = _state_path(db_path)
    state = _load_state(state_path)
    if not state:
        return {"processed": [], "remaining": [], "state_path": str(state_path)}

    processed: list[dict] = []
    remaining = dict(state)

    for rel_path, record in state.items():
        event = record.get("event")
        try:
            if event == "removed":
                cleanup = _delete_index_records(db_path, graph_db_path, rel_path)
                processed.append({"file_path": rel_path, "event": event, **cleanup})
            elif event in {"created", "updated"}:
                result = _refresh_file(repo, db_path, graph_db_path, rel_path, model)
                processed.append({"file_path": rel_path, "event": event, **result})
            else:
                continue
        except Exception:
            continue
        remaining.pop(rel_path, None)

    if remaining:
        _save_state(state_path, remaining)
    else:
        _delete_state(state_path)

    return {
        "processed": processed,
        "remaining": sorted(remaining),
        "state_path": str(state_path),
    }


def _repo_relative_path(repo: Path, file_path: str | Path) -> str:
    path = Path(file_path).expanduser()
    absolute = path.resolve() if path.is_absolute() else (repo / path).resolve()
    try:
        return absolute.relative_to(repo).as_posix()
    except ValueError:
        raise ValueError(f"File {absolute} is not inside repo {repo}")


def _state_path(db_path: Path) -> Path:
    return db_path.parent / "state" / "file_changes.json"


def _load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _delete_state(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _delete_index_records(db_path: Path, graph_db_path: Path, rel_path: str) -> dict:
    cleanup = {"vector_deleted": False, "graph_deleted": False}

    if db_path.exists():
        db = lancedb.connect(db_path)
        if TABLE_NAME in db.table_names():
            escaped = rel_path.replace("'", "''")
            db.open_table(TABLE_NAME).delete(f"file_path = '{escaped}'")
            cleanup["vector_deleted"] = True

    if graph_db_path.exists():
        graph_store = create_graph_store("kuzu", str(graph_db_path))
        graph_store.delete_file(rel_path)
        graph_store.close()
        cleanup["graph_deleted"] = True

    return cleanup


def _refresh_file(repo: Path, db_path: Path, graph_db_path: Path, rel_path: str, model: str) -> dict:
    source_file = repo / rel_path
    if not source_file.is_file():
        cleanup = _delete_index_records(db_path, graph_db_path, rel_path)
        return {"status": "missing_removed", **cleanup}

    _delete_index_records(db_path, graph_db_path, rel_path)

    chunks = chunk_file(source_file, repo)
    records: list[dict] = []
    if chunks:
        db_path.mkdir(parents=True, exist_ok=True)
        vectors = embed_texts([_embedding_text(chunk) for chunk in chunks], model=model)
        records = [chunk.to_record(vector) for chunk, vector in zip(chunks, vectors)]
        db = lancedb.connect(db_path)
        if TABLE_NAME in db.table_names():
            db.open_table(TABLE_NAME).add(records)
        else:
            db.create_table(TABLE_NAME, data=records)

    graph_db_path.parent.mkdir(parents=True, exist_ok=True)
    graph_store = create_graph_store("kuzu", str(graph_db_path))
    try:
        result = extract_file(source_file, repo)
        graph_store.insert_nodes(result["nodes"])
        graph_store.insert_edges(result["edges"])
    finally:
        graph_store.close()

    return {"status": "refreshed", "chunks": len(records)}


def main() -> None:
    load_dotenv()
    args = build_parser().parse_args()
    try:
        result = report_file_change(Path(args.repo), args.file, args.event)
    except ValueError as e:
        raise SystemExit(str(e))

    print(
        f"Recorded {result['event']} for {result['file_path']} "
        f"as {result['status']} in {result['state_path']}."
    )


if __name__ == "__main__":
    main()
