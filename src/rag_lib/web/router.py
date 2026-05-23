"""rag_lib web router — 4 REST endpoints + /rag HTML page."""
from __future__ import annotations

import dataclasses
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

import rag_lib

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def build_router(db_path: str | Path) -> APIRouter:
    """Return an APIRouter with /rag page and /api/rag/* endpoints.

    Usage:
        app.include_router(rag_lib.web.build_router(config.rag_db_path))
    """
    router = APIRouter()
    db = str(db_path)

    @router.get("/rag", response_class=HTMLResponse, include_in_schema=False)
    async def rag_page() -> str:
        html = (_TEMPLATES_DIR / "rag.html").read_text(encoding="utf-8")
        return html

    @router.get("/api/rag/manuals")
    async def list_manuals_endpoint():
        manuals = await rag_lib.list_manuals(db_path=db)
        return [dataclasses.asdict(m) for m in manuals]

    @router.get("/api/rag/manuals/{manual_id}/chunks")
    async def list_chunks_endpoint(manual_id: int, offset: int = 0, limit: int = 50):
        chunks = await rag_lib.list_chunks(manual_id, db_path=db, offset=offset, limit=limit)
        return [dataclasses.asdict(c) for c in chunks]

    @router.get("/api/rag/chunks/{chunk_id}")
    async def get_chunk_endpoint(chunk_id: int):
        chunk = await rag_lib.get_chunk(chunk_id, db_path=db)
        if chunk is None:
            raise HTTPException(status_code=404, detail="Chunk not found")
        return dataclasses.asdict(chunk)

    @router.delete("/api/rag/manuals/{manual_id}", status_code=204)
    async def delete_manual_endpoint(manual_id: int):
        deleted = await rag_lib.delete_manual(manual_id, db_path=db)
        if not deleted:
            raise HTTPException(status_code=404, detail="Manual not found")

    return router
