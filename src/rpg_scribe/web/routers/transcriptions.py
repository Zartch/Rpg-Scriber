"""Transcription and word-replacement endpoints."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from rpg_scribe.web.state import WebState

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_state() -> WebState:
    from rpg_scribe.web import routes as _routes
    return _routes.router.state  # type: ignore[attr-defined]


def _get_database():
    from rpg_scribe.web import routes as _routes
    return getattr(_routes.router, "database", None)


def _get_application():
    from rpg_scribe.web import routes as _routes
    return getattr(_routes.router, "application", None)


# ── Transcription read endpoints ──────────────────────────────────


@router.get("/api/sessions/{session_id}/transcriptions")
async def get_transcriptions(session_id: str) -> dict[str, Any]:
    """Return transcriptions for a session.

    For the active live session (or when no DB is available), returns
    in-memory data.  For historical sessions, queries the database.
    """
    state = _get_state()

    filtered = [t for t in state.transcriptions if t.get("session_id") == session_id]

    if filtered or session_id == state.active_session_id:
        return {"session_id": session_id, "transcriptions": filtered}

    db = _get_database()
    if db is not None:
        try:
            rows = await db.get_transcriptions(session_id)
            return {"session_id": session_id, "transcriptions": rows}
        except Exception as exc:
            logger.error("Error fetching transcriptions from DB: %s", exc)

    return {"session_id": session_id, "transcriptions": filtered}


@router.get("/api/sessions/{session_id}/transcriptions/full")
async def get_full_transcriptions(session_id: str) -> dict[str, Any]:
    """Return full stored transcriptions for a session (DB-first)."""
    db = _get_database()
    state = _get_state()

    if db is not None:
        try:
            rows = await db.get_transcriptions(session_id)
            return {"session_id": session_id, "transcriptions": rows}
        except Exception as exc:
            logger.error("Error fetching full transcriptions from DB: %s", exc)

    filtered = [t for t in state.transcriptions if t.get("session_id") == session_id]
    return {"session_id": session_id, "transcriptions": filtered}


# ── Transcription editing ─────────────────────────────────────────


@router.put("/api/transcriptions/{transcription_id}")
async def update_transcription(
    transcription_id: int, body: dict[str, Any]
) -> dict[str, Any]:
    """Update a transcription's text and record word-level edits."""
    db = _get_database()
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")

    new_text = body.get("text", "")
    if not new_text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty")

    ok = await db.update_transcription_text(transcription_id, new_text)
    if not ok:
        raise HTTPException(status_code=404, detail="Transcription not found")

    edits = body.get("edits", [])
    for edit in edits:
        await db.save_transcription_edit(
            transcription_id=transcription_id,
            original_word=edit.get("original", ""),
            new_word=edit.get("new", ""),
            position=edit.get("position", 0),
        )

    state = _get_state()
    for t in state.transcriptions:
        if t.get("id") == transcription_id:
            t["text"] = new_text
            break

    return {"ok": True, "id": transcription_id}


@router.delete("/api/transcriptions/{transcription_id}")
async def delete_transcription(transcription_id: int) -> dict[str, Any]:
    """Delete a transcription by ID."""
    db = _get_database()
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")
    ok = await db.delete_transcription(transcription_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Transcription not found")

    state = _get_state()
    state.transcriptions = [
        t for t in state.transcriptions if t.get("id") != transcription_id
    ]

    return {"ok": True, "id": transcription_id}


@router.patch("/api/transcriptions/{transcription_id}/meta")
async def toggle_transcription_meta(
    transcription_id: int, body: dict[str, Any]
) -> dict[str, Any]:
    """Toggle the is_ingame flag on a transcription."""
    db = _get_database()
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")

    is_ingame = body.get("is_ingame", True)
    ok = await db.update_transcription_is_ingame(transcription_id, is_ingame)
    if not ok:
        raise HTTPException(status_code=404, detail="Transcription not found")

    state = _get_state()
    for t in state.transcriptions:
        if t.get("id") == transcription_id:
            t["is_ingame"] = is_ingame
            break

    return {"ok": True, "id": transcription_id, "is_ingame": is_ingame}


# ── Word replacements ─────────────────────────────────────────────


@router.get("/api/campaigns/{campaign_id}/word-replacements")
async def get_word_replacements(campaign_id: str) -> dict[str, Any]:
    """List all word replacement rules for a campaign."""
    db = _get_database()
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")
    replacements = await db.get_word_replacements(campaign_id)
    return {"replacements": replacements}


@router.post("/api/campaigns/{campaign_id}/word-replacements")
async def create_word_replacement(
    campaign_id: str, body: dict[str, str]
) -> dict[str, Any]:
    """Create a word replacement rule."""
    db = _get_database()
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")
    original = body.get("original_word", "").strip()
    replacement = body.get("replacement_word", "").strip()
    if not original or not replacement:
        raise HTTPException(
            status_code=400,
            detail="Both original_word and replacement_word are required",
        )
    rule_id = await db.save_word_replacement(campaign_id, original, replacement)
    app = _get_application()
    if app and hasattr(app, "reload_word_replacements"):
        await app.reload_word_replacements()
    return {"ok": True, "id": rule_id}


@router.delete("/api/campaigns/{campaign_id}/word-replacements/{replacement_id}")
async def delete_word_replacement(
    campaign_id: str, replacement_id: int
) -> dict[str, Any]:
    """Delete a word replacement rule."""
    db = _get_database()
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")
    ok = await db.delete_word_replacement(replacement_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Replacement rule not found")
    app = _get_application()
    if app and hasattr(app, "reload_word_replacements"):
        await app.reload_word_replacements()
    return {"ok": True}


@router.post("/api/campaigns/{campaign_id}/word-replacements/apply")
async def apply_word_replacements(campaign_id: str) -> dict[str, Any]:
    """Apply all word replacement rules retroactively to existing transcriptions."""
    db = _get_database()
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")
    modified = await db.apply_word_replacements(campaign_id)
    return {"ok": True, "modified_count": modified}
