"""rag_lib SQLite schema DDL."""
from __future__ import annotations

RAG_SCHEMA_SQL = """\
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS rag_manuals (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    source_path   TEXT NOT NULL,
    source_hash   TEXT NOT NULL UNIQUE,
    page_count    INTEGER NOT NULL,
    file_size     INTEGER NOT NULL,
    parser        TEXT NOT NULL DEFAULT 'pdfplumber',
    ingested_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS rag_chunks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    manual_id     INTEGER NOT NULL REFERENCES rag_manuals(id) ON DELETE CASCADE,
    seq           INTEGER NOT NULL,
    chunk_type    TEXT NOT NULL CHECK (chunk_type IN ('prose', 'table')),
    page          INTEGER NOT NULL,
    page_end      INTEGER,
    section_path  TEXT,
    text          TEXT NOT NULL,
    text_hash     TEXT NOT NULL,
    token_count   INTEGER NOT NULL,
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (manual_id, seq)
);

CREATE TABLE IF NOT EXISTS rag_embeddings (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id   INTEGER NOT NULL UNIQUE REFERENCES rag_chunks(id) ON DELETE CASCADE,
    vector     BLOB NOT NULL,
    dim        INTEGER NOT NULL,
    model      TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_chunks_manual_page ON rag_chunks(manual_id, page);
CREATE INDEX IF NOT EXISTS idx_chunks_type        ON rag_chunks(chunk_type);
CREATE INDEX IF NOT EXISTS idx_chunks_hash        ON rag_chunks(text_hash);
CREATE INDEX IF NOT EXISTS idx_embeddings_chunk   ON rag_embeddings(chunk_id);
"""
