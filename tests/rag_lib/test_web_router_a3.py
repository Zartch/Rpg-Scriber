"""Tests for A3 web router endpoints: /search/fts, /search/semantic, /chunks/{id}/similar."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

import rag_lib
from rag_lib.web import build_router


@pytest.fixture
async def client(tmp_path: Path, simple_pdf: Path, fake_embedder):
    db_path = tmp_path / "rag.db"
    result = await rag_lib.ingest_pdf(
        simple_pdf, manual_name="Test Manual", db_path=db_path, embedder=fake_embedder,
    )
    app = FastAPI()
    app.include_router(build_router(db_path))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c, db_path, result.manual_id


async def test_search_fts_returns_200(client) -> None:
    c, db_path, manual_id = client
    chunks = await rag_lib.list_chunks(manual_id, db_path=db_path)
    first_word = chunks[0].text.split()[0] if chunks else "el"
    resp = await c.get(f"/api/rag/search/fts?q={first_word}")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_search_fts_empty_query_returns_empty_list(client) -> None:
    c, _, _ = client
    resp = await c.get("/api/rag/search/fts?q=")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_search_fts_manual_ids_filter(client) -> None:
    c, _, manual_id = client
    resp = await c.get(f"/api/rag/search/fts?q=el&manual_ids={manual_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert all(r["manual_id"] == manual_id for r in data)


async def test_search_fts_unknown_manual_id_returns_empty(client) -> None:
    c, _, _ = client
    resp = await c.get("/api/rag/search/fts?q=el&manual_ids=9999")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_search_semantic_returns_200(client, fake_embedder) -> None:
    c, _, _ = client
    with patch("rag_lib.OpenAIEmbedder", return_value=fake_embedder):
        resp = await c.get("/api/rag/search/semantic?q=combate")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_search_semantic_empty_query_returns_empty(client) -> None:
    c, _, _ = client
    resp = await c.get("/api/rag/search/semantic?q=")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_similar_endpoint_returns_200(client, fake_embedder) -> None:
    c, db_path, manual_id = client
    chunks = await rag_lib.list_chunks(manual_id, db_path=db_path)
    chunk_id = chunks[0].id
    with patch("rag_lib.OpenAIEmbedder", return_value=fake_embedder):
        resp = await c.get(f"/api/rag/chunks/{chunk_id}/similar?k=3")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert all(r["chunk_id"] != chunk_id for r in data)


async def test_similar_endpoint_nonexistent_chunk_returns_empty(client, fake_embedder) -> None:
    c, _, _ = client
    with patch("rag_lib.OpenAIEmbedder", return_value=fake_embedder):
        resp = await c.get("/api/rag/chunks/99999/similar")
    assert resp.status_code == 200
    assert resp.json() == []
