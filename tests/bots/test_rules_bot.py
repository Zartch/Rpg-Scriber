"""Tests de RulesBot: orquestación retriever → answerer, y casos de borde."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

from rag_lib.types import Chunk
from rpg_scribe.bots.base import BotResponse
from rpg_scribe.bots.rules.bot import RulesBot
from rpg_scribe.core.events import Citation


def _chunk() -> Chunk:
    return Chunk(
        id=1,
        manual_id=1,
        seq=0,
        chunk_type="prose",
        page=45,
        page_end=None,
        section_path="Netrunning",
        text="El hackeo requiere una tirada de Interface.",
        text_hash="h",
        token_count=10,
    )


def _wired_bot() -> RulesBot:
    """Bot con retriever/answerer mockeados (simula un setup() exitoso)."""
    bot = RulesBot()
    bot._enabled = True
    bot._retriever = MagicMock()
    bot._answerer = MagicMock()
    return bot


async def test_handle_disabled_returns_notice():
    bot = RulesBot()  # sin setup → deshabilitado
    out = await bot.handle(
        "¿cómo se hackea?", session_id="s", speaker_id="u", speaker_name="A"
    )
    assert "no" in out.lower()  # mensaje de no-configurado


async def test_handle_no_results_returns_not_found():
    bot = _wired_bot()
    bot._retriever.retrieve = AsyncMock(return_value=[])
    out = await bot.handle(
        "¿cómo se hackea?", session_id="s", speaker_id="u", speaker_name="A"
    )
    assert isinstance(out, BotResponse)
    assert "no encontré" in out.spoken.lower()


async def test_handle_orchestrates_retriever_and_answerer():
    bot = _wired_bot()
    bot._retriever.retrieve = AsyncMock(return_value=[_chunk()])
    expected = BotResponse(
        spoken="respuesta", written="respuesta\n\n**Fuentes:**\n- *X*, p. 45"
    )
    bot._answerer.answer = AsyncMock(return_value=expected)

    out = await bot.handle(
        "¿cómo se hackea?", session_id="s", speaker_id="u", speaker_name="A"
    )

    assert out is expected
    bot._retriever.retrieve.assert_awaited_once_with("¿cómo se hackea?")
    bot._answerer.answer.assert_awaited_once()


async def test_handle_logs_trigger(caplog):
    bot = _wired_bot()
    bot._retriever.retrieve = AsyncMock(return_value=[])
    with caplog.at_level(logging.INFO):
        await bot.handle("¿algo?", session_id="s", speaker_id="u", speaker_name="Alice")
    assert any("disparado" in r.getMessage() for r in caplog.records)


async def test_handle_debug_log_gated(caplog):
    chunk = _chunk()
    resp = BotResponse(
        spoken="respuesta",
        written="w",
        citations=[Citation(manual="M", page=45)],
    )

    # debug OFF → no [debug] respuesta line
    bot = _wired_bot()
    bot._retriever.retrieve = AsyncMock(return_value=[chunk])
    bot._answerer.answer = AsyncMock(return_value=resp)
    with caplog.at_level(logging.INFO):
        await bot.handle("q", session_id="s", speaker_id="u", speaker_name="A")
    assert not any("[debug] respuesta" in r.getMessage() for r in caplog.records)

    # debug ON → emits the [debug] respuesta line
    caplog.clear()
    bot2 = _wired_bot()
    bot2._debug = True
    bot2._retriever.retrieve = AsyncMock(return_value=[chunk])
    bot2._answerer.answer = AsyncMock(return_value=resp)
    with caplog.at_level(logging.INFO):
        await bot2.handle("q", session_id="s", speaker_id="u", speaker_name="A")
    assert any("[debug] respuesta" in r.getMessage() for r in caplog.records)
