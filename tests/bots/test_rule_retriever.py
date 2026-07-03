"""Tests de RuleRetriever: fusión híbrida y follow de página (1 salto)."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from rag_lib.store import Database
from rpg_scribe.bots.rules.retriever import RuleRetriever, _PAGE_RE
from tests.rag_lib.conftest import FakeEmbedder


async def _retriever_db(tmp_path: Path) -> tuple[str, int, list[int]]:
    """Manual con: pág 1 (menciona 'ver pág. 2'), pág 1 (otra), pág 2 (destino)."""
    db_path = str(tmp_path / "retr.db")
    db = Database(db_path)
    await db.connect()
    manual_id = await db.manuals.insert(
        name="Manual A",
        source_path="a.pdf",
        source_hash="sha_r",
        page_count=2,
        file_size=10,
        parser="pdfplumber",
    )
    chunks = [
        {
            "seq": 0,
            "chunk_type": "prose",
            "page": 1,
            "page_end": None,
            "section_path": "Hackeo",
            "text": "Para el hackeo de sistemas ver pág. 2 donde se detalla el proceso.",
            "text_hash": "r1",
            "token_count": 12,
        },
        {
            "seq": 1,
            "chunk_type": "prose",
            "page": 1,
            "page_end": None,
            "section_path": "Combate",
            "text": "El combate cuerpo a cuerpo no tiene relación con esto.",
            "text_hash": "r2",
            "token_count": 10,
        },
        {
            "seq": 2,
            "chunk_type": "prose",
            "page": 2,
            "page_end": None,
            "section_path": "Hackeo / Detalle",
            "text": "El hackeo requiere superar la tirada de Interface contra la dificultad.",
            "text_hash": "r3",
            "token_count": 11,
        },
    ]
    ids = await db.chunks.insert_many(manual_id, chunks)
    emb = FakeEmbedder()
    vecs = await emb.embed([c["text"] for c in chunks])
    await db.embeddings.upsert_many(
        [
            {
                "chunk_id": cid,
                "vector_bytes": np.array(v, dtype=np.float32).tobytes(),
                "dim": emb.dim,
                "model": emb.model,
            }
            for cid, v in zip(ids, vecs)
        ]
    )
    await db.close()
    return db_path, manual_id, ids


async def test_retrieve_returns_chunks(tmp_path):
    db_path, manual_id, _ = await _retriever_db(tmp_path)
    retriever = RuleRetriever(db_path, [manual_id], top_k=8, embedder=FakeEmbedder())
    results = await retriever.retrieve("hackeo")
    assert results, "debe devolver al menos un chunk"
    assert all(c.manual_id == manual_id for c in results)


async def test_retrieve_follows_page_reference(tmp_path):
    """El chunk que dice 'ver pág. 2' arrastra el chunk de la página 2."""
    db_path, manual_id, ids = await _retriever_db(tmp_path)
    retriever = RuleRetriever(db_path, [manual_id], top_k=8, embedder=FakeEmbedder())
    results = await retriever.retrieve("hackeo")
    pages = {c.page for c in results}
    assert 2 in pages, "el follow de página debe traer la página 2"
    result_ids = [c.id for c in results]
    assert len(result_ids) == len(set(result_ids))


async def test_retrieve_empty_when_no_manuals(tmp_path):
    db_path, _, _ = await _retriever_db(tmp_path)
    retriever = RuleRetriever(db_path, [], top_k=8, embedder=FakeEmbedder())
    assert await retriever.retrieve("hackeo") == []


async def test_retrieve_blank_question_returns_empty(tmp_path):
    db_path, manual_id, _ = await _retriever_db(tmp_path)
    retriever = RuleRetriever(db_path, [manual_id], top_k=8, embedder=FakeEmbedder())
    assert await retriever.retrieve("   ") == []


def test_page_regex_ignores_non_page_abbreviations():
    assert _PAGE_RE.findall("ver pág. 2 y página 5 y p. 7") == ["2", "5", "7"]
    assert _PAGE_RE.findall("ver cap. 2, exp. 3, comp. 4") == []


async def test_retrieve_handles_natural_language_punctuation(tmp_path):
    """Una pregunta en LN con puntuación no debe romper FTS5.

    Regresión: 'fts5: syntax error near "."'. La pregunta se pasaba en crudo
    al MATCH de FTS5, que interpreta '.', '?', '(' como sintaxis de consulta.
    """
    db_path, manual_id, _ = await _retriever_db(tmp_path)
    retriever = RuleRetriever(db_path, [manual_id], top_k=8, embedder=FakeEmbedder())
    results = await retriever.retrieve("Dime cómo funciona el hackeo.")
    assert results, "debe recuperar chunks pese a la puntuación"
    assert any("hackeo" in c.text.lower() for c in results)


def test_to_fts_query_strips_punctuation_stopwords_and_ors():
    from rpg_scribe.bots.rules.retriever import _to_fts_query

    # tokens de contenido citados y unidos con OR; stopwords y puntuación fuera
    assert _to_fts_query("Dime cómo funciona el netrunning.") == '"funciona" OR "netrunning"'
    assert _to_fts_query("¿daño?") == '"daño"'
    assert _to_fts_query("armas (pesadas)") == '"armas" OR "pesadas"'
    # solo stopwords → query vacía (search_fts la trata como sin resultados)
    assert _to_fts_query("el la de") == ""
