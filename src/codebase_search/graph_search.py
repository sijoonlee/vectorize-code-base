from __future__ import annotations

import argparse
import json
import os

from dotenv import load_dotenv

from codebase_search.graph.base import GraphStore
from codebase_search.graph.factory import create_graph_store


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Traverse the code graph by entity name or file path.")
    _env_graph_db = os.environ.get("CODEBASE_GRAPH_DB")
    parser.add_argument("--graph-db", default=_env_graph_db, required=_env_graph_db is None,
                        help="Path to the graph DB directory. Env: CODEBASE_GRAPH_DB")
    parser.add_argument("--graph-backend", default=os.environ.get("CODEBASE_GRAPH_BACKEND", "kuzu"),
                        choices=["kuzu", "neo4j"], help="Graph backend. Env: CODEBASE_GRAPH_BACKEND. Default: kuzu")
    parser.add_argument("--query", default=None,
                        help="Entity name or partial label to search for (case-insensitive).")
    parser.add_argument("--depth", type=int, default=1,
                        help="Max traversal depth when using --query. Default: 1")
    parser.add_argument("--roots", action="store_true",
                        help="List all root nodes (no incoming edges), or root ancestor of --query.")
    parser.add_argument("--leaves", action="store_true",
                        help="List all leaf nodes (no outgoing edges), or leaf descendants of --query.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    return parser


def main() -> None:
    load_dotenv()
    args = build_parser().parse_args()

    if not args.query and not args.roots and not args.leaves:
        raise SystemExit("Provide --query, --roots, or --leaves.")

    graph_store = create_graph_store(args.graph_backend, args.graph_db)

    if args.roots and not args.query:
        rows = graph_store.query(
            "MATCH (n:Entity) WHERE NOT ()-[:RELATES]->(n) "
            "RETURN n.id AS id, n.label AS label, n.entity_type AS entity_type, "
            "n.file_path AS file_path, n.source_location AS source_location "
            "ORDER BY n.file_path",
        )
        graph_store.close()
        _print_or_json(rows, args.json, "No root nodes found.")
        return

    if args.leaves and not args.query:
        rows = graph_store.query(
            "MATCH (n:Entity) WHERE NOT (n)-[:RELATES]->() "
            "RETURN n.id AS id, n.label AS label, n.entity_type AS entity_type, "
            "n.file_path AS file_path, n.source_location AS source_location "
            "ORDER BY n.entity_type, n.label",
        )
        graph_store.close()
        _print_or_json(rows, args.json, "No leaf nodes found.")
        return

    # --query mode
    matches = graph_store.query(
        "MATCH (n:Entity) WHERE lower(n.label) CONTAINS lower($q) "
        "RETURN n.id AS id, n.label AS label, n.entity_type AS entity_type, "
        "n.file_path AS file_path, n.source_location AS source_location "
        "ORDER BY n.entity_type, n.label",
        {"q": args.query},
    )

    if not matches:
        print(f"No entities found matching '{args.query}'.")
        graph_store.close()
        return

    results = []
    for entity in matches:
        parent_rows = graph_store.query(
            "MATCH (parent:Entity)-[:RELATES]->(n:Entity) "
            "WHERE n.id = $id "
            "RETURN parent.label AS label, parent.entity_type AS entity_type, "
            "parent.source_location AS source_location LIMIT 1",
            {"id": entity["id"]},
        )
        descendants = _fetch_descendants(graph_store, entity["id"], args.depth)
        root_ancestor = _fetch_root_ancestor(graph_store, entity["id"]) if args.roots else None
        leaf_descendants = _fetch_leaf_descendants(graph_store, entity["id"], args.depth) if args.leaves else None

        results.append({
            "entity": entity,
            "parent": parent_rows[0] if parent_rows else None,
            "root_ancestor": root_ancestor,
            "leaf_descendants": leaf_descendants,
            "descendants": descendants,
        })

    graph_store.close()

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        _print_results(results, args.depth)


def _fetch_descendants(graph_store: GraphStore, entity_id: str, depth: int) -> list[dict]:
    """Iteratively collect descendants up to given depth."""
    visited: set[str] = {entity_id}
    frontier = [entity_id]
    all_descendants: list[dict] = []

    for _ in range(depth):
        next_frontier = []
        for nid in frontier:
            children = graph_store.query(
                "MATCH (n:Entity)-[:RELATES]->(child:Entity) "
                "WHERE n.id = $id "
                "RETURN child.id AS id, child.label AS label, child.entity_type AS entity_type, "
                "child.file_path AS file_path, child.source_location AS source_location",
                {"id": nid},
            )
            for child in children:
                if child["id"] not in visited:
                    visited.add(child["id"])
                    all_descendants.append(child)
                    next_frontier.append(child["id"])
        frontier = next_frontier
        if not frontier:
            break

    return sorted(all_descendants, key=lambda x: (x["entity_type"], x["label"]))


def _fetch_root_ancestor(graph_store: GraphStore, entity_id: str) -> dict | None:
    """Walk up the graph until a node with no parent is found."""
    current_id = entity_id
    visited: set[str] = {entity_id}
    root = None

    while True:
        rows = graph_store.query(
            "MATCH (parent:Entity)-[:RELATES]->(n:Entity) "
            "WHERE n.id = $id "
            "RETURN parent.id AS id, parent.label AS label, parent.entity_type AS entity_type, "
            "parent.file_path AS file_path, parent.source_location AS source_location LIMIT 1",
            {"id": current_id},
        )
        if not rows or rows[0]["id"] in visited:
            break
        root = rows[0]
        visited.add(root["id"])
        current_id = root["id"]

    return root


def _fetch_leaf_descendants(graph_store: GraphStore, entity_id: str, depth: int) -> list[dict]:
    """Return descendants within depth that have no children."""
    all_descendants = _fetch_descendants(graph_store, entity_id, depth)
    leaves = []
    for d in all_descendants:
        children = graph_store.query(
            "MATCH (n:Entity)-[:RELATES]->(child:Entity) WHERE n.id = $id RETURN child.id AS id",
            {"id": d["id"]},
        )
        if not children:
            leaves.append(d)
    return leaves


def _print_results(results: list[dict], depth: int) -> None:
    for item in results:
        e = item["entity"]
        print(f"{e['entity_type']}  {e['label']}  {e['file_path']}:{e['source_location']}")
        if item.get("root_ancestor"):
            r = item["root_ancestor"]
            print(f"  root: {r['entity_type']} {r['label']}  {r['file_path']}:{r['source_location']}")
        if item["parent"]:
            p = item["parent"]
            print(f"  parent: {p['entity_type']} {p['label']}  {p['source_location']}")
        if item["descendants"]:
            label = f"descendants (depth={depth})"
            print(f"  {label} ({len(item['descendants'])}):")
            for child in item["descendants"]:
                print(f"    {child['entity_type']:<10} {child['label']:<30} {child['source_location']}")
        if item.get("leaf_descendants"):
            print(f"  leaves ({len(item['leaf_descendants'])}):")
            for leaf in item["leaf_descendants"]:
                print(f"    {leaf['entity_type']:<10} {leaf['label']:<30} {leaf['file_path']}:{leaf['source_location']}")
        print()


def _print_or_json(rows: list[dict], as_json: bool, empty_msg: str) -> None:
    if not rows:
        print(empty_msg)
        return
    if as_json:
        print(json.dumps(rows, indent=2))
    else:
        for row in rows:
            print(f"{row['entity_type']:<10} {row['label']:<30} {row['file_path']}:{row['source_location']}")


if __name__ == "__main__":
    main()
