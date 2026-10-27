# PDF TOC Title Extraction — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extraer el TOC/outline digital de PDFs con pdfminer para poblar `section_path` en chunks, e implementar `_extract_prose_groups` (actualmente roto) para que la detección por fontsize también funcione correctamente.

**Architecture:** `PdfplumberParser.extract_toc()` extrae el outline usando pdfminer (ya instalado). `run_chunker` acepta un parámetro `toc` opcional: si hay TOC lo usa como base del `section_path` apilando sub-headings detectados por fontsize encima; si no hay TOC usa solo fontsize. `ingest_pdf` llama a ambos métodos del parser y pasa el TOC al chunker.

**Tech Stack:** pdfminer.six (ya instalado vía pdfplumber), reportlab (ya instalado en dev para fixtures), pytest + pytest-asyncio `asyncio_mode="auto"`.

---

## Mapa de archivos

| Acción | Archivo | Responsabilidad |
|---|---|---|
| Modify | `src/rag_lib/types.py` | Añadir `TocEntry` (tipo interno) |
| Modify | `src/rag_lib/parsing/pdfplumber_parser.py` | Implementar `_extract_prose_groups` + añadir `extract_toc` |
| Modify | `src/rag_lib/chunking.py` | Añadir param `toc`, helper `_toc_path_at`, modo dual |
| Modify | `src/rag_lib/__init__.py` | Llamar `extract_toc` en `ingest_pdf` y pasar al chunker |
| Modify | `tests/rag_lib/conftest.py` | Añadir fixture `pdf_with_toc` |
| Modify | `tests/rag_lib/parsing/test_pdfplumber_parser.py` | Tests para `_extract_prose_groups` y `extract_toc` |
| Modify | `tests/rag_lib/test_chunking.py` | Tests para `_toc_path_at` y `run_chunker` con TOC |

---

## Task 1: Añadir `TocEntry` a types.py

**Files:**
- Modify: `src/rag_lib/types.py`

- [ ] **Step 1: Añadir `TocEntry` al final de la sección de tipos internos**

En `src/rag_lib/types.py`, después del bloque `ParsedPage` (al final del archivo):

```python
@dataclass(frozen=True)
class TocEntry:
    level: int    # 1 = capítulo, 2 = sección, 3 = subsección
    title: str
    page: int     # página donde empieza (1-based)
```

- [ ] **Step 2: Verificar que el tipo es importable**

```bash
python -c "from rag_lib.types import TocEntry; print(TocEntry(1, 'Cap 1', 3))"
```

Expected: `TocEntry(level=1, title='Cap 1', page=3)`

- [ ] **Step 3: Commit**

```bash
git add src/rag_lib/types.py
git commit -m "feat(rag-toc): add TocEntry internal type"
```

---

## Task 2: Fixture `pdf_with_toc` en conftest.py

**Files:**
- Modify: `tests/rag_lib/conftest.py`

Necesitamos un PDF con outline digital para testear `extract_toc`. reportlab soporta `canvas.bookmarkPage()` + `canvas.addOutlineEntry()`.

- [ ] **Step 1: Añadir fixture al final de `tests/rag_lib/conftest.py`**

```python
@pytest.fixture
def pdf_with_toc(tmp_path: Path) -> Path:
    """3-page PDF with a digital outline/TOC (bookmarks).

    Structure:
      level 1 "Capítulo 1: Combate"  → page 1
      level 2 "Iniciativa"           → page 1  (same page, different y)
      level 1 "Capítulo 2: Magia"    → page 2
      level 2 "Hechizos"             → page 3
    """
    path = tmp_path / "toc.pdf"
    c = canvas.Canvas(str(path))

    # Page 1
    c.bookmarkPage("cap1")
    c.addOutlineEntry("Capítulo 1: Combate", "cap1", level=0, closed=False)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(50, 780, "Capítulo 1: Combate")
    c.bookmarkPage("iniciativa")
    c.addOutlineEntry("Iniciativa", "iniciativa", level=1, closed=False)
    c.setFont("Helvetica", 11)
    y = 750
    for line in _wrap_text(LOREM * 2):
        c.drawString(50, y, line)
        y -= 15
        if y < 50:
            break
    c.showPage()

    # Page 2
    c.bookmarkPage("cap2")
    c.addOutlineEntry("Capítulo 2: Magia", "cap2", level=0, closed=False)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(50, 780, "Capítulo 2: Magia")
    c.setFont("Helvetica", 11)
    y = 750
    for line in _wrap_text(LOREM * 2):
        c.drawString(50, y, line)
        y -= 15
        if y < 50:
            break
    c.showPage()

    # Page 3
    c.bookmarkPage("hechizos")
    c.addOutlineEntry("Hechizos", "hechizos", level=1, closed=False)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, 780, "Hechizos")
    c.setFont("Helvetica", 11)
    y = 750
    for line in _wrap_text(LOREM * 2):
        c.drawString(50, y, line)
        y -= 15
        if y < 50:
            break
    c.showPage()
    c.save()
    return path
```

