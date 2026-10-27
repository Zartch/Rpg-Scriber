# PDF TOC Title Extraction — Design Spec

**Date:** 2026-05-28
**Branch:** rag
**Status:** Approved

## Problem

`section_path` en los chunks ingestados es inútil porque:

1. `_extract_prose_groups` está llamado en `_parse_page` pero el método no existe — el parser crashea en runtime si llega a esa línea.
2. La detección de headings en `run_chunker` usa el `fontsize_avg` de un `ProseBlock` que representa toda la página mezclada, no un bloque individual — la heurística p90 nunca puede distinguir un heading del cuerpo con esta granularidad.
3. Los PDFs de manuales de rol tienen outline/bookmarks en los metadatos del PDF (al menos una parte de ellos) — fuente de títulos exacta que no se aprovecha.

## Objetivo

Que `section_path` de cada chunk contenga el título correcto de la sección del manual donde aparece ese texto. Para PDFs con outline digital: títulos exactos del TOC. Para PDFs sin outline: títulos detectados por heurística de fontsize (con agrupación correcta).

## Arquitectura

```
PDF → PdfplumberParser.parse()       → list[ParsedPage]   (sin cambio)
    → PdfplumberParser.extract_toc() → list[TocEntry]      (nuevo)
                                              ↓
                               run_chunker(pages, toc=toc)
                                              ↓
                     chunks con section_path combinado TOC + sub-headings fontsize
```

Solo cuatro archivos cambian; la API pública de `ingest_pdf` no cambia.

## Tipos

### `TocEntry` (nuevo, interno en `types.py`)

```python
@dataclass(frozen=True)
class TocEntry:
    level: int    # 1 = capítulo, 2 = sección, 3 = subsección
    title: str
    page: int     # página donde empieza esta entrada (1-based)
```

## Cambios por archivo

### 1. `src/rag_lib/parsing/pdfplumber_parser.py`

#### `_extract_prose_groups(page_obj, table_bboxes) -> list[tuple[str, float]]`

Implementar el método actualmente faltante. Algoritmo:

1. Filtrar chars fuera de table bboxes (mismo filtro que `_extract_prose`).
2. Agrupar chars en **líneas** por proximidad vertical (±2pt en coordenada `top`).
3. Agrupar líneas adyacentes con fontsize similar (±1pt) en un **bloque**.
4. Devolver `[(texto_del_bloque, fontsize_avg_del_bloque), ...]` ordenados top→bottom.

Esto hace que `_parse_page` produzca múltiples `ProseBlock` por página — uno por grupo visual — en lugar de uno solo con el promedio de toda la página. El chunker puede entonces detectar headings por fontsize individual de cada bloque.

`_extract_prose` (el método que sí existe) se convierte en helper o se elimina si queda sin uso directo.

#### `extract_toc(pdf_path) -> list[TocEntry]`

Nuevo método público del parser. Usa **pdfminer** (ya instalado como dep de pdfplumber, sin nueva dependencia):

```python
with pdfplumber.open(pdf_path) as pdf:
    doc = pdf.doc   # pdfminer PDFDocument
    pageid_map = {p.page_obj.pageid: p.page_number for p in pdf.pages}
    outlines = list(doc.get_outlines())   # (level, title, dest, action, se)
    # resolver cada dest → page_number via pageid_map
```

Resolución de `dest` a número de página: `dest` es una lista donde el primer elemento es una referencia a un objeto página de pdfminer (`PDFObjRef`). Se resuelve a `objid` y se busca en `pageid_map`.

Fallback: si el PDF lanza `PDFNoOutlines`, devuelve `[]`. Cualquier entrada cuya página no se pueda resolver se omite sin error.

Resultado: `list[TocEntry]` ordenada por página ascendente.

### 2. `src/rag_lib/chunking.py`

#### Firma nueva de `run_chunker`

```python
def run_chunker(
    pages: list[ParsedPage],
    *,
    token_target: int = 500,
    overlap: int = 75,
    toc: list[TocEntry] | None = None,
) -> list[dict[str, Any]]:
```

