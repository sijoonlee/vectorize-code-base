from __future__ import annotations

from pathlib import Path

from codebase_search.graph.base import GraphStore


def create_graph_store(backend: str, db_path: str | Path, **kwargs) -> GraphStore:
    if backend == "kuzu":
        try:
            from codebase_search.graph.kuzu_store import KuzuStore
        except ImportError:
            raise SystemExit("kuzu not installed. Run: pip install kuzu")
        return KuzuStore(Path(db_path))

    # TODO: expose Neo4j as an option via env var (e.g. CODEBASE_GRAPH_BACKEND=neo4j +
    #       CODEBASE_NEO4J_URL=bolt://localhost:7687) so CLI and MCP can use it without
    #       adding a --graph-backend flag back.
    # Neo4j support exists but is not exposed via CLI or MCP (no --graph-backend option).
    # Uncomment to re-enable when needed:
    # if backend == "neo4j":
    #     from codebase_search.graph.neo4j_store import Neo4jStore
    #     uri = kwargs.get("uri", "bolt://localhost:7687")
    #     user = kwargs.get("user", "neo4j")
    #     password = kwargs.get("password", "neo4j")
    #     return Neo4jStore(uri, user, password)

    raise ValueError(f"Unknown graph backend: {backend!r}. Choose 'kuzu' or 'neo4j'.")
