"""Discord voice playback for TTS narration with queue + transport controls.

Maintains a queue of WAV files (the same files cached by the Web narrator)
and exposes pause / resume / stop / play-at semantics so the frontend can
build a controls panel similar to the browser one.
"""
from __future__ import annotations

import asyncio
import io
import logging
from pathlib import Path
from typing import Any

import discord
from discord.ext import commands

from rpg_scribe.core.event_bus import EventBus
from rpg_scribe.tts.audio_utils import pcm_from_wav

logger = logging.getLogger(__name__)


class DiscordTTSPlayer:
    """Plays a queue of cached WAV chunks through the bot's voice client.

    The class owns a background task that walks ``self._queue`` from
    ``self._index`` onward, awaiting completion of each ``play()`` call.
    Pause / resume map directly to ``VoiceClient.pause()`` /
    ``VoiceClient.resume()``. Stop and play-at cancel the current source
    via ``VoiceClient.stop()`` (which fires the ``after`` callback so the
    waiting coroutine wakes up).
    """

    def __init__(self, bot: commands.Bot, event_bus: EventBus) -> None:
        self._bot = bot
        self._event_bus = event_bus

        self._queue: list[str] = []
        self._index: int = -1
        self._task: asyncio.Task[None] | None = None
        # When set, the running task should NOT advance to next index after
        # the current chunk finishes — used for play_at and stop.
        self._jump_to: int | None = None
        self._stopping: bool = False
        self._lock = asyncio.Lock()

    # ── Voice client discovery ─────────────────────────────────────

    def get_voice_client(self) -> discord.VoiceClient | None:
        """Return the bot's currently connected voice client, or ``None``."""
        for cog in self._bot.cogs.values():
            listener = getattr(cog, "listener", None)
            if listener is None:
                continue
            vc: Any = getattr(listener, "_voice_client", None)
            if vc is not None and getattr(vc, "is_connected", lambda: False)():
                return vc
        return None

    def is_busy(self) -> bool:
        """``True`` if a task is currently driving the queue."""
        return self._task is not None and not self._task.done()

    # ── Status ─────────────────────────────────────────────────────

    def status(self) -> dict:
        vc = self.get_voice_client()
        playing = bool(vc and vc.is_playing())
        paused = bool(vc and vc.is_paused())
        return {
            "total": len(self._queue),
            "index": self._index,
            "playing": playing,
            "paused": paused,
            "active": self.is_busy(),
        }

    # ── Public controls ────────────────────────────────────────────

    async def start_queue(self, wav_paths: list[str]) -> None:
        """Replace the current queue and start playback from index 0."""
        async with self._lock:
            await self._cancel_task_locked()
            self._queue = list(wav_paths)
            self._index = 0
            self._stopping = False
            self._jump_to = None
            if not self._queue:
                return
            self._task = asyncio.create_task(self._run(), name="discord-tts-queue")

    async def play_at(self, index: int) -> None:
        """Jump to ``index`` in the current queue (must be in range)."""
        if not (0 <= index < len(self._queue)):
            raise IndexError(index)
        async with self._lock:
            self._jump_to = index
            self._stopping = False
            vc = self.get_voice_client()
            if vc and (vc.is_playing() or vc.is_paused()):
                vc.stop()  # fires `after` callback → loop wakes up
            elif self._task is None or self._task.done():
                # No active task — start a fresh one at the requested index.
                self._index = index
                self._jump_to = None
                self._task = asyncio.create_task(self._run(), name="discord-tts-queue")

    def pause(self) -> None:
        vc = self.get_voice_client()
        if vc and vc.is_playing():
            vc.pause()

    def resume(self) -> None:
        vc = self.get_voice_client()
        if vc and vc.is_paused():
            vc.resume()

    async def stop(self) -> None:
        """Cancel playback and clear the queue."""
        async with self._lock:
            self._stopping = True
            self._jump_to = None
            vc = self.get_voice_client()
            if vc and (vc.is_playing() or vc.is_paused()):
                vc.stop()
            await self._cancel_task_locked()
            self._queue = []
            self._index = -1

    # ── Internals ──────────────────────────────────────────────────

    async def _cancel_task_locked(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self._task = None

    async def _run(self) -> None:
        """Background loop: play queue[index..] until exhausted or stopped."""
        loop = asyncio.get_running_loop()
        try:
            while 0 <= self._index < len(self._queue):
                if self._stopping:
                    break

                wav_path = self._queue[self._index]
                try:
                    pcm = pcm_from_wav(Path(wav_path).read_bytes())
                except Exception as exc:
                    logger.error("Cannot read WAV %s: %s", wav_path, exc)
                    self._index += 1
                    continue

                vc = self.get_voice_client()
                if vc is None:
                    logger.warning("Voice client gone — stopping queue")
                    break

                done = asyncio.Event()
                err_box: list[BaseException | None] = [None]

                def _after(error: BaseException | None,
                           _ev: asyncio.Event = done,
                           _box: list[BaseException | None] = err_box) -> None:
                    _box[0] = error
                    loop.call_soon_threadsafe(_ev.set)

                try:
                    vc.play(discord.PCMAudio(io.BytesIO(pcm)), after=_after)
                except discord.ClientException as exc:
                    logger.error("vc.play raised: %s", exc)
                    break

                await done.wait()

                if err_box[0] is not None:
                    logger.error(
                        "Discord playback error on chunk %d: %s",
                        self._index, err_box[0],
                    )
                    break

                # Decide next index: jump_to overrides natural advance.
                if self._stopping:
                    break
                if self._jump_to is not None:
                    self._index = self._jump_to
                    self._jump_to = None
                else:
                    self._index += 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Discord TTS queue crashed: %s", exc)
