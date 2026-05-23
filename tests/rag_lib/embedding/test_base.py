"""Tests for Embedder ABC contract using FakeEmbedder."""
from __future__ import annotations

from rag_lib.embedding import Embedder


async def test_fake_embedder_returns_one_vector_per_text(fake_embedder) -> None:
    texts = ["hello", "world", "foo"]
    result = await fake_embedder.embed(texts)
    assert len(result) == 3


async def test_fake_embedder_vector_has_correct_dim(fake_embedder) -> None:
    result = await fake_embedder.embed(["text"])
    assert len(result[0]) == fake_embedder.dim


async def test_fake_embedder_is_embedder_subclass(fake_embedder) -> None:
    assert isinstance(fake_embedder, Embedder)


async def test_fake_embedder_model_is_string(fake_embedder) -> None:
    assert isinstance(fake_embedder.model, str)


async def test_fake_embedder_with_fixed_vectors(fake_embedder_factory) -> None:
    vecs = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]]
    emb = fake_embedder_factory(vectors=vecs)
    result = await emb.embed(["a", "b"])
    assert result[0] == [1.0, 0.0, 0.0, 0.0]
    assert result[1] == [0.0, 1.0, 0.0, 0.0]


async def test_fake_embedder_deterministic_for_same_text(fake_embedder) -> None:
    r1 = await fake_embedder.embed(["same text"])
    r2 = await fake_embedder.embed(["same text"])
    assert r1 == r2


async def test_fake_embedder_different_texts_differ(fake_embedder) -> None:
    r = await fake_embedder.embed(["alpha", "beta"])
    assert r[0] != r[1]
