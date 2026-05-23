"""rag_lib — reusable RAG module. Public API."""
from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path
from typing import Any

import numpy as np

from rag_lib.chunking import run_chunker
from rag_lib.embedding.base import Embedder
from rag_lib.embedding.index import VectorIndex
from rag_lib.embedding.openai import OpenAIEmbedder
from rag_lib.errors import EmbeddingError as EmbeddingError
from rag_lib.errors import PdfParseError as PdfParseError
from rag_lib.parsing.pdfplumber_parser import PdfplumberParser
from rag_lib.store import Database
from rag_lib.types import Chunk, IngestResult, Manual, SearchResult

logger = logging.getLogger(__name__)

_PARSER = PdfplumberParser()
_VECTOR_CACHE: dict[str, VectorIndex] = {}


async def ingest_pdf(
    pdf_path: str | Path,
    *,
    manual_name: str,
    db_path: str | Path,
    embedder: Embedder | None = None,
) -> IngestResult:
    """Ingest a PDF. Idempotent: same SHA256 → returns existing manual_id.

    Generates and stores embeddings for all chunks using *embedder*
    (default: OpenAIEmbedder from OPENAI_API_KEY env var).
    """
    pdf_path = Path(pdf_path)
    file_bytes = pdf_path.read_bytes()
    source_hash = hashlib.sha256(file_bytes).hexdigest()
    file_size = len(file_bytes)

    db = Database(db_path)
    await db.connect()
    try:
        existing = await db.manuals.find_by_hash(source_hash)
        if existing:
            logger.info(
                "rag_lib.ingest: %s already ingested as manual_id=%d",
                manual_name, existing["id"],
            )
            return IngestResult(
                manual_id=existing["id"], chunks_created=0, was_already_ingested=True,
            )

        logger.info("rag_lib.ingest: parsing %s", pdf_path.name)
        pages = await asyncio.to_thread(_PARSER.parse, pdf_path)
        page_count = len(pages)
        chunks = run_chunker(pages)

        manual_id = await db.manuals.insert(
            name=manual_name,
            source_path=str(pdf_path),
            source_hash=source_hash,
            page_count=page_count,
            file_size=file_size,
            parser="pdfplumber",
        )

        if chunks:
            inserted_ids = await db.chunks.insert_many(manual_id, chunks)
            _emb = embedder or OpenAIEmbedder()
            vectors = await _emb.embed([c["text"] for c in chunks])
            await db.embeddings.upsert_many([
                {
                    "chunk_id": cid,
                    "vector_bytes": np.array(v, dtype=np.float32).tobytes(),
                    "dim": _emb.dim,
                    "model": _emb.model,
                }
                for cid, v in zip(inserted_ids, vectors)
            ])
            _VECTOR_CACHE.pop(str(db_path), None)

        logger.info(
            "rag_lib.ingest: saved manual_id=%d with %d chunks", manual_id, len(chunks),
        )
        return IngestResult(
            manual_id=manual_id, chunks_created=len(chunks), was_already_ingested=False,
        )
    finally:
        await db.close()


async def list_manuals(db_path: str | Path) -> list[Manual]:
    db = Database(db_path)
    await db.connect()
    try:
        rows = await db.manuals.list_all()
        return [_row_to_manual(r) for r in rows]
    finally:
        await db.close()


async def delete_manual(manual_id: int, db_path: str | Path) -> bool:
    """Delete a manual and its chunks + embeddings (cascade). Returns True if existed."""
    db = Database(db_path)
    await db.connect()
    try:
        return await db.manuals.delete(manual_id)
    finally:
        await db.close()


async def get_chunk(chunk_id: int, db_path: str | Path) -> Chunk | None:
    db = Database(db_path)
    await db.connect()
    try:
        row = await db.chunks.get_by_id(chunk_id)
        return _row_to_chunk(row) if row else None
    finally:
        await db.close()


async def list_chunks(
    manual_id: int,
    db_path: str | Path,
    *,
    offset: int = 0,
    limit: int = 50,
) -> list[Chunk]:
    db = Database(db_path)
    await db.connect()
    try:
        rows = await db.chunks.list_by_manual(manual_id, offset=offset, limit=limit)
        return [_row_to_chunk(r) for r in rows]
    finally:
        await db.close()


async def search(
    query: str,
    db_path: str | Path,
    *,
    manual_ids: list[int] | None = None,
    k: int = 10,
    threshold: float | None = None,
    embedder: Embedder | None = None,
) -> list[SearchResult]:
    """Search for chunks by semantic similarity.

    Returns up to *k* results sorted by descending cosine score.
    If *manual_ids* is given, only chunks from those manuals are considered.
    """
    _emb = embedder or OpenAIEmbedder()
    [query_vec] = await _emb.embed([query])

    key = str(db_path)
    if key not in _VECTOR_CACHE:
        _VECTOR_CACHE[key] = VectorIndex()

    db = Database(db_path)
    await db.connect()
    try:
        await _VECTOR_CACHE[key].ensure_loaded(db)
        hits = _VECTOR_CACHE[key].search(
            query_vec, k=k, threshold=threshold, manual_ids=manual_ids,
        )
        if not hits:
            return []
        rows = await db.chunks.get_many_by_ids([cid for cid, _ in hits])
        row_map = {r["id"]: r for r in rows}
        return [
            SearchResult(
                chunk_id=cid,
                manual_id=row_map[cid]["manual_id"],
                score=score,
                chunk=_row_to_chunk(row_map[cid]),
            )
            for cid, score in hits
            if cid in row_map
        ]
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Row → dataclass helpers
# ---------------------------------------------------------------------------

def _row_to_manual(row: dict[str, Any]) -> Manual:
    return Manual(
        id=row["id"],
        name=row["name"],
        source_path=row["source_path"],
        source_hash=row["source_hash"],
        page_count=row["page_count"],
        file_size=row["file_size"],
        parser=row["parser"],
        ingested_at=row["ingested_at"],
        chunk_count=row.get("chunk_count", 0),
    )


def _row_to_chunk(row: dict[str, Any]) -> Chunk:
    return Chunk(
        id=row["id"],
        manual_id=row["manual_id"],
        seq=row["seq"],
        chunk_type=row["chunk_type"],
        page=row["page"],
        page_end=row.get("page_end"),
        section_path=row.get("section_path"),
        text=row["text"],
        text_hash=row["text_hash"],
        token_count=row["token_count"],
    )
