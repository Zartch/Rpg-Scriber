# RAG Column Detection, Page-level Dedup & Decorative Drop — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminar el interleaving de columnas, el doble-char en tablas y el flavor decorativo scrambled de la ingesta de PDFs, reestructurando `_extract_prose_groups` con detección de columnas y moviendo el dedup a nivel de página.

**Architecture:** El parser deduplica chars y descarta fuentes decorativas una sola vez en `_parse_page` (alimentando tablas, caption y prosa). `_extract_prose_groups` se descompone en helpers de módulo puros y reconstruye el orden de lectura a 2 columnas vía detección de canalón (gutter) por proyección de huecos, con fallback seguro a 1 columna.

**Tech Stack:** Python 3.10, pdfplumber, pytest. Spec: [`docs/superpowers/specs/2026-06-05-rag-column-detection-design.md`](../specs/2026-06-05-rag-column-detection-design.md).

> **Nota sobre commits (CLAUDE.md):** este proyecto prohíbe commits salvo petición explícita del usuario — el usuario prueba antes de commitear. Por eso los pasos terminan en **Checkpoint** (correr la suite), no en `git commit`. El usuario commiteará al final.

---

## File Structure

- **Modify** `src/rag_lib/parsing/pdfplumber_parser.py` — todo el trabajo de parsing: dedup/drop a nivel de página, helpers de módulo (`_dedup_and_drop`, `_group_lines`, `_body_chars`, `_detect_gutter`, `_segment_reading_order`, `_strip_overlay`, `_lines_to_blocks`, `_reading_order_blocks`), refactor de `_extract_prose_groups`, `_extract_caption` column-aware.
- **Modify** `tests/rag_lib/parsing/test_pdfplumber_parser.py` — migrar 2 tests de dedup; añadir tests de helpers de columnas, drop decorativo, orden de lectura y regresión.
- **Reference** `docs/rag-lib.md` — doc de dominio del módulo RAG (no se modifica, solo contexto).

Helpers nuevos a **nivel de módulo** (funciones puras, fáciles de testear con dicts sintéticos). `_extract_prose_groups`, `_extract_caption`, `_parse_page`, `_deduped_page` quedan como métodos de `PdfplumberParser`.

---

## Task 1: Helper de dedup + drop decorativo (función pura)

**Files:**
- Modify: `src/rag_lib/parsing/pdfplumber_parser.py`
- Test: `tests/rag_lib/parsing/test_pdfplumber_parser.py`

- [ ] **Step 1: Migrar los 2 tests de dedup existentes y añadir el de drop decorativo**

En `tests/rag_lib/parsing/test_pdfplumber_parser.py`, **reemplazar** las dos funciones `test_extract_prose_groups_deduplicates_same_position_chars` y `test_extract_prose_groups_preserves_distinct_position_chars` (líneas ~180-207) por tests que apuntan al nuevo helper puro `_dedup_and_drop`. Añadir el import del helper al top del archivo.

```python
from rag_lib.parsing.pdfplumber_parser import (
    PdfplumberParser,
    _dedup_and_drop,
)


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
```

- [ ] **Step 2: Correr los tests nuevos para verificar que fallan**

Run: `pytest tests/rag_lib/parsing/test_pdfplumber_parser.py -k "dedup_and_drop" -v`
Expected: FAIL con `ImportError: cannot import name '_dedup_and_drop'`.

- [ ] **Step 3: Implementar `_dedup_and_drop` y la constante de fuentes decorativas**

En `src/rag_lib/parsing/pdfplumber_parser.py`, tras la línea `_CAPTION_LOOKAHEAD_PT = 40.0` (línea 21), añadir:

