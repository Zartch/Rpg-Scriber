"""rag_lib web router — REST endpoints + /rag HTML page."""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import rag_lib
from rag_lib.embedding.base import Embedder

_TEMPLATES_DIR = Path(__file__).parent / "templates"


class ChunkUpdate(BaseModel):
    text: Optional[str] = None
    section_path: Optional[str] = None
    chunk_type: Optional[Literal["prose", "table"]] = None


def build_router(db_path: str | Path, embedder: Embedder | None = None) -> APIRouter:
    """Return an APIRouter with /rag page and /api/rag/* endpoints."""
    router = APIRouter()
    db = str(db_path)

    @router.get("/rag", response_class=HTMLResponse, include_in_schema=False)
    async def rag_page() -> str:
        return (_TEMPLATES_DIR / "rag.html").read_text(encoding="utf-8")

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

    def _parse_manual_ids(raw: str) -> list[int] | None:
        if not raw.strip():
            return None
        try:
            return [int(x) for x in raw.split(",") if x.strip()]
        except ValueError:
            raise HTTPException(
                status_code=422, detail="manual_ids must be comma-separated integers"
            )

    @router.get("/api/rag/search/fts")
    async def search_fts_endpoint(q: str = "", manual_ids: str = "", k: int = 10):
        ids = _parse_manual_ids(manual_ids)
        results = await rag_lib.search_fts(q, db_path=db, manual_ids=ids, k=k)
        return [dataclasses.asdict(r) for r in results]

    @router.get("/api/rag/search/semantic")
    async def search_semantic_endpoint(q: str = "", manual_ids: str = "", k: int = 10):
        if not q.strip():
            return []
        ids = _parse_manual_ids(manual_ids)
        results = await rag_lib.search(q, db_path=db, manual_ids=ids, k=k)
        return [dataclasses.asdict(r) for r in results]

    @router.get("/api/rag/chunks/{chunk_id}/similar")
    async def similar_chunks_endpoint(chunk_id: int, k: int = 5):
        results = await rag_lib.search_similar(chunk_id, db_path=db, k=k)
        return [dataclasses.asdict(r) for r in results]

    @router.post("/api/rag/manuals/upload", status_code=202)
    async def upload_manual_endpoint(
        file: UploadFile,
        manual_name: str = Form(...),
    ):
        if not manual_name.strip():
            raise HTTPException(status_code=422, detail="manual_name cannot be empty")
        if file.content_type != "application/pdf":
            raise HTTPException(
                status_code=400,
                detail="File must be a PDF (content-type: application/pdf)",
            )
        pdf_bytes = await file.read()
        job = await rag_lib.upload_pdf(
            pdf_bytes,
            manual_name=manual_name,
            db_path=db,
            embedder=embedder,
        )
        return dataclasses.asdict(job)

    @router.get("/api/rag/jobs/{job_id}")
    async def get_job_endpoint(job_id: str):
        job = await rag_lib.get_job(job_id, db_path=db)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return dataclasses.asdict(job)

    @router.patch("/api/rag/chunks/{chunk_id}")
    async def patch_chunk_endpoint(chunk_id: int, body: ChunkUpdate):
        kwargs: dict = {}
        if "text" in body.model_fields_set:
            kwargs["text"] = body.text
        if "section_path" in body.model_fields_set:
            kwargs["section_path"] = body.section_path
        if "chunk_type" in body.model_fields_set:
            kwargs["chunk_type"] = body.chunk_type

        chunk = await rag_lib.update_chunk(chunk_id, db_path=db, embedder=embedder, **kwargs)
        if chunk is None:
            raise HTTPException(status_code=404, detail="Chunk not found")
        return dataclasses.asdict(chunk)

    return router
