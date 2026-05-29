"""rag_lib custom exceptions."""
from __future__ import annotations


class IngestError(Exception):
    """Base class for ingestion errors."""


class PdfParseError(IngestError):
    """Raised when the PDF cannot be parsed."""


class ManualNotFound(Exception):
    """Raised when a manual_id does not exist in the database."""


class EmbeddingError(Exception):
    """Raised when embedding generation fails (API error, network, quota)."""
