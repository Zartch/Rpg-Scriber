"""Synthetic PDF fixtures for rag_lib tests using reportlab.

All fixtures return a Path to a temporary PDF file in tmp_path.
No binary fixtures are committed to the repo.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from reportlab.pdfgen import canvas


LOREM = (
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit. "
    "Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. "
    "Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris. "
    "Duis aute irure dolor in reprehenderit in voluptate velit esse cillum. "
    "Excepteur sint occaecat cupidatat non proident, sunt in culpa qui "
    "officia deserunt mollit anim id est laborum. "
)

# Long paragraph that does NOT end with a sentence terminator
CONTINUATION_PARA = (
    "Este párrafo empieza en la primera página y termina sin punto final "
    "porque continúa en la siguiente hoja del documento sin interrupción"
)
CONTINUATION_NEXT = (
    "continuando el texto anterior de forma natural y fluida hasta "
    "completar el pensamiento con un punto final aquí."
)


def _wrap_text(text: str, max_chars: int = 90) -> list[str]:
    words = text.split()
    lines, current = [], ""
    for w in words:
        if len(current) + len(w) + 1 <= max_chars:
            current = f"{current} {w}".lstrip()
        else:
            lines.append(current)
            current = w
    if current:
        lines.append(current)
    return lines


def _draw_grid_table(c: canvas.Canvas, x: float, y: float, data: list[list[str]]) -> None:
    """Draw a bordered grid table pdfplumber can detect via line strategy."""
    col_w, row_h = 100.0, 20.0
    n_cols = max(len(row) for row in data)
    for ri, row in enumerate(data):
        for ci in range(n_cols):
            cell_x = x + ci * col_w
            cell_y = y - (ri + 1) * row_h
            c.rect(cell_x, cell_y, col_w, row_h)
            text = row[ci] if ci < len(row) else ""
            c.drawString(cell_x + 3, cell_y + 5, str(text)[:14])


@pytest.fixture
def simple_pdf(tmp_path: Path) -> Path:
    """3-page prose PDF with no headings or tables."""
    path = tmp_path / "simple.pdf"
    c = canvas.Canvas(str(path))
    c.setFont("Helvetica", 11)
    for _ in range(3):
        y = 750
        for line in _wrap_text(LOREM * 5):
            c.drawString(50, y, line)
            y -= 15
            if y < 50:
                break
        c.showPage()
    c.save()
    return path


@pytest.fixture
def pdf_with_table(tmp_path: Path) -> Path:
    """1-page PDF with a 4-column × 3-row table (header + 2 data rows)."""
    path = tmp_path / "table.pdf"
    c = canvas.Canvas(str(path))
    c.setFont("Helvetica", 11)
    # Prose above table (caption-ish)
    c.drawString(50, 750, "Tabla de Armas")
    table_data = [
        ["Arma", "Daño", "Tipo", "Coste"],
        ["Espada", "1d8", "Cortante", "15 po"],
        ["Daga", "1d4", "Perforante", "2 po"],
    ]
    _draw_grid_table(c, 50, 720, table_data)
    c.showPage()
    c.save()
    return path


@pytest.fixture
def pdf_with_headings(tmp_path: Path) -> Path:
    """2-page PDF with H1 (18pt) and H2 (14pt) headings above 11pt body text."""
    path = tmp_path / "headings.pdf"
    c = canvas.Canvas(str(path))
    # Page 1 — H1 + H2 + body
    c.setFont("Helvetica-Bold", 18)
    c.drawString(50, 780, "Capítulo 1: Combate")
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, 750, "Iniciativa")
    c.setFont("Helvetica", 11)
    y = 720
    for line in _wrap_text(LOREM * 3):
        c.drawString(50, y, line)
        y -= 15
        if y < 50:
            break
    c.showPage()
    # Page 2 — H2 + body
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, 780, "Acciones de combate")
    c.setFont("Helvetica", 11)
    y = 750
    for line in _wrap_text(LOREM * 3):
        c.drawString(50, y, line)
        y -= 15
        if y < 50:
            break
    c.showPage()
    c.save()
    return path


@pytest.fixture
def pdf_with_continuation(tmp_path: Path) -> Path:
    """2-page PDF where a paragraph continues across page boundary (no terminator)."""
    path = tmp_path / "continuation.pdf"
    c = canvas.Canvas(str(path))
    c.setFont("Helvetica", 11)
    # Page 1 — paragraph that does NOT end with sentence terminator
    c.drawString(50, 750, CONTINUATION_PARA)
    c.showPage()
    # Page 2 — continues with lowercase (continuation)
    c.setFont("Helvetica", 11)
    c.drawString(50, 750, CONTINUATION_NEXT)
    c.showPage()
    c.save()
    return path


@pytest.fixture
def pdf_with_repeated_footer(tmp_path: Path) -> Path:
    """3-page PDF with identical footer text on every page (for dedup testing)."""
    path = tmp_path / "footer.pdf"
    footer = "© 2024 Manual RPG — todos los derechos reservados"
    c = canvas.Canvas(str(path))
    c.setFont("Helvetica", 11)
    for i in range(3):
        y = 750
        for line in _wrap_text(LOREM):
            c.drawString(50, y, line)
            y -= 15
        # Draw footer at bottom of each page
        c.setFont("Helvetica", 9)
        c.drawString(50, 30, footer)
        c.setFont("Helvetica", 11)
        c.showPage()
    c.save()
    return path
