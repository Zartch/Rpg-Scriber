"""Session endpoints."""
from __future__ import annotations

import html
import logging
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse

from rpg_scribe.core.events import (
    SessionEndRequestEvent,
    SummaryRefreshRequestEvent,
)
from rpg_scribe.services.export_service import SessionExportData, SessionExportService
from rpg_scribe.web.state import WebState

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_state() -> WebState:
    from rpg_scribe.web import routes as _routes
    return _routes.router.state  # type: ignore[attr-defined]


def _get_database():
    from rpg_scribe.web import routes as _routes
    return getattr(_routes.router, "database", None)


def _get_config():
    from rpg_scribe.web import routes as _routes
    return getattr(_routes.router, "config", None)


def _get_event_bus():
    from rpg_scribe.web import routes as _routes
    return getattr(_routes.router, "event_bus", None)


def _logs_root() -> Path:
    """Return the base logs directory."""
    return Path("logs").resolve()


def _session_logs_dir(session_id: str) -> Path:
    """Return the logs directory for a session."""
    return (_logs_root() / session_id).resolve()


def _exports_root() -> Path:
    """Return the base directory for immutable session exports."""
    from rpg_scribe.web import routes as _routes
    return Path(getattr(_routes.router, "export_root", Path("exports").resolve())).resolve()


def _get_export_service() -> SessionExportService:
    """Create the export service using the configured exports root."""
    return SessionExportService(_exports_root())


async def _load_session_export_data(session_id: str) -> SessionExportData | None:
    """Load normalized export data for a session from memory and/or DB."""
    state = _get_state()
    db = _get_database()

    live_transcriptions = [
        dict(item)
        for item in state.transcriptions
        if item.get("session_id") == session_id
    ]

    if session_id == state.active_session_id:
        session_row: dict[str, Any] = {}
        transcriptions = live_transcriptions
        if db is not None:
            try:
                session_row = await db.sessions.get_session(session_id) or {}
                transcriptions = [dict(item) for item in await db.transcriptions.get_transcriptions(session_id)]
            except Exception as exc:
                logger.error("Error loading active session row for export: %s", exc)
        return SessionExportData(
            session_id=session_id,
            transcriptions=transcriptions,
            session_summary=state.session_summary or "",
            session_chronology=state.session_chronology or "",
            started_at=session_row.get("started_at", ""),
            ended_at=session_row.get("ended_at", ""),
            status=session_row.get("status", "active") or "active",
            title=session_row.get("title")
        )

    if db is not None:
        try:
            session_row = await db.sessions.get_session(session_id)
            transcriptions = await db.transcriptions.get_transcriptions(session_id)
        except Exception as exc:
            logger.error("Error loading historical session export data: %s", exc)
            session_row = None
            transcriptions = []

        if session_row:
            return SessionExportData(
                session_id=session_id,
                transcriptions=[dict(item) for item in transcriptions],
                session_summary=str(session_row.get("session_summary", "") or ""),
                session_chronology=str(session_row.get("session_chronology", "") or ""),
                started_at=session_row.get("started_at", ""),
                ended_at=session_row.get("ended_at", ""),
                status=str(session_row.get("status", "") or ""),
                title=str(session_row.get("title", "") or ""),
            )

    if live_transcriptions:
        return SessionExportData(
            session_id=session_id,
            transcriptions=live_transcriptions,
            session_summary="",
            session_chronology="",
            status="snapshot",
            title="",
        )

    return None


_SUMMARY_PREVIEW_LEN = 150


