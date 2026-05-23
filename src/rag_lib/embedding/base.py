"""Embedder ABC — interface for all embedding implementations."""
from __future__ import annotations

from abc import ABC, abstractmethod


class Embedder(ABC):
    @property
    @abstractmethod
    def model(self) -> str:
        """Model identifier stored in rag_embeddings.model."""

    @property
    @abstractmethod
    def dim(self) -> int:
        """Vector dimension."""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per text. Raises EmbeddingError on failure."""