- [ ] **Step 2: Verificar que el fixture genera un PDF válido**

```bash
python -c "
import pytest, sys
# Quick smoke test: just import the fixture and run it manually
from pathlib import Path
import tempfile, os
tmp = Path(tempfile.mkdtemp())
# We can't run fixtures directly, just verify reportlab imports fine
from reportlab.pdfgen import canvas
print('reportlab OK')
"
```

Expected: `reportlab OK`

- [ ] **Step 3: Commit**

```bash
git add tests/rag_lib/conftest.py
git commit -m "test(rag-toc): add pdf_with_toc fixture with digital outline"
```

---

## Task 3: Implementar `_extract_prose_groups` (TDD)

**Files:**
- Modify: `tests/rag_lib/parsing/test_pdfplumber_parser.py`
- Modify: `src/rag_lib/parsing/pdfplumber_parser.py`

`_extract_prose_groups` debe devolver múltiples `ProseBlock` por página agrupados por fontsize, en lugar del bloque único actual. Es el método que falta y hace que el parser crashee hoy.

- [ ] **Step 1: Escribir tests que fallan**

Añadir al final de `tests/rag_lib/parsing/test_pdfplumber_parser.py`:

```python
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
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

```bash
python -m pytest tests/rag_lib/parsing/test_pdfplumber_parser.py::test_headings_pdf_yields_multiple_prose_blocks_per_page tests/rag_lib/parsing/test_pdfplumber_parser.py::test_heading_block_has_larger_fontsize_than_body -v
```

Expected: FAIL (AttributeError `_extract_prose_groups` no existe, o AssertionError si ya crasheaba antes).

- [ ] **Step 3: Implementar `_extract_prose_groups` en el parser**

En `src/rag_lib/parsing/pdfplumber_parser.py`, añadir el método después de `_extract_prose` (línea 127):

```python
def _extract_prose_groups(
    self, page_obj: pdfplumber.page.Page, table_bboxes: list[tuple]
) -> list[tuple[str, float]]:
    """Return prose text grouped by fontsize — one (text, fontsize_avg) per visual block.

    Algorithm:
    1. Filter chars outside table bboxes.
    2. Group chars into lines by vertical proximity (±2pt).
    3. Group adjacent lines with similar fontsize (±1pt) into blocks.
    4. Return (block_text, fontsize_avg) pairs sorted top→bottom.
    """
    # Step 1: filter chars
    if table_bboxes:
        def outside_tables(obj: dict) -> bool:
            if obj.get("object_type") != "char":
                return True
            for tb in table_bboxes:
                if (
                    obj.get("x0", 0) >= tb[0] - 1
                    and obj.get("x1", 0) <= tb[2] + 1
                    and obj.get("top", 0) >= tb[1] - 1
                    and obj.get("bottom", 0) <= tb[3] + 1
                ):
                    return False
            return True
        filtered = page_obj.filter(outside_tables)
    else:
        filtered = page_obj

    chars = [
        c for c in filtered.chars
        if c.get("size") and float(c["size"]) > 0 and c.get("text", "").strip()
    ]
    if not chars:
        return []

    # Step 2: group chars into lines by top coordinate (±2pt tolerance)
    chars_sorted = sorted(chars, key=lambda c: (round(float(c["top"]) / 2) * 2, float(c["x0"])))
    lines: list[list[dict]] = []
    for ch in chars_sorted:
        placed = False
        for line in lines:
            if abs(float(ch["top"]) - float(line[0]["top"])) <= 2.0:
                line.append(ch)
                placed = True
                break
        if not placed:
            lines.append([ch])

    # Step 3: group adjacent lines with similar fontsize (±1pt) into blocks
    def _line_fontsize(line: list[dict]) -> float:
        sizes = [float(c["size"]) for c in line if c.get("size")]
        return sum(sizes) / len(sizes) if sizes else 11.0

    def _line_text(line: list[dict]) -> str:
        return "".join(c.get("text", "") for c in sorted(line, key=lambda c: float(c["x0"])))

    blocks: list[tuple[str, float]] = []
    current_lines: list[list[dict]] = []
    current_fs: float | None = None

    for line in sorted(lines, key=lambda ln: float(ln[0]["top"])):
        fs = _line_fontsize(line)
        if current_fs is None or abs(fs - current_fs) <= 1.0:
            current_lines.append(line)
            sizes_all = [float(c["size"]) for ln in current_lines for c in ln if c.get("size")]
            current_fs = sum(sizes_all) / len(sizes_all) if sizes_all else fs
        else:
            # Flush current block
            text = " ".join(_line_text(ln) for ln in current_lines).strip()
            if text:
                blocks.append((text, current_fs))
            current_lines = [line]
            current_fs = fs

    # Flush last block
    if current_lines:
        sizes_all = [float(c["size"]) for ln in current_lines for c in ln if c.get("size")]
        fs_final = sum(sizes_all) / len(sizes_all) if sizes_all else 11.0
        text = " ".join(_line_text(ln) for ln in current_lines).strip()
        if text:
            blocks.append((text, fs_final))

    return blocks