```python
# Fuentes small-caps decorativas (flavor sidebars) cuyo texto sale scrambled —
# se descartan en la ingesta porque son ambientación, no reglas.
_DECORATIVE_FONT_MARKERS = ("SC700",)


def _dedup_and_drop(chars: list[dict]) -> list[dict]:
    """Drop decorative-font chars and de-duplicate chars at the same (x0, top, text).

    PDFs decorativos renderizan glifos dos veces en coordenadas idénticas; los
    sidebars de flavor usan fuentes *SC700* que salen ilegibles. Ambos son ruido.
    """
    seen: set[tuple[float, float, str | None]] = set()
    kept: list[dict] = []
    for c in chars:
        font = c.get("fontname", "")
        if any(marker in font for marker in _DECORATIVE_FONT_MARKERS):
            continue
        key = (round(float(c["x0"]), 1), round(float(c["top"]), 1), c.get("text"))
        if key in seen:
            continue
        seen.add(key)
        kept.append(c)
    return kept
```

- [ ] **Step 4: Correr los tests para verificar que pasan**

Run: `pytest tests/rag_lib/parsing/test_pdfplumber_parser.py -k "dedup_and_drop" -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Eliminar el Step 1.5 (dedup) de `_extract_prose_groups`**

En `_extract_prose_groups`, **borrar** el bloque "Step 1.5: dedup chars at same position" (líneas 203-212 del original):

```python
        # Step 1.5: dedup chars at same position (PDF decorative double-render).
        # Keeps the first occurrence; assumes duplicate renders carry identical text/size.
        seen_pos: set[tuple[float, float]] = set()
        deduped: list[dict] = []
        for c in chars:
            pos = (round(float(c["x0"]), 1), round(float(c["top"]), 1))
            if pos not in seen_pos:
                seen_pos.add(pos)
                deduped.append(c)
        chars = deduped
```

El dedup ahora ocurre upstream (Task 2). `_extract_prose_groups` asume chars ya deduplicados.

- [ ] **Step 6: Checkpoint — correr la suite del parser**

Run: `pytest tests/rag_lib/parsing/ -q`
Expected: PASS (los tests de dedup viejos ya no existen; los nuevos pasan; el resto intacto).

---

## Task 2: Dedup/drop a nivel de página en `_parse_page`

**Files:**
- Modify: `src/rag_lib/parsing/pdfplumber_parser.py`
- Test: `tests/rag_lib/parsing/test_pdfplumber_parser.py`

- [ ] **Step 1: Test de regresión — las tablas siguen extrayéndose tras el dedup (PDF real)**

Añadir en `test_pdfplumber_parser.py` (la fixture `pdf_with_table` ya existe en `conftest.py`):

```python
def test_table_still_extracted_after_page_dedup(pdf_with_table: Path) -> None:
    """El dedup a nivel de página no debe romper la detección de tablas."""
    pages = _parser().parse(pdf_with_table)
    tables = [b for p in pages for b in p.blocks if isinstance(b, TableBlock)]
    assert len(tables) >= 1
    header = [cell.strip() for cell in tables[0].rows[0]]
    assert "Arma" in header
```

- [ ] **Step 2: Correr para verificar que pasa con el código actual (baseline)**

Run: `pytest tests/rag_lib/parsing/test_pdfplumber_parser.py::test_table_still_extracted_after_page_dedup -v`
Expected: PASS (aún no hemos cambiado `_parse_page`; este test fija el comportamiento que NO debe romperse).

- [ ] **Step 3: Añadir `_deduped_page` y aplicarlo en `_parse_page`**

En `PdfplumberParser`, añadir el método:

```python
    def _deduped_page(self, page_obj: pdfplumber.page.Page):
        """Return a FilteredPage with decorative fonts dropped and positional
        duplicates removed, so tables, captions and prose share clean chars."""
        kept_ids = {id(c) for c in _dedup_and_drop(page_obj.chars)}

        def keep(obj: dict) -> bool:
            return obj.get("object_type") != "char" or id(obj) in kept_ids

        return page_obj.filter(keep)
