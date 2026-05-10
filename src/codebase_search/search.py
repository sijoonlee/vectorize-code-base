from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from typing import Any

import lancedb

from codebase_search.db_paths import derive_db_paths
from codebase_search.embed import DEFAULT_MODEL, embed_text
from codebase_search.file_changes import process_pending_file_changes
from codebase_search.graph.base import GraphStore
from codebase_search.graph.factory import create_graph_store
from codebase_search.index import TABLE_NAME


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Search an indexed codebase.")
    parser.add_argument("--repo", default=os.environ.get("CODEBASE_REPO", str(Path.cwd())),
                        help="Path to the repo root. Defaults to CWD. Env: CODEBASE_REPO")
    parser.add_argument("--query", required=True, help="Natural language search query.")
    parser.add_argument("--limit", type=int, default=5, help="Number of results to return. Default: 5")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama embedding model. Default: {DEFAULT_MODEL}")
    parser.add_argument("--scope", default=None,
                        help="Restrict results to files under this directory prefix "
                             "(e.g. src/auth).")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    return parser


def main() -> None:
    load_dotenv()
    args = build_parser().parse_args()
    repo = Path(args.repo).expanduser().resolve()
    process_pending_file_changes(repo, model=args.model)
    db_path, graph_db_path = derive_db_paths(repo)

    db = lancedb.connect(db_path)
    if TABLE_NAME not in db.table_names():
        raise SystemExit(f"Table '{TABLE_NAME}' not found in {db_path}. Run codebase-index first.")

    graph_store: GraphStore | None = None
    if graph_db_path.exists():
        graph_store = create_graph_store("kuzu", str(graph_db_path))

    table = db.open_table(TABLE_NAME)
    query_vector = embed_text(args.query, model=args.model)
    lance_query = table.search(query_vector)
    if args.scope:
        scope_prefix = args.scope.rstrip("/").replace("'", "''") + "/"
        lance_query = lance_query.where(f"file_path LIKE '{scope_prefix}%'")
    results = lance_query.limit(args.limit).to_list()

    normalized = [_normalize_result(result, graph_store) for result in results]

    if graph_store is not None:
        graph_store.close()

    if args.json:
        print(json.dumps(normalized, indent=2))
    else:
        _print_results(normalized, scope=args.scope)


def _normalize_result(result: dict[str, Any], graph_store: GraphStore | None) -> dict[str, Any]:
    normalized: dict[str, Any] = {
        "id": result["id"],
        "file_path": result["file_path"],
        "language": result["language"],
        "symbol": result.get("symbol") or "",
        "entity_type": result.get("entity_type") or "",
        "start_line": result["start_line"],
        "end_line": result["end_line"],
        "distance": result.get("_distance"),
        "code": result["code"],
        "graph_context": None,
    }
    if graph_store is not None and normalized["symbol"]:
        normalized["graph_context"] = _fetch_graph_context(
            graph_store, normalized["symbol"], normalized["file_path"]
        )
    return normalized


def _fetch_graph_context(graph_store: GraphStore, label: str, file_path: str) -> dict | None:
    entity = graph_store.query(
        "MATCH (n:Entity) WHERE n.label = $label AND n.file_path = $fp "
        "RETURN n.id AS id LIMIT 1",
        {"label": label, "fp": file_path},
    )
    if not entity:
        return None

    entity_id = entity[0]["id"]

    parents = _fetch_ancestors(graph_store, entity_id, depth=2)
    children = _fetch_descendants(graph_store, entity_id, depth=2)

    if not parents and not children:
        return None
    return {"file_path": file_path, "parents": parents, "children": children}


def _fetch_ancestors(graph_store: GraphStore, entity_id: str, depth: int) -> list[dict]:
    visited: set[str] = {entity_id}
    frontier = [entity_id]
    all_ancestors: list[dict] = []

    for _ in range(depth):
        next_frontier = []
        for nid in frontier:
            rows = graph_store.query(
                "MATCH (parent:Entity)-[r:RELATES]->(n:Entity) WHERE n.id = $id "
                "RETURN parent.id AS id, parent.label AS label, "
                "parent.entity_type AS entity_type, parent.source_location AS source_location, "
                "r.relation AS relation, r.confidence AS confidence, "
                "r.source AS edge_source, r.details AS details",
                {"id": nid},
            )
            for row in rows:
                if row["id"] not in visited:
                    visited.add(row["id"])
                    all_ancestors.append(row)
                    next_frontier.append(row["id"])
        frontier = next_frontier
        if not frontier:
            break

    return all_ancestors


def _fetch_descendants(graph_store: GraphStore, entity_id: str, depth: int) -> list[dict]:
    visited: set[str] = {entity_id}
    frontier = [entity_id]
    all_descendants: list[dict] = []

    for _ in range(depth):
        next_frontier = []
        for nid in frontier:
            rows = graph_store.query(
                "MATCH (n:Entity)-[r:RELATES]->(child:Entity) WHERE n.id = $id "
                "RETURN child.id AS id, child.label AS label, "
                "child.entity_type AS entity_type, child.source_location AS source_location, "
                "r.relation AS relation, r.confidence AS confidence, "
                "r.source AS edge_source, r.details AS details",
                {"id": nid},
            )
            for row in rows:
                if row["id"] not in visited:
                    visited.add(row["id"])
                    all_descendants.append(row)
                    next_frontier.append(row["id"])
        frontier = next_frontier
        if not frontier:
            break

    return sorted(all_descendants, key=lambda x: (x["entity_type"], x["label"]))


def _print_results(results: list[dict[str, Any]], scope: str | None = None) -> None:
    if scope:
        print(f"scope: {scope.rstrip('/')}/")
    for index, result in enumerate(results, start=1):
        symbol = f" {result['symbol']}" if result["symbol"] else ""
        distance = result["distance"]
        score_text = f" distance={distance:.4f}" if isinstance(distance, int | float) else ""
        print(
            f"{index}. {result['file_path']}:{result['start_line']}-{result['end_line']}"
            f"{symbol}{score_text}"
        )
        ctx = result.get("graph_context")
        if ctx:
            if ctx["parents"]:
                parents_str = ", ".join(_format_relation_entity(p) for p in ctx["parents"])
                print(f"   [incoming: {parents_str}  {ctx['file_path']}]")
            if ctx["children"]:
                children_str = ", ".join(_format_relation_entity(c) for c in ctx["children"])
                print(f"   [outgoing: {children_str}]")
        print(_indent_code(result["code"]))
        print()


def _format_relation_entity(e: dict) -> str:
    relation = e.get("relation") or "relates"
    return f"{relation} {_format_entity(e)}"


def _format_entity(e: dict) -> str:
    if e["entity_type"] == "file":
        return e["entity_type"]
    return f"{e['entity_type']} {e['label']}"


def _indent_code(code: str) -> str:
    return "\n".join(f"    {line}" for line in code.splitlines())


if __name__ == "__main__":
    main()
