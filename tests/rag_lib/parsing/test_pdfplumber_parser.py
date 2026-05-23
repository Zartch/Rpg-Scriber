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