```

En `_parse_page`, sustituir el cuerpo para que opere sobre la página deduplicada. Cambiar el inicio (líneas 119-121):

```python
    def _parse_page(self, page_obj: pdfplumber.page.Page) -> ParsedPage:
        page_num: int = page_obj.page_number  # pdfplumber is 1-indexed
        page = self._deduped_page(page_obj)
        blocks: list[ProseBlock | TableBlock] = []
```

Y en el resto del método, reemplazar las llamadas que usan `page_obj` para extraer contenido por `page`:
- `found_tables = page.find_tables()` (antes `page_obj.find_tables()`)
- `caption = self._extract_caption(page, ft.bbox)` (antes `page_obj`)
- `for text, fontsize in self._extract_prose_groups(page, table_bboxes):` (antes `page_obj`)

(El `except ValueError` y el resto de la estructura no cambian. `page_num` sigue saliendo de `page_obj`.)

- [ ] **Step 4: Correr la regresión de tablas + suite del parser**

Run: `pytest tests/rag_lib/parsing/ -q`
Expected: PASS. Si `find_tables()` fallara sobre la `FilteredPage`, revisar la versión de pdfplumber; el código ya usaba `page_obj.filter(...)` dentro de `_extract_prose_groups`, así que `FilteredPage` soporta las operaciones necesarias.

- [ ] **Step 5: Gate de validación SC700 (manual)**

Confirmar que descartar `SC700` no elimina contenido real de reglas. Ejecutar este script y revisar que el texto perdido es solo flavor decorativo, no subtítulos/reglas:

```powershell
$env:PYTHONIOENCODING="utf-8"; python -c "import pdfplumber, collections; pdf=pdfplumber.open('manual.pdf'); pages=[33,34,199,388]; [print('p',i+1, collections.Counter(c.get('fontname','?').split('+')[-1] for c in pdf.pages[i].chars if 'SC700' in c.get('fontname','') and c.get('text','').strip())) for i in pages]; pdf.close()"
```

Si en páginas de reglas (p200→índice 199, p389→índice 388) aparecieran muchos chars SC700 que forman texto de reglas legible, **parar** y afinar `_DECORATIVE_FONT_MARKERS` (p.ej. `("IndustryInc-Base-SC700", "BisectModificadaRegular-SC700")` para ser más específico). Documentar la decisión en el commit/PR.

- [ ] **Step 6: Checkpoint**

Run: `pytest tests/rag_lib/ -q`
Expected: PASS.

---

## Task 3: Extraer helpers de prosa (refactor sin cambio de comportamiento)

**Files:**
- Modify: `src/rag_lib/parsing/pdfplumber_parser.py`
- Test: `tests/rag_lib/parsing/test_pdfplumber_parser.py`

- [ ] **Step 1: Test de preservación de orden en `_lines_to_blocks`**

Este test fija el cambio clave: `_lines_to_blocks` debe respetar el orden de entrada (no re-ordenar por `top`), porque el orden de lectura a 2 columnas se reconstruye antes.

```python
from rag_lib.parsing.pdfplumber_parser import _lines_to_blocks


def test_lines_to_blocks_preserves_input_order() -> None:
    """Las líneas se concatenan en el orden dado, no re-ordenadas por top."""
    line_low = [{"text": "abajo", "x0": 10.0, "x1": 40.0, "top": 200.0, "size": 11.0}]
    line_high = [{"text": "arriba", "x0": 10.0, "x1": 40.0, "top": 100.0, "size": 11.0}]
    # Entrada deliberadamente fuera de orden vertical:
    blocks = _lines_to_blocks([line_low, line_high])
    assert len(blocks) == 1
    text, _fs = blocks[0]
    assert text == "abajo arriba"
