"""rag_lib domain types."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Manual:
    id: int
    name: str
    source_path: str
    source_hash: str
    page_count: int
    file_size: int
    parser: str
    ingested_at: str
    chunk_count: int


@dataclass(frozen=True)
class Chunk:
    id: int
    manual_id: int
    seq: int
    chunk_type: str
    page: int
    page_end: int | None
    section_path: str | None
    text: str
    text_hash: str
    token_count: int


@dataclass(frozen=True)
class IngestResult:
    manual_id: int
    chunks_created: int
    was_already_ingested: bool


@dataclass(frozen=True)
class SearchResult:
    chunk_id: int
    manual_id: int
    score: float
    chunk: Chunk


@dataclass(frozen=True)
class IngestJob:
    id: str
    status: str           # 'pending' | 'processing' | 'done' | 'error'
    manual_name: str
    manual_id: int | None
    was_duplicate: bool
    error: str | None


# --- Internal pipeline types (not part of public API) ---

@dataclass(frozen=True)
class ProseBlock:
    text: str
    page: int
    fontsize_avg: float


@dataclass(frozen=True)
class TableBlock:
    rows: list[list[str]]
    page: int
    caption: str | None


@dataclass(frozen=True)
class ParsedPage:
    page_num: int
    blocks: list[ProseBlock | TableBlock] = field(default_factory=list)
