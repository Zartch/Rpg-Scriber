# RAG Ingestion Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminar tres tipos de ruido en la ingesta de PDFs de manuales: caracteres duplicados por doble-render decorativo, chunks de TOC/índice, y terminadores de frase incompletos en la heurística de merge entre páginas.

**Architecture:** Tres fixes quirúrgicos en dos archivos (`pdfplumber_parser.py` y `chunking.py`). Ningún tipo nuevo, ninguna abstracción nueva. Tras los cambios se re-ingesta el manual desde cero.

**Tech Stack:** Python 3.10, pdfplumber, tiktoken, pytest, SQLite (via `python -m rag_lib`)

---

## File Map

| Archivo | Acción | Responsabilidad |
|---|---|---|
| `src/rag_lib/parsing/pdfplumber_parser.py` | Modify | Añadir Step 1.5 de dedup por posición en `_extract_prose_groups` |
| `src/rag_lib/chunking.py` | Modify | Añadir `_is_toc_noise`, skip en main loop, fix terminators + docstring |
| `tests/rag_lib/parsing/test_pdfplumber_parser.py` | Modify | Tests de dedup |
| `tests/rag_lib/test_chunking.py` | Modify | Tests de TOC noise y nuevos terminadores |

---

## Task 1: Dedup de chars duplicados en `_extract_prose_groups`

**Files:**
- Modify: `src/rag_lib/parsing/pdfplumber_parser.py:196-201` (después de construir `chars`, antes de Step 2)
- Test: `tests/rag_lib/parsing/test_pdfplumber_parser.py`

- [ ] **Step 1: Añadir `_FakePage` helper y escribir los tests que fallan**

Abre `tests/rag_lib/parsing/test_pdfplumber_parser.py`. Añade al final del archivo:

```python
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


def test_extract_prose_groups_deduplicates_same_position_chars() -> None:
    """PDF decorativo renderiza texto dos veces en la misma (x0, top) — el output debe ser limpio."""
    parser = _parser()
    char_h      = {"text": "H", "x0": 10.0, "top": 100.0, "size": 11.0, "object_type": "char"}
    char_h_dup  = {"text": "H", "x0": 10.0, "top": 100.0, "size": 11.0, "object_type": "char"}
    char_i      = {"text": "i", "x0": 16.0, "top": 100.0, "size": 11.0, "object_type": "char"}

    result = parser._extract_prose_groups(_FakePage([char_h, char_h_dup, char_i]), [])

    assert len(result) == 1
    text, _ = result[0]
    assert text == "Hi"


def test_extract_prose_groups_preserves_distinct_position_chars() -> None:
    """Chars en posiciones distintas se conservan todos."""
    parser = _parser()
    chars = [
        {"text": "A", "x0": 10.0, "top": 100.0, "size": 11.0, "object_type": "char"},
        {"text": "B", "x0": 20.0, "top": 100.0, "size": 11.0, "object_type": "char"},
        {"text": "C", "x0": 30.0, "top": 100.0, "size": 11.0, "object_type": "char"},
    ]
    result = parser._extract_prose_groups(_FakePage(chars), [])

    assert len(result) == 1
    text, _ = result[0]
    assert text == "ABC"
```

- [ ] **Step 2: Verificar que los tests fallan**

```
pytest tests/rag_lib/parsing/test_pdfplumber_parser.py::test_extract_prose_groups_deduplicates_same_position_chars tests/rag_lib/parsing/test_pdfplumber_parser.py::test_extract_prose_groups_preserves_distinct_position_chars -v
```

Resultado esperado: `FAILED` — el primero falla porque sin dedup el texto es `"HHi"`.

- [ ] **Step 3: Implementar el Step 1.5 en `_extract_prose_groups`**

En `src/rag_lib/parsing/pdfplumber_parser.py`, localiza estas líneas (alrededor de la línea 196):

```python
        chars = [
            c for c in filtered.chars
            if c.get("size") and float(c["size"]) > 0 and c.get("text", "")
        ]
        if not chars:
            return []

        # Step 2: group chars into lines by top coordinate (±2pt tolerance)
```

Reemplázalas por:

```python
        chars = [
            c for c in filtered.chars
            if c.get("size") and float(c["size"]) > 0 and c.get("text", "")
        ]
        if not chars:
            return []

        # Step 1.5: dedup chars at same position (PDF decorative double-render)
        seen_pos: set[tuple] = set()
        deduped: list[dict] = []
        for c in chars:
            pos = (round(float(c["x0"]), 1), round(float(c["top"]), 1))
            if pos not in seen_pos:
                seen_pos.add(pos)
                deduped.append(c)
        chars = deduped

        # Step 2: group chars into lines by top coordinate (±2pt tolerance)
```

- [ ] **Step 4: Verificar que los tests pasan**

```
pytest tests/rag_lib/parsing/test_pdfplumber_parser.py::test_extract_prose_groups_deduplicates_same_position_chars tests/rag_lib/parsing/test_pdfplumber_parser.py::test_extract_prose_groups_preserves_distinct_position_chars -v
```

