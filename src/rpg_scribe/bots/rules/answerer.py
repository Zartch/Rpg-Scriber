"""RuleAnswerer: redacta la respuesta con Claude y construye citas deterministas."""

from __future__ import annotations

import logging

from rag_lib.types import Chunk
from rpg_scribe.bots.base import BotResponse
from rpg_scribe.core.events import Citation

logger = logging.getLogger(__name__)

_MAX_TOKENS = 1024


class RuleAnswerer:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        manual_names: dict[int, str],
        language: str = "es",
        client=None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._manual_names = manual_names
        self._language = language
        self._client = client

    def _get_client(self):
        if self._client is None:
            from anthropic import AsyncAnthropic

            self._client = AsyncAnthropic(api_key=self._api_key)
        return self._client

    def _manual_name(self, manual_id: int) -> str:
        return self._manual_names.get(manual_id, f"manual {manual_id}")

    def _build_citations(self, chunks: list[Chunk]) -> list[Citation]:
        seen: set[tuple[int, int]] = set()
        out: list[Citation] = []
        for c in chunks:
            key = (c.manual_id, c.page)
            if key in seen:
                continue
            seen.add(key)
            out.append(
                Citation(
                    manual=self._manual_name(c.manual_id),
                    page=c.page,
                    section_path=c.section_path,
                )
            )
        return out

    def _build_prompt(self, question: str, chunks: list[Chunk]) -> tuple[str, str]:
        system = (
            "Eres un asistente experto en reglas de juegos de rol. Responde "
            "ÚNICAMENTE con la información presente en los fragmentos de manual "
            "proporcionados. Si la respuesta no aparece en los fragmentos, dilo "
            "explícitamente. Cita el manual y la página de forma inline. Sé "
            f"conciso. Responde en este idioma (código ISO): {self._language}."
        )
        blocks = []
        for c in chunks:
            sec = c.section_path or "—"
            blocks.append(
                f"[{self._manual_name(c.manual_id)} · pág. {c.page} · {sec}]\n{c.text}"
            )
        user = (
            f"Pregunta: {question}\n\n"
            "Fragmentos de los manuales:\n\n" + "\n\n---\n\n".join(blocks)
        )
        return system, user

    def _format_sources(self, citations: list[Citation]) -> str:
        lines = ["**Fuentes:**"]
        for c in citations:
            sec = f" — {c.section_path}" if c.section_path else ""
            lines.append(f"- *{c.manual}*, p. {c.page}{sec}")
        return "\n".join(lines)

    def _fallback_text(self, chunks: list[Chunk]) -> str:
        top = chunks[0]
        return (
            f"Según *{self._manual_name(top.manual_id)}*, pág. {top.page}:\n{top.text}"
        )

    async def answer(self, question: str, chunks: list[Chunk]) -> BotResponse:
        citations = self._build_citations(chunks)
        system, user = self._build_prompt(question, chunks)
        try:
            client = self._get_client()
            resp = await client.messages.create(
                model=self._model,
                max_tokens=_MAX_TOKENS,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            text = resp.content[0].text.strip()
        except Exception as exc:
            logger.exception("RuleAnswerer LLM failed, using fallback: %s", exc)
            text = self._fallback_text(chunks)

        written = f"{text}\n\n{self._format_sources(citations)}"
        return BotResponse(spoken=text, written=written, citations=citations)
