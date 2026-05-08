from __future__ import annotations

import os
from pathlib import Path

import lancedb
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from codebase_search.db_paths import derive_db_paths
from codebase_search.embed import DEFAULT_MODEL, embed_text
from codebase_search.graph.factory import create_graph_store
from codebase_search.graph_search import (
    _fetch_descendants,
    _fetch_leaf_descendants,
    _fetch_root_ancestor,
)
from codebase_search.index import TABLE_NAME, run_index
from codebase_search.search import _normalize_result

load_dotenv()

mcp = FastMCP("codebase-search")


@mcp.tool()
def codebase_index(
    repo: str | None = None,
) -> dict:
    """Index a codebase for semantic search and graph traversal.

    Chunks the source code with tree-sitter, embeds with Ollama, and writes both a
    vector DB (LanceDB) and a graph DB (Kuzu) under the vectorize-code-base db/ directory:
      db/<repo-name>/<branch>/vector
      db/<repo-name>/<branch>/graph

    Unchanged files are skipped via SHA256 cache. Safe to re-run after code changes.

    Args:
        repo: Absolute path to the repo to index. Defaults to the current working directory.
    """
    repo_path = Path(repo).expanduser().resolve() if repo else Path(os.getcwd())
    try:
        return run_index(repo_path)
    except ValueError as e:
        raise RuntimeError(str(e))


@mcp.tool()
def codebase_search(
    query: str,
    limit: int = 5,
    scope: str | None = None,
) -> list[dict]:
    """Semantic search over an indexed codebase using vector similarity.

    Returns code chunks (functions, classes, files) most relevant to the query.
    Each result includes file_path, line range, symbol name, and the code itself,
    optionally enriched with graph context (parent/child entities).

    DB paths are derived from the current working directory and git branch:
    db/<repo-name>/<branch>/vector  and  db/<repo-name>/<branch>/graph

    Args:
        query: Natural language description of what you are looking for.
        limit: Number of results to return (default 5).
        scope: Restrict results to files under this directory prefix, e.g. "src/auth".
    """
    repo = Path(os.getcwd())
    db_path, graph_db_path = derive_db_paths(repo)

    lance_db = lancedb.connect(db_path)
    if TABLE_NAME not in lance_db.table_names():
        raise ValueError(f"Table '{TABLE_NAME}' not found in {db_path}. Run codebase-index first.")

    graph_store = None
    if graph_db_path.exists():
        graph_store = create_graph_store("kuzu", str(graph_db_path))

    try:
        table = lance_db.open_table(TABLE_NAME)
        query_vector = embed_text(query, model=DEFAULT_MODEL)
        lance_query = table.search(query_vector)
        if scope:
            scope_prefix = scope.rstrip("/").replace("'", "''") + "/"
            lance_query = lance_query.where(f"file_path LIKE '{scope_prefix}%'")
        results = lance_query.limit(limit).to_list()
        return [_normalize_result(r, graph_store) for r in results]
    finally:
        if graph_store is not None:
            graph_store.close()


@mcp.tool()
def codebase_graph_traverse(
    query: str = "",
    depth: int = 1,
    scope: str | None = None,
    roots: bool = False,
    leaves: bool = False,
) -> list[dict]:
    """Traverse the code graph by entity name, or list root/leaf nodes.

    Use to explore how classes, functions, and files relate to each other.
    At least one of query, roots, or leaves must be set.

    DB path is derived from the current working directory and git branch:
    db/<repo-name>/<branch>/graph

    Args:
        query: Entity name or partial label to search for (case-insensitive).
        depth: Max traversal depth when using query (default 1).
        scope: Restrict to entities whose file_path starts with this prefix.
        roots: Include root ancestor of each matched entity (or list all roots if no query).
        leaves: Include leaf descendants of each matched entity (or list all leaves if no query).
    """
    if not query and not roots and not leaves:
        raise ValueError("Provide query, roots=True, or leaves=True.")

    _, graph_db_path = derive_db_paths(Path(os.getcwd()))
    graph_store = create_graph_store("kuzu", str(graph_db_path))
    scope_prefix = scope.rstrip("/") + "/" if scope else None

    try:
        if roots and not query:
            scope_clause = " AND n.file_path STARTS WITH $scope" if scope_prefix else ""
            return graph_store.query(
                f"MATCH (n:Entity) WHERE NOT ()-[:RELATES]->(n){scope_clause} "
                "RETURN n.id AS id, n.label AS label, n.entity_type AS entity_type, "
                "n.file_path AS file_path, n.source_location AS source_location "
                "ORDER BY n.file_path",
                {"scope": scope_prefix} if scope_prefix else None,
            )

        if leaves and not query:
            scope_clause = " AND n.file_path STARTS WITH $scope" if scope_prefix else ""
            return graph_store.query(
                f"MATCH (n:Entity) WHERE NOT (n)-[:RELATES]->(){scope_clause} "
                "RETURN n.id AS id, n.label AS label, n.entity_type AS entity_type, "
                "n.file_path AS file_path, n.source_location AS source_location "
                "ORDER BY n.entity_type, n.label",
                {"scope": scope_prefix} if scope_prefix else None,
            )

        scope_clause = " AND n.file_path STARTS WITH $scope" if scope_prefix else ""
        matches = graph_store.query(
            f"MATCH (n:Entity) WHERE lower(n.label) CONTAINS lower($q){scope_clause} "
            "RETURN n.id AS id, n.label AS label, n.entity_type AS entity_type, "
            "n.file_path AS file_path, n.source_location AS source_location "
            "ORDER BY n.entity_type, n.label",
            {"q": query, **({"scope": scope_prefix} if scope_prefix else {})},
        )

        results = []
        for entity in matches:
            parent_rows = graph_store.query(
                "MATCH (parent:Entity)-[:RELATES]->(n:Entity) WHERE n.id = $id "
                "RETURN parent.label AS label, parent.entity_type AS entity_type, "
                "parent.source_location AS source_location LIMIT 1",
                {"id": entity["id"]},
            )
            results.append({
                "entity": entity,
                "parent": parent_rows[0] if parent_rows else None,
                "root_ancestor": _fetch_root_ancestor(graph_store, entity["id"]) if roots else None,
                "leaf_descendants": _fetch_leaf_descendants(graph_store, entity["id"], depth) if leaves else None,
                "descendants": _fetch_descendants(graph_store, entity["id"], depth),
            })

        return results
    finally:
        graph_store.close()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
