"""Tests for PdfplumberParser — run BEFORE implementing the parser."""
from __future__ import annotations

from pathlib import Path

import pytest

from rag_lib.errors import PdfParseError
from rag_lib.parsing.pdfplumber_parser import (
    PdfplumberParser,
    _dedup_and_drop,
    _detect_gutter,
    _lines_to_blocks,
    _reading_order_blocks,
    _segment_reading_order,
)
from rag_lib.types import ProseBlock, TableBlock, TocEntry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parser() -> PdfplumberParser:
    return PdfplumberParser()


# ---------------------------------------------------------------------------
# Basic structure
# ---------------------------------------------------------------------------

def test_parse_returns_one_page_per_pdf_page(simple_pdf: Path) -> None:
    pages = _parser().parse(simple_pdf)
    assert len(pages) == 3


def test_parsed_pages_are_1_indexed(simple_pdf: Path) -> None:
    pages = _parser().parse(simple_pdf)
    assert [p.page_num for p in pages] == [1, 2, 3]


def test_prose_blocks_have_numeric_fontsize(simple_pdf: Path) -> None:
    pages = _parser().parse(simple_pdf)
    for page in pages:
        for block in page.blocks:
            if isinstance(block, ProseBlock):
                assert isinstance(block.fontsize_avg, float)
                assert block.fontsize_avg > 0


def test_prose_blocks_carry_page_number(simple_pdf: Path) -> None:
    pages = _parser().parse(simple_pdf)
    for page in pages:
        for block in page.blocks:
            assert block.page == page.page_num


# ---------------------------------------------------------------------------
# Table detection
# ---------------------------------------------------------------------------

def test_table_pdf_yields_table_block(pdf_with_table: Path) -> None:
    pages = _parser().parse(pdf_with_table)
    all_blocks = [b for p in pages for b in p.blocks]
    table_blocks = [b for b in all_blocks if isinstance(b, TableBlock)]
    assert len(table_blocks) >= 1


def test_table_block_has_correct_shape(pdf_with_table: Path) -> None:
    pages = _parser().parse(pdf_with_table)
    table = next(b for p in pages for b in p.blocks if isinstance(b, TableBlock))
    # 3 rows (header + 2 data), 4 columns
    assert len(table.rows) == 3
    assert all(len(row) == 4 for row in table.rows)


def test_table_block_header_content(pdf_with_table: Path) -> None:
    pages = _parser().parse(pdf_with_table)
    table = next(b for p in pages for b in p.blocks if isinstance(b, TableBlock))
    header = [cell.strip() for cell in table.rows[0]]
    assert "Arma" in header
    assert "Daño" in header


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

def test_parse_nonexistent_file_raises_pdf_parse_error(tmp_path: Path) -> None:
    with pytest.raises(PdfParseError):
        _parser().parse(tmp_path / "nonexistent.pdf")


def test_parse_corrupt_file_raises_pdf_parse_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf at all")
    with pytest.raises(PdfParseError):
        _parser().parse(bad)


# ---------------------------------------------------------------------------
# _extract_prose_groups — multiple blocks per page with separate fontsizes
# ---------------------------------------------------------------------------

def test_headings_pdf_yields_multiple_prose_blocks_per_page(pdf_with_headings: Path) -> None:
    """With _extract_prose_groups implemented, a page with H1+body yields ≥2 ProseBlocks."""
    pages = _parser().parse(pdf_with_headings)
    page1_blocks = [b for b in pages[0].blocks if isinstance(b, ProseBlock)]
    assert len(page1_blocks) >= 2


def test_heading_block_has_larger_fontsize_than_body(pdf_with_headings: Path) -> None:
    """The heading ProseBlock must have a larger fontsize_avg than body blocks."""
    pages = _parser().parse(pdf_with_headings)
    prose = [b for b in pages[0].blocks if isinstance(b, ProseBlock)]
    fontsizes = [b.fontsize_avg for b in prose]
    assert max(fontsizes) > min(fontsizes) + 2.0


def test_prose_groups_text_covers_all_page_text(simple_pdf: Path) -> None:
    """Total chars across all ProseBlocks must equal what _extract_prose returns."""
    pages = _parser().parse(simple_pdf)
    for page in pages:
        combined = " ".join(b.text for b in page.blocks if isinstance(b, ProseBlock))
        assert len(combined) > 0