```

- [ ] **Step 2: Correr para verificar que falla**

Run: `pytest tests/rag_lib/parsing/test_pdfplumber_parser.py::test_lines_to_blocks_preserves_input_order -v`
Expected: FAIL con `ImportError` (helper aún no existe).

- [ ] **Step 3: Extraer `_group_lines`, `_body_chars`, `_strip_overlay`, `_lines_to_blocks` y `_reading_order_blocks` a nivel de módulo**

Añadir estas funciones de módulo (debajo de `_dedup_and_drop`). Conservan la lógica existente de los Steps 2, 2.5 y 3, salvo que `_lines_to_blocks` **ya no ordena por `top`** (itera en el orden recibido):

```python
def _group_lines(chars: list[dict]) -> list[list[dict]]:
    """Group chars into visual lines by top coordinate (±2pt), top→bottom."""
    chars_sorted = sorted(chars, key=lambda c: (round(float(c["top"]) / 2) * 2, float(c["x0"])))
    lines: list[list[dict]] = []
    for ch in chars_sorted:
        if lines and abs(float(lines[-1][0]["top"]) - float(ch["top"])) <= 2.0:
            lines[-1].append(ch)
        else:
            lines.append([ch])
    return lines


def _body_chars(chars: list[dict]) -> list[dict]:
    """Chars at body fontsize (≤1.5× the page's 10th-percentile size).

    Excludes large spanning titles so they don't fill the column gutter.
    """
    sizes = sorted(float(c["size"]) for c in chars if c.get("size") and float(c["size"]) > 0)
    if not sizes:
        return chars
    p10 = sizes[max(0, int(len(sizes) * 0.1))]
    limit = max(p10, 6.0) * 1.5
    return [c for c in chars if float(c.get("size", p10)) <= limit]


def _strip_overlay(lines: list[list[dict]]) -> list[list[dict]]:
    """Step 2.5 — drop decorative overlay chars from mixed-fontsize lines."""
    cleaned: list[list[dict]] = []
    for line in lines:
        sizes = sorted(float(c["size"]) for c in line if c.get("size") and float(c["size"]) > 0)
        if not sizes:
            cleaned.append(line)
            continue
        p10 = sizes[max(0, int(len(sizes) * 0.1))]
        limit = max(p10, 6.0) * 1.5
        kept = [c for c in line if float(c.get("size", p10)) <= limit]
        cleaned.append(kept if kept else line)
    return cleaned


def _line_fontsize(line: list[dict]) -> float:
    sizes = [float(c["size"]) for c in line if c.get("size")]
    return sum(sizes) / len(sizes) if sizes else 11.0


def _line_text(line: list[dict]) -> str:
    return "".join(c.get("text", "") for c in sorted(line, key=lambda c: float(c["x0"])))


def _lines_to_blocks(lines: list[list[dict]]) -> list[tuple[str, float]]:
    """Step 3 — group adjacent lines with similar fontsize (±1pt) into blocks.

    Preserves input order (does NOT re-sort by top): callers establish reading
    order beforehand (single-column lines arrive top-sorted from _group_lines;
    two-column lines arrive in reading order from _segment_reading_order).
    """
    blocks: list[tuple[str, float]] = []
    current_lines: list[list[dict]] = []
    current_fs: float | None = None

    for line in lines:
        fs = _line_fontsize(line)
        if current_fs is None or abs(fs - current_fs) <= 1.0:
            if current_fs is None:
                current_fs = fs
            current_lines.append(line)
        else:
            text = " ".join(_line_text(ln) for ln in current_lines).strip()
            if text:
                blocks.append((text, current_fs))
            current_lines = [line]
            current_fs = fs

    if current_lines:
        text = " ".join(_line_text(ln) for ln in current_lines).strip()
        if text:
            blocks.append((text, current_fs or 11.0))
    return blocks


def _reading_order_blocks(chars: list[dict], page_width: float) -> list[tuple[str, float]]:
    """Core: chars → (text, fontsize) blocks in reading order (single column for now)."""
    chars = [c for c in chars if c.get("size") and float(c["size"]) > 0 and c.get("text", "")]
    if not chars:
        return []
    lines = _group_lines(chars)
    lines = _strip_overlay(lines)
    return _lines_to_blocks(lines)
