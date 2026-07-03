"""RulesBot: bot de reglas activado por voz que consulta los manuales RAG."""

from __future__ import annotations

import logging
from typing import ClassVar

import rag_lib
from rpg_scribe.bots.base import BaseBot, BotResponse, BotServices
from rpg_scribe.bots.rules.answerer import RuleAnswerer
from rpg_scribe.bots.rules.retriever import RuleRetriever

logger = logging.getLogger(__name__)

_NOT_CONFIGURED = "El bot de reglas no está configurado para esta campaña."
_NOT_FOUND = "No encontré esa regla en los manuales."


class RulesBot(BaseBot):
    keyword: ClassVar[str] = "bot reglas"
    name: ClassVar[str] = "Bot de Reglas"

    def __init__(self) -> None:
        self._enabled = False
        self._debug = False
        self._retriever: RuleRetriever | None = None
        self._answerer: RuleAnswerer | None = None

    async def setup(self, services: BotServices) -> None:
        rag = services.rag
        if rag is None or not rag.manuals:
            logger.info("RulesBot: sin [campaign.rag] o sin manuales → deshabilitado")
            return

        # Permite override de keyword desde el TOML antes de que el watcher
        # construya su tabla de keywords.
        if rag.keyword:
            self.keyword = rag.keyword

        try:
            manuals = await rag_lib.list_manuals(services.rag_db_path)
        except Exception as exc:
            logger.error("RulesBot: no se pudo abrir rag.db (%s) → deshabilitado", exc)
            return

        name_to_id = {m.name: m.id for m in manuals}
        manual_ids = [name_to_id[n] for n in rag.manuals if n in name_to_id]
        missing = [n for n in rag.manuals if n not in name_to_id]
        if missing:
            logger.warning("RulesBot: manuales no encontrados en rag.db: %s", missing)
        if not manual_ids:
            logger.info("RulesBot: ningún manual configurado existe → deshabilitado")
            return

        manual_names = {mid: name for name, mid in name_to_id.items()}
        language = services.campaign.language if services.campaign else "es"

        self._debug = rag.debug
        self._retriever = RuleRetriever(
            services.rag_db_path, manual_ids, top_k=rag.top_k, debug=self._debug
        )
        self._answerer = RuleAnswerer(
            api_key=services.anthropic_api_key,
            model=services.summarizer_model,
            manual_names=manual_names,
            language=language,
        )
        self._enabled = True
        logger.info(
            "RulesBot habilitado: keyword=%r, manuales=%s", self.keyword, manual_ids
        )

    async def handle(
        self,
        command: str,
        *,
        session_id: str,
        speaker_id: str,
        speaker_name: str,
    ) -> str | BotResponse:
        if not self._enabled or self._retriever is None or self._answerer is None:
            return _NOT_CONFIGURED

        logger.info("RulesBot disparado por %s: %r", speaker_name, command)

        chunks = await self._retriever.retrieve(command)
        if not chunks:
            if self._debug:
                logger.info("RulesBot[debug] sin resultados para %r", command)
            return BotResponse(spoken=_NOT_FOUND)

        response = await self._answerer.answer(command, chunks)
        if self._debug:
            cites = [f"{c.manual} p.{c.page}" for c in (response.citations or [])]
            logger.info(
                "RulesBot[debug] respuesta=%r | fuentes=%s",
                response.spoken[:200],
                cites,
            )
        return response