def _format_session_list(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Format session rows into a list suitable for the API response."""
    result = []
    for s in sessions:
        summary = s.get("session_summary") or ""
        preview = summary[:_SUMMARY_PREVIEW_LEN]
        if len(summary) > _SUMMARY_PREVIEW_LEN:
            preview += "..."

        started = s.get("started_at")
        ended = s.get("ended_at")
        duration_minutes = None
        if started and ended:
            try:
                duration_minutes = round((float(ended) - float(started)) / 60, 1)
            except (TypeError, ValueError):
                duration_minutes = None

        result.append(
            {
                "id": s["id"],
                "campaign_id": s.get("campaign_id", ""),
                "title": s.get("title", "") or "",
                "started_at": started,
                "ended_at": ended,
                "duration_minutes": duration_minutes,
                "status": s.get("status", ""),
                "summary_preview": preview,
                "has_summary": bool(summary),
            }
        )
    return result


@router.get("/api/sessions/{session_id}/summary")
async def get_summary(session_id: str) -> dict[str, Any]:
    """Return current summary for a session."""
    state = _get_state()

    if session_id == state.active_session_id:
        return {
            "session_id": session_id,
            "session_summary": state.session_summary,
            "session_chronology": state.session_chronology,
            "campaign_summary": state.campaign_summary,
            "last_updated": state.last_summary_update,
        }

    db = _get_database()
    if db is not None:
        try:
            session = await db.sessions.get_session(session_id)
            if session:
                campaign_summary = ""
                campaign_id = session.get("campaign_id", "")
                if campaign_id:
                    campaign = await db.campaigns.get_campaign(campaign_id)
                    if campaign:
                        campaign_summary = campaign.get("campaign_summary", "")
                return {
                    "session_id": session_id,
                    "session_summary": session.get("session_summary", ""),
                    "session_chronology": session.get("session_chronology", ""),
                    "campaign_summary": campaign_summary,
                    "last_updated": session.get("ended_at", 0),
                }
        except Exception as exc:
            logger.error("Error fetching summary from DB: %s", exc)

    if db is None:
        return {
            "session_id": session_id,
            "session_summary": state.session_summary,
            "session_chronology": state.session_chronology,
            "campaign_summary": state.campaign_summary,
            "last_updated": state.last_summary_update,
        }

    return {
        "session_id": session_id,
        "session_summary": "",
        "session_chronology": "",
        "campaign_summary": "",
        "last_updated": 0,
    }


@router.put("/api/sessions/{session_id}/summary")
async def update_session_summary(
    session_id: str, body: dict[str, str]
) -> dict[str, Any]:
    """Update the session summary text (overwrite, no history)."""
    db = _get_database()
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")
    text = body.get("session_summary", "")
    ok = await db.sessions.update_session_summary(session_id, text)
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found")

    state = _get_state()
    if session_id == state.active_session_id:
        state.session_summary = text

    return {"ok": True}


@router.put("/api/sessions/{session_id}/chronology")
async def update_session_chronology(
    session_id: str, body: dict[str, str]
) -> dict[str, Any]:
    """Update the session chronology text (overwrite)."""
    db = _get_database()
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")
    text = body.get("session_chronology", "")
    ok = await db.sessions.update_session_chronology(session_id, text)
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found")

    state = _get_state()
    if session_id == state.active_session_id:
        state.session_chronology = text

    return {"ok": True}


@router.patch("/api/sessions/{session_id}/title")
async def update_session_title(
    session_id: str, body: dict[str, str]
) -> dict[str, Any]:
    """Set or update the human-readable title of a session."""
    db = _get_database()
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")
    title = body.get("title", "")
    ok = await db.sessions.update_session_title(session_id, title)
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": True}


@router.patch("/api/sessions/{session_id}/status")
async def update_session_status(
    session_id: str, body: dict[str, str]
) -> dict[str, Any]:
    """Force-set the status of a session (active or completed).

    Useful for unsticking sessions left active after a crash.
    """
    db = _get_database()
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")
    status = body.get("status", "")
    try:
        ok = await db.sessions.update_session_status(session_id, status)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": True}


@router.post("/api/sessions/{session_id}/generate-title")
async def generate_session_title(session_id: str) -> dict[str, Any]:
    """Auto-generate and save a session title using the LLM (on demand)."""
    db = _get_database()
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")

    session = await db.sessions.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    summary = str(session.get("session_summary") or "")
    config = _get_config()

    from rpg_scribe.core.models import CampaignContext, SummarizerConfig
    from rpg_scribe.summarizers.claude_summarizer import ClaudeSummarizer
    from rpg_scribe.web.routers.campaigns import _load_campaign_context_from_db

    campaign = None
    campaign_id = session.get("campaign_id")
    if campaign_id:
        campaign = await _load_campaign_context_from_db(db, campaign_id)
    if campaign is None:
        campaign = CampaignContext.create_generic()

    summarizer_config = (
        config.summarizer
        if config is not None and getattr(config, "summarizer", None)
        else SummarizerConfig()
    )

    summarizer = ClaudeSummarizer(
        _get_event_bus(),
        summarizer_config,
        campaign,
        database=db,
    )

    title = await summarizer.generate_title_from_summary(summary)
    await db.sessions.update_session_title(session_id, title)
    return {"ok": True, "title": title}


@router.post("/api/sessions/{session_id}/generate-summary")
async def generate_session_summary(session_id: str) -> dict[str, Any]:
    """Generate a narrative summary for an existing session (post-hoc)."""
    state = _get_state()
    event_bus = _get_event_bus()
    db = _get_database()

    if (
        state.active_session_id == session_id
        and event_bus is not None
    ):
        await event_bus.publish(
            SummaryRefreshRequestEvent(session_id=session_id, source="web")
        )
        return {"ok": True, "session_summary": "", "mode": "live_refresh"}

    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")

    session = await db.sessions.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    rows = await db.transcriptions.get_transcriptions(session_id)
    if not rows:
        raise HTTPException(
            status_code=400,
            detail="No transcriptions found for this session",
        )

    config = _get_config()

    from rpg_scribe.core.models import CampaignContext, SummarizerConfig
    from rpg_scribe.summarizers.claude_summarizer import ClaudeSummarizer
    from rpg_scribe.web.routers.campaigns import _load_campaign_context_from_db

    campaign = None
    campaign_id = session.get("campaign_id")
    if campaign_id:
        campaign = await _load_campaign_context_from_db(db, campaign_id)
    if campaign is None:
        campaign = CampaignContext.create_generic()

    summarizer_config = (
        config.summarizer
        if config is not None and getattr(config, "summarizer", None)
        else SummarizerConfig()
    )

    from rpg_scribe.core.event_bus import EventBus as _EventBus

    summarizer = ClaudeSummarizer(
        event_bus or _EventBus(),
        summarizer_config,
        campaign,
        database=db,
    )

    summary = await summarizer.generate_session_summary_from_transcriptions(rows)
    if summary:
        await db.sessions.update_session_summary(session_id, summary)
        if session_id == state.active_session_id:
            state.session_summary = summary

    return {"ok": True, "session_summary": summary or ""}


@router.post("/api/sessions/{session_id}/generate-chronology")
async def generate_session_chronology(session_id: str) -> dict[str, Any]:
    """Generate a chronological timeline for an existing session (post-hoc)."""
    db = _get_database()
    config = _get_config()
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")

    session = await db.sessions.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    session_summary = session.get("session_summary", "") or ""
    rows = await db.transcriptions.get_transcriptions(session_id)
    if not rows:
        raise HTTPException(
            status_code=400,
            detail="No transcriptions found for this session",
        )

    from rpg_scribe.core.models import CampaignContext, SummarizerConfig
    from rpg_scribe.summarizers.claude_summarizer import ClaudeSummarizer
    from rpg_scribe.web.routers.campaigns import _load_campaign_context_from_db

    campaign = None
    campaign_id = session.get("campaign_id")
    if campaign_id:
        campaign = await _load_campaign_context_from_db(db, campaign_id)
    if campaign is None:
        campaign = CampaignContext.create_generic()
    summarizer_config = (
        config.summarizer
        if config is not None and getattr(config, "summarizer", None)
        else SummarizerConfig()
    )

    summarizer = ClaudeSummarizer(
        _get_event_bus(),
        summarizer_config,
        campaign,
        database=db,
    )

    chronology = await summarizer.generate_chronology_from_transcriptions(
        [dict(r) for r in rows], session_id=session_id
    )
    await db.sessions.update_session_chronology(session_id, chronology)

    state = _get_state()
    if session_id == state.active_session_id:
        state.session_chronology = chronology

    return {"ok": True, "session_chronology": chronology}


@router.get("/api/sessions")
async def list_all_sessions() -> dict[str, Any]:
    """Return all sessions across campaigns, ordered by date descending."""
    db = _get_database()
    if db is None:
        return {"sessions": []}
    try:
        sessions = await db.sessions.list_all_sessions()
    except Exception as exc:
        logger.error("Error listing all sessions: %s", exc)
        return {"sessions": []}
    return {"sessions": _format_session_list(sessions)}


@router.get("/api/browse/sessions/uncategorized")
async def list_uncategorized_sessions() -> dict[str, Any]:
    """Return sessions not linked to any campaign."""
    db = _get_database()
    if db is None:
        return {"sessions": []}
    try:
        sessions = await db.sessions.list_uncategorized_sessions()
    except Exception as exc:
        logger.error("Error listing uncategorized sessions: %s", exc)
        return {"sessions": []}
    return {"sessions": _format_session_list(sessions)}


@router.get("/api/campaigns/{campaign_id}/sessions")
async def list_campaign_sessions(campaign_id: str) -> dict[str, Any]:
    """Return all sessions for a campaign, ordered by date descending."""
    db = _get_database()
    if db is None:
        return {"sessions": []}
    try:
        sessions = await db.sessions.list_sessions(campaign_id)
    except Exception as exc:
        logger.error("Error listing campaign sessions: %s", exc)
        return {"sessions": []}
    return {"sessions": _format_session_list(sessions)}


@router.get("/api/sessions/{session_id}/logs")
async def get_session_logs(session_id: str) -> dict[str, Any]:
    """Return log artifacts available for a session."""
    session_dir = _session_logs_dir(session_id)
    if not session_dir.is_dir():
        return {
            "session_id": session_id,
            "exists": False,
            "explorer_url": None,
            "files": [],
        }

    files: list[dict[str, Any]] = []
    for path in sorted(session_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(session_dir).as_posix()
        files.append(
            {
                "name": rel,
                "size": path.stat().st_size,
                "url": f"/api/sessions/{session_id}/logs/file/{quote(rel)}",
            }
        )

    return {
        "session_id": session_id,
        "exists": True,
        "explorer_url": f"/api/sessions/{session_id}/logs/explorer",
        "files": files,
    }


@router.get("/api/sessions/{session_id}/logs/file/{file_path:path}")
async def get_session_log_file(session_id: str, file_path: str) -> FileResponse:
    """Serve one log artifact file for a session."""
    session_dir = _session_logs_dir(session_id)
    if not session_dir.is_dir():
        raise HTTPException(status_code=404, detail="Session logs not found")

    target = (session_dir / file_path).resolve()
    if session_dir not in target.parents or not target.is_file():
        raise HTTPException(status_code=404, detail="Log file not found")

    return FileResponse(path=target, filename=target.name)


@router.get("/api/sessions/{session_id}/logs/explorer")
async def get_session_logs_explorer(session_id: str) -> HTMLResponse:
    """Render a simple file explorer page for session logs."""
    session_dir = _session_logs_dir(session_id)
    if not session_dir.is_dir():
        return HTMLResponse(
            "<h1>Logs not found</h1><p>No log folder for this session.</p>",
            status_code=404,
        )

    items: list[str] = []
    for path in sorted(session_dir.rglob("*")):
        rel = path.relative_to(session_dir).as_posix()
        safe_rel = html.escape(rel)
        if path.is_dir():
            items.append(f"<li><strong>{safe_rel}/</strong></li>")
            continue
        file_url = f"/api/sessions/{session_id}/logs/file/{quote(rel)}"
        size = path.stat().st_size
        items.append(
            f'<li><a href="{file_url}" target="_blank" rel="noopener">{safe_rel}</a> '
            f"<span>({size} bytes)</span></li>"
        )

    title = html.escape(f"Session {session_id} logs")
    body = "\n".join(items) if items else "<li>No files found.</li>"
    page = (
        '<!DOCTYPE html><html><head><meta charset="utf-8" />'
        f"<title>{title}</title>"
        "<style>body{font-family:Segoe UI,Arial,sans-serif;padding:1rem;}"
        "ul{line-height:1.6;}span{color:#666;}</style></head><body>"
        f"<h1>{title}</h1><p>Directory: {html.escape(str(session_dir))}</p>"
        f"<ul>{body}</ul></body></html>"
    )
    return HTMLResponse(page)


@router.post("/api/sessions/{session_id}/export")
async def create_session_export(session_id: str) -> dict[str, Any]:
    """Generate a new immutable export bundle for a session."""
    data = await _load_session_export_data(session_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Session not found")

    service = _get_export_service()
    manifest = service.build_export(data)
    export_id = str(manifest["export_id"])
    return {
        "ok": True,
        "session_id": session_id,
        "export_id": export_id,
        "exported_at": manifest.get("created_at", ""),
        "display_date": manifest.get("display_date", ""),
        "export_dir": manifest.get("export_dir", ""),
        "zip_name": manifest.get("zip_name", ""),
        "files": manifest.get("files", []),
        "download_url": (
            f"/api/sessions/{quote(session_id)}/export/download"
            f"?export_id={quote(export_id)}"
        ),
    }


@router.get("/api/sessions/{session_id}/exports")
async def list_session_exports(session_id: str) -> dict[str, Any]:
    """List immutable export bundles previously generated for a session."""
    service = _get_export_service()
    exports = []
    for item in service.list_exports(session_id):
        export_id = str(item.get("export_id", ""))
        exports.append(
            {
                "session_id": item.get("session_id", session_id),
                "export_id": export_id,
                "created_at": item.get("created_at", ""),
                "display_date": item.get("display_date", ""),
                "status": item.get("status", ""),
                "zip_name": item.get("zip_name", ""),
                "files": item.get("files", []),
                "download_url": (
                    f"/api/sessions/{quote(session_id)}/export/download"
                    f"?export_id={quote(export_id)}"
                ),
            }
        )
    return {"session_id": session_id, "exports": exports}


@router.get("/api/sessions/{session_id}/export/download")
async def download_session_export(
    session_id: str,
    export_id: str = Query(default=""),
) -> FileResponse:
    """Download one concrete version of a session export bundle."""
    if not export_id.strip():
        raise HTTPException(status_code=400, detail="export_id is required")

    service = _get_export_service()
    zip_path = service.get_export_zip(session_id, export_id)
    if zip_path is None:
        raise HTTPException(status_code=404, detail="Export not found")
    return FileResponse(path=zip_path, filename=zip_path.name, media_type="application/zip")


@router.post("/api/sessions/{session_id}/finalize")
async def finalize_session(session_id: str) -> dict[str, Any]:
    """Trigger finalization of the active session from the web UI."""
    state = _get_state()
    event_bus = _get_event_bus()

    if event_bus is None:
        return {"ok": False, "error": "Event bus not available"}

    if state.active_session_id is None:
        return {"ok": False, "error": "No active session"}

    if state.active_session_id != session_id:
        return {"ok": False, "error": "Session ID does not match active session"}

    await event_bus.publish(SessionEndRequestEvent(session_id=session_id, source="web"))
    state.active_session_id = None
    return {"ok": True, "status": "finalizing"}


@router.post("/api/sessions/{session_id}/extract-entities")
async def extract_entities(session_id: str) -> dict[str, Any]:
    """Trigger entity extraction (NPCs, locations, relationships) for a session."""
    state = _get_state()
    db = _get_database()
    config = _get_config()
    event_bus = _get_event_bus()

    if db is None:
        return {"ok": False, "error": "Database not available"}

    session_row = None
    if session_id == state.active_session_id:
        session_summary = state.session_summary
    else:
        try:
            session_row = await db.sessions.get_session(session_id)
        except Exception as exc:
            return {"ok": False, "error": f"Session not found: {exc}"}
        if not session_row:
            return {"ok": False, "error": "Session not found"}
        session_summary = session_row.get("session_summary", "")

    if not session_summary:
        return {"ok": False, "error": "No session summary available to extract from"}

    campaign_id = None
    if session_row:
        campaign_id = session_row.get("campaign_id")
    elif state.active_campaign:
        campaign_id = state.active_campaign.get("id")

    from rpg_scribe.web.routers.campaigns import _load_campaign_context_from_db

    campaign = None
    if campaign_id:
        campaign = await _load_campaign_context_from_db(db, campaign_id)
    if campaign is None:
        return {"ok": False, "error": "No campaign found for this session"}

    try:
        from rpg_scribe.summarizers.claude_summarizer import ClaudeSummarizer
        from rpg_scribe.core.models import SummarizerConfig

        summarizer_config = (
            config.summarizer
            if config is not None and getattr(config, "summarizer", None)
            else SummarizerConfig()
        )
        summarizer = ClaudeSummarizer(
            event_bus,
            summarizer_config,
            campaign,
            database=db,
        )
        results = await summarizer.extract_entities_from_summary(
            session_id, session_summary
        )
        if any(results.values()):
            from rpg_scribe.core.events import EntitiesUpdatedEvent

            await event_bus.publish(
                EntitiesUpdatedEvent(
                    campaign_id=campaign.campaign_id,
                    session_id=session_id,
                    new_npcs=tuple(results["new_npcs"]),
                    new_locations=tuple(results["new_locations"]),
                    new_entities=tuple(results["new_entities"]),
                    new_relationships=tuple(results["new_relationships"]),
                )
            )
        return {"ok": True, **results}
    except Exception as exc:
        logger.error("Entity extraction failed for session %s: %s", session_id, exc)
        return {"ok": False, "error": str(exc)}


@router.post("/api/sessions/{session_id}/refresh-summary")
async def refresh_summary(session_id: str) -> dict[str, Any]:
    """Trigger an on-demand summary refresh for the active session."""
    state = _get_state()
    event_bus = _get_event_bus()

    if event_bus is None:
        return {"ok": False, "error": "Event bus not available"}

    if state.active_session_id is None:
        return {"ok": False, "error": "No active session"}

    if state.active_session_id != session_id:
        return {"ok": False, "error": "Session ID does not match active session"}

    await event_bus.publish(
        SummaryRefreshRequestEvent(session_id=session_id, source="web")
    )
    return {"ok": True, "status": "refresh_requested"}


@router.post("/api/sessions/merge")
async def merge_sessions_endpoint(body: dict[str, Any]) -> dict[str, Any]:
    """Merge one session into another, combining transcriptions and summaries."""
    db = _get_database()
    if db is None:
        return {"ok": False, "error": "Database not available"}

    source_id = str(body.get("source_id", "")).strip()
    target_id = str(body.get("target_id", "")).strip()
    if not source_id or not target_id:
        return {"ok": False, "error": "source_id and target_id are required"}

    try:
        await db.sessions.merge_sessions(source_id, target_id)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    return {"ok": True, "target_session_id": target_id}