```

- [ ] **Step 4: Refactor de `_extract_prose_groups` para usar el core**

Reemplazar el cuerpo de `_extract_prose_groups` (todo lo que va tras el Step 1) por una llamada al core. El método queda:

```python
    def _extract_prose_groups(
        self, page_obj: pdfplumber.page.Page, table_bboxes: list[tuple]
    ) -> list[tuple[str, float]]:
        """Return prose text grouped by fontsize — one (text, fontsize_avg) per block."""
        chars = self._chars_outside_tables(page_obj, table_bboxes)
        return _reading_order_blocks(chars, float(page_obj.width))
```

Y extraer el Step 1 actual a un método `_chars_outside_tables`:

```python
    def _chars_outside_tables(
        self, page_obj: pdfplumber.page.Page, table_bboxes: list[tuple]
    ) -> list[dict]:
        """Step 1 — chars del page que no caen dentro de ninguna table bbox."""
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
        return [
            c for c in filtered.chars
            if c.get("size") and float(c["size"]) > 0 and c.get("text", "")
        ]
```

- [ ] **Step 5: Correr el test de orden + toda la suite del parser**

Run: `pytest tests/rag_lib/parsing/ -q`
Expected: PASS (incluyendo `test_lines_to_blocks_preserves_input_order` y todos los tests de prosa existentes, que dan salida idéntica porque las líneas de 1 columna ya venían top-ordenadas).

- [ ] **Step 6: Checkpoint**

Run: `pytest tests/rag_lib/ -q`
Expected: PASS.

---

## Task 4: Detección de canalón — `_detect_gutter`

**Files:**
- Modify: `src/rag_lib/parsing/pdfplumber_parser.py`
- Test: `tests/rag_lib/parsing/test_pdfplumber_parser.py`

- [ ] **Step 1: Tests de `_detect_gutter`**

```python
from rag_lib.parsing.pdfplumber_parser import _detect_gutter


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
```

- [ ] **Step 2: Correr para verificar que fallan**

Run: `pytest tests/rag_lib/parsing/test_pdfplumber_parser.py -k detect_gutter -v`
Expected: FAIL con `ImportError`.

- [ ] **Step 3: Implementar `_detect_gutter` y sus constantes**

Bajo `_DECORATIVE_FONT_MARKERS`, añadir constantes; e implementar la función a nivel de módulo:

```python
_MIN_GUTTER_PT = 10.0
_GUTTER_CENTRAL_BAND = (0.30, 0.70)
_GUTTER_MIN_SIDE_FRAC = 0.15
```

```python
def _detect_gutter(body_chars: list[dict], page_width: float) -> float | None:
    """Return the x of a vertical gutter splitting two columns, or None.

    Proyecta los intervalos [x0, x1] de los body chars sobre el eje X y busca
    la banda contigua de cobertura cero más ancha en la región central. Acepta
    si es ≥ _MIN_GUTTER_PT y hay ≥15% de chars a cada lado.
    """
    import math

    if not body_chars or page_width <= 0:
        return None
    width = int(math.ceil(page_width))
    coverage = [0] * (width + 1)
    for c in body_chars:
        x0 = int(max(0.0, float(c["x0"])))
        x1 = int(min(float(width), float(c.get("x1", c["x0"]))))
        if x1 < x0:
            x1 = x0
        for x in range(x0, x1 + 1):
            coverage[x] += 1

    lo = int(width * _GUTTER_CENTRAL_BAND[0])
    hi = int(width * _GUTTER_CENTRAL_BAND[1])
    best_start = best_len = 0
    run_start: int | None = None
    for x in range(lo, hi + 1):
        if coverage[x] == 0:
            if run_start is None:
                run_start = x
            if x - run_start + 1 > best_len:
                best_len = x - run_start + 1
                best_start = run_start
        else:
            run_start = None

    if best_len < _MIN_GUTTER_PT:
        return None
    gutter = best_start + best_len / 2.0
    left = sum(1 for c in body_chars if float(c["x0"]) < gutter)
    right = len(body_chars) - left
    threshold = _GUTTER_MIN_SIDE_FRAC * len(body_chars)
    if left < threshold or right < threshold:
        return None
    return gutter
