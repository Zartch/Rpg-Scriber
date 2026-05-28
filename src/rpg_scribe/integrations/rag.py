"""Mount rag_lib's web router into the RPG Scribe FastAPI app."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

import rag_lib.web


def mount_rag(app: FastAPI, rag_db_path: str | Path) -> None:
    """Include the rag_lib router in *app* using the given DB path."""
    router = rag_lib.web.build_router(rag_db_path)
    app.include_router(router)

    rag_static = Path(rag_lib.web.__file__).parent / "static"
    app.mount("/rag-static", StaticFiles(directory=str(rag_static)), name="rag_static")