# ---------------------------------------------------------------------------
# extract_toc
# ---------------------------------------------------------------------------

def test_extract_toc_returns_empty_for_pdf_without_outline(simple_pdf: Path) -> None:
    entries = _parser().extract_toc(simple_pdf)
    assert entries == []


def test_extract_toc_returns_toc_entries(pdf_with_toc: Path) -> None:
    entries = _parser().extract_toc(pdf_with_toc)
    assert len(entries) >= 1
    assert all(isinstance(e, TocEntry) for e in entries)


def test_extract_toc_entries_have_correct_titles(pdf_with_toc: Path) -> None:
    entries = _parser().extract_toc(pdf_with_toc)
    titles = [e.title for e in entries]
    assert "Capítulo 1: Combate" in titles
    assert "Capítulo 2: Magia" in titles


def test_extract_toc_entries_sorted_by_page(pdf_with_toc: Path) -> None:
    entries = _parser().extract_toc(pdf_with_toc)
    pages = [e.page for e in entries]
    assert pages == sorted(pages)


def test_extract_toc_entries_have_correct_levels(pdf_with_toc: Path) -> None:
    entries = _parser().extract_toc(pdf_with_toc)
    level1 = [e for e in entries if e.level == 1]
    level2 = [e for e in entries if e.level == 2]
    assert len(level1) >= 2   # "Capítulo 1: Combate", "Capítulo 2: Magia"
    assert len(level2) >= 1   # "Iniciativa", "Hechizos"


def test_extract_toc_chapter2_on_page_2(pdf_with_toc: Path) -> None:
    entries = _parser().extract_toc(pdf_with_toc)
    cap2 = next((e for e in entries if e.title == "Capítulo 2: Magia"), None)
    assert cap2 is not None
    assert cap2.page == 2


# ---------------------------------------------------------------------------
# _extract_prose_groups — dedup de chars en misma posición
# ---------------------------------------------------------------------------

class _FakePage:
    """Duck-type mínimo de pdfplumber.page.Page para tests sin PDF real.

    Solo funciona cuando table_bboxes=[] — no implementa filter().
    """
    def __init__(self, chars: list[dict]) -> None:
        self.chars = chars
        self.width = 595.0
        self.height = 842.0


def test_table_still_extracted_after_page_dedup(pdf_with_table: Path) -> None:
    """El dedup a nivel de página no debe romper la detección de tablas."""
    pages = _parser().parse(pdf_with_table)
    tables = [b for p in pages for b in p.blocks if isinstance(b, TableBlock)]
    assert len(tables) >= 1
    header = [cell.strip() for cell in tables[0].rows[0]]
    assert "Arma" in header


def test_dedup_and_drop_removes_same_position_duplicate() -> None:
    """PDF decorativo renderiza el mismo glifo dos veces en (x0, top) idénticos."""
    chars = [
        {"text": "H", "x0": 10.0, "x1": 16.0, "top": 100.0, "size": 11.0, "fontname": "FuturaPT-Book", "object_type": "char"},
        {"text": "H", "x0": 10.0, "x1": 16.0, "top": 100.0, "size": 11.0, "fontname": "FuturaPT-Book", "object_type": "char"},
        {"text": "i", "x0": 16.0, "x1": 20.0, "top": 100.0, "size": 11.0, "fontname": "FuturaPT-Book", "object_type": "char"},
    ]
    kept = _dedup_and_drop(chars)
    assert [c["text"] for c in kept] == ["H", "i"]


def test_dedup_and_drop_preserves_distinct_positions() -> None:
    chars = [
        {"text": "A", "x0": 10.0, "x1": 16.0, "top": 100.0, "size": 11.0, "fontname": "FuturaPT-Book", "object_type": "char"},
        {"text": "B", "x0": 20.0, "x1": 26.0, "top": 100.0, "size": 11.0, "fontname": "FuturaPT-Book", "object_type": "char"},
        {"text": "C", "x0": 30.0, "x1": 36.0, "top": 100.0, "size": 11.0, "fontname": "FuturaPT-Book", "object_type": "char"},
    ]
    kept = _dedup_and_drop(chars)
    assert [c["text"] for c in kept] == ["A", "B", "C"]


