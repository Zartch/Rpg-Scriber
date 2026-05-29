"""Mount rag_lib's web router into the RPG Scribe FastAPI app."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.types import Receive, Scope, Send

import rag_lib.web


class _NoCacheStaticFiles(StaticFiles):
    """StaticFiles that disables browser caching — UI assets update without hard-reload."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers = [(k, v) for (k, v) in headers if k.lower() != b"cache-control"]
                headers.append((b"cache-control", b"no-cache, no-store, must-revalidate"))
                message["headers"] = headers
            await send(message)
        await super().__call__(scope, receive, send_wrapper)


def mount_rag(app: FastAPI, rag_db_path: str | Path) -> None:
    """Include the rag_lib router in *app* using the given DB path."""
    router = rag_lib.web.build_router(rag_db_path)
    app.include_router(router)

    rag_static = Path(rag_lib.web.__file__).parent / "static"
    app.mount("/rag-static", _NoCacheStaticFiles(directory=str(rag_static)), name="rag_static")
