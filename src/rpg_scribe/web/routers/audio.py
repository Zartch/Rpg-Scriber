"""Audio chunk retrain/discard endpoints."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


def _audio_base() -> Path:
    return Path.cwd() / "data" / "audio"


async def _move_audio_to_discard(session_id: str, filename: str) -> None:
    """Move audio file to discard folder. Silently skips if file not found."""
    base = _audio_base()
    src = base / session_id / filename
    if not src.exists():
        return
    dest_dir = base / "discard" / session_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), dest_dir / filename)


@router.post("/api/audio/{session_id}/{filename}/retrain")
async def mark_retrain(
    session_id: str, filename: str, body: dict[str, Any]
) -> dict[str, Any]:
    base = _audio_base()
    src = base / session_id / filename
    if not src.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")

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
    return {"ok": True}


@router.post("/api/audio/{session_id}/{filename}/discard")
async def mark_discard(session_id: str, filename: str) -> dict[str, Any]:
    await _move_audio_to_discard(session_id, filename)
    return {"ok": True}
