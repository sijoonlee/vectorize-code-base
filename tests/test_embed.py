from codebase_search import embed


class FakeEmbeddings:
    def __init__(self, model: str) -> None:
        self.model = model
        self.queries: list[str] = []

    def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return [float(len(text))]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[float(index), float(len(text))] for index, text in enumerate(texts)]


def test_embed_text_uses_langchain_ollama_embeddings(monkeypatch) -> None:
    loaded_models = []

    def fake_load_embeddings(model: str) -> FakeEmbeddings:
        loaded_models.append(model)
        return FakeEmbeddings(model)

    monkeypatch.setattr(embed, "_load_embeddings", fake_load_embeddings)

    assert embed.embed_text("hello", model="nomic-embed-text") == [5.0]
    assert loaded_models == ["nomic-embed-text"]


def test_embed_text_formats_qwen3_queries_with_instruction(monkeypatch) -> None:
    fake_embeddings = FakeEmbeddings("qwen3-embedding:0.6b")

    def fake_load_embeddings(model: str) -> FakeEmbeddings:
        return fake_embeddings

    monkeypatch.setattr(embed, "_load_embeddings", fake_load_embeddings)

    embed.embed_text("where is auth checked", model="qwen3-embedding:0.6b")

    assert fake_embeddings.queries == [
        "Instruct: Given a natural language query about a codebase, retrieve the most relevant code chunk.\n"
        "Query: where is auth checked"
    ]


def test_embed_texts_uses_batch_embedding(monkeypatch) -> None:
    loaded_models = []

    def fake_load_embeddings(model: str) -> FakeEmbeddings:
        loaded_models.append(model)
        return FakeEmbeddings(model)

    monkeypatch.setattr(embed, "_load_embeddings", fake_load_embeddings)

    assert embed.embed_texts(["abc", "defg"], model="nomic-embed-code") == [
        [0.0, 3.0],
        [1.0, 4.0],
    ]
    assert loaded_models == ["nomic-embed-code"]


def test_embed_texts_skips_loading_model_for_empty_batch(monkeypatch) -> None:
    def fail_load_embeddings(model: str) -> FakeEmbeddings:
        raise AssertionError("model should not be loaded for an empty batch")

    monkeypatch.setattr(embed, "_load_embeddings", fail_load_embeddings)

    assert embed.embed_texts([]) == []