```

- [ ] **Step 4: Correr los tests para verificar que pasan**

Run: `pytest tests/rag_lib/parsing/test_pdfplumber_parser.py -k detect_gutter -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Checkpoint**

Run: `pytest tests/rag_lib/parsing/ -q`
Expected: PASS.

---

## Task 5: Orden de lectura por bandas — `_segment_reading_order`

**Files:**
- Modify: `src/rag_lib/parsing/pdfplumber_parser.py`
- Test: `tests/rag_lib/parsing/test_pdfplumber_parser.py`

- [ ] **Step 1: Tests de `_segment_reading_order`**

```python
from rag_lib.parsing.pdfplumber_parser import _segment_reading_order, _lines_to_blocks


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
```

- [ ] **Step 2: Correr para verificar que fallan**

Run: `pytest tests/rag_lib/parsing/test_pdfplumber_parser.py -k segment_reading_order -v`
Expected: FAIL con `ImportError`.

- [ ] **Step 3: Implementar `_segment_reading_order`**

```python
def _segment_reading_order(
    lines: list[list[dict]], gutter_x: float, tol: float = 2.0
) -> list[list[dict]]:
    """Reorder line-clusters into two-column reading order.

    Cada línea cruda (cluster por top) se clasifica:
      - cruza el canalón (algún char ocupa [gutter_x±tol]) → ancho completo,
        separa bandas y se emite entera en orden documental.
      - no lo cruza → columnar: se parte en sub-línea izquierda/derecha por
        el centro del char.
    Orden final: por bandas delimitadas por líneas full-width; dentro de cada
    banda todas las sub-líneas izquierdas (top↑) y luego las derechas (top↑).
    """
    def crosses(line: list[dict]) -> bool:
        return any(
            float(c["x0"]) < gutter_x + tol and float(c.get("x1", c["x0"])) > gutter_x - tol
            for c in line
        )

    ordered: list[list[dict]] = []
    left_buf: list[list[dict]] = []
    right_buf: list[list[dict]] = []

    def flush() -> None:
        ordered.extend(left_buf)
        ordered.extend(right_buf)
        left_buf.clear()
        right_buf.clear()

    for line in lines:
        if crosses(line):
            flush()
            ordered.append(line)
            continue
        left = [c for c in line if (float(c["x0"]) + float(c.get("x1", c["x0"]))) / 2.0 < gutter_x]
        right = [c for c in line if (float(c["x0"]) + float(c.get("x1", c["x0"]))) / 2.0 >= gutter_x]
        if left:
            left_buf.append(left)
        if right:
            right_buf.append(right)
    flush()
    return ordered
```

- [ ] **Step 4: Correr los tests para verificar que pasan**

Run: `pytest tests/rag_lib/parsing/test_pdfplumber_parser.py -k segment_reading_order -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Checkpoint**

Run: `pytest tests/rag_lib/parsing/ -q`
Expected: PASS.

---

## Task 6: Integrar columnas en el core + test de integración

**Files:**
- Modify: `src/rag_lib/parsing/pdfplumber_parser.py`
- Test: `tests/rag_lib/parsing/test_pdfplumber_parser.py`

- [ ] **Step 1: Test de integración — `_extract_prose_groups` reconstruye 2 columnas**

```python
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
```

(`_FakePage` necesita `width` — ya lo tiene, 595.0. `_extract_prose_groups` con `table_bboxes=[]` no llama a `filter`, así que `_FakePage` sirve.)

- [ ] **Step 2: Correr para verificar que falla**

Run: `pytest tests/rag_lib/parsing/test_pdfplumber_parser.py::test_extract_prose_groups_reconstructs_two_columns -v`
Expected: FAIL — el core aún es single-column, el texto sale interleaved (`IDZEQRU...`).

- [ ] **Step 3: Añadir detección de columnas a `_reading_order_blocks`**

Modificar `_reading_order_blocks` para insertar gutter + segmentación entre `_group_lines` y `_strip_overlay`:

```python
def _reading_order_blocks(chars: list[dict], page_width: float) -> list[tuple[str, float]]:
    """Core: chars → (text, fontsize) blocks in reading order (1 o 2 columnas)."""
    chars = [c for c in chars if c.get("size") and float(c["size"]) > 0 and c.get("text", "")]
    if not chars:
        return []
    lines = _group_lines(chars)
    gutter = _detect_gutter(_body_chars(chars), page_width)
    if gutter is not None:
        lines = _segment_reading_order(lines, gutter)
    lines = _strip_overlay(lines)
    return _lines_to_blocks(lines)