Resultado esperado: `PASSED PASSED`

- [ ] **Step 5: Suite completa de parser sin regresiones**

```
pytest tests/rag_lib/parsing/ -v
```

Resultado esperado: todos pasan.

- [ ] **Step 6: Commit**

```bash
git add src/rag_lib/parsing/pdfplumber_parser.py tests/rag_lib/parsing/test_pdfplumber_parser.py
git commit -m "fix(rag): dedup chars at same position in _extract_prose_groups"
```

---

## Task 2: Filtro de TOC-noise en `run_chunker`

**Files:**
- Modify: `src/rag_lib/chunking.py` (añadir `_is_toc_noise` antes de `run_chunker`, añadir check en main loop)
- Test: `tests/rag_lib/test_chunking.py`

- [ ] **Step 1: Escribir los tests que fallan**

Abre `tests/rag_lib/test_chunking.py`. Añade este import al principio del archivo (junto a los demás imports):

```python
from rag_lib.chunking import _is_toc_noise
```

Luego añade al final del archivo:

```python
# ---------------------------------------------------------------------------
# _is_toc_noise
# ---------------------------------------------------------------------------

_TOC_LINE = (
    "Sala de trauma ...............................6 "
    "Cómo montar la escena ......................126"
)
_BODY_LINE = "El netrunner atacó al guardia con su monofilamento y escapó por la ventana."


def test_is_toc_noise_short_text_returns_false() -> None:
    assert not _is_toc_noise(".....")


def test_is_toc_noise_toc_line_returns_true() -> None:
    assert _is_toc_noise(_TOC_LINE)


def test_is_toc_noise_body_text_returns_false() -> None:
    assert not _is_toc_noise(_BODY_LINE)


def test_run_chunker_skips_toc_noise_blocks() -> None:
    pages = [ParsedPage(page_num=7, blocks=[ProseBlock(text=_TOC_LINE, page=7, fontsize_avg=11.0)])]
    chunks = run_chunker(pages)
    assert chunks == []
```

- [ ] **Step 2: Verificar que los tests fallan**

```
pytest tests/rag_lib/test_chunking.py::test_is_toc_noise_short_text_returns_false tests/rag_lib/test_chunking.py::test_is_toc_noise_toc_line_returns_true tests/rag_lib/test_chunking.py::test_is_toc_noise_body_text_returns_false tests/rag_lib/test_chunking.py::test_run_chunker_skips_toc_noise_blocks -v
```

Resultado esperado: `ImportError` o `FAILED` — `_is_toc_noise` no existe aún.

- [ ] **Step 3: Añadir `_is_toc_noise` en `chunking.py`**

En `src/rag_lib/chunking.py`, localiza la sección `# Internal helpers` al final del archivo. Añade `_is_toc_noise` justo antes de `_compute_p90`:

```python
def _is_toc_noise(text: str) -> bool:
    """True if block looks like a table-of-contents line (dot leaders + page numbers)."""
    if len(text) < 20:
        return False
    return text.count(".") / len(text) > 0.30
```

- [ ] **Step 4: Añadir el skip en el main loop de `run_chunker`**

En `src/rag_lib/chunking.py`, localiza (alrededor de línea 224):

```python
            elif isinstance(block, ProseBlock):
                # Non-TOC: strictly greater than p90 to avoid flagging body text when all
```

Reemplaza el `elif isinstance(block, ProseBlock):` completo por:

```python
            elif isinstance(block, ProseBlock):
                if _is_toc_noise(block.text):
                    continue

                # Non-TOC: strictly greater than p90 to avoid flagging body text when all
```

(Solo se añade el bloque `if _is_toc_noise` con el `continue` — el resto del `elif` queda intacto.)

- [ ] **Step 5: Verificar que los tests pasan**

```
pytest tests/rag_lib/test_chunking.py::test_is_toc_noise_short_text_returns_false tests/rag_lib/test_chunking.py::test_is_toc_noise_toc_line_returns_true tests/rag_lib/test_chunking.py::test_is_toc_noise_body_text_returns_false tests/rag_lib/test_chunking.py::test_run_chunker_skips_toc_noise_blocks -v
```

Resultado esperado: `PASSED PASSED PASSED PASSED`

- [ ] **Step 6: Suite completa de chunking sin regresiones**

```
pytest tests/rag_lib/test_chunking.py -v
```

Resultado esperado: todos pasan.

- [ ] **Step 7: Commit**

```bash
git add src/rag_lib/chunking.py tests/rag_lib/test_chunking.py
git commit -m "fix(rag): skip TOC-noise blocks in run_chunker"
```

---

## Task 3: Fix de terminadores y docstring en `should_merge_across_pages`

**Files:**
- Modify: `src/rag_lib/chunking.py:58-64` (función `should_merge_across_pages`)
- Test: `tests/rag_lib/test_chunking.py`

- [ ] **Step 1: Escribir los tests que fallan**

En `tests/rag_lib/test_chunking.py`, añade al final de la sección `should_merge_across_pages`:

