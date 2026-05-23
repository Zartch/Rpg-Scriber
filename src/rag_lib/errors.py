"""rag_lib exceptions."""
from __future__ import annotations


class IngestError(Exception):
    """Base class for rag_lib ingestion errors."""


class PdfParseError(IngestError):
    """pdfplumber failed to open or parse the PDF."""


class ManualNotFound(Exception):
    """manual_id does not exist in the database."""
