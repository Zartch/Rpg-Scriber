"""Tests for the CLI (python -m rag_lib)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from rag_lib.cli import _build_parser, _dispatch
from tests.rag_lib.conftest import FakeEmbedder


async def _run(args: list[str]) -> int:
    """Parse args and dispatch directly, avoiding asyncio.run() re-entry."""
    parser = _build_parser()
    try:
        parsed = parser.parse_args(args)
        await _dispatch(parsed)
        return 0
    except SystemExit as e:
        return int(e.code) if e.code is not None else 0


@pytest.fixture(autouse=True)
def patch_openai_embedder():
    """Replace OpenAIEmbedder with FakeEmbedder for all CLI tests."""
    with patch("rag_lib.OpenAIEmbedder", FakeEmbedder):
        yield


async def test_ingest_creates_db(simple_pdf: Path, tmp_path: Path) -> None:
    db = tmp_path / "rag.db"
    code = await _run(["ingest", str(simple_pdf), "--name", "Simple", "--db", str(db)])
    assert code == 0
    assert db.exists()


async def test_ingest_twice_is_idempotent(simple_pdf: Path, tmp_path: Path) -> None:
    db = tmp_path / "rag.db"
    await _run(["ingest", str(simple_pdf), "--name", "Simple", "--db", str(db)])
    code = await _run(["ingest", str(simple_pdf), "--name", "Simple", "--db", str(db)])
    assert code == 0


async def test_list_shows_ingested_manual(simple_pdf: Path, tmp_path: Path) -> None:
    db = tmp_path / "rag.db"
    await _run(["ingest", str(simple_pdf), "--name", "My Book", "--db", str(db)])
    code = await _run(["list", "--db", str(db)])
    assert code == 0


async def test_delete_removes_manual(simple_pdf: Path, tmp_path: Path) -> None:
    db = tmp_path / "rag.db"
    await _run(["ingest", str(simple_pdf), "--name", "Del", "--db", str(db)])
    code = await _run(["delete", "1", "--db", str(db)])
    assert code == 0


async def test_delete_missing_manual_exits_nonzero(tmp_path: Path) -> None:
    db = tmp_path / "rag.db"
    await _run(["list", "--db", str(db)])
    code = await _run(["delete", "9999", "--db", str(db)])
    assert code != 0


async def test_show_lists_chunks(simple_pdf: Path, tmp_path: Path) -> None:
    db = tmp_path / "rag.db"
    await _run(["ingest", str(simple_pdf), "--name", "Show Test", "--db", str(db)])
    code = await _run(["show", "1", "--db", str(db)])
    assert code == 0