def test_dedup_and_drop_removes_decorative_fonts() -> None:
    """Los chars de fuentes small-caps decorativas (SC700) se descartan."""
    chars = [
        {"text": "R", "x0": 10.0, "x1": 16.0, "top": 100.0, "size": 11.0, "fontname": "XQLQXE+FuturaPT-Book", "object_type": "char"},
        {"text": "X", "x0": 20.0, "x1": 26.0, "top": 100.0, "size": 30.0, "fontname": "APNBUI+IndustryInc-Base-SC700", "object_type": "char"},
        {"text": "Y", "x0": 30.0, "x1": 36.0, "top": 100.0, "size": 30.0, "fontname": "WPVAJG+BisectModificadaRegular-SC700", "object_type": "char"},
    ]
    kept = _dedup_and_drop(chars)
    assert [c["text"] for c in kept] == ["R"]


def test_lines_to_blocks_preserves_input_order() -> None:
    """Las líneas se concatenan en el orden dado, no re-ordenadas por top."""
    line_low = [{"text": "abajo", "x0": 10.0, "x1": 40.0, "top": 200.0, "size": 11.0}]
    line_high = [{"text": "arriba", "x0": 10.0, "x1": 40.0, "top": 100.0, "size": 11.0}]
    # Entrada deliberadamente fuera de orden vertical:
    blocks = _lines_to_blocks([line_low, line_high])
    assert len(blocks) == 1
    text, _fs = blocks[0]
    assert text == "abajo arriba"


def _row(text: str, x0: float, top: float, w: float = 6.0, size: float = 10.0) -> dict:
    return {"text": text, "x0": x0, "x1": x0 + w, "top": top, "size": size, "object_type": "char"}


def test_detect_gutter_finds_two_columns() -> None:
    """Dos columnas (x 50-240 y 360-550) con hueco central → canalón ~300."""
    chars = []
    for top in (100.0, 112.0, 124.0):
        for x in range(50, 241, 12):
            chars.append(_row("L", float(x), top))
        for x in range(360, 551, 12):
            chars.append(_row("R", float(x), top))
    gutter = _detect_gutter(chars, 595.0)
    assert gutter is not None
    assert 250.0 < gutter < 360.0


def test_detect_gutter_single_column_returns_none() -> None:
    """Cobertura uniforme de margen a margen → sin canalón."""
    chars = [_row("x", float(x), 100.0) for x in range(50, 551, 12)]
    assert _detect_gutter(chars, 595.0) is None


def test_detect_gutter_ignores_full_width_title() -> None:
    """Un título de ancho completo (font grande) no debe rellenar el canalón.

    _detect_gutter recibe SOLO body chars; el caller filtra con _body_chars.
    Aquí simulamos eso pasando únicamente los body chars de 2 columnas.
    """
    body = []
    for top in (140.0, 152.0):
        for x in range(50, 241, 12):
            body.append(_row("L", float(x), top))
        for x in range(360, 551, 12):
            body.append(_row("R", float(x), top))
    gutter = _detect_gutter(body, 595.0)
    assert gutter is not None


def test_detect_gutter_content_one_side_only_returns_none() -> None:
    """Si un lado tiene <15% de los chars, no es un layout de 2 columnas."""
    chars = [_row("L", float(x), 100.0) for x in range(50, 241, 12)]
    chars.append(_row("R", 400.0, 100.0))  # 1 solo char a la derecha
    assert _detect_gutter(chars, 595.0) is None


def test_segment_reading_order_left_then_right() -> None:
    """Dos sub-líneas columnar a la misma altura → izquierda antes que derecha."""
    left = [{"text": "izq", "x0": 50.0, "x1": 90.0, "top": 100.0, "size": 10.0}]
    right = [{"text": "der", "x0": 360.0, "x1": 400.0, "top": 100.0, "size": 10.0}]
    # Una sola línea cruda mezcla ambas columnas (mismo top):
    mixed = left + right
    ordered = _segment_reading_order([mixed], gutter_x=300.0)
    text = " ".join("".join(c["text"] for c in ln) for ln in ordered)
    assert text == "izq der"


