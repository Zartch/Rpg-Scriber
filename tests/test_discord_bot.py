"""Tests for Discord bot commands (/scribe summary, /scribe ask)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from rpg_scribe.core.event_bus import EventBus
from rpg_scribe.core.events import SessionEndRequestEvent, SessionStartRequestEvent
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


# ---------------------------------------------------------------------------
# Event publishing tests — /scribe start and /scribe stop
# ---------------------------------------------------------------------------


class TestScribeStartStopEvents:
    """Verify that /scribe start and /scribe stop publish session events."""

    @pytest.mark.asyncio
    async def test_scribe_start_publishes_session_start_event(self) -> None:
        """After successful connect, SessionStartRequestEvent should be published."""
        bus = EventBus()
        config = ListenerConfig()
        cog = ScribeCog(MagicMock(), bus, config)

        published: list[SessionStartRequestEvent] = []

        async def _capture(event: SessionStartRequestEvent) -> None:
            published.append(event)

        bus.subscribe(SessionStartRequestEvent, _capture)

        interaction = _make_interaction()
        # Simulate user in a voice channel
        member = MagicMock(spec=discord.Member)
        voice_state = MagicMock()
        voice_state.channel = MagicMock(spec=discord.VoiceChannel)
        voice_state.channel.name = "General"
        voice_state.channel.members = [member]
        member.voice = voice_state
        member.display_name = "TestUser"
        member.id = 12345
        member.bot = False
        interaction.user = member

        mock_listener = AsyncMock()
        mock_listener.connect = AsyncMock()
        mock_listener.is_connected = MagicMock(return_value=False)

        with patch(
            "rpg_scribe.discord_bot.commands.DiscordListener",
            return_value=mock_listener,
        ):
            await cog.scribe_start.callback(cog, interaction)

        assert len(published) == 1
        assert published[0].source == "discord"
        assert published[0].session_id is not None

    @pytest.mark.asyncio
    async def test_scribe_stop_publishes_session_end_event(self) -> None:
        """After disconnect, SessionEndRequestEvent should be published."""
        bus = EventBus()
        config = ListenerConfig()
        cog = ScribeCog(MagicMock(), bus, config)

        # Set up an active session
        cog.session_id = "test-session-123"
        mock_listener = AsyncMock()
        mock_listener.is_connected = MagicMock(return_value=True)
        mock_listener.disconnect = AsyncMock()
        cog.listener = mock_listener

        published: list[SessionEndRequestEvent] = []

        async def _capture(event: SessionEndRequestEvent) -> None:
            published.append(event)

        bus.subscribe(SessionEndRequestEvent, _capture)

        interaction = _make_interaction()
        interaction.user.display_name = "TestUser"
        interaction.user.id = 12345

        await cog.scribe_stop.callback(cog, interaction)

        assert len(published) == 1
        assert published[0].session_id == "test-session-123"
        assert published[0].source == "discord"
        # Cog should have cleared session state
        assert cog.session_id is None
        assert cog.listener is None
