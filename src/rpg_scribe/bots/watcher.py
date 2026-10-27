"""TriggerWatcher: keyword detection + multi-chunk capture + TTS dispatch.

Subscribes to :class:`TranscriptionEvent`. When a registered bot keyword
appears in the text, opens a per-speaker capture that accumulates the
text of subsequent transcriptions of the same speaker until one of three
conditions closes it:

* Timeout — ``bot.timeout_s`` seconds without a new chunk.
* Close word — ``bot.close_word`` appears in the text; the close word is
  stripped before passing the command to the bot.
* (Future) explicit cancel via session end — not implemented in v1.

On close, the watcher: (a) publishes :class:`TriggerActivatedEvent` for
observability, (b) calls ``bot.handle(command, …)`` inline, (c) if the
bot returns a :class:`BotResponse` with a ``written`` field, publishes a
:class:`BotTextResponseEvent` (with the current voice channel id
attached), (d) synthesizes the spoken response via the shared TTS
helper, (e) enqueues the resulting WAV(s) on the
:class:`DiscordTTSPlayer`, and (f) publica :class:`BotSpeechEvent` (con
``total_chunks``) tras encolar el audio, para que el Web UI muestre el
panel de control.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass

from rpg_scribe.bots.base import BaseBot, BotResponse
from rpg_scribe.core.event_bus import EventBus
from rpg_scribe.core.events import (
    BotSpeechEvent,
    BotTextResponseEvent,
    TranscriptionEvent,
    TriggerActivatedEvent,
)
from rpg_scribe.tts.cache import TTSCache
from rpg_scribe.tts.synthesizer import synthesize_to_wav_paths

logger = logging.getLogger(__name__)


def _normalize_response(raw: "str | BotResponse") -> BotResponse:
    """Acepta el retorno legado (str) o el nuevo BotResponse y normaliza a BotResponse."""
    if isinstance(raw, BotResponse):
        return raw
    return BotResponse(spoken=raw)


@dataclass
class _Capture:
    bot: BaseBot
    text: str
    started_at: float
    last_chunk_at: float
    timer: asyncio.Task | None = None


class TriggerWatcher:
    def __init__(
        self,
        event_bus: EventBus,
        bots: list[BaseBot],
        *,
        tts_provider,
        tts_cache: TTSCache,
        tts_model: str,
        default_voice: str,
        player,
    ) -> None:
        self._bus = event_bus
        self._bots: dict[str, BaseBot] = {b.keyword.lower(): b for b in bots}
        self._captures: dict[tuple[str, str], _Capture] = {}
        self._tts_provider = tts_provider
        self._tts_cache = tts_cache
        self._tts_model = tts_model
        self._default_voice = default_voice
        self._player = player

    async def start(self) -> None:
        self._bus.subscribe(TranscriptionEvent, self._on_transcription)

    async def stop(self) -> None:
        """Cancel any pending timers and clear active captures."""
        for cap in self._captures.values():
            if cap.timer:
                cap.timer.cancel()
        self._captures.clear()

    async def _on_transcription(self, ev: TranscriptionEvent) -> None:
        if ev.is_partial or ev.is_corrected:
            return
        text = ev.text.strip()
        if not text:
            return

        key = (ev.session_id, ev.speaker_id)
        cap = self._captures.get(key)

        if cap is None:
            match = self._find_keyword(text)
            if match is None:
                return
            bot, remainder = match
            cap = _Capture(
                bot=bot,
                text=remainder,
                started_at=time.time(),
                last_chunk_at=time.time(),
            )
            self._captures[key] = cap
            logger.info(
                "🎯 Trigger '%s' detectado (hablante=%s, sesión=%s) → captura abierta",
                bot.keyword,
                ev.speaker_name,
                ev.session_id,
            )
        else:
            cap.text = (cap.text + " " + text).strip()
            cap.last_chunk_at = time.time()

        # Close-word check after appending.
        if cap.bot.close_word:
            m = re.search(
                rf"\b{re.escape(cap.bot.close_word)}\b",
                cap.text,
                re.IGNORECASE,
            )
            if m:
                cap.text = cap.text[: m.start()].strip()
                # We're being called from outside the timer, so it's safe
                # to cancel it before finalizing. If we let it fire later,
                # it would no-op because the capture is popped.
                if cap.timer is not None:
                    cap.timer.cancel()
                # Run finalize in the background (like the timeout path). If we
                # awaited it inline here, the whole bot pipeline (RAG + Claude +
                # TTS + Discord playback, up to 30s) would run inside the
                # EventBus dispatch of this TranscriptionEvent, blocking the
                # publish chain all the way up to the audio flush loop and
                # stalling transcription. _finalize pops the capture first, so
                # backgrounding it cannot double-fire.
                asyncio.create_task(
                    self._finalize(key, ev, reason="close_word"),
                    name=f"trigger-finalize-{cap.bot.keyword}",
                )
                return

        # (Re)arm the silence timer.
        if cap.timer is not None:
            cap.timer.cancel()
        cap.timer = asyncio.create_task(
            self._timeout(key, ev, cap.bot.timeout_s),
            name=f"trigger-timeout-{cap.bot.keyword}",
        )

    async def _timeout(
        self, key: tuple[str, str], ev: TranscriptionEvent, delay: float
    ) -> None:
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        await self._finalize(key, ev, reason="timeout")

    async def _finalize(
        self,
        key: tuple[str, str],
        ev: TranscriptionEvent,
        *,
        reason: str,
    ) -> None:
        cap = self._captures.pop(key, None)
        if cap is None:
            return
        # NOTE: do NOT cancel cap.timer here — when _finalize is reached via
        # the timeout path it IS the running timer task; cancelling itself
        # raises CancelledError on the next await and aborts the bot call.
        # Callers that finalize externally (close_word) are responsible for
        # cancelling the timer beforehand.
        command = cap.text.strip()
        if not command:
            return

        _fin_t0 = time.monotonic()
        logger.info(
            "▶️  Finalize bot '%s' (motivo=%s) comando=%r — inicio pipeline",
            cap.bot.keyword,
            reason,
            command[:120],
        )

        await self._bus.publish(
            TriggerActivatedEvent(
                session_id=ev.session_id,
                speaker_id=ev.speaker_id,
                speaker_name=ev.speaker_name,
                bot_keyword=cap.bot.keyword,
                command=command,
                started_at=cap.started_at,
                closed_at=time.time(),
                close_reason=reason,
            )
        )

        _handle_t0 = time.monotonic()
        try:
            raw = await asyncio.wait_for(
                cap.bot.handle(
                    command,
                    session_id=ev.session_id,
                    speaker_id=ev.speaker_id,
                    speaker_name=ev.speaker_name,
                ),
                timeout=30.0,
            )
        except Exception as exc:
            logger.exception("Bot %s.handle failed: %s", cap.bot.keyword, exc)
            raw = "Lo siento, ha habido un problema."
        logger.info(
            "   bot '%s'.handle tardó %.1fs",
            cap.bot.keyword,
            time.monotonic() - _handle_t0,
        )

        response = _normalize_response(raw)

        # Publish the written answer (if any). Adjuntamos el canal de voz actual
        # para que el publisher pueda hacer fallback a su chat integrado.
        if response.written:
            vc = self._player.get_voice_client()
            voice_channel_id = (
                vc.channel.id if vc is not None and vc.channel is not None else None
            )
            await self._bus.publish(
                BotTextResponseEvent(
                    session_id=ev.session_id,
                    bot_keyword=cap.bot.keyword,
                    speaker_name=ev.speaker_name,
                    question=command,
                    answer_md=response.written,
                    citations=tuple(response.citations or ()),
                    voice_channel_id=voice_channel_id,
                )
            )

        spoken = response.spoken
        if not spoken or not spoken.strip():
            return

        voice = cap.bot.voice or self._default_voice
        _tts_t0 = time.monotonic()
        try:
            paths = await synthesize_to_wav_paths(
                spoken,
                voice,
                provider=self._tts_provider,
                cache=self._tts_cache,
                model=self._tts_model,
                source=f"bot:{cap.bot.keyword}",
            )
        except Exception as exc:
            logger.exception(
                "TTS synthesis for bot %s failed: %s", cap.bot.keyword, exc
            )
            return
        logger.info(
            "   TTS bot '%s' tardó %.1fs (%d chunk(s))",
            cap.bot.keyword,
            time.monotonic() - _tts_t0,
            len(paths),
        )

        if self._player.get_voice_client() is None:
            logger.warning(
                "Bot %s response not played: voice channel not connected",
                cap.bot.keyword,
            )
            return

        _play_t0 = time.monotonic()
        try:
            await self._player.start_queue([str(p) for p in paths])
        except Exception as exc:
            logger.exception(
                "Discord playback for bot %s failed: %s",
                cap.bot.keyword,
                exc,
            )
            return

        await self._bus.publish(
            BotSpeechEvent(
                session_id=ev.session_id,
                bot_keyword=cap.bot.keyword,
                speaker_name=ev.speaker_name,
                question=command,
                answer_md=response.written or spoken,
                total_chunks=len(paths),
            )
        )
        logger.info(
            "✅ Finalize bot '%s' completado: playback %.1fs | pipeline total %.1fs "
            "(motivo=%s). Nota: si este total es alto y el finalize corriera inline "
            "en el dispatch del evento, bloquearía la ingesta de audio.",
            cap.bot.keyword,
            time.monotonic() - _play_t0,
            time.monotonic() - _fin_t0,
            reason,
        )

    def _find_keyword(self, text: str) -> tuple[BaseBot, str] | None:
        """Return (bot, text_after_keyword) for the first matching keyword."""
        for kw, bot in self._bots.items():
            m = re.search(rf"\b{re.escape(kw)}\b", text, re.IGNORECASE)
            if m:
                remainder = text[m.end() :].lstrip(" ,.:;!?¿¡").strip()
                return bot, remainder
        return None
