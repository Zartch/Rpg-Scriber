"""rag_lib database layer: Database class + repositories."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import aiosqlite

from rag_lib.schema import RAG_SCHEMA_SQL

logger = logging.getLogger(__name__)


class Database:
    """Async SQLite wrapper for rag_lib."""

    def __init__(self, db_path: str | Path = "rag.db") -> None:
        self._db_path = str(db_path)
        self._conn: aiosqlite.Connection | None = None
        self.manuals = ManualRepo(self)
        self.chunks = ChunkRepo(self)

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        # FK must be enabled per connection before executescript
        await self._conn.execute("PRAGMA foreign_keys = ON")
        await self._conn.executescript(RAG_SCHEMA_SQL)
        await self._conn.commit()
        logger.debug("rag_lib database connected: %s", self._db_path)

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._conn


class ManualRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def find_by_hash(self, source_hash: str) -> dict[str, Any] | None:
        cur = await self._db.conn.execute(
            "SELECT * FROM rag_manuals WHERE source_hash = ?", (source_hash,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def insert(
        self, *, name: str, source_path: str, source_hash: str,
        page_count: int, file_size: int, parser: str,
    ) -> int:
        cur = await self._db.conn.execute(
            """INSERT INTO rag_manuals (name, source_path, source_hash, page_count, file_size, parser)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (name, source_path, source_hash, page_count, file_size, parser),
        )
        await self._db.conn.commit()
        assert cur.lastrowid is not None
        return cur.lastrowid

    async def list_all(self) -> list[dict[str, Any]]:
        cur = await self._db.conn.execute(
            """SELECT m.*, COUNT(c.id) AS chunk_count
               FROM rag_manuals m
               LEFT JOIN rag_chunks c ON c.manual_id = m.id
               GROUP BY m.id
               ORDER BY m.ingested_at DESC"""
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def delete(self, manual_id: int) -> bool:
        cur = await self._db.conn.execute(
            "DELETE FROM rag_manuals WHERE id = ?", (manual_id,)
        )
        await self._db.conn.commit()
        return cur.rowcount > 0


class ChunkRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def insert_many(self, manual_id: int, chunks: list[dict[str, Any]]) -> None:
        await self._db.conn.executemany(
            """INSERT INTO rag_chunks
               (manual_id, seq, chunk_type, page, page_end, section_path, text, text_hash, token_count)
               VALUES (:manual_id, :seq, :chunk_type, :page, :page_end,
                       :section_path, :text, :text_hash, :token_count)""",
            [{"manual_id": manual_id, **c} for c in chunks],
        )
        await self._db.conn.commit()

    async def list_by_manual(
        self, manual_id: int, *, offset: int = 0, limit: int = 50,
    ) -> list[dict[str, Any]]:
        cur = await self._db.conn.execute(
            """SELECT * FROM rag_chunks WHERE manual_id = ?
               ORDER BY seq LIMIT ? OFFSET ?""",
            (manual_id, limit, offset),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_by_id(self, chunk_id: int) -> dict[str, Any] | None:
        cur = await self._db.conn.execute(
            "SELECT * FROM rag_chunks WHERE id = ?", (chunk_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None
