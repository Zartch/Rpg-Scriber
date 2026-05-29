"""End-to-end tests for rag_lib.search() using FakeEmbedder."""
from __future__ import annotations

from pathlib import Path

import pytest

import rag_lib
from rag_lib.embedding.base import Embedder
from rag_lib.types import SearchResult


@pytest.fixture(autouse=True)
def clear_vector_cache():
    rag_lib._VECTOR_CACHE.clear()
    yield
    rag_lib._VECTOR_CACHE.clear()


async def test_search_returns_search_results(
    simple_pdf: Path, tmp_path: Path, fake_embedder,
) -> None:
    db = tmp_path / "rag.db"
    await rag_lib.ingest_pdf(simple_pdf, manual_name="Book", db_path=db, embedder=fake_embedder)
    results = await rag_lib.search("any query", db, embedder=fake_embedder)
    assert len(results) > 0
    assert all(isinstance(r, SearchResult) for r in results)


async def test_search_result_has_chunk_text(
    simple_pdf: Path, tmp_path: Path, fake_embedder,
) -> None:
    db = tmp_path / "rag.db"
    await rag_lib.ingest_pdf(simple_pdf, manual_name="Book", db_path=db, embedder=fake_embedder)
    results = await rag_lib.search("any query", db, embedder=fake_embedder)
    assert all(isinstance(r.chunk.text, str) and len(r.chunk.text) > 0 for r in results)


async def test_search_respects_k_limit(
    simple_pdf: Path, tmp_path: Path, fake_embedder,
) -> None:
    db = tmp_path / "rag.db"
    await rag_lib.ingest_pdf(simple_pdf, manual_name="Book", db_path=db, embedder=fake_embedder)
    results = await rag_lib.search("query", db, k=2, embedder=fake_embedder)
    assert len(results) <= 2


async def test_search_respects_threshold(
    simple_pdf: Path, tmp_path: Path,
) -> None:
    db = tmp_path / "rag.db"

    chunk_vecs = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]]

    class CyclicEmbedder(Embedder):
        def __init__(self, vecs: list[list[float]]) -> None:
            self._cycle = vecs
        @property
        def model(self) -> str: return "cyclic"
        @property
        def dim(self) -> int: return 4
        async def embed(self, texts: list[str]) -> list[list[float]]:
            return [self._cycle[i % len(self._cycle)] for i in range(len(texts))]

    emb = CyclicEmbedder(chunk_vecs)
    await rag_lib.ingest_pdf(simple_pdf, manual_name="Book", db_path=db, embedder=emb)

    query_emb = CyclicEmbedder([[1.0, 0.0, 0.0, 0.0]])
    results_no_thresh = await rag_lib.search("q", db, k=10, embedder=query_emb)
    results_high_thresh = await rag_lib.search("q", db, k=10, threshold=0.9, embedder=query_emb)
    assert len(results_high_thresh) < len(results_no_thresh)
    assert all(r.score >= 0.9 for r in results_high_thresh)


async def test_search_manual_ids_filter(
    simple_pdf: Path, tmp_path: Path, fake_embedder,
) -> None:
    db = tmp_path / "rag.db"
    r1 = await rag_lib.ingest_pdf(
        simple_pdf, manual_name="Manual A", db_path=db, embedder=fake_embedder,
    )
    results_filtered = await rag_lib.search(
        "query", db, manual_ids=[r1.manual_id], embedder=fake_embedder,
    )
    assert all(r.manual_id == r1.manual_id for r in results_filtered)


async def test_search_empty_db_returns_empty_list(
    tmp_path: Path, fake_embedder,
) -> None:
    db = tmp_path / "empty.db"
    results = await rag_lib.search("query", db, embedder=fake_embedder)
    assert results == []


async def test_search_scores_are_between_0_and_1(
    simple_pdf: Path, tmp_path: Path, fake_embedder,
) -> None:
    db = tmp_path / "rag.db"
    await rag_lib.ingest_pdf(simple_pdf, manual_name="Book", db_path=db, embedder=fake_embedder)
    results = await rag_lib.search("query", db, embedder=fake_embedder)
    assert all(0.0 <= r.score <= 1.0 for r in results)


async def test_search_results_sorted_descending_by_score(
    simple_pdf: Path, tmp_path: Path, fake_embedder,
) -> None:
    db = tmp_path / "rag.db"
    await rag_lib.ingest_pdf(simple_pdf, manual_name="Book", db_path=db, embedder=fake_embedder)
    results = await rag_lib.search("query", db, embedder=fake_embedder)
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)
