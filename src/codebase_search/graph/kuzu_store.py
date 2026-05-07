from __future__ import annotations

from pathlib import Path

import kuzu

from codebase_search.graph.base import GraphStore


class KuzuStore(GraphStore):
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = kuzu.Database(str(db_path))
        self._conn = kuzu.Connection(self._db)
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            "CREATE NODE TABLE IF NOT EXISTS Entity("
            "id STRING, label STRING, entity_type STRING, "
            "file_path STRING, source_location STRING, PRIMARY KEY(id))"
        )
        self._conn.execute(
            "CREATE REL TABLE IF NOT EXISTS RELATES("
            "FROM Entity TO Entity, relation STRING)"
        )

    def insert_nodes(self, nodes: list[dict]) -> None:
        for node in nodes:
            try:
                self._conn.execute(
                    "CREATE (:Entity {id: $id, label: $label, entity_type: $et, "
                    "file_path: $fp, source_location: $sl})",
                    {
                        "id": node["id"],
                        "label": node.get("label", ""),
                        "et": node.get("entity_type", ""),
                        "fp": node.get("file_path", ""),
                        "sl": node.get("source_location", ""),
                    },
                )
            except Exception:
                pass  # skip duplicate ids

    def insert_edges(self, edges: list[dict]) -> None:
        for edge in edges:
            try:
                self._conn.execute(
                    "MATCH (a:Entity {id: $src}), (b:Entity {id: $tgt}) "
                    "CREATE (a)-[:RELATES {relation: $rel}]->(b)",
                    {
                        "src": edge["source"],
                        "tgt": edge["target"],
                        "rel": edge.get("relation", ""),
                    },
                )
            except Exception:
                pass  # skip edges where either endpoint doesn't exist

    def delete_file(self, rel_path: str) -> None:
        self._conn.execute(
            "MATCH (n:Entity) WHERE n.file_path = $fp DETACH DELETE n",
            {"fp": rel_path},
        )

    def clear(self) -> None:
        self._conn.execute("MATCH (n:Entity) DETACH DELETE n")

    def query(self, cypher: str, params: dict | None = None) -> list[dict]:
        result = self._conn.execute(cypher, params or {})
        column_names = result.get_column_names()
        rows = []
        while result.has_next():
            rows.append(dict(zip(column_names, result.get_next())))
        return rows

    def close(self) -> None:
        pass  # kuzu connections are closed on GC
