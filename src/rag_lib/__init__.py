"""rag_lib — reusable RAG module. Public API."""
from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path
from typing import Any

from rag_lib.chunking import run_chunker
from rag_lib.errors import PdfParseError as PdfParseError
from rag_lib.parsing.pdfplumber_parser import PdfplumberParser
from rag_lib.store import Database
from rag_lib.types import Chunk, IngestResult, Manual

logger = logging.getLogger(__name__)

_PARSER = PdfplumberParser()


async def ingest_pdf(
    pdf_path: str | Path,
    *,
    manual_name: str,
    db_path: str | Path,
) -> IngestResult:
    """Ingest a PDF into rag_lib. Idempotent: same SHA256 → returns existing manual_id."""
    pdf_path = Path(pdf_path)
    file_bytes = pdf_path.read_bytes()
    source_hash = hashlib.sha256(file_bytes).hexdigest()
    file_size = len(file_bytes)

    db = Database(db_path)
    await db.connect()
    try:
        existing = await db.manuals.find_by_hash(source_hash)
        if existing:
            logger.info("rag_lib.ingest: %s already ingested as manual_id=%d", manual_name, existing["id"])
            return IngestResult(manual_id=existing["id"], chunks_created=0, was_already_ingested=True)

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
            await db.chunks.insert_many(manual_id, chunks)

        logger.info("rag_lib.ingest: saved manual_id=%d with %d chunks", manual_id, len(chunks))
        return IngestResult(manual_id=manual_id, chunks_created=len(chunks), was_already_ingested=False)
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
    """Delete a manual and its chunks (cascade). Returns True if existed."""
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
