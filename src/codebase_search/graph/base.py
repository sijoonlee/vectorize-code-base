from __future__ import annotations

from abc import ABC, abstractmethod


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
