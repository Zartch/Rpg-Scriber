"""TTS (Text-to-Speech) endpoints."""
from __future__ import annotations

import json as json_mod
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter()

_TTS_CHAR_LIMIT = 4096


def _split_tts_chunks(text: str, limit: int = _TTS_CHAR_LIMIT) -> list[str]:
    """Split text into chunks that fit within the TTS char limit.

    Cuts at the last '.', then last ',', then last space before the limit.
    Recurses until every chunk fits.
    """
    if len(text) <= limit:
        return [text]
    for sep in (".", ",", " "):
        cut = text.rfind(sep, 0, limit)
        if cut != -1:
            head = text[: cut + 1].strip()
            tail = text[cut + 1 :].strip()
            return _split_tts_chunks(head, limit) + _split_tts_chunks(tail, limit)
    return [text[:limit]] + _split_tts_chunks(text[limit:], limit)


@router.post("/api/tts/narrate")
async def tts_narrate(body: dict):
    """Stream TTS audio URLs for each paragraph via NDJSON."""
    from rpg_scribe.web import routes as _routes
    tts_config = getattr(_routes.router, "tts_config", None)
    if tts_config is None or not tts_config.enabled:
        raise HTTPException(status_code=503, detail="TTS is not enabled")

    tts_provider = getattr(_routes.router, "tts_provider", None)
    tts_cache = getattr(_routes.router, "tts_cache", None)
    if tts_provider is None or tts_cache is None:
        raise HTTPException(status_code=503, detail="TTS provider not configured")

    text = body.get("text", "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    voice = body.get("voice") or tts_config.voice
    provider_name = tts_provider.name
    model = tts_config.model

    raw_paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not raw_paragraphs:
        raise HTTPException(status_code=400, detail="No paragraphs found in text")

    chunks: list[str] = []
    for p_idx, paragraph in enumerate(raw_paragraphs):
        sub = _split_tts_chunks(paragraph)
        if len(sub) > 1:
            logger.info("TTS chunk split: párrafo %d → %d subchunks (%d chars)", p_idx, len(sub), len(paragraph))
        chunks.extend(sub)

    total = len(chunks)
    logger.info("TTS narrate: %d párrafos, %d chunks, voice=%s", len(raw_paragraphs), total, voice)

    async def generate():
        for idx, chunk in enumerate(chunks):
            key = tts_cache.make_key(chunk, provider_name, voice, model)
            cached = tts_cache.has(key)
            logger.info("TTS → OpenAI: chunk %d/%d (%d chars) cached=%s", idx + 1, total, len(chunk), cached)
            if not cached:
                try:
                    audio = await tts_provider.synthesize(chunk, voice)
                    tts_cache.put(key, audio)
                except Exception as exc:
                    line = json_mod.dumps({"index": idx, "total": total, "error": str(exc)})
                    yield line + "\n"
                    continue
            line = json_mod.dumps({
                "index": idx,
                "total": total,
                "audio_url": tts_cache.url_for(key),
                "cached": cached,
            })
            yield line + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")


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
