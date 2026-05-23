"""Abstract base class for PDF parsers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from rag_lib.types import ParsedPage


class PdfParser(ABC):
    """Interface for PDF parsers. Implementations must be sync (called via asyncio.to_thread)."""

    @abstractmethod
    def parse(self, pdf_path: str | Path) -> list[ParsedPage]:
        """Parse a PDF file and return one ParsedPage per page.

        Raises:
            PdfParseError: if the file cannot be opened or parsed.
        """
