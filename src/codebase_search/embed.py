from __future__ import annotations

from collections.abc import Sequence

from langchain_ollama import OllamaEmbeddings


DEFAULT_MODEL = "qwen3-embedding:0.6b"
QWEN3_CODE_QUERY_INSTRUCTION = (
    "Instruct: Given a natural language query about a codebase, retrieve the most relevant code chunk.\n"
    "Query: "
)


def embed_text(text: str, model: str = DEFAULT_MODEL) -> list[float]:
    return list(_load_embeddings(model).embed_query(_format_query_text(text, model)))


def embed_texts(texts: Sequence[str], model: str = DEFAULT_MODEL) -> list[list[float]]:
    if not texts:
        return []

    vectors = _load_embeddings(model).embed_documents(list(texts))
    return [list(vector) for vector in vectors]


_embeddings_cache: dict[str, OllamaEmbeddings] = {}


def _load_embeddings(model: str = DEFAULT_MODEL) -> OllamaEmbeddings:
    if model not in _embeddings_cache:
        _embeddings_cache[model] = OllamaEmbeddings(model=model)
    return _embeddings_cache[model]


def _format_query_text(text: str, model: str) -> str:
    if model.startswith("qwen3-embedding"):
        return f"{QWEN3_CODE_QUERY_INSTRUCTION}{text}"
    return text
