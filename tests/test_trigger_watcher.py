"""Tests for TriggerWatcher: keyword detection, multi-chunk capture, TTS dispatch."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from rpg_scribe.bots.base import BaseBot, BotResponse
from rpg_scribe.bots.watcher import _normalize_response
from rpg_scribe.core.event_bus import EventBus
from rpg_scribe.core.events import BotTextResponseEvent, Citation, TranscriptionEvent
from rpg_scribe.tts.cache import TTSCache


def _mk_event(text: str, *, speaker_id: str = "user-1",
              speaker_name: str = "Alice", session_id: str = "s-1",
              is_partial: bool = False, is_corrected: bool = False) -> TranscriptionEvent:
    return TranscriptionEvent(
        session_id=session_id,
        speaker_id=speaker_id,
        speaker_name=speaker_name,
        text=text,
        timestamp=0.0,
        confidence=1.0,
        is_partial=is_partial,
        is_corrected=is_corrected,
    )


def _mk_player() -> MagicMock:
    """A DiscordTTSPlayer mock that pretends to be voice-connected."""
    player = MagicMock()
    player.get_voice_client.return_value = MagicMock()  # truthy = connected
    player.start_queue = AsyncMock()
    return player


def _mk_provider(pcm: bytes = b"\x00\x00" * 8) -> MagicMock:
    provider = MagicMock()
    provider.name = "openai"
    provider.synthesize = AsyncMock(return_value=pcm)
    return provider


class _BotForTesting(BaseBot):
    """Bot that records what it received and returns a fixed reply."""

    keyword = "echo"
    close_word = "fin"
    timeout_s = 0.08  # fast for tests
    name = "Test"

    def __init__(self) -> None:
        self.received: list[dict] = []
        self.reply: str = "ok"

    async def handle(self, command, *, session_id, speaker_id, speaker_name):
        self.received.append({
            "command": command,
            "session_id": session_id,
            "speaker_id": speaker_id,
            "speaker_name": speaker_name,
        })
        return self.reply


def _mk_watcher(bots, *, tmp_path: Path, player=None, provider=None):
    """Build a TriggerWatcher wired with real cache and mocked TTS/player."""
    from rpg_scribe.bots.watcher import TriggerWatcher

    return TriggerWatcher(
        event_bus=EventBus(),
        bots=bots,
        tts_provider=provider or _mk_provider(),
        tts_cache=TTSCache(str(tmp_path)),
        tts_model="tts-1",
        default_voice="nova",
        player=player or _mk_player(),
    )


class TestSingleChunk:
    @pytest.mark.asyncio
    async def test_single_chunk_with_keyword_triggers_bot(self, tmp_path: Path) -> None:
        bot = _BotForTesting()
        player = _mk_player()
        watcher = _mk_watcher([bot], tmp_path=tmp_path, player=player)
        await watcher.start()

        await watcher._on_transcription(_mk_event("echo, hola mundo"))
        # Wait for timeout to fire and finalize
        await asyncio.sleep(0.2)

        assert len(bot.received) == 1
        assert bot.received[0]["command"] == "hola mundo"
        assert bot.received[0]["speaker_id"] == "user-1"
        player.start_queue.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_text_without_keyword_does_nothing(self, tmp_path: Path) -> None:
        bot = _BotForTesting()
        player = _mk_player()
        watcher = _mk_watcher([bot], tmp_path=tmp_path, player=player)
        await watcher.start()

        await watcher._on_transcription(_mk_event("hola, qué tal todo"))
        await asyncio.sleep(0.2)

        assert bot.received == []
        player.start_queue.assert_not_called()

    @pytest.mark.asyncio
    async def test_is_partial_is_ignored(self, tmp_path: Path) -> None:
        bot = _BotForTesting()
        watcher = _mk_watcher([bot], tmp_path=tmp_path)
        await watcher.start()

        await watcher._on_transcription(_mk_event("echo, hola", is_partial=True))
        await asyncio.sleep(0.15)
        assert bot.received == []

    @pytest.mark.asyncio
    async def test_is_corrected_is_ignored(self, tmp_path: Path) -> None:
        bot = _BotForTesting()
        watcher = _mk_watcher([bot], tmp_path=tmp_path)
        await watcher.start()

        await watcher._on_transcription(_mk_event("echo, hola", is_corrected=True))
        await asyncio.sleep(0.15)
        assert bot.received == []


class TestMultiChunkCapture:
    @pytest.mark.asyncio
    async def test_two_chunks_concatenated(self, tmp_path: Path) -> None:
        bot = _BotForTesting()
        watcher = _mk_watcher([bot], tmp_path=tmp_path)
        await watcher.start()

        await watcher._on_transcription(_mk_event("echo, comprueba"))
        # Second chunk arrives before timeout
        await asyncio.sleep(0.03)
        await watcher._on_transcription(_mk_event("la dificultad"))
        # Now wait for timeout to fire
        await asyncio.sleep(0.2)

        assert len(bot.received) == 1
        assert bot.received[0]["command"] == "comprueba la dificultad"

    @pytest.mark.asyncio
    async def test_three_chunks_concatenated(self, tmp_path: Path) -> None:
        bot = _BotForTesting()
        watcher = _mk_watcher([bot], tmp_path=tmp_path)
        await watcher.start()

        await watcher._on_transcription(_mk_event("echo,"))
        await asyncio.sleep(0.02)
        await watcher._on_transcription(_mk_event("dame la dificultad"))
        await asyncio.sleep(0.02)
        await watcher._on_transcription(_mk_event("de disparo a 20 metros"))
        await asyncio.sleep(0.2)

        assert len(bot.received) == 1
        assert bot.received[0]["command"] == "dame la dificultad de disparo a 20 metros"


class TestCloseWord:
    @pytest.mark.asyncio
    async def test_close_word_finalizes_immediately(self, tmp_path: Path) -> None:
        bot = _BotForTesting()  # close_word="fin"
        watcher = _mk_watcher([bot], tmp_path=tmp_path)
        await watcher.start()

        await watcher._on_transcription(_mk_event("echo, dispara fin"))
        # Should finalize immediately, no need to wait timeout
        await asyncio.sleep(0.02)

        assert len(bot.received) == 1
        # "fin" is cut, so the recorded command excludes it
        assert "fin" not in bot.received[0]["command"]
        assert bot.received[0]["command"] == "dispara"

    @pytest.mark.asyncio
    async def test_close_word_across_chunks(self, tmp_path: Path) -> None:
        bot = _BotForTesting()
        watcher = _mk_watcher([bot], tmp_path=tmp_path)
        await watcher.start()

        await watcher._on_transcription(_mk_event("echo, dispara"))
        await asyncio.sleep(0.02)
        await watcher._on_transcription(_mk_event("a 20 metros fin"))
        await asyncio.sleep(0.02)

        assert len(bot.received) == 1
        assert bot.received[0]["command"] == "dispara a 20 metros"


class TestTimeout:
    @pytest.mark.asyncio
    async def test_timeout_closes_capture(self, tmp_path: Path) -> None:
        bot = _BotForTesting()  # timeout_s = 0.08
        watcher = _mk_watcher([bot], tmp_path=tmp_path)
        await watcher.start()

        await watcher._on_transcription(_mk_event("echo, comprueba algo"))
        # Don't send more chunks; timeout must finalize
        await asyncio.sleep(0.2)

        assert len(bot.received) == 1


class TestMultipleSpeakers:
    @pytest.mark.asyncio
    async def test_two_speakers_independent_captures(self, tmp_path: Path) -> None:
        bot = _BotForTesting()
        watcher = _mk_watcher([bot], tmp_path=tmp_path)
        await watcher.start()

        await watcher._on_transcription(
            _mk_event("echo, primero", speaker_id="u1", speaker_name="A"))
        await watcher._on_transcription(
            _mk_event("echo, segundo", speaker_id="u2", speaker_name="B"))
        await asyncio.sleep(0.2)

        assert len(bot.received) == 2
        commands_by_speaker = {r["speaker_id"]: r["command"] for r in bot.received}
        assert commands_by_speaker == {"u1": "primero", "u2": "segundo"}


class TestBotErrorFallback:
    @pytest.mark.asyncio
    async def test_handle_exception_triggers_fallback_speech(self, tmp_path: Path) -> None:
        class BrokenBot(_BotForTesting):
            async def handle(self, command, *, session_id, speaker_id, speaker_name):
                raise RuntimeError("boom")

        bot = BrokenBot()
        player = _mk_player()
        provider = _mk_provider()
        watcher = _mk_watcher([bot], tmp_path=tmp_path, player=player, provider=provider)
        await watcher.start()

        await watcher._on_transcription(_mk_event("echo, falla"))
        await asyncio.sleep(0.2)

        # start_queue must still have been called (with the fallback message)
        player.start_queue.assert_awaited_once()
        # And the provider must have synthesized at least one chunk.
        provider.synthesize.assert_awaited()


class TestVoiceClientDisconnected:
    @pytest.mark.asyncio
    async def test_no_voice_client_skips_player(self, tmp_path: Path) -> None:
        bot = _BotForTesting()
        player = MagicMock()
        player.get_voice_client.return_value = None  # not connected
        player.start_queue = AsyncMock()
        watcher = _mk_watcher([bot], tmp_path=tmp_path, player=player)
        await watcher.start()

        await watcher._on_transcription(_mk_event("echo, hola"))
        await asyncio.sleep(0.2)

        # Bot.handle ran but player was skipped
        assert len(bot.received) == 1
        player.start_queue.assert_not_called()


class TestTriggerActivatedEvent:
    @pytest.mark.asyncio
    async def test_event_is_published_on_finalize(self, tmp_path: Path) -> None:
        from rpg_scribe.core.events import TriggerActivatedEvent

        bot = _BotForTesting()
        watcher = _mk_watcher([bot], tmp_path=tmp_path)
        captured: list[TriggerActivatedEvent] = []

        async def listener(ev):
            captured.append(ev)

        await watcher.start()
        watcher._bus.subscribe(TriggerActivatedEvent, listener)

        await watcher._on_transcription(_mk_event("echo, comprueba algo"))
        await asyncio.sleep(0.2)

        # Sanity: bot.handle must have run, which means publish() also ran
        assert len(bot.received) == 1, "bot.handle did not run"
        assert len(captured) == 1
        ev = captured[0]
        assert ev.bot_keyword == "echo"
        assert ev.command == "comprueba algo"
        assert ev.close_reason == "timeout"
        assert ev.speaker_id == "user-1"


def test_keyword_match_is_case_insensitive(tmp_path: Path) -> None:
    """Uppercase keyword text triggers a bot registered with a lowercase keyword."""

    class RulesBotStub(BaseBot):
        keyword = "bot reglas"
        name = "Reglas"

        async def handle(self, command, *, session_id, speaker_id, speaker_name):
            return "ok"

    bot = RulesBotStub()
    watcher = _mk_watcher([bot], tmp_path=tmp_path)

    result = watcher._find_keyword("BOT REGLAS, ¿cómo funciona el hackeo?")
    assert result is not None
    found_bot, remainder = result
    assert found_bot is bot
    assert "hackeo" in remainder


def test_normalize_str_wraps_in_bot_response():
    r = _normalize_response("hola")
    assert isinstance(r, BotResponse)
    assert r.spoken == "hola"
    assert r.written is None


def test_normalize_bot_response_passthrough():
    original = BotResponse(spoken="s", written="w")
    assert _normalize_response(original) is original


class TestBotTextResponseEventPublished:
    @pytest.mark.asyncio
    async def test_bot_response_with_written_publishes_event(self, tmp_path: Path) -> None:
        """A bot returning BotResponse(written=...) triggers BotTextResponseEvent."""

        class OracleBot(BaseBot):
            keyword = "oracle"
            timeout_s = 0.08

            async def handle(self, command, *, session_id, speaker_id, speaker_name):
                return BotResponse(
                    spoken="hablado",
                    written="respuesta escrita",
                    citations=[Citation(manual="M", page=3, section_path="S")],
                )

        bus = EventBus()
        collected: list[BotTextResponseEvent] = []

        async def _collect(ev: BotTextResponseEvent) -> None:
            collected.append(ev)

        bus.subscribe(BotTextResponseEvent, _collect)

        # Player with a concrete voice channel id
        player = _mk_player()
        vc = MagicMock()
        vc.channel = MagicMock()
        vc.channel.id = 12345
        player.get_voice_client.return_value = vc

        from rpg_scribe.bots.watcher import TriggerWatcher

        watcher = TriggerWatcher(
            event_bus=bus,
            bots=[OracleBot()],
            tts_provider=_mk_provider(),
            tts_cache=TTSCache(str(tmp_path)),
            tts_model="tts-1",
            default_voice="nova",
            player=player,
        )
        await watcher.start()

        await watcher._on_transcription(_mk_event("oracle, quién es el asesino"))
        await asyncio.sleep(0.2)

        assert len(collected) == 1
        ev = collected[0]
        assert ev.answer_md == "respuesta escrita"
        assert ev.bot_keyword == "oracle"
        assert ev.voice_channel_id == 12345
        assert len(ev.citations) == 1
        assert ev.citations[0].manual == "M"
        assert ev.citations[0].page == 3


class TestBotSpeechEventPublished:
    @pytest.mark.asyncio
    async def test_event_published_when_playback_starts(self, tmp_path: Path) -> None:
        from rpg_scribe.core.events import BotSpeechEvent

        bot = _BotForTesting()  # keyword "echo", reply "ok"
        player = _mk_player()
        watcher = _mk_watcher([bot], tmp_path=tmp_path, player=player)

        collected: list[BotSpeechEvent] = []

        async def _collect(ev: BotSpeechEvent) -> None:
            collected.append(ev)

        watcher._bus.subscribe(BotSpeechEvent, _collect)
        await watcher.start()

        await watcher._on_transcription(_mk_event("echo, hola mundo"))
        await asyncio.sleep(0.2)

        assert len(collected) == 1
        ev = collected[0]
        assert ev.bot_keyword == "echo"
        assert ev.speaker_name == "Alice"
        assert ev.question == "hola mundo"
        assert ev.answer_md == "ok"
        queued = player.start_queue.await_args.args[0]
        assert ev.total_chunks == len(queued)
        assert ev.total_chunks >= 1

    @pytest.mark.asyncio
    async def test_no_event_when_voice_disconnected(self, tmp_path: Path) -> None:
        from rpg_scribe.core.events import BotSpeechEvent

        bot = _BotForTesting()
        player = MagicMock()
        player.get_voice_client.return_value = None  # not connected
        player.start_queue = AsyncMock()
        watcher = _mk_watcher([bot], tmp_path=tmp_path, player=player)

        collected: list = []

        async def _collect(ev) -> None:
            collected.append(ev)

        watcher._bus.subscribe(BotSpeechEvent, _collect)
        await watcher.start()

        await watcher._on_transcription(_mk_event("echo, hola"))
        await asyncio.sleep(0.2)

        assert collected == []
        player.start_queue.assert_not_called()
