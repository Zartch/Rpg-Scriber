"""Tests for Discord bot commands (/scribe summary, /scribe ask)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from rpg_scribe.core.event_bus import EventBus
from rpg_scribe.core.models import ListenerConfig
from rpg_scribe.discord_bot.commands import (
    AnswerQuestionModal,
    ScribeCog,
    _EMBED_DESC_LIMIT,
    _TRUNCATION_SUFFIX,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_interaction() -> MagicMock:
    """Create a mock discord.Interaction with response helpers."""
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.send_modal = AsyncMock()
    interaction.followup = AsyncMock()
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.voice = None
    return interaction


def _make_cog(
    database: AsyncMock | None = None,
    session_id: str | None = None,
) -> ScribeCog:
    """Create a ScribeCog with mocked dependencies."""
    bot = MagicMock()
    bus = EventBus()
    config = ListenerConfig()
    cog = ScribeCog(bot, bus, config, database=database)
    cog.session_id = session_id
    return cog


# ---------------------------------------------------------------------------
# /scribe summary tests
# ---------------------------------------------------------------------------


class TestScribeSummary:
    @pytest.mark.asyncio
    async def test_summary_no_active_session(self) -> None:
        cog = _make_cog(session_id=None)
        interaction = _make_interaction()

        await cog.scribe_summary.callback(cog, interaction)

        interaction.response.send_message.assert_called_once()
        args, kwargs = interaction.response.send_message.call_args
        assert "No hay sesión activa" in args[0]
        assert kwargs["ephemeral"] is True

    @pytest.mark.asyncio
    async def test_summary_no_database(self) -> None:
        cog = _make_cog(database=None, session_id="session-1")
        interaction = _make_interaction()

        await cog.scribe_summary.callback(cog, interaction)

        interaction.response.send_message.assert_called_once()
        args, kwargs = interaction.response.send_message.call_args
        assert "Base de datos no disponible" in args[0]

    @pytest.mark.asyncio
    async def test_summary_no_summary_yet(self) -> None:
        db = AsyncMock()
        db.get_session = AsyncMock(return_value={"session_summary": ""})
        cog = _make_cog(database=db, session_id="session-1")
        interaction = _make_interaction()

        await cog.scribe_summary.callback(cog, interaction)

        interaction.response.send_message.assert_called_once()
        args, kwargs = interaction.response.send_message.call_args
        assert "no hay resumen disponible" in args[0]

    @pytest.mark.asyncio
    async def test_summary_returns_embed(self) -> None:
        db = AsyncMock()
        db.get_session = AsyncMock(
            return_value={"session_summary": "El grupo exploró la cueva."}
        )
        cog = _make_cog(database=db, session_id="session-1")
        interaction = _make_interaction()

        await cog.scribe_summary.callback(cog, interaction)

        interaction.response.send_message.assert_called_once()
        kwargs = interaction.response.send_message.call_args.kwargs
        embed = kwargs["embed"]
        assert isinstance(embed, discord.Embed)
        assert "El grupo exploró la cueva." in embed.description
        assert kwargs["ephemeral"] is True

    @pytest.mark.asyncio
    async def test_summary_truncates_long_text(self) -> None:
        long_text = "A" * 5000
        db = AsyncMock()
        db.get_session = AsyncMock(
            return_value={"session_summary": long_text}
        )
        cog = _make_cog(database=db, session_id="session-1")
        interaction = _make_interaction()

        await cog.scribe_summary.callback(cog, interaction)

        kwargs = interaction.response.send_message.call_args.kwargs
        embed = kwargs["embed"]
        assert len(embed.description) <= _EMBED_DESC_LIMIT
        assert embed.description.endswith(_TRUNCATION_SUFFIX)

    @pytest.mark.asyncio
    async def test_summary_session_not_found(self) -> None:
        db = AsyncMock()
        db.get_session = AsyncMock(return_value=None)
        cog = _make_cog(database=db, session_id="session-1")
        interaction = _make_interaction()

        await cog.scribe_summary.callback(cog, interaction)

        interaction.response.send_message.assert_called_once()
        args, _ = interaction.response.send_message.call_args
        assert "no hay resumen disponible" in args[0]


# ---------------------------------------------------------------------------
# /scribe ask tests
# ---------------------------------------------------------------------------


class TestScribeAsk:
    @pytest.mark.asyncio
    async def test_ask_no_active_session(self) -> None:
        cog = _make_cog(session_id=None)
        interaction = _make_interaction()

        await cog.scribe_ask.callback(cog, interaction)

        interaction.response.send_message.assert_called_once()
        args, kwargs = interaction.response.send_message.call_args
        assert "No hay sesión activa" in args[0]

    @pytest.mark.asyncio
    async def test_ask_no_database(self) -> None:
        cog = _make_cog(database=None, session_id="session-1")
        interaction = _make_interaction()

        await cog.scribe_ask.callback(cog, interaction)

        interaction.response.send_message.assert_called_once()
        args, _ = interaction.response.send_message.call_args
        assert "Base de datos no disponible" in args[0]

    @pytest.mark.asyncio
    async def test_ask_no_pending_questions(self) -> None:
        db = AsyncMock()
        db.get_pending_questions = AsyncMock(return_value=[])
        cog = _make_cog(database=db, session_id="session-1")
        interaction = _make_interaction()

        await cog.scribe_ask.callback(cog, interaction)

        interaction.response.send_message.assert_called_once()
        args, _ = interaction.response.send_message.call_args
        assert "No hay preguntas pendientes" in args[0]

    @pytest.mark.asyncio
    async def test_ask_shows_modal_with_question(self) -> None:
        db = AsyncMock()
        db.get_pending_questions = AsyncMock(
            return_value=[
                {"id": 42, "question": "¿Quién habla ahora?", "status": "pending"}
            ]
        )
        cog = _make_cog(database=db, session_id="session-1")
        interaction = _make_interaction()

        await cog.scribe_ask.callback(cog, interaction)

        interaction.response.send_modal.assert_called_once()
        modal = interaction.response.send_modal.call_args.args[0]
        assert isinstance(modal, AnswerQuestionModal)
        assert modal.question_id == 42

    @pytest.mark.asyncio
    async def test_ask_truncates_long_question_label(self) -> None:
        long_question = "A" * 60
        db = AsyncMock()
        db.get_pending_questions = AsyncMock(
            return_value=[
                {"id": 1, "question": long_question, "status": "pending"}
            ]
        )
        cog = _make_cog(database=db, session_id="session-1")
        interaction = _make_interaction()

        await cog.scribe_ask.callback(cog, interaction)

        modal = interaction.response.send_modal.call_args.args[0]
        assert len(modal.answer.label) <= 45


# ---------------------------------------------------------------------------
# AnswerQuestionModal tests
# ---------------------------------------------------------------------------


class TestAnswerQuestionModal:
    @pytest.mark.asyncio
    async def test_on_submit_saves_answer(self) -> None:
        db = AsyncMock()
        db.answer_question = AsyncMock()
        modal = AnswerQuestionModal(
            question_id=42,
            question_text="¿Es un PNJ?",
            database=db,
        )
        modal.answer._value = "Sí, es el tabernero."

        interaction = _make_interaction()
        await modal.on_submit(interaction)

        db.answer_question.assert_called_once_with(42, "Sí, es el tabernero.")
        interaction.response.send_message.assert_called_once()
        args, kwargs = interaction.response.send_message.call_args
        assert "Respuesta guardada" in args[0]
        assert kwargs["ephemeral"] is True
