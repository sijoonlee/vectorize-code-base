from __future__ import annotations

from codebase_search.graph.base import GraphStore, normalize_edge


class Neo4jStore(GraphStore):
    def __init__(self, uri: str, user: str, password: str) -> None:
        try:
            from neo4j import GraphDatabase
        except ImportError:
            raise SystemExit(
                "neo4j package not installed. Run: pip install codebase-search[neo4j]"
            )
        self._driver = GraphDatabase.driver(uri, auth=(user, password))
        self._init_constraints()

    def _init_constraints(self) -> None:
        with self._driver.session() as s:
            s.run("CREATE CONSTRAINT IF NOT EXISTS FOR (n:Entity) REQUIRE n.id IS UNIQUE")

    def insert_nodes(self, nodes: list[dict]) -> None:
        with self._driver.session() as s:
            s.run(
                "UNWIND $nodes AS n "
                "MERGE (e:Entity {id: n.id}) "
                "SET e.label = n.label, e.entity_type = n.entity_type, "
                "    e.file_path = n.file_path, e.source_location = n.source_location",
                nodes=nodes,
            )

    def insert_edges(self, edges: list[dict]) -> None:
        payloads = [normalize_edge(edge) for edge in edges]
        with self._driver.session() as s:
            s.run(
                "UNWIND $edges AS e "
                "MATCH (a:Entity {id: e.source}), (b:Entity {id: e.target}) "
                "MERGE (a)-[r:RELATES {relation: e.relation}]->(b) "
                "SET r.confidence = e.confidence, "
                "    r.source = e.edge_source, "
                "    r.details = e.details",
                edges=payloads,
            )

    def delete_file(self, rel_path: str) -> None:
        with self._driver.session() as s:
            s.run(
                "MATCH (n:Entity {file_path: $fp}) DETACH DELETE n",
                fp=rel_path,
            )

    def clear(self) -> None:
        with self._driver.session() as s:
            s.run("MATCH (n:Entity) DETACH DELETE n")

    def query(self, cypher: str, params: dict | None = None) -> list[dict]:
        with self._driver.session() as s:
            result = s.run(cypher, **(params or {}))
            return [dict(record) for record in result]

    def close(self) -> None:
        self._driver.close()