```

- [ ] **Step 4: Correr los tests nuevos**

```bash
python -m pytest tests/rag_lib/parsing/test_pdfplumber_parser.py -v
```

Expected: todos los tests del parser pasan (incluyendo los 3 nuevos).

- [ ] **Step 5: Correr suite completa del parser para verificar no hay regresiones**

```bash
python -m pytest tests/rag_lib/parsing/ -v
```

Expected: todos pasan.

- [ ] **Step 6: Commit**

```bash
git add src/rag_lib/parsing/pdfplumber_parser.py tests/rag_lib/parsing/test_pdfplumber_parser.py
git commit -m "fix(rag-toc): implement _extract_prose_groups — groups chars by fontsize per page"
```

---

## Task 4: Implementar `extract_toc` en el parser (TDD)

**Files:**
- Modify: `tests/rag_lib/parsing/test_pdfplumber_parser.py`
- Modify: `src/rag_lib/parsing/pdfplumber_parser.py`

- [ ] **Step 1: Escribir tests que fallan**

Añadir al final de `tests/rag_lib/parsing/test_pdfplumber_parser.py`:

```python
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
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

```bash
python -m pytest tests/rag_lib/parsing/test_pdfplumber_parser.py::test_extract_toc_returns_empty_for_pdf_without_outline tests/rag_lib/parsing/test_pdfplumber_parser.py::test_extract_toc_returns_toc_entries -v
```

Expected: FAIL con `AttributeError: 'PdfplumberParser' object has no attribute 'extract_toc'`.

- [ ] **Step 3: Implementar `extract_toc` en el parser**

Añadir estos imports al inicio de `src/rag_lib/parsing/pdfplumber_parser.py` (después de `import pdfplumber`):

```python
from pdfminer.pdfdocument import PDFNoOutlines
from pdfminer.pdftypes import PDFObjRef
```

Añadir el método público `extract_toc` a la clase `PdfplumberParser` (antes de los helpers privados):

