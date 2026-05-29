"""OpenAIEmbedder — text-embedding-3-small via OpenAI async API."""
from __future__ import annotations

import logging
import os

import tiktoken
from openai import AsyncOpenAI, OpenAIError

from rag_lib.embedding.base import Embedder
from rag_lib.errors import EmbeddingError

logger = logging.getLogger(__name__)

_ENC = tiktoken.get_encoding("cl100k_base")


class OpenAIEmbedder(Embedder):
    _MODEL = "text-embedding-3-small"
    _DIM = 1536
    _MAX_ITEMS_PER_BATCH = 2048   # OpenAI's hard item limit
    _MAX_TOKENS_PER_BATCH = 250_000  # below the 300k API limit, with headroom
    _MAX_TOKENS_PER_INPUT = 8000  # text-embedding-3-* context window is 8192
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
        # Truncate any input exceeding the model context window (rare for chunks)
        prepared: list[tuple[str, int]] = []
        for t in cleaned:
            toks = _ENC.encode(t)
            if len(toks) > self._MAX_TOKENS_PER_INPUT:
                t = _ENC.decode(toks[: self._MAX_TOKENS_PER_INPUT])
                n = self._MAX_TOKENS_PER_INPUT
            else:
                n = len(toks)
            prepared.append((t, n))

        results: list[list[float]] = []
        try:
            for batch in self._iter_batches(prepared):
                response = await self._client.embeddings.create(
                    model=self._model_name,
                    input=batch,
                )
                results.extend(item.embedding for item in response.data)
        except OpenAIError as exc:
            raise EmbeddingError(str(exc)) from exc
        return results

    def _iter_batches(self, prepared: list[tuple[str, int]]):
        """Yield string batches sized by both item count and total tokens."""
        batch: list[str] = []
        batch_tokens = 0
        for text, n in prepared:
            if batch and (
                len(batch) >= self._MAX_ITEMS_PER_BATCH
                or batch_tokens + n > self._MAX_TOKENS_PER_BATCH
            ):
                yield batch
                batch = []
                batch_tokens = 0
            batch.append(text)
            batch_tokens += n
        if batch:
            yield batch