```

- [ ] **Step 4: Correr el test de integración + suite del parser**

Run: `pytest tests/rag_lib/parsing/ -q`
Expected: PASS (incluyendo `test_extract_prose_groups_reconstructs_two_columns` y todos los de 1 columna sin cambios).

- [ ] **Step 5: Checkpoint**

Run: `pytest tests/rag_lib/ -q`
Expected: PASS.

---

## Task 7: Caption column-aware

**Files:**
- Modify: `src/rag_lib/parsing/pdfplumber_parser.py`
- Test: `tests/rag_lib/parsing/test_pdfplumber_parser.py`

- [ ] **Step 1: Test — el texto de caption se reconstruye column-aware**

Probamos el core de reconstrucción que usará el caption (`_reading_order_blocks`) sobre chars de 2 columnas, verificando que el texto unido no queda interleaved:

```python
def test_caption_text_reconstructs_columns() -> None:
    """Una región de caption que cruza 2 columnas se lee izq-luego-der."""
    from rag_lib.parsing.pdfplumber_parser import _reading_order_blocks
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
```

- [ ] **Step 2: Correr para verificar que pasa con el core ya integrado**

Run: `pytest tests/rag_lib/parsing/test_pdfplumber_parser.py::test_caption_text_reconstructs_columns -v`
Expected: PASS (el core de Task 6 ya hace la reconstrucción; este test fija que el caption la heredará).

- [ ] **Step 3: Hacer `_extract_caption` column-aware**

Reemplazar la extracción de texto en `_extract_caption` (líneas 158-165) para usar el core en vez de `region.extract_text()`:

```python
        try:
            region = page_obj.crop(
                (x0, max(0.0, top_clamped - _CAPTION_LOOKAHEAD_PT), x1, top_clamped)
            )
            blocks = _reading_order_blocks(list(region.chars), float(page_obj.width))
        except ValueError:
            return None
        text = " ".join(t for t, _ in blocks)
        return text.strip() if text.strip() else None
```

(Se pasa `page_obj.width` —no `region.width`— porque los chars conservan coordenadas absolutas de página y `_detect_gutter` opera en ese sistema.)

- [ ] **Step 4: Correr la suite del parser**

Run: `pytest tests/rag_lib/parsing/ -q`
Expected: PASS (los tests de caption/tabla existentes siguen verdes; el texto de caption de tablas de 1 columna es idéntico).

- [ ] **Step 5: Checkpoint**

Run: `pytest tests/rag_lib/ -q`
Expected: PASS.

---

## Task 8: Re-ingesta y validación de aceptación

**Files:**
- Reference: `manual.pdf`, `data/rag.db`
- No code changes — verificación end-to-end.

- [ ] **Step 1: Suite completa verde**

Run: `pytest tests/rag_lib/ -q`
Expected: PASS (≥200 tests; los pre-existentes conocidos de `test_config`/TTS no aplican aquí).

- [ ] **Step 2: Borrar el manual viejo y re-ingestar**

```powershell
python -c "import sqlite3; c=sqlite3.connect('data/rag.db'); c.execute('DELETE FROM rag_manuals WHERE id = 8'); c.commit(); c.close()"
```

Re-ingestar con el CLI de ingesta del módulo RAG sobre `manual.pdf` (ver `docs/rag-lib.md` para el comando exacto del proyecto). Anotar el nuevo `manual_id` (esperado: 9).

- [ ] **Step 3: Validar criterios de aceptación**

```powershell
$env:PYTHONIOENCODING="utf-8"; python -c @'
import sqlite3, re, sys
sys.stdout.reconfigure(encoding="utf-8")
conn = sqlite3.connect("data/rag.db"); cur = conn.cursor()

