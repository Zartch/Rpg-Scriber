"""Tests for OpenAIEmbedder — API calls are mocked."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rag_lib.embedding.openai import OpenAIEmbedder
from rag_lib.errors import EmbeddingError


def _make_openai_response(vectors: list[list[float]]):
    """Build a mock openai embeddings response."""
    resp = MagicMock()
    resp.data = [MagicMock(embedding=v) for v in vectors]
    return resp


async def test_embed_returns_one_vector_per_text() -> None:
    vecs = [[0.1, 0.2], [0.3, 0.4]]
    with patch("rag_lib.embedding.openai.AsyncOpenAI") as mock_cls:
        instance = MagicMock()
        mock_cls.return_value = instance
        instance.embeddings.create = AsyncMock(return_value=_make_openai_response(vecs))
        embedder = OpenAIEmbedder(api_key="fake-key")
        result = await embedder.embed(["hello", "world"])
    assert len(result) == 2
    assert result[0] == pytest.approx([0.1, 0.2])
    assert result[1] == pytest.approx([0.3, 0.4])


async def test_embed_batches_large_input() -> None:
    """Inputs exceeding the per-batch item cap trigger multiple API calls."""
    batch_size = 3  # override for test
    total = 7
    texts = [f"text {i}" for i in range(total)]
    vecs = [[float(i)] for i in range(total)]

    call_count = 0

    async def fake_create(model, input):
        nonlocal call_count
        call_count += 1
        start = (call_count - 1) * batch_size
        end = start + len(input)
        return _make_openai_response(vecs[start:end])

    with patch("rag_lib.embedding.openai.AsyncOpenAI") as mock_cls:
        instance = MagicMock()
        mock_cls.return_value = instance
        instance.embeddings.create = fake_create
        embedder = OpenAIEmbedder(api_key="fake-key")
        embedder._MAX_ITEMS_PER_BATCH = batch_size
        result = await embedder.embed(texts)

    assert len(result) == total
    assert call_count == 3   # ceil(7/3) = 3


async def test_embed_empty_string_replaced_by_space() -> None:
    """Empty strings must be replaced with a space before sending to API."""
    captured_inputs: list[list[str]] = []

    async def fake_create(model, input):
        captured_inputs.append(list(input))
        return _make_openai_response([[0.0]] * len(input))

    with patch("rag_lib.embedding.openai.AsyncOpenAI") as mock_cls:
        instance = MagicMock()
        mock_cls.return_value = instance
        instance.embeddings.create = fake_create
        embedder = OpenAIEmbedder(api_key="fake-key")
        await embedder.embed(["", "real text", "   "])

    sent = captured_inputs[0]
    assert sent[0] == " "
    assert sent[2] == " "
    assert sent[1] == "real text"


async def test_embed_wraps_api_error_in_embedding_error() -> None:
    from openai import OpenAIError

    with patch("rag_lib.embedding.openai.AsyncOpenAI") as mock_cls:
        instance = MagicMock()
        mock_cls.return_value = instance
        instance.embeddings.create = AsyncMock(
            side_effect=OpenAIError("quota exceeded")
        )
        embedder = OpenAIEmbedder(api_key="fake-key")
        with pytest.raises(EmbeddingError, match="quota exceeded"):
            await embedder.embed(["hello"])


async def test_model_property_returns_correct_value() -> None:
    with patch("rag_lib.embedding.openai.AsyncOpenAI"):
        embedder = OpenAIEmbedder(api_key="fake-key")
    assert embedder.model == "text-embedding-3-small"


async def test_dim_property_returns_1536() -> None:
    with patch("rag_lib.embedding.openai.AsyncOpenAI"):
        embedder = OpenAIEmbedder(api_key="fake-key")
    assert embedder.dim == 1536
