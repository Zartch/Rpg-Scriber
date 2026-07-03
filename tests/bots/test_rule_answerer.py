"""Tests de RuleAnswerer: prompt, citas deterministas, fallback."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock


from rag_lib.types import Chunk
from rpg_scribe.bots.base import BotResponse
from rpg_scribe.bots.rules.answerer import RuleAnswerer


def _chunk(cid, manual_id, page, section, text) -> Chunk:
    return Chunk(
        id=cid,
        manual_id=manual_id,
        seq=cid,
        chunk_type="prose",
        page=page,
        page_end=None,
        section_path=section,
        text=text,
        text_hash=f"h{cid}",
        token_count=10,
    )


def _mock_anthropic_response(text: str):
    block = MagicMock()
    block.text = text
    resp = MagicMock()
    resp.content = [block]
    return resp


def _answerer(client=None) -> RuleAnswerer:
    return RuleAnswerer(
        api_key="sk-test",
        model="claude-sonnet-5",
        manual_names={1: "Cyberpunk RED"},
        language="es",
        client=client,
    )


CHUNKS = [
    _chunk(1, 1, 45, "Netrunning", "El hackeo requiere una tirada de Interface."),
    _chunk(2, 1, 45, "Netrunning", "La dificultad la fija el GM."),
    _chunk(3, 1, 46, "Netrunning / NET", "Cada NET architecture tiene niveles."),
]


def test_build_prompt_includes_chunk_text_and_page():
    answerer = _answerer()
    system, user = answerer._build_prompt("¿Cómo se hackea?", CHUNKS)
    assert "es" in system
    assert "El hackeo requiere una tirada de Interface." in user
    assert "pág. 45" in user
    assert "Cyberpunk RED" in user


def test_build_citations_dedupes_by_manual_and_page():
    answerer = _answerer()
    cits = answerer._build_citations(CHUNKS)
    # (1,45) y (1,46) → 2 citas; el segundo chunk (1,45) se deduplica.
    assert len(cits) == 2
    assert cits[0].manual == "Cyberpunk RED"
    assert {c.page for c in cits} == {45, 46}


async def test_answer_returns_bot_response_with_sources():
    client = MagicMock()
    client.messages.create = AsyncMock(
        return_value=_mock_anthropic_response("Se hackea con una tirada de Interface.")
    )
    answerer = _answerer(client=client)
    resp = await answerer.answer("¿Cómo se hackea?", CHUNKS)

    assert isinstance(resp, BotResponse)
    assert resp.spoken == "Se hackea con una tirada de Interface."
    assert "**Fuentes:**" in resp.written
    assert "Cyberpunk RED" in resp.written
    assert len(resp.citations) == 2


async def test_answer_falls_back_when_llm_fails():
    client = MagicMock()
    client.messages.create = AsyncMock(side_effect=RuntimeError("API down"))
    answerer = _answerer(client=client)
    resp = await answerer.answer("¿Cómo se hackea?", CHUNKS)

    # Degradación: usa el chunk top en bruto + cita determinista.
    assert "El hackeo requiere una tirada de Interface." in resp.spoken
    assert resp.citations  # citas siguen presentes