rx = re.compile(r"(?:([a-záéíóúñ])\1){3,}", re.IGNORECASE)
cur.execute("SELECT seq, page, text FROM rag_chunks")
rows = cur.fetchall()
dbl = [(s,p) for s,p,t in rows if rx.search(t or "")]
print("1) doble-char (incl. tablas):", len(dbl), "→ esperado 0", dbl[:5])

cur.execute("SELECT COUNT(*) FROM rag_chunks WHERE text LIKE '%DATOSC iberterminal%'")
print("2) interleaving p200 'DATOSC iberterminal':", cur.fetchone()[0], "→ esperado 0")

cur.execute("SELECT COUNT(*) FROM rag_chunks WHERE text LIKE '%Quieresenelmundo%'")
print("3) gibberish SC700 'Quieresenelmundo':", cur.fetchone()[0], "→ esperado 0")

cur.execute("SELECT COUNT(*) FROM rag_chunks")
total = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM rag_chunks WHERE section_path IS NOT NULL AND section_path != ''")
sp = cur.fetchone()[0]
print(f"4) section_path: {sp}/{total} = {100*sp/total:.1f}% → esperado ≥99%")

cur.execute("SELECT seq, section_path, substr(text,1,300) FROM rag_chunks WHERE page=200 LIMIT 3")
print("5) muestra p200 (legibilidad reglas):")
for r in cur.fetchall(): print("   ", r)
conn.close()
'@
```

Criterios: (1) 0, (2) 0, (3) 0, (4) ≥99%, (5) texto de Netrunning legible y secuencial.

- [ ] **Step 4: Muestreo manual de páginas antes problemáticas**

Inspeccionar pp.34-42 (flavor) y p389 (tabla `PUBLI...`) con una query similar y confirmar a ojo: body limpio, sin gibberish decorativo, tablas sin doble-char. Contrastar 1-2 chunks con `manual.pdf` vía pdfplumber (`pdf.pages[N-1].extract_text()`).

- [ ] **Step 5: Checkpoint final**

Reportar resultados de los 5 criterios. Si todos verdes, avisar al usuario para que pruebe y commitee (CLAUDE.md: el usuario commitea).

---

## Self-review notes

- **Cobertura del spec:** dedup página (Task 1-2), drop decorativo (Task 1 + gate Task 2 Step 5), detección columnas (Task 4-6), orden por bandas (Task 5), caption column-aware (Task 7), tests + regresión (todas), re-ingesta + aceptación (Task 8). Sin huecos.
- **Consistencia de tipos:** helpers de módulo `_dedup_and_drop`, `_group_lines`, `_body_chars`, `_strip_overlay`, `_line_fontsize`, `_line_text`, `_lines_to_blocks`, `_reading_order_blocks`, `_detect_gutter`, `_segment_reading_order`; métodos `_deduped_page`, `_chars_outside_tables`, `_extract_prose_groups`, `_extract_caption`, `_parse_page`. Nombres usados de forma consistente entre tareas.
- **Orden de lectura:** `_lines_to_blocks` deja de ordenar por `top` (Task 3) — requisito para que la reconstrucción de columnas (Task 5-6) no se deshaga; las páginas de 1 columna no cambian porque `_group_lines` ya entrega top-ordenado.
