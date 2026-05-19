"""Tests for the DiscordTTSPlayer service (queue + transport controls)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from rpg_scribe.core.event_bus import EventBus
from rpg_scribe.discord_bot.tts_player import DiscordTTSPlayer
from rpg_scribe.tts.audio_utils import wrap_pcm_as_wav


def _make_bot_with_voice(voice_client) -> MagicMock:
    listener = MagicMock()
    listener._voice_client = voice_client
    cog = MagicMock()
    cog.listener = listener
    bot = MagicMock()
    bot.cogs = {"Scribe": cog}
    return bot


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


def _make_vc(*, playing: bool = False, paused: bool = False) -> MagicMock:
    vc = MagicMock()
    vc.is_connected = MagicMock(return_value=True)
    vc.is_playing = MagicMock(return_value=playing)
    vc.is_paused = MagicMock(return_value=paused)
    vc.pause = MagicMock()
    vc.resume = MagicMock()
    vc.stop = MagicMock()
    return vc


def _write_dummy_wav(path: Path, n_samples: int = 64) -> str:
    pcm = bytes(n_samples * 2 * 2)  # silence, stereo int16
    path.write_bytes(wrap_pcm_as_wav(pcm))
    return str(path)


class TestGetVoiceClient:
    def test_returns_none_when_no_cogs(self, event_bus: EventBus) -> None:
        bot = MagicMock()
        bot.cogs = {}
        player = DiscordTTSPlayer(bot=bot, event_bus=event_bus)
        assert player.get_voice_client() is None

    def test_returns_none_when_listener_not_connected(self, event_bus: EventBus) -> None:
        vc = MagicMock()
        vc.is_connected = MagicMock(return_value=False)
        bot = _make_bot_with_voice(vc)
        player = DiscordTTSPlayer(bot=bot, event_bus=event_bus)
        assert player.get_voice_client() is None

    def test_returns_voice_client_when_connected(self, event_bus: EventBus) -> None:
        vc = _make_vc()
        bot = _make_bot_with_voice(vc)
        player = DiscordTTSPlayer(bot=bot, event_bus=event_bus)
        assert player.get_voice_client() is vc


class TestStatus:
    def test_status_idle(self, event_bus: EventBus) -> None:
        bot = MagicMock()
        bot.cogs = {}
        player = DiscordTTSPlayer(bot=bot, event_bus=event_bus)
        s = player.status()
        assert s["total"] == 0
        assert s["index"] == -1
        assert s["active"] is False

    def test_status_reflects_playing(self, event_bus: EventBus) -> None:
        vc = _make_vc(playing=True)
        bot = _make_bot_with_voice(vc)
        player = DiscordTTSPlayer(bot=bot, event_bus=event_bus)
        s = player.status()
        assert s["playing"] is True
        assert s["paused"] is False


class TestPauseResume:
    def test_pause_calls_vc_pause(self, event_bus: EventBus) -> None:
        vc = _make_vc(playing=True)
        bot = _make_bot_with_voice(vc)
        player = DiscordTTSPlayer(bot=bot, event_bus=event_bus)
        player.pause()
        vc.pause.assert_called_once()

    def test_resume_calls_vc_resume(self, event_bus: EventBus) -> None:
        vc = _make_vc(paused=True)
        bot = _make_bot_with_voice(vc)
        player = DiscordTTSPlayer(bot=bot, event_bus=event_bus)
        player.resume()
        vc.resume.assert_called_once()

    def test_pause_noop_when_idle(self, event_bus: EventBus) -> None:
        vc = _make_vc()
        bot = _make_bot_with_voice(vc)
        player = DiscordTTSPlayer(bot=bot, event_bus=event_bus)
        player.pause()
        vc.pause.assert_not_called()


class TestStartQueueAndStop:
    async def test_start_queue_plays_each_chunk(
        self, event_bus: EventBus, tmp_path: Path,
    ) -> None:
        # vc.play schedules its `after` callback so the loop advances.
        vc = _make_vc()
        play_log: list = []

        def fake_play(source, after=None):
            play_log.append(source)
            if after is not None:
                loop = asyncio.get_event_loop()
                loop.call_soon(after, None)

        vc.play = MagicMock(side_effect=fake_play)
        bot = _make_bot_with_voice(vc)
        player = DiscordTTSPlayer(bot=bot, event_bus=event_bus)

        paths = [
            _write_dummy_wav(tmp_path / "a.wav"),
            _write_dummy_wav(tmp_path / "b.wav"),
        ]
        await player.start_queue(paths)
        # wait for the background task to finish
        await asyncio.wait_for(player._task, timeout=2.0)

        assert vc.play.call_count == 2

    async def test_stop_cancels_task_and_clears_queue(
        self, event_bus: EventBus, tmp_path: Path,
    ) -> None:
        vc = _make_vc()
        # play() never fires its callback → loop hangs at `await done.wait()`.
        vc.play = MagicMock(side_effect=lambda source, after=None: None)
        bot = _make_bot_with_voice(vc)
        player = DiscordTTSPlayer(bot=bot, event_bus=event_bus)

        paths = [_write_dummy_wav(tmp_path / "a.wav")]
        await player.start_queue(paths)
        # Let the task run until it's stuck waiting.
        await asyncio.sleep(0)

        await player.stop()
        assert player.status()["total"] == 0
        assert player.status()["index"] == -1
        assert player._task is None or player._task.done()