```python
def test_no_merge_when_last_ends_with_closing_paren() -> None:
    assert not should_merge_across_pages("(ver apéndice A)", "el siguiente párrafo")


def test_no_merge_when_last_ends_with_closing_guillemet() -> None:
    assert not should_merge_across_pages("dijo el maestro»", "continuó la historia")


def test_no_merge_when_last_ends_with_closing_bracket() -> None:
    assert not should_merge_across_pages("consultar [tabla 3]", "para más detalles")
```

- [ ] **Step 2: Verificar que los tests fallan**

```
pytest tests/rag_lib/test_chunking.py::test_no_merge_when_last_ends_with_closing_paren tests/rag_lib/test_chunking.py::test_no_merge_when_last_ends_with_closing_guillemet tests/rag_lib/test_chunking.py::test_no_merge_when_last_ends_with_closing_bracket -v
```

Resultado esperado: `FAILED` — `)`, `»`, `]` no están en `TERMINATORS` todavía.

- [ ] **Step 3: Actualizar `should_merge_across_pages`**

En `src/rag_lib/chunking.py`, reemplaza la función completa (líneas 36–64 aprox.):

```python
def should_merge_across_pages(last_text: str, next_text: str) -> bool:
    """Return True if next_text continues last_text across a page boundary.

    False when:
    - Either input is empty.
    - last_text ends with a sentence terminator: . ! ? … : ) ] »
    - next_text starts with an uppercase letter (new sentence or heading).

    Note: Spanish opening punctuation (¡ ¿) does NOT terminate — it opens a sentence.
    """
    if not last_text or not next_text:
        return False
    last_char = last_text.rstrip()[-1]
    next_first = next_text.lstrip()[0]
    TERMINATORS = {'.', '!', '?', '…', ':', ')', ']', '»'}
    return last_char not in TERMINATORS and not next_first.isupper()
```

- [ ] **Step 4: Verificar que los tests pasan**

```
pytest tests/rag_lib/test_chunking.py::test_no_merge_when_last_ends_with_closing_paren tests/rag_lib/test_chunking.py::test_no_merge_when_last_ends_with_closing_guillemet tests/rag_lib/test_chunking.py::test_no_merge_when_last_ends_with_closing_bracket -v
```

Resultado esperado: `PASSED PASSED PASSED`

- [ ] **Step 5: Suite completa sin regresiones**

```
pytest tests/rag_lib/ -v
```

Resultado esperado: todos pasan.

- [ ] **Step 6: Commit**

```bash
git add src/rag_lib/chunking.py tests/rag_lib/test_chunking.py
git commit -m "fix(rag): add ), ], » terminators and update should_merge_across_pages docstring"
```

---

## Task 4: Re-ingesta del manual

**Files:** ninguno (operación sobre la DB)

- [ ] **Step 1: Borrar el manual existente de la DB**

El CLI tiene el comando `delete` que borra en cascada chunks y embeddings:

```
python -m rag_lib delete 6
```

Resultado esperado: confirmación de borrado (el manual_id 6 es el de `Ciberpunk RED - Libro básico_compressed` en la DB actual).

- [ ] **Step 2: Verificar que la DB está vacía**

```
python -m rag_lib list
```

Resultado esperado: lista vacía o sin manuales.

- [ ] **Step 3: Re-ingestar**

```
python -m rag_lib ingest manual.pdf --name "Ciberpunk RED - Libro básico"
```

Resultado esperado: progreso de ingesta y confirmación de chunks creados.

- [ ] **Step 4: Verificar calidad de los chunks**

```python
python -c "
import sqlite3
conn = sqlite3.connect('data/rag.db')
cur = conn.cursor()
cur.execute('SELECT COUNT(*) FROM rag_chunks')
print('Total chunks:', cur.fetchone())
# Verificar que no hay chunks con patron duplicado
cur.execute(\"SELECT COUNT(*) FROM rag_chunks WHERE text LIKE '%aattoo%' OR text LIKE '%ppaarr%'\")
print('Chunks con doble-char:', cur.fetchone())
# Verificar que no hay chunks de TOC
cur.execute(\"SELECT COUNT(*) FROM rag_chunks WHERE text LIKE '%.....%' AND length(text) > 50\")
print('Chunks con dots (posible TOC residual):', cur.fetchone())
conn.close()
"
```

Resultado esperado: `Chunks con doble-char: (0,)`. El conteo de dots puede ser >0 por tablas legítimas con puntos suspensivos, pero no debería haber líneas de índice puras.

- [ ] **Step 5: Muestra visual de chunks en páginas antes problemáticas**

```python
python -c "
import sqlite3
conn = sqlite3.connect('data/rag.db')
cur = conn.cursor()
# Páginas 34-36 eran las más afectadas por doble-char
cur.execute('SELECT seq, page, section_path, substr(text, 1, 300) FROM rag_chunks WHERE page BETWEEN 34 AND 36 LIMIT 5')
for row in cur.fetchall():
    print(f'seq={row[0]} page={row[1]} section={row[2]}')
    print(row[3])
    print()
conn.close()
"
```

Resultado esperado: texto legible en español, sin patrones `ppaassaarr`.
