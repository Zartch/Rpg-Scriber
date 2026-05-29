"""rag_lib embedding subpackage."""
from __future__ import annotations

from rag_lib.embedding.base import Embedder
from rag_lib.embedding.index import VectorIndex
from rag_lib.embedding.openai import OpenAIEmbedder

__all__ = ["Embedder", "OpenAIEmbedder", "VectorIndex"]
