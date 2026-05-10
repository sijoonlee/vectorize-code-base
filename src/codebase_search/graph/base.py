from __future__ import annotations

from abc import ABC, abstractmethod


DEFAULT_EDGE_CONFIDENCE = 1.0
DEFAULT_EDGE_SOURCE = ""
DEFAULT_EDGE_DETAILS = ""


def normalize_edge(edge: dict) -> dict:
    """Return a storage-ready edge payload with metadata defaults.

    Edge dictionaries already use ``source`` for the source node id, so edge provenance is
    accepted as ``edge_source`` or ``provenance`` and persisted as the graph edge's
    ``source`` property by concrete stores.
    """
    return {
        "source": edge["source"],
        "target": edge["target"],
        "relation": edge.get("relation", ""),
        "confidence": float(edge.get("confidence", DEFAULT_EDGE_CONFIDENCE)),
        "edge_source": edge.get("edge_source", edge.get("provenance", DEFAULT_EDGE_SOURCE)),
        "details": edge.get("details", DEFAULT_EDGE_DETAILS),
    }


class GraphStore(ABC):
    @abstractmethod
    def insert_nodes(self, nodes: list[dict]) -> None: ...

    @abstractmethod
    def insert_edges(self, edges: list[dict]) -> None: ...

    @abstractmethod
    def delete_file(self, rel_path: str) -> None: ...

    @abstractmethod
    def clear(self) -> None: ...

    @abstractmethod
    def query(self, cypher: str, params: dict | None = None) -> list[dict]: ...

    @abstractmethod
    def close(self) -> None: ...
