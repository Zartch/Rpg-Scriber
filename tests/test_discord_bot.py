"""Tests for Discord bot commands (/scribe summary, /scribe ask)."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from rpg_scribe.core.event_bus import EventBus
from rpg_scribe.core.events import (
    ListenerRecoverRequestEvent,
    SessionEndRequestEvent,
    SessionStartRequestEvent,
)
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


async def _drain_loop() -> None:
    await asyncio.sleep(0)
    await asyncio.sleep(0)


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
        db = MagicMock()
        db.sessions.get_session = AsyncMock(return_value={"session_summary": ""})
        cog = _make_cog(database=db, session_id="session-1")
        interaction = _make_interaction()

        await cog.scribe_summary.callback(cog, interaction)

        interaction.response.send_message.assert_called_once()
        args, kwargs = interaction.response.send_message.call_args
        assert "no hay resumen disponible" in args[0]

    @pytest.mark.asyncio
    async def test_summary_returns_embed(self) -> None:
        db = MagicMock()
        db.sessions.get_session = AsyncMock(
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
        db = MagicMock()
        db.sessions.get_session = AsyncMock(
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
        db = MagicMock()
        db.sessions.get_session = AsyncMock(return_value=None)
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
        db = MagicMock()
        db.entities.get_pending_questions = AsyncMock(return_value=[])
        cog = _make_cog(database=db, session_id="session-1")
        interaction = _make_interaction()

        await cog.scribe_ask.callback(cog, interaction)

        interaction.response.send_message.assert_called_once()
        args, _ = interaction.response.send_message.call_args
        assert "No hay preguntas pendientes" in args[0]

    @pytest.mark.asyncio
    async def test_ask_shows_modal_with_question(self) -> None:
        db = MagicMock()
        db.entities.get_pending_questions = AsyncMock(
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
        db = MagicMock()
        db.entities.get_pending_questions = AsyncMock(
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
        db = MagicMock()
        db.entities.answer_question = AsyncMock()
        modal = AnswerQuestionModal(
            question_id=42,
            question_text="¿Es un PNJ?",
            database=db,
        )
        modal.answer._value = "Sí, es el tabernero."

        interaction = _make_interaction()
        await modal.on_submit(interaction)

        db.entities.answer_question.assert_called_once_with(42, "Sí, es el tabernero.")
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

    @pytest.mark.asyncio
    async def test_recovery_request_reconnects_listener_without_rotating_session(self) -> None:
        bus = EventBus()
        config = ListenerConfig()
        bot = MagicMock()
        bot.user = MagicMock()
        bot.user.id = 999
        cog = ScribeCog(bot, bus, config)
        cog.session_id = "test-session-123"

        voice_channel = MagicMock(spec=discord.VoiceChannel)
        voice_channel.name = "General"

        old_listener = AsyncMock()
        old_listener.is_connected = MagicMock(return_value=True)
        old_listener.disconnect = AsyncMock()
        old_listener._voice_client = MagicMock()
        old_listener._voice_client.channel = voice_channel
        cog.listener = old_listener
        cog._voice_channel = voice_channel

        new_listener = AsyncMock()
        new_listener.connect = AsyncMock()
        new_listener.is_connected = MagicMock(return_value=True)

        published: list[SessionEndRequestEvent] = []

        async def _capture(event: SessionEndRequestEvent) -> None:
            published.append(event)

        bus.subscribe(SessionEndRequestEvent, _capture)

        with patch(
            "rpg_scribe.discord_bot.commands.DiscordListener",
            return_value=new_listener,
        ):
            await bus.publish(
                ListenerRecoverRequestEvent(
                    session_id="test-session-123",
                    reason="transcriber_stall",
                )
            )
            await _drain_loop()

        old_listener.disconnect.assert_awaited_once()
        new_listener.connect.assert_awaited_once_with(
            session_id="test-session-123",
            voice_channel=voice_channel,
        )
        assert cog.listener is new_listener
        assert cog.session_id == "test-session-123"
        assert published == []

    @pytest.mark.asyncio
    async def test_voice_state_cleanup_is_suppressed_during_managed_recovery(self) -> None:
        bus = EventBus()
        config = ListenerConfig()
        bot = MagicMock()
        bot.user = MagicMock()
        bot.user.id = 999
        cog = ScribeCog(bot, bus, config)
        cog.session_id = "test-session-123"
        cog.listener = AsyncMock()
        cog._listener_recovery_in_progress = True

        published: list[SessionEndRequestEvent] = []

        async def _capture(event: SessionEndRequestEvent) -> None:
            published.append(event)

        bus.subscribe(SessionEndRequestEvent, _capture)

        member = MagicMock(spec=discord.Member)
        member.id = 999
        before = MagicMock(spec=discord.VoiceState)
        before.channel = MagicMock(spec=discord.VoiceChannel)
        after = MagicMock(spec=discord.VoiceState)
        after.channel = None

        await cog.on_voice_state_update(member, before, after)

        assert published == []
        assert cog.session_id == "test-session-123"
        assert cog.listener is not None

    @pytest.mark.asyncio
    async def test_scribe_stop_allows_degraded_listener_if_session_is_active(self) -> None:
        bus = EventBus()
        config = ListenerConfig()
        cog = ScribeCog(MagicMock(), bus, config)
        cog.session_id = "test-session-123"
        cog._voice_channel = MagicMock(spec=discord.VoiceChannel)

        mock_listener = AsyncMock()
        mock_listener.is_connected = MagicMock(return_value=False)
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

        mock_listener.disconnect.assert_awaited_once()
        assert len(published) == 1
        assert published[0].session_id == "test-session-123"
        assert cog.session_id is None
        assert cog.listener is None


# ---------------------------------------------------------------------------
# Listener recovery: retries, backoff, gateway wait
# ---------------------------------------------------------------------------


def _make_recovery_cog(gateway_open: bool = True) -> tuple[ScribeCog, MagicMock]:
    bot = MagicMock()
    bot.user = MagicMock()
    bot.user.id = 999
    bot.ws = MagicMock()
    bot.ws.open = gateway_open
    cog = ScribeCog(bot, EventBus(), ListenerConfig())
    cog.session_id = "sess-1"

    voice_channel = MagicMock(spec=discord.VoiceChannel)
    voice_channel.name = "rol"
    voice_channel.guild = MagicMock()
    voice_channel.guild.voice_client = None

    old_listener = AsyncMock()
    old_listener.is_connected = MagicMock(return_value=False)
    old_listener._voice_client = None
    cog.listener = old_listener
    cog._voice_channel = voice_channel
    return cog, voice_channel


def _ok_listener() -> AsyncMock:
    listener = AsyncMock()
    listener.is_connected = MagicMock(return_value=True)
    return listener


def _failing_listener() -> AsyncMock:
    listener = AsyncMock()
    listener.connect = AsyncMock(side_effect=ConnectionResetError("closing transport"))
    listener.is_connected = MagicMock(return_value=False)
    return listener


@pytest.fixture
def fast_recovery(monkeypatch: pytest.MonkeyPatch) -> None:
    import rpg_scribe.discord_bot.commands as cmds

    monkeypatch.setattr(cmds, "_LISTENER_RECOVERY_BACKOFF_S", (0.0,))
    monkeypatch.setattr(cmds, "_LISTENER_RECOVERY_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(cmds, "_GATEWAY_WAIT_POLL_S", 0.0)
    monkeypatch.setattr(cmds, "_GATEWAY_WAIT_TIMEOUT_S", 0.05)
    monkeypatch.setattr(cmds, "_SILENT_DROP_GRACE_S", 0.0)


class TestListenerRecoveryRetries:
    @pytest.mark.asyncio
    async def test_retries_after_failed_attempt_and_succeeds(self, fast_recovery: None) -> None:
        cog, voice_channel = _make_recovery_cog()
        good = _ok_listener()
        with patch(
            "rpg_scribe.discord_bot.commands.DiscordListener",
            side_effect=[_failing_listener(), good],
        ):
            await cog._recover_listener("sess-1", reason="test")

        good.connect.assert_awaited_once_with(session_id="sess-1", voice_channel=voice_channel)
        assert cog.listener is good
        assert cog.session_id == "sess-1"
        assert cog._listener_recovery_in_progress is False

    @pytest.mark.asyncio
    async def test_exhausted_retries_end_session_cleanly(self, fast_recovery: None) -> None:
        cog, _ = _make_recovery_cog()
        ended: list[SessionEndRequestEvent] = []

        async def _capture(event: SessionEndRequestEvent) -> None:
            ended.append(event)

        cog.event_bus.subscribe(SessionEndRequestEvent, _capture)
        with patch(
            "rpg_scribe.discord_bot.commands.DiscordListener",
            side_effect=lambda *a, **k: _failing_listener(),
        ) as factory:
            await cog._recover_listener("sess-1", reason="test")

        assert factory.call_count == 3
        assert [e.session_id for e in ended] == ["sess-1"]
        assert cog.session_id is None
        assert cog.listener is None
        assert cog._listener_recovery_in_progress is False

    @pytest.mark.asyncio
    async def test_waits_for_gateway_before_connecting(
        self, fast_recovery: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import rpg_scribe.discord_bot.commands as cmds

        monkeypatch.setattr(cmds, "_GATEWAY_WAIT_TIMEOUT_S", 5.0)
        cog, _ = _make_recovery_cog(gateway_open=False)
        good = _ok_listener()

        async def _gateway_comes_back() -> None:
            await asyncio.sleep(0.01)
            cog.bot.ws.open = True

        restorer = asyncio.create_task(_gateway_comes_back())
        with patch("rpg_scribe.discord_bot.commands.DiscordListener", return_value=good):
            await cog._recover_listener("sess-1", reason="test")
        await restorer

        good.connect.assert_awaited_once()
        assert cog.listener is good

    @pytest.mark.asyncio
    async def test_gateway_down_counts_as_failed_attempt(self, fast_recovery: None) -> None:
        cog, _ = _make_recovery_cog(gateway_open=False)
        with patch("rpg_scribe.discord_bot.commands.DiscordListener") as factory:
            await cog._recover_listener("sess-1", reason="test")

        factory.assert_not_called()
        assert cog.session_id is None

    @pytest.mark.asyncio
    async def test_stop_during_recovery_aborts_retries(self, fast_recovery: None) -> None:
        cog, _ = _make_recovery_cog()
        ended: list[SessionEndRequestEvent] = []

        async def _capture(event: SessionEndRequestEvent) -> None:
            ended.append(event)

        cog.event_bus.subscribe(SessionEndRequestEvent, _capture)

        def _fail_and_stop(*_a: object, **_k: object) -> AsyncMock:
            cog.session_id = None  # user ran /scribe stop meanwhile
            return _failing_listener()

        with patch(
            "rpg_scribe.discord_bot.commands.DiscordListener", side_effect=_fail_and_stop
        ) as factory:
            await cog._recover_listener("sess-1", reason="test")

        assert factory.call_count == 1
        assert ended == []

    @pytest.mark.asyncio
    async def test_dead_listener_bypasses_long_cooldown(self, fast_recovery: None) -> None:
        cog, _ = _make_recovery_cog()
        cog._last_listener_recovery_ts = time.monotonic()  # a recovery just ran
        good = _ok_listener()
        with patch("rpg_scribe.discord_bot.commands.DiscordListener", return_value=good):
            await cog.event_bus.publish(
                ListenerRecoverRequestEvent(session_id="sess-1", reason="voice_silent_drop")
            )
            # Short dead-listener cooldown still applies right after a recovery
            assert cog._recovery_task is None

            cog._last_listener_recovery_ts = time.monotonic() - 3600
            await cog.event_bus.publish(
                ListenerRecoverRequestEvent(session_id="sess-1", reason="voice_silent_drop")
            )
            assert cog._recovery_task is not None
            await cog._recovery_task

        assert cog.listener is good

    @pytest.mark.asyncio
    async def test_gateway_resume_triggers_recovery_of_dead_listener(
        self, fast_recovery: None
    ) -> None:
        cog, _ = _make_recovery_cog()
        good = _ok_listener()
        with patch("rpg_scribe.discord_bot.commands.DiscordListener", return_value=good):
            await cog.on_resumed()
            assert cog._recovery_task is not None
            await cog._recovery_task

        assert cog.listener is good

    @pytest.mark.asyncio
    async def test_gateway_resume_ignores_healthy_listener(self) -> None:
        cog, _ = _make_recovery_cog()
        cog.listener.is_connected = MagicMock(return_value=True)

        await cog.on_resumed()

        assert cog._recovery_task is None


# ---------------------------------------------------------------------------
# Manual kick vs. unexpected voice leave
# ---------------------------------------------------------------------------


def _audit_entry(entry_id: int, count: int) -> MagicMock:
    entry = MagicMock()
    entry.id = entry_id
    entry.extra = MagicMock()
    entry.extra.count = count
    return entry


def _audit_logs_returning(*snapshots: list[MagicMock]) -> MagicMock:
    """guild.audit_logs mock: each call yields the next snapshot (last repeats)."""
    calls = {"n": 0}

    def _audit_logs(**_kwargs: object):  # noqa: ANN202
        idx = min(calls["n"], len(snapshots) - 1)
        calls["n"] += 1

        async def _gen():  # noqa: ANN202
            for entry in snapshots[idx]:
                yield entry

        return _gen()

    return MagicMock(side_effect=_audit_logs)


def _bot_leave_event(cog: ScribeCog, channel: MagicMock) -> tuple:
    member = MagicMock(spec=discord.Member)
    member.id = cog.bot.user.id
    before = MagicMock(spec=discord.VoiceState)
    before.channel = channel
    after = MagicMock(spec=discord.VoiceState)
    after.channel = None
    return member, before, after


@pytest.fixture
def fast_kick_check(monkeypatch: pytest.MonkeyPatch) -> None:
    import rpg_scribe.discord_bot.commands as cmds

    monkeypatch.setattr(cmds, "_MANUAL_KICK_AUDIT_WAIT_S", 0.05)
    monkeypatch.setattr(cmds, "_MANUAL_KICK_AUDIT_POLL_S", 0.0)
    monkeypatch.setattr(cmds, "_SILENT_DROP_GRACE_S", 0.2)


class TestManualKick:
    @pytest.mark.asyncio
    async def test_manual_kick_ends_session_without_reconnecting(
        self, fast_recovery: None, fast_kick_check: None
    ) -> None:
        cog, channel = _make_recovery_cog()
        cog.listener.is_connected = MagicMock(return_value=True)
        cog._audit_disconnect_baseline = {1: 1}
        # Same moderator again → Discord bumps the count of the existing entry
        channel.guild.audit_logs = _audit_logs_returning([_audit_entry(1, 2)])
        ended: list[SessionEndRequestEvent] = []

        async def _capture(event: SessionEndRequestEvent) -> None:
            ended.append(event)

        cog.event_bus.subscribe(SessionEndRequestEvent, _capture)
        with patch("rpg_scribe.discord_bot.commands.DiscordListener") as factory:
            await cog.on_voice_state_update(*_bot_leave_event(cog, channel))
            await cog._voice_leave_task

        factory.assert_not_called()
        assert [e.session_id for e in ended] == ["sess-1"]
        assert cog.session_id is None
        assert cog.listener is None

    @pytest.mark.asyncio
    async def test_manual_kick_cancels_silent_drop_recovery(
        self, fast_recovery: None, fast_kick_check: None
    ) -> None:
        cog, channel = _make_recovery_cog()
        cog._audit_disconnect_baseline = {}
        channel.guild.audit_logs = _audit_logs_returning([_audit_entry(7, 1)])
        ended: list[SessionEndRequestEvent] = []

        async def _capture(event: SessionEndRequestEvent) -> None:
            ended.append(event)

        cog.event_bus.subscribe(SessionEndRequestEvent, _capture)
        with patch("rpg_scribe.discord_bot.commands.DiscordListener") as factory:
            # Flush loop notices the drop first and asks for recovery...
            await cog.event_bus.publish(
                ListenerRecoverRequestEvent(session_id="sess-1", reason="voice_silent_drop")
            )
            recovery = cog._recovery_task
            assert recovery is not None
            # ...then the gateway reports the leave and the audit log shows a kick
            await cog.on_voice_state_update(*_bot_leave_event(cog, channel))
            await cog._voice_leave_task
            with pytest.raises(asyncio.CancelledError):
                await recovery

        factory.assert_not_called()
        assert [e.session_id for e in ended] == ["sess-1"]
        assert cog.session_id is None

    @pytest.mark.asyncio
    async def test_unexpected_leave_without_audit_entry_recovers(
        self, fast_recovery: None, fast_kick_check: None
    ) -> None:
        cog, channel = _make_recovery_cog()
        cog.listener.is_connected = MagicMock(return_value=True)
        cog._audit_disconnect_baseline = {1: 1}
        channel.guild.audit_logs = _audit_logs_returning([_audit_entry(1, 1)])
        good = _ok_listener()
        with patch("rpg_scribe.discord_bot.commands.DiscordListener", return_value=good):
            await cog.on_voice_state_update(*_bot_leave_event(cog, channel))
            await cog._voice_leave_task
            assert cog._recovery_task is not None
            await cog._recovery_task

        assert cog.listener is good
        assert cog.session_id == "sess-1"

    @pytest.mark.asyncio
    async def test_no_audit_permission_is_treated_as_manual_kick(
        self, fast_recovery: None, fast_kick_check: None
    ) -> None:
        cog, channel = _make_recovery_cog()
        cog.listener.is_connected = MagicMock(return_value=True)
        cog._audit_disconnect_baseline = None  # baseline failed: no View Audit Log
        with patch("rpg_scribe.discord_bot.commands.DiscordListener") as factory:
            await cog.on_voice_state_update(*_bot_leave_event(cog, channel))
            await cog._voice_leave_task

        factory.assert_not_called()
        assert cog.session_id is None

    @pytest.mark.asyncio
    async def test_leave_caused_by_own_recovery_is_ignored(
        self, fast_kick_check: None
    ) -> None:
        cog, channel = _make_recovery_cog()
        cog._listener_recovery_in_progress = True
        cog._audit_disconnect_baseline = None
        await cog.on_voice_state_update(*_bot_leave_event(cog, channel))
        await cog._voice_leave_task

        assert cog.session_id == "sess-1"
        assert cog.listener is not None