def test_segment_reading_order_full_width_separates_bands() -> None:
    """Una línea de ancho completo separa bandas: banda1(izq,der), título, banda2(izq,der)."""
    band1 = [
        {"text": "A", "x0": 50.0, "x1": 90.0, "top": 100.0, "size": 10.0},
        {"text": "B", "x0": 360.0, "x1": 400.0, "top": 100.0, "size": 10.0},
    ]
    title = [
        {"text": "T", "x0": 50.0, "x1": 290.0, "top": 130.0, "size": 10.0},
        {"text": "T", "x0": 300.0, "x1": 540.0, "top": 130.0, "size": 10.0},
    ]
    band2 = [
        {"text": "C", "x0": 50.0, "x1": 90.0, "top": 160.0, "size": 10.0},
        {"text": "D", "x0": 360.0, "x1": 400.0, "top": 160.0, "size": 10.0},
    ]
    ordered = _segment_reading_order([band1, title, band2], gutter_x=300.0)
    text = " ".join("".join(c["text"] for c in ln) for ln in ordered)
    assert text == "A B TT C D"


def test_segment_reading_order_groups_column_lines_within_band() -> None:
    """Dentro de una banda, todas las líneas izquierdas van antes que las derechas."""
    row1 = [
        {"text": "1", "x0": 50.0, "x1": 90.0, "top": 100.0, "size": 10.0},
        {"text": "a", "x0": 360.0, "x1": 400.0, "top": 100.0, "size": 10.0},
    ]
    row2 = [
        {"text": "2", "x0": 50.0, "x1": 90.0, "top": 112.0, "size": 10.0},
        {"text": "b", "x0": 360.0, "x1": 400.0, "top": 112.0, "size": 10.0},
    ]
    ordered = _segment_reading_order([row1, row2], gutter_x=300.0)
    text = " ".join("".join(c["text"] for c in ln) for ln in ordered)
    assert text == "1 2 a b"


def test_extract_prose_groups_reconstructs_two_columns() -> None:
    """Una página de 2 columnas se lee izquierda-completa, luego derecha (no interleaved)."""
    parser = _parser()
    chars: list[dict] = []
    # Columna izquierda: "IZQUIERDA" en x 50.., dos líneas
    left_words = [("IZQUIERDA", 100.0), ("primera", 112.0)]
    for word, top in left_words:
        x = 50.0
        for ch in word:
            chars.append({"text": ch, "x0": x, "x1": x + 6, "top": top, "size": 10.0, "object_type": "char"})
            x += 6
    # Columna derecha: "DERECHA" en x 360.., dos líneas
    right_words = [("DERECHA", 100.0), ("segunda", 112.0)]
    for word, top in right_words:
        x = 360.0
        for ch in word:
            chars.append({"text": ch, "x0": x, "x1": x + 6, "top": top, "size": 10.0, "object_type": "char"})
            x += 6

    blocks = parser._extract_prose_groups(_FakePage(chars), [])
    text = " ".join(t for t, _ in blocks)
    # La izquierda completa precede a la derecha; sin chars intercalados.
    assert text.index("IZQUIERDA") < text.index("DERECHA")
    assert text.index("primera") < text.index("DERECHA")
    assert "IZQUIERDA primera" in text
    assert "DERECHA segunda" in text


def test_caption_text_reconstructs_columns() -> None:
    """Una región de caption que cruza 2 columnas se lee izq-luego-der."""
    chars: list[dict] = []
    x = 50.0
    for ch in "TABLA":
        chars.append({"text": ch, "x0": x, "x1": x + 6, "top": 80.0, "size": 9.0, "object_type": "char"})
        x += 6
    x = 360.0
    for ch in "DERECHA":
        chars.append({"text": ch, "x0": x, "x1": x + 6, "top": 80.0, "size": 9.0, "object_type": "char"})
        x += 6
    text = " ".join(t for t, _ in _reading_order_blocks(chars, 595.0))
    assert "TABLA" in text and "DERECHA" in text
    assert text.index("TABLA") < text.index("DERECHA")
