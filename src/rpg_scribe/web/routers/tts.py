"""TTS (Text-to-Speech) endpoints.

The cache stores a single WAV (48 kHz stereo int16 LE) per chunk so both
the browser narrator and the Discord narrator share the same file. The
browser plays the WAV directly via ``<audio>``; the Discord player strips
the 44-byte WAV header and feeds the raw PCM to ``discord.PCMAudio``.
"""
from __future__ import annotations

import json as json_mod
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from rpg_scribe.tts.synthesizer import _ensure_chunk_wav, _split_text_to_chunks

logger = logging.getLogger(__name__)

router = APIRouter()


def _resolve_tts_components():
    """Return (config, provider, cache) or raise 503 if TTS is not ready."""
    from rpg_scribe.web import routes as _routes

    tts_config = getattr(_routes.router, "tts_config", None)
    if tts_config is None or not tts_config.enabled:
        raise HTTPException(status_code=503, detail="TTS is not enabled")

    tts_provider = getattr(_routes.router, "tts_provider", None)
    tts_cache = getattr(_routes.router, "tts_cache", None)
    if tts_provider is None or tts_cache is None:
        raise HTTPException(status_code=503, detail="TTS provider not configured")
    return tts_config, tts_provider, tts_cache


def _split_or_400(text: str) -> list[str]:
    """Run the shared splitter and translate ValueError into HTTP 400."""
    try:
        return _split_text_to_chunks(text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/api/tts/narrate")
async def tts_narrate(body: dict):
    """Stream TTS audio URLs for each paragraph via NDJSON.

    Audio is cached as 48 kHz stereo WAV so the Discord narrator can
    reuse the very same file.
    """
    tts_config, tts_provider, tts_cache = _resolve_tts_components()

    voice = body.get("voice") or tts_config.voice
    model = tts_config.model
    chunks = _split_or_400(body.get("text", ""))
    total = len(chunks)
    logger.info("TTS narrate: %d chunks, voice=%s", total, voice)

    async def generate():
        hits = 0
        for idx, chunk in enumerate(chunks):
            try:
                key, cached = await _ensure_chunk_wav(
                    chunk, voice,
                    provider=tts_provider, cache=tts_cache, model=model,
                    source="narrate(web)",
                )
            except Exception as exc:
                logger.error("TTS synthesis failed (chunk %d): %s", idx, exc)
                yield json_mod.dumps({"index": idx, "total": total, "error": str(exc)}) + "\n"
                continue
            if cached:
                hits += 1
            yield json_mod.dumps({
                "index": idx,
                "total": total,
                "audio_url": tts_cache.url_for(key),
                "cached": cached,
            }) + "\n"
        logger.info("narrate(web) done: %d/%d chunks from cache", hits, total)

    return StreamingResponse(generate(), media_type="application/x-ndjson")


@router.post("/api/tts/narrate-discord")
async def tts_narrate_discord(body: dict):
    """Prepare a Discord narration queue and start playback in the background.

    Returns NDJSON: one ``{index, total, audio_url, cached}`` line per
    ready chunk (same shape as ``/narrate``), followed by a final
    ``{status: "started"}``. Actual playback proceeds asynchronously —
    the client controls it via ``/api/tts/discord/{pause,resume,stop,
    play-at,status}``.
    """
    tts_config, tts_provider, tts_cache = _resolve_tts_components()

    from rpg_scribe.web import routes as _routes
    application = getattr(_routes.router, "application", None)
    player = application.get_discord_tts_player() if application is not None else None
    if player is None or player.get_voice_client() is None:
        raise HTTPException(status_code=409, detail="Discord voice is not connected")

    voice = body.get("voice") or tts_config.voice
    model = tts_config.model
    chunks = _split_or_400(body.get("text", ""))
    total = len(chunks)
    logger.info("TTS narrate-discord: %d chunks, voice=%s", total, voice)

    async def generate():
        keys: list[str] = []
        hits = 0
        for idx, chunk in enumerate(chunks):
            try:
                key, cached = await _ensure_chunk_wav(
                    chunk, voice,
                    provider=tts_provider, cache=tts_cache, model=model,
                    source="narrate(discord)",
                )
            except Exception as exc:
                logger.error("TTS synthesis failed (chunk %d): %s", idx, exc)
                yield json_mod.dumps({"index": idx, "total": total, "error": str(exc)}) + "\n"
                return
            keys.append(key)
            if cached:
                hits += 1
            yield json_mod.dumps({
                "index": idx,
                "total": total,
                "audio_url": tts_cache.url_for(key),
                "cached": cached,
            }) + "\n"
        logger.info("narrate(discord) prep: %d/%d chunks from cache", hits, total)

        # Queue up the WAVs (resolved to disk paths) and start playback.
        wav_paths = [str(tts_cache._path(k)) for k in keys]  # noqa: SLF001
        try:
            await player.start_queue(wav_paths)
        except Exception as exc:
            logger.error("Discord playback start failed: %s", exc)
            yield json_mod.dumps({"status": "error", "error": str(exc)}) + "\n"
            return

        yield json_mod.dumps({"status": "started", "total": total}) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")


def _require_player():
    """Resolve the DiscordTTSPlayer or raise 409 if unavailable."""
    from rpg_scribe.web import routes as _routes
    application = getattr(_routes.router, "application", None)
    player = application.get_discord_tts_player() if application is not None else None
    if player is None or player.get_voice_client() is None:
        raise HTTPException(status_code=409, detail="Discord voice is not connected")
    return player


@router.post("/api/tts/discord/pause")
async def tts_discord_pause():
    player = _require_player()
    player.pause()
    return player.status()


@router.post("/api/tts/discord/resume")
async def tts_discord_resume():
    player = _require_player()
    player.resume()
    return player.status()


@router.post("/api/tts/discord/stop")
async def tts_discord_stop():
    player = _require_player()
    await player.stop()
    return player.status()


@router.post("/api/tts/discord/play-at")
async def tts_discord_play_at(body: dict):
    player = _require_player()
    try:
        index = int(body.get("index"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="index (int) is required")
    try:
        await player.play_at(index)
    except IndexError:
        raise HTTPException(status_code=400, detail="index out of range")
    return player.status()


@router.get("/api/tts/discord/status")
async def tts_discord_status():
    """Return the current Discord playback state.

    Returns 200 with ``{"connected": false}`` rather than 409 when the
    bot is not in a voice channel, so the frontend can poll without
    spamming errors.
    """
    from rpg_scribe.web import routes as _routes
    application = getattr(_routes.router, "application", None)
    player = application.get_discord_tts_player() if application is not None else None
    if player is None or player.get_voice_client() is None:
        return {"connected": False}
    return {"connected": True, **player.status()}


@router.get("/api/tts/voices")
async def tts_voices():
    """Return available TTS voices for the active provider."""
    from rpg_scribe.web import routes as _routes
    tts_config = getattr(_routes.router, "tts_config", None)
    if tts_config is None or not tts_config.enabled:
        raise HTTPException(status_code=503, detail="TTS is not enabled")

    tts_provider = getattr(_routes.router, "tts_provider", None)
    if tts_provider is None:
        raise HTTPException(status_code=503, detail="TTS provider not configured")

    return {
        "provider": tts_provider.name,
        "voices": tts_provider.supported_voices(),
        "current": tts_config.voice,
    }