#### Modo dual

**Con TOC (`toc` no vacío):**

- Se construye `_toc_path_at(page) -> str | None`: devuelve el path jerárquico de todas las entradas del TOC activas en esa página (la entrada con `page ≤ chunk.page` más reciente por nivel). Ejemplo: `"Capítulo 2: Personajes / Construcción de Personaje"`.
- El `section_stack` de fontsize sigue activo, pero se apila **sobre** el path base del TOC. El `section_path` resultante es: `toc_base + " / " + fontsize_subheadings` (si hay sub-headings detectados).
- Los bloques cuyo fontsize supera el threshold siguen clasificándose como headings — se añaden al stack sobre el path del TOC, no lo reemplazan.

**Sin TOC (`toc` vacío o None):**

- Comportamiento actual sin cambios: detección p90, `section_stack`, etc.
- Ahora sí funciona correctamente porque `_extract_prose_groups` produce bloques separados con fontsizes individuales.

#### Helper `_toc_path_at(page, toc)`

```python
def _toc_path_at(page: int, toc: list[TocEntry]) -> str | None:
    """Return the active TOC path for a given page number."""
    active: dict[int, str] = {}  # level → title
    for entry in toc:
        if entry.page > page:
            break
        # New entry at this level clears deeper levels
        active[entry.level] = entry.title
        for deeper in list(active):
            if deeper > entry.level:
                del active[deeper]
    if not active:
        return None
    return " / ".join(active[lvl] for lvl in sorted(active))
```

### 3. `src/rag_lib/__init__.py`

Dos líneas añadidas en `ingest_pdf`, entre `parse` y `run_chunker`:

```python
pages  = await asyncio.to_thread(_PARSER.parse, pdf_path)
toc    = await asyncio.to_thread(_PARSER.extract_toc, pdf_path)  # nuevo
chunks = run_chunker(pages, toc=toc)                              # toc= nuevo
```

Ambas llamadas en thread pool (sin bloquear el event loop). La firma pública de `ingest_pdf` no cambia.

### 4. `src/rag_lib/types.py`

Añadir `TocEntry` en la sección de tipos internos (junto a `ProseBlock`, `TableBlock`, `ParsedPage`).

## Testing

| Test | Archivo |
|---|---|
| `_extract_prose_groups` devuelve múltiples bloques por página con fontsizes distintos | `tests/rag_lib/test_parser.py` |
| `_extract_prose_groups` excluye texto dentro de table bboxes | `tests/rag_lib/test_parser.py` |
| `extract_toc` devuelve `[]` para PDF sin outline | `tests/rag_lib/test_parser.py` |
| `extract_toc` devuelve entradas ordenadas por página con level/title correctos | `tests/rag_lib/test_parser.py` |
| `_toc_path_at` devuelve el path jerárquico correcto | `tests/rag_lib/test_chunker.py` |
| `_toc_path_at` limpia niveles más profundos al encontrar nuevo entry de nivel superior | `tests/rag_lib/test_chunker.py` |
| `run_chunker` con TOC: chunks tienen section_path del TOC | `tests/rag_lib/test_chunker.py` |
| `run_chunker` sin TOC: comportamiento existente inalterado | `tests/rag_lib/test_chunker.py` |
| `run_chunker` con TOC: sub-headings fontsize se apilan sobre path del TOC | `tests/rag_lib/test_chunker.py` |

Tests de parser que usan PDFs reales (con y sin outline) se crean con fixtures de PDFs sintéticos generados con `reportlab` o `fpdf2` en `conftest.py`.

## Scope y no-scope

**En scope:**
- Fix de `_extract_prose_groups` (bug activo)
- `extract_toc` vía pdfminer
- `run_chunker` modo dual TOC + fontsize

**Fuera de scope:**
- Parsear el índice visual de un PDF que no tiene outline digital
- Cambios en la Web UI (`section_path` ya se muestra)
- Cambios en la API pública (`ingest_pdf`, `search`, etc.)
- Re-ingestar manuales ya existentes en la DB (el usuario borra y re-ingesta si quiere)
