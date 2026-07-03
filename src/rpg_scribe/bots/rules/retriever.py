"""RuleRetriever: recuperación híbrida (semántica + FTS5) con follow de página."""

from __future__ import annotations

import asyncio
import logging
import re

import rag_lib
from rag_lib.embedding.base import Embedder
from rag_lib.types import Chunk, SearchResult

logger = logging.getLogger(__name__)

# "pág. 45", "página 45", "p. 45" (case-insensitive); lookbehind prevents
# matching abbreviations like "cap.", "exp.", "comp." that end in a word char.
_PAGE_RE = re.compile(r"(?<!\w)(?:pág(?:ina)?\.?|p\.)\s*(\d+)", re.IGNORECASE)

# Word tokens (unicode-aware: incluye acentos y dígitos).
# (puntuación, '¿', '.', paréntesis) queda fuera y no llega nunca a FTS5.
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

# Palabras vacías ES + verbos genéricos de pregunta ("dime", "explica"): no
# aportan señal y, unidas con AND, dejarían la query FTS sin resultados.
_STOPWORDS_ES = frozenset(
    {
        "a", "al", "algo", "como", "cómo", "con", "cual", "cuál", "de", "del",
        "dime", "dinos", "el", "en", "es", "esa", "ese", "esta", "este",
        "explica", "hay", "la", "las", "le", "les", "lo", "los", "me", "mi",
        "no", "nos", "o", "para", "por", "que", "qué", "se", "su", "sus", "un",
        "una", "unas", "unos", "y",
    }
)


def _to_fts_query(question: str) -> str:
    """Convierte una pregunta en LN en una query FTS5 segura.

    Tokeniza, descarta stopwords y tokens de 1 carácter, cita cada token
    (evita que '.', '?', operadores, etc. se interpreten como sintaxis FTS5)
    y los une con OR (recall: el re-ranking por score y el top_k acotan el
    ruido). Devuelve "" si no queda ningún token de contenido.
    """
    tokens = [
        t
        for t in _TOKEN_RE.findall(question.lower())
        if len(t) > 1 and t not in _STOPWORDS_ES
    ]
    return " OR ".join(f'"{t}"' for t in tokens)


class RuleRetriever:
    """Recupera chunks relevantes para una pregunta de reglas.

    Combina búsqueda semántica y FTS5 (fusión por chunk_id con scores
    normalizados) y aplica un único salto de follow de página: si un chunk
    top referencia "ver pág. N", trae los chunks de esa página del mismo
    manual.
    """

    def __init__(
        self,
        db_path: str,
        manual_ids: list[int],
        *,
        top_k: int = 8,
        sem_weight: float = 0.5,
        embedder: Embedder | None = None,
        debug: bool = False,
    ) -> None:
        self._db_path = db_path
        self._manual_ids = manual_ids
        self._top_k = top_k
        self._sem_weight = sem_weight
        self._embedder = embedder
        self._debug = debug

    async def retrieve(self, question: str) -> list[Chunk]:
        if not self._manual_ids or not question.strip():
            return []

        if self._debug:
            logger.info(
                "RuleRetriever[debug] pregunta=%r manuales=%s",
                question,
                self._manual_ids,
            )

        sem, fts = await asyncio.gather(
            rag_lib.search(
                question,
                self._db_path,
                manual_ids=self._manual_ids,
                k=self._top_k,
                embedder=self._embedder,
            ),
            rag_lib.search_fts(
                _to_fts_query(question),
                self._db_path,
                manual_ids=self._manual_ids,
                k=self._top_k,
            ),
        )
        merged = self._merge(sem, fts)
        return await self._follow_pages(merged)

    def _merge(self, sem: list[SearchResult], fts: list[SearchResult]) -> list[Chunk]:
        """Fusiona por chunk_id sumando scores normalizados ponderados."""
        scores: dict[int, float] = {}
        chunks: dict[int, Chunk] = {}

        def add(results: list[SearchResult], weight: float) -> None:
            if not results:
                return
            top = max(r.score for r in results) or 1.0
            for r in results:
                norm = (r.score / top) * weight
                scores[r.chunk_id] = scores.get(r.chunk_id, 0.0) + norm
                chunks[r.chunk_id] = r.chunk

        add(sem, self._sem_weight)
        add(fts, 1.0 - self._sem_weight)

        ranked = sorted(scores, key=lambda cid: scores[cid], reverse=True)
        top = ranked[: self._top_k]
        if self._debug:
            for cid in top:
                c = chunks[cid]
                logger.info(
                    "RuleRetriever[debug] chunk_id=%s manual_id=%s pág=%s score=%.3f",
                    cid,
                    c.manual_id,
                    c.page,
                    scores[cid],
                )
        return [chunks[cid] for cid in top]

    async def _follow_pages(self, chunks: list[Chunk]) -> list[Chunk]:
        """Un salto: por cada (manual_id, página) referida, añade sus chunks."""
        seen_ids = {c.id for c in chunks}
        refs: set[tuple[int, int]] = set()
        for c in chunks:
            for m in _PAGE_RE.finditer(c.text):
                refs.add((c.manual_id, int(m.group(1))))

        if self._debug and refs:
            logger.info("RuleRetriever[debug] follow páginas: %s", sorted(refs))

        out = list(chunks)
        for manual_id, page in refs:
            extra = await rag_lib.list_chunks_by_page(manual_id, page, self._db_path)
            for ch in extra:
                if ch.id not in seen_ids:
                    seen_ids.add(ch.id)
                    out.append(ch)
        return out
