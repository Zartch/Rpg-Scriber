"""Tests for chunking logic — run BEFORE implementing chunking.py."""
from __future__ import annotations


from rag_lib.chunking import gfm_table, run_chunker, should_merge_across_pages
from rag_lib.types import ParsedPage, ProseBlock, TableBlock


# ---------------------------------------------------------------------------
# gfm_table
# ---------------------------------------------------------------------------

def test_gfm_table_basic_structure() -> None:
    rows = [["Arma", "Daño"], ["Espada", "1d8"]]
    result = gfm_table(rows)
    lines = result.splitlines()
    assert lines[0] == "| Arma | Daño |"
    assert lines[1] == "| --- | --- |"
    assert lines[2] == "| Espada | 1d8 |"


def test_gfm_table_newline_in_cell_replaced_by_space() -> None:
    rows = [["Col"], ["line1\nline2"]]
    result = gfm_table(rows)
    # Cell content must not contain a raw newline — it should be replaced by a space
    data_line = result.splitlines()[-1]  # last line = the data row
    assert "\n" not in data_line
    assert "line1 line2" in data_line


def test_gfm_table_pipe_in_cell_escaped() -> None:
    rows = [["Hechizo"], ["Bola de fuego | Rayo"]]
    result = gfm_table(rows)
    assert r"Bola de fuego \| Rayo" in result


def test_gfm_table_empty_input_returns_empty_string() -> None:
    assert gfm_table([]) == ""


def test_gfm_table_ragged_rows_normalized() -> None:
    # Row 0 has 3 cols, row 1 only 2 — should pad to 3
    rows = [["A", "B", "C"], ["1", "2"]]
    result = gfm_table(rows)
    assert result.count("|") == (3 + 1) * 3  # 4 pipes per row × 3 rows


# ---------------------------------------------------------------------------
# should_merge_across_pages
# ---------------------------------------------------------------------------

def test_no_merge_when_last_ends_with_period() -> None:
    assert not should_merge_across_pages("Esto termina con punto.", "continua sin mayúscula")


def test_no_merge_when_next_starts_uppercase() -> None:
    assert not should_merge_across_pages("sin terminador", "Empieza con mayúscula")


def test_merge_when_no_terminator_and_next_lowercase() -> None:
    assert should_merge_across_pages("sin terminador", "continúa en minúscula")


def test_no_merge_exclamation_terminator() -> None:
    assert not should_merge_across_pages("¡Qué bien!", "siguiente párrafo")


def test_no_merge_question_terminator() -> None:
    assert not should_merge_across_pages("¿Por qué?", "respuesta aquí")


def test_no_merge_ellipsis_terminator() -> None:
    assert not should_merge_across_pages("Y así sucesivamente…", "continuando")


def test_merge_returns_false_for_empty_inputs() -> None:
    assert not should_merge_across_pages("", "algo")
    assert not should_merge_across_pages("algo", "")


# ---------------------------------------------------------------------------
# run_chunker — prose splitting
# ---------------------------------------------------------------------------

def _make_prose_page(text: str, page: int = 1, fontsize: float = 11.0) -> ParsedPage:
    return ParsedPage(page_num=page, blocks=[ProseBlock(text=text, page=page, fontsize_avg=fontsize)])


def _make_table_page(rows: list[list[str]], page: int = 1) -> ParsedPage:
    return ParsedPage(
        page_num=page,
        blocks=[TableBlock(rows=rows, page=page, caption="Tabla de prueba")],
    )


SHORT_WORD = "palabra "
LONG_PROSE = SHORT_WORD * 600  # ~600 palabras ≈ ~800 tokens (above 500 target)


def test_long_prose_splits_into_multiple_chunks() -> None:
    pages = [_make_prose_page(LONG_PROSE)]
    chunks = run_chunker(pages, token_target=500, overlap=75)
    assert len(chunks) >= 2


def test_chunks_respect_token_target_with_tolerance() -> None:
    pages = [_make_prose_page(LONG_PROSE)]
    chunks = run_chunker(pages, token_target=500, overlap=75)
    for c in chunks[:-1]:  # last chunk can be smaller
        assert c["token_count"] <= 600  # target + some tolerance


def test_table_block_becomes_single_atomic_chunk() -> None:
    table_rows = [["Arma", "Daño"], ["Espada", "1d8"], ["Daga", "1d4"]]
    pages = [_make_table_page(table_rows)]
    chunks = run_chunker(pages)
    assert len(chunks) == 1
    assert chunks[0]["chunk_type"] == "table"


def test_table_chunk_text_contains_gfm_table() -> None:
    table_rows = [["Arma", "Daño"], ["Espada", "1d8"]]
    pages = [_make_table_page(table_rows)]
    chunks = run_chunker(pages)
    assert "| Arma | Daño |" in chunks[0]["text"]


def test_table_chunk_text_prefixed_with_section_path() -> None:
    table_rows = [["A", "B"], ["1", "2"]]
    page = ParsedPage(
        page_num=1,
        blocks=[TableBlock(rows=table_rows, page=1, caption="Mi tabla")],
    )
    chunks = run_chunker([page])
    # section_path is None here but caption should appear
    assert "Mi tabla" in chunks[0]["text"]


def test_chunks_have_required_keys() -> None:
    pages = [_make_prose_page("Hola mundo " * 10)]
    chunks = run_chunker(pages)
    for c in chunks:
        for key in ("seq", "chunk_type", "page", "page_end", "section_path",
                    "text", "text_hash", "token_count"):
            assert key in c, f"Missing key: {key}"


def test_chunk_text_hash_is_sha256_hex() -> None:
    pages = [_make_prose_page("Texto de prueba")]
    chunks = run_chunker(pages)
    import hashlib
    for c in chunks:
        expected = hashlib.sha256(c["text"].encode()).hexdigest()
        assert c["text_hash"] == expected


def test_seq_is_zero_indexed_and_sequential() -> None:
    pages = [_make_prose_page(LONG_PROSE)]
    chunks = run_chunker(pages, token_target=500, overlap=75)
    assert [c["seq"] for c in chunks] == list(range(len(chunks)))


# ---------------------------------------------------------------------------
# Heading detection — section_path propagation
# ---------------------------------------------------------------------------

def test_heading_block_propagates_to_subsequent_prose_chunks() -> None:
    # Need enough body blocks so p90(fontsize) ≈ 11.0 and 18.0 > p90
    h1_block = ProseBlock(text="Capítulo 1: Combate", page=1, fontsize_avg=18.0)
    body_blocks = [
        ProseBlock(text=f"El combate se resuelve con dados. Turno {i}. " * 5, page=1, fontsize_avg=11.0)
        for i in range(20)
    ]
    page = ParsedPage(page_num=1, blocks=[h1_block] + body_blocks)
    chunks = run_chunker([page])
    body_chunks = [c for c in chunks if c["chunk_type"] == "prose" and c["section_path"]]
    assert len(body_chunks) >= 1
    assert "Combate" in body_chunks[0]["section_path"]