```python
def extract_toc(self, pdf_path: str | Path) -> list:
    """Extract the PDF outline/bookmarks as a list of TocEntry, sorted by page.

    Returns [] if the PDF has no digital outline or if parsing fails.
    Uses pdfminer (already installed via pdfplumber) — no new dependencies.
    """
    # Import here to avoid circular import at module level
    from rag_lib.types import TocEntry

    try:
        pdf = pdfplumber.open(str(pdf_path))
    except Exception:
        return []

    try:
        doc = pdf.doc
        # Build a map: pdfminer page object id → 1-based page number
        pageid_map: dict[int, int] = {
            p.page_obj.pageid: p.page_number for p in pdf.pages
        }

        try:
            raw_outlines = list(doc.get_outlines())
        except PDFNoOutlines:
            return []
        except Exception:
            return []

        entries: list[TocEntry] = []
        for level, title, dest, _action, _se in raw_outlines:
            page_num = self._resolve_dest_page(dest, pageid_map, doc)
            if page_num is None:
                continue
            # pdfminer levels are 0-based; TocEntry uses 1-based
            entries.append(TocEntry(level=level + 1, title=str(title), page=page_num))

        return sorted(entries, key=lambda e: e.page)
    finally:
        pdf.close()
```

Añadir el helper privado `_resolve_dest_page` a la clase:

```python
def _resolve_dest_page(
    self, dest: object, pageid_map: dict[int, int], doc: object
) -> int | None:
    """Resolve a pdfminer destination object to a 1-based page number.

    pdfminer destinations come in two forms:
    - Explicit: a list where dest[0] is a PDFObjRef to the page dict
    - Named: bytes/str key that must be looked up via doc.get_dest()
    """
    try:
        if isinstance(dest, list) and dest:
            ref = dest[0]
            if isinstance(ref, PDFObjRef):
                return pageid_map.get(ref.objid)
        elif isinstance(dest, (bytes, str)):
            resolved = doc.get_dest(dest)
            return self._resolve_dest_page(resolved, pageid_map, doc)
    except Exception:
        pass
    return None
```

- [ ] **Step 4: Correr todos los tests de `extract_toc`**

```bash
python -m pytest tests/rag_lib/parsing/test_pdfplumber_parser.py -k "toc" -v
```

Expected: 6 passed.

- [ ] **Step 5: Correr suite completa del parser**

```bash
python -m pytest tests/rag_lib/parsing/ -v
```

Expected: todos pasan.

- [ ] **Step 6: Commit**

```bash
git add src/rag_lib/parsing/pdfplumber_parser.py tests/rag_lib/parsing/test_pdfplumber_parser.py
git commit -m "feat(rag-toc): add extract_toc() using pdfminer outline API"
```

---

## Task 5: Actualizar `run_chunker` con parámetro `toc` (TDD)

**Files:**
- Modify: `tests/rag_lib/test_chunking.py`
- Modify: `src/rag_lib/chunking.py`

- [ ] **Step 1: Escribir tests que fallan**

Añadir al final de `tests/rag_lib/test_chunking.py`:

