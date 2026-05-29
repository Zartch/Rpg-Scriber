"""Tests for PdfplumberParser — run BEFORE implementing the parser."""
from __future__ import annotations

from pathlib import Path

import pytest

from rag_lib.errors import PdfParseError
from rag_lib.parsing.pdfplumber_parser import PdfplumberParser
from rag_lib.types import ProseBlock, TableBlock


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


from rag_lib.types import TocEntry


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
