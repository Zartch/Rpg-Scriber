"""OpenAIEmbedder — text-embedding-3-small via OpenAI async API."""
from __future__ import annotations

import logging
import os

from openai import AsyncOpenAI, OpenAIError

from rag_lib.embedding.base import Embedder
from rag_lib.errors import EmbeddingError

logger = logging.getLogger(__name__)


class OpenAIEmbedder(Embedder):
    _MODEL = "text-embedding-3-small"
    _DIM = 1536
    _BATCH_SIZE = 2048
    _DIM_BY_MODEL: dict[str, int] = {
        "text-embedding-3-small": 1536,
        "text-embedding-3-large": 3072,
        "text-embedding-ada-002": 1536,
    }

    def __init__(
        self,
        api_key: str | None = None,
        model: str = _MODEL,
    ) -> None:
        self._model_name = model
        self._client = AsyncOpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"))

    @property
    def model(self) -> str:
        return self._model_name

    @property
    def dim(self) -> int:
        return self._DIM_BY_MODEL.get(self._model_name, self._DIM)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        cleaned = [t if t.strip() else " " for t in texts]
        results: list[list[float]] = []
        try:
            for i in range(0, len(cleaned), self._BATCH_SIZE):
                batch = cleaned[i : i + self._BATCH_SIZE]
                response = await self._client.embeddings.create(
                    model=self._model_name,
                    input=batch,
                )
                results.extend(item.embedding for item in response.data)
        except OpenAIError as exc:
            raise EmbeddingError(str(exc)) from exc
        return results