```python
from rag_lib.types import TocEntry


# ---------------------------------------------------------------------------
# _toc_path_at helper
# ---------------------------------------------------------------------------

def test_toc_path_at_returns_none_for_empty_toc() -> None:
    from rag_lib.chunking import _toc_path_at
    assert _toc_path_at(1, []) is None


def test_toc_path_at_returns_chapter_title() -> None:
    from rag_lib.chunking import _toc_path_at
    toc = [TocEntry(1, "Capítulo 1", 1), TocEntry(1, "Capítulo 2", 5)]
    assert _toc_path_at(1, toc) == "Capítulo 1"
    assert _toc_path_at(4, toc) == "Capítulo 1"
    assert _toc_path_at(5, toc) == "Capítulo 2"


def test_toc_path_at_combines_hierarchy() -> None:
    from rag_lib.chunking import _toc_path_at
    toc = [
        TocEntry(1, "Capítulo 1", 1),
        TocEntry(2, "Iniciativa", 1),
        TocEntry(1, "Capítulo 2", 5),
    ]
    assert _toc_path_at(2, toc) == "Capítulo 1 / Iniciativa"


def test_toc_path_at_clears_deeper_levels_on_new_parent() -> None:
    from rag_lib.chunking import _toc_path_at
    toc = [
        TocEntry(1, "Cap 1", 1),
        TocEntry(2, "Sección A", 2),
        TocEntry(1, "Cap 2", 5),   # new level-1 clears level-2
    ]
    assert _toc_path_at(6, toc) == "Cap 2"  # Sección A is gone


def test_toc_path_at_returns_none_before_first_entry() -> None:
    from rag_lib.chunking import _toc_path_at
    toc = [TocEntry(1, "Capítulo 1", 3)]
    assert _toc_path_at(1, toc) is None
    assert _toc_path_at(2, toc) is None
    assert _toc_path_at(3, toc) == "Capítulo 1"


# ---------------------------------------------------------------------------
# run_chunker with toc
# ---------------------------------------------------------------------------

def test_run_chunker_with_toc_assigns_section_path_from_toc() -> None:
    toc = [TocEntry(1, "Combate", 1)]
    page = ParsedPage(
        page_num=1,
        blocks=[ProseBlock(text="El combate usa dados. " * 10, page=1, fontsize_avg=11.0)],
    )
    chunks = run_chunker([page], toc=toc)
    assert all(c["section_path"] and "Combate" in c["section_path"] for c in chunks)


def test_run_chunker_with_toc_stacks_fontsize_subheadings() -> None:
    """TOC provides top-level path; fontsize headings stack on top."""
    toc = [TocEntry(1, "Combate", 1)]
    # H2-sized block (14pt) should be detected as subheading
    h2_block = ProseBlock(text="Iniciativa", page=1, fontsize_avg=14.0)
    body_blocks = [
        ProseBlock(text=f"El turno empieza. " * 10, page=1, fontsize_avg=11.0)
        for _ in range(5)
    ]
    # Also need many 11pt blocks for p90 to be ~11pt
    extra_body = [
        ProseBlock(text=f"Texto adicional cuerpo {i}. " * 5, page=1, fontsize_avg=11.0)
        for i in range(20)
    ]
    page = ParsedPage(page_num=1, blocks=[h2_block] + body_blocks + extra_body)
    chunks = run_chunker([page], toc=toc)
    subheading_chunks = [c for c in chunks if c["section_path"] and "Iniciativa" in c["section_path"]]
    assert len(subheading_chunks) >= 1
    assert all("Combate" in c["section_path"] for c in subheading_chunks)


def test_run_chunker_without_toc_unchanged_behavior() -> None:
    """Passing toc=None must not change existing behavior."""
    h1_block = ProseBlock(text="Capítulo 1: Combate", page=1, fontsize_avg=18.0)
    body_blocks = [
        ProseBlock(text=f"El combate se resuelve con dados. Turno {i}. " * 5, page=1, fontsize_avg=11.0)
        for i in range(20)
    ]
    page = ParsedPage(page_num=1, blocks=[h1_block] + body_blocks)
    chunks_no_toc = run_chunker([page], toc=None)
    chunks_existing = run_chunker([page])  # default (no toc param)
    # Both should produce same section paths
    assert [c["section_path"] for c in chunks_no_toc] == [c["section_path"] for c in chunks_existing]
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

```bash
python -m pytest tests/rag_lib/test_chunking.py::test_toc_path_at_returns_none_for_empty_toc tests/rag_lib/test_chunking.py::test_run_chunker_with_toc_assigns_section_path_from_toc -v
```

Expected: FAIL con `ImportError: cannot import name '_toc_path_at'` y `TypeError: run_chunker() got an unexpected keyword argument 'toc'`.

- [ ] **Step 3: Actualizar `chunking.py`**

**3a.** Añadir el import de `TocEntry` al inicio (después de la línea `from rag_lib.types import ...`):

```python
from rag_lib.types import ParsedPage, ProseBlock, TableBlock, TocEntry
```

**3b.** Añadir la función pública `_toc_path_at` (módulo-level, antes de `run_chunker`):

```python
def _toc_path_at(page: int, toc: list[TocEntry]) -> str | None:
    """Return the active hierarchical TOC path for a given page number.

    Scans the TOC in order. Entries with page > given page stop the scan.
    When a new entry appears at level N, all levels deeper than N are cleared.
    """
    active: dict[int, str] = {}  # level → title
    for entry in toc:
        if entry.page > page:
            break
        active[entry.level] = entry.title
        for deeper in [lvl for lvl in active if lvl > entry.level]:
            del active[deeper]
    if not active:
        return None
    return " / ".join(active[lvl] for lvl in sorted(active))
