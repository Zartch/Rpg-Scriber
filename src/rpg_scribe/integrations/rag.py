"""Mount rag_lib's web router into the RPG Scribe FastAPI app."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

import rag_lib.web


def mount_rag(app: FastAPI, rag_db_path: str | Path) -> None:
    """Include the rag_lib router in *app* using the given DB path."""
    router = rag_lib.web.build_router(rag_db_path)
    app.include_router(router)
