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

CREATE TABLE IF NOT EXISTS rag_jobs (
    id           TEXT PRIMARY KEY,
    status       TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending', 'processing', 'done', 'error')),
    manual_name  TEXT NOT NULL,
    manual_id    INTEGER,
    was_duplicate INTEGER NOT NULL DEFAULT 0,
    error        TEXT,
    created_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE VIRTUAL TABLE IF NOT EXISTS rag_chunks_fts USING fts5(
    text,
    section_path,
    content="rag_chunks",
    content_rowid="id"
);

CREATE INDEX IF NOT EXISTS idx_chunks_manual_page ON rag_chunks(manual_id, page);
CREATE INDEX IF NOT EXISTS idx_chunks_type        ON rag_chunks(chunk_type);
CREATE INDEX IF NOT EXISTS idx_chunks_hash        ON rag_chunks(text_hash);
CREATE INDEX IF NOT EXISTS idx_embeddings_chunk   ON rag_embeddings(chunk_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status        ON rag_jobs(status);

CREATE TRIGGER IF NOT EXISTS rag_chunks_ai AFTER INSERT ON rag_chunks BEGIN
    INSERT INTO rag_chunks_fts(rowid, text, section_path)
    VALUES (new.id, new.text, new.section_path);
END;

CREATE TRIGGER IF NOT EXISTS rag_chunks_ad AFTER DELETE ON rag_chunks BEGIN
    INSERT INTO rag_chunks_fts(rag_chunks_fts, rowid, text, section_path)
    VALUES ('delete', old.id, old.text, old.section_path);
END;

CREATE TRIGGER IF NOT EXISTS rag_chunks_au AFTER UPDATE ON rag_chunks BEGIN
    INSERT INTO rag_chunks_fts(rag_chunks_fts, rowid, text, section_path)
    VALUES ('delete', old.id, old.text, old.section_path);
    INSERT INTO rag_chunks_fts(rowid, text, section_path)
    VALUES (new.id, new.text, new.section_path);
END;
"""