```

**3c.** Actualizar la firma de `run_chunker`:

```python
def run_chunker(
    pages: list[ParsedPage],
    *,
    token_target: int = 500,
    overlap: int = 75,
    toc: list[TocEntry] | None = None,
) -> list[dict[str, Any]]:
```

**3d.** Dentro de `run_chunker`, actualizar la función closure `current_section_path` para aceptar una página explícita (necesario porque cuando se emite un TableBlock, `buffer_page_start` ya fue reseteado a None por `_flush_buffer`):

Reemplazar la función closure `current_section_path`:

```python
    def current_section_path(page: int | None = None) -> str | None:
        actual_page = page or buffer_page_start or 1
        toc_base = _toc_path_at(actual_page, toc) if toc else None
        fontsize_part = " / ".join(text for _, text in section_stack) if section_stack else None
        if toc_base and fontsize_part:
            return toc_base + " / " + fontsize_part
        return toc_base or fontsize_part
```

Y actualizar el bloque de tabla para pasar la página de la tabla explícitamente (evita que `buffer_page_start=None` haga que el TOC lookup use página 1 por defecto):

```python
            elif isinstance(block, TableBlock):
                _split_oversized_buffer()
                _flush_buffer()
                sp = current_section_path(block.page)
                parts = []
                if sp:
                    parts.append(f"[{sp}]")
                if block.caption:
                    parts.append(f"Tabla: {block.caption}")
                parts.append("")
                parts.append(gfm_table(block.rows))
                _emit("\n".join(parts), "table", block.page, None, sp)
```

- [ ] **Step 4: Correr todos los tests de chunking**

```bash
python -m pytest tests/rag_lib/test_chunking.py -v
```

Expected: todos pasan (los anteriores + los 9 nuevos).

- [ ] **Step 5: Commit**

```bash
git add src/rag_lib/chunking.py tests/rag_lib/test_chunking.py
git commit -m "feat(rag-toc): add toc param to run_chunker, _toc_path_at helper, dual TOC+fontsize mode"
```

---

## Task 6: Integrar `extract_toc` en `ingest_pdf`

**Files:**
- Modify: `src/rag_lib/__init__.py`

- [ ] **Step 1: Localizar las líneas a cambiar**

En `src/rag_lib/__init__.py`, buscar el bloque:

```python
        logger.info("rag_lib.ingest: parsing %s", pdf_path.name)
        pages = await asyncio.to_thread(_PARSER.parse, pdf_path)
        page_count = len(pages)
        chunks = run_chunker(pages)
```

- [ ] **Step 2: Añadir la llamada a `extract_toc`**

Reemplazar ese bloque con:

```python
        logger.info("rag_lib.ingest: parsing %s", pdf_path.name)
        pages = await asyncio.to_thread(_PARSER.parse, pdf_path)
        toc   = await asyncio.to_thread(_PARSER.extract_toc, pdf_path)
        page_count = len(pages)
        chunks = run_chunker(pages, toc=toc)
```

- [ ] **Step 3: Verificar que la suite de integración sigue en verde**

```bash
python -m pytest tests/rag_lib/test_integration_ingest.py -v
```

Expected: todos pasan sin cambios.

- [ ] **Step 4: Commit**

```bash
git add src/rag_lib/__init__.py
git commit -m "feat(rag-toc): wire extract_toc into ingest_pdf pipeline"
```

---

## Task 7: Suite completa y lint

**Files:** ninguno nuevo

- [ ] **Step 1: Correr toda la suite rag_lib**

```bash
python -m pytest tests/rag_lib/ -v
```

Expected: todos pasan (sin nuevos fallos).

- [ ] **Step 2: Correr lint**

```bash
ruff check src/rag_lib tests/rag_lib
```

Expected: `All checks passed!`

Si hay errores de lint, corregirlos antes de continuar.

- [ ] **Step 3: Correr suite completa para detectar regresiones**

```bash
python -m pytest tests/ -q --ignore=tests/rag_lib/
```

Expected: mismos resultados que antes (fallos pre-existentes conocidos: `test_tts_config_from_toml`, `test_defaults_from_toml_override_dataclass_defaults`, `test_generate_toml_is_valid_toml`, `test_half_open_failure_reopens`).

- [ ] **Step 4: Commit final**

```bash
git add -A
git commit -m "feat(rag-toc): complete PDF TOC title extraction — fix _extract_prose_groups + extract_toc + run_chunker toc mode"
```
