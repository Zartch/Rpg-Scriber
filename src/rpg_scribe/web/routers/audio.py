"""Audio chunk retrain/discard endpoints."""
from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


def _audio_base() -> Path:
    return Path.cwd() / "data" / "audio"


def _do_discard(session_id: str, filename: str) -> None:
    base = _audio_base()
    src = base / session_id / filename
    if not src.exists():
        return
    dest_dir = base / "discard" / session_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(src, dest_dir / filename)


async def _move_audio_to_discard(session_id: str, filename: str) -> None:
    """Move audio file to discard folder. Silently skips if file not found."""
    await asyncio.to_thread(_do_discard, session_id, filename)


def _do_retrain(session_id: str, filename: str, body: dict[str, Any]) -> bool:
    """Returns False if source wav not found."""
    base = _audio_base()
    src = base / session_id / filename
    if not src.exists():
        return False
    dest_dir = base / "retrain" / session_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest_dir / filename)
    stem = Path(filename).stem
    (dest_dir / f"{stem}.json").write_text(
        json.dumps(
            {
                "original": body.get("original", ""),
                "corrected": body.get("corrected", ""),
                "speaker": body.get("speaker", ""),
                "timestamp": body.get("timestamp", 0),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return True


@router.post("/api/audio/{session_id}/{filename}/retrain")
async def mark_retrain(
    session_id: str, filename: str, body: dict[str, Any]
) -> dict[str, Any]:
    ok = await asyncio.to_thread(_do_retrain, session_id, filename, body)
    if not ok:
        raise HTTPException(status_code=404, detail="Audio file not found")
    return {"ok": True}


@router.post("/api/audio/{session_id}/{filename}/discard")
async def mark_discard(session_id: str, filename: str) -> dict[str, Any]:
    await _move_audio_to_discard(session_id, filename)
    return {"ok": True}
