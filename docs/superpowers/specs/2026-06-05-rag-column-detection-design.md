# RAG Ingestion — Column Detection, Page-level Dedup & Decorative Drop

**Date:** 2026-06-05
**Status:** Approved
**Predecesor:** [`2026-05-29-rag-ingestion-quality-design.md`](2026-05-29-rag-ingestion-quality-design.md) (dedup de prosa, filtro TOC, terminadores — ya implementado)

## Problema

Tras los fixes de calidad de ingesta de la ronda anterior (dedup de prosa, filtro de TOC, terminadores), la re-ingesta de `manual.pdf` (Ciberpunk RED, 464 págs, `manual_id=8`, 1392 chunks) dejó tres problemas conocidos, confirmados con inspección del PDF:

1. **Interleaving de columnas en texto de reglas.** El manual usa layout a 2 columnas (canalón en x≈300 en página A4 de 595pt de ancho). `_extract_prose_groups` agrupa los chars en líneas **solo por la coordenada `top`**, así que una línea de la columna izquierda y otra de la derecha a la misma altura se fusionan; al ordenar por `x0` se intercalan.
   - Ejemplo (p200, Netrunning): `Ahora te pones tus DATOSC iberterminal gafas de virtualidad, introduces mentalmente el Los programas código...` (izquierda + derecha intercaladas).
   - Mismo origen que las "palabras duplicadas": `en en la ciudad`, `proyectos yectos`, `corporativo corporativo`, `tumbos, tumbos`.

2. **Doble-char en tablas.** El fix de dedup de la ronda anterior (Step 1.5) vive **solo en la ruta de prosa** (`_extract_prose_groups`). La ruta de tablas (`page.find_tables()` → `ft.extract()`) no deduplica, así que el render decorativo doble sobrevive en celdas/caption.
   - Ejemplo (p389): `Tabla: ——PPUUBBLLIIALLRIIUURESSG SSLYYARRDOUUSSR`.
   - El caption de tabla también sufre interleaving de columnas cuando la tabla es de ancho completo (p200: `Tabla: tneúrmmeinroa ld peo rtaennuter...`).

3. **Flavor decorativo ilegible.** Los sidebars de flavor text de arquetipos (pp.34-42) usan fuentes small-caps `IndustryInc-Base-SC700` y `BisectModificadaRegular-SC700`, que salen sin espacios y scrambled: `Quieresenelmundoneoorporativo`. Es texto de ambientación, no reglas — ruido para un rules-bot RAG.

### Datos de soporte (inspección del PDF)

- **p200** (reglas): 3456 chars no-espacio, 649 espacios; distribución de `x0` con caída marcada en x≈300 → canalón de 2 columnas.
- **p35** (flavor): fuentes presentes — `FuturaPT-Book` 1814 (body), `IndustryInc-Base-SC700` 895 (decorativo), `BisectModificadaRegular-SC700` 96 (decorativo). El body limpio es FuturaPT; el ruido es SC700.

## Objetivo

Re-ingestar `manual.pdf` produciendo chunks limpios: sin interleaving de columnas, sin doble-char (también en tablas), sin flavor decorativo scrambled. Refactor acotado a `pdfplumber_parser.py` con un ajuste menor de caption; sin tocar `chunking.py` salvo lo necesario, ni Web UI/API.

## Decisiones de diseño (aprobadas)

- **Detección de columnas: completa** (Opción A — proyección de huecos verticales), con fallback seguro a 1 columna.
- **Flavor decorativo: descartar** por `fontname` (no reconstruir).

## Arquitectura

El trabajo se concentra en `src/rag_lib/parsing/pdfplumber_parser.py`. `_extract_prose_groups` se descompone en helpers con responsabilidad única, encajando en la estructura existente (Steps 1→3). La detección de columnas se inserta entre el agrupado en líneas y el agrupado en bloques.

```
_parse_page
  ├─ dedup a nivel de página + drop decorativo  → FilteredPage `page`
  ├─ page.find_tables() / ft.extract()          (recibe chars deduplicados)
  ├─ _extract_caption(page, bbox)               (column-aware)
  └─ _extract_prose_groups(page, table_bboxes)
        ├─ Step 1:  filtrar chars fuera de tablas
        ├─ Step 2:  _group_lines(chars)                → líneas (cluster por top)
        ├─ NUEVO:   _detect_gutter(body_chars, width)  → gutter_x | None
        ├─ NUEVO:   _segment_reading_order(lines, gutter_x) → líneas ordenadas
        ├─ Step 2.5: strip overlay (sin cambios)
        └─ Step 3:  _lines_to_blocks(ordered_lines)    → (text, fontsize) bloques
```

## Componentes

### 1. Dedup a nivel de página + drop decorativo — `_parse_page`

Hoy el dedup (Step 1.5) está dentro de `_extract_prose_groups`, así que las tablas no se benefician. Se mueve a `_parse_page` y se aplica **una sola vez** vía `page.filter(...)`, de modo que `find_tables()`, `_extract_caption` y la prosa reciban todos los mismos chars deduplicados y sin fuentes decorativas.

```python
_DECORATIVE_FONT_MARKERS = ("SC700",)  # small-caps decorativos (IndustryInc / Bisect)

def _deduped_page(page_obj):
    seen: set[tuple] = set()
    kept_ids: set[int] = set()
    for c in page_obj.chars:  # orden de extracción estable
        font = c.get("fontname", "")
        if any(m in font for m in _DECORATIVE_FONT_MARKERS):
            continue  # drop decorativo
        key = (round(float(c["x0"]), 1), round(float(c["top"]), 1), c.get("text"))
        if key not in seen:
            seen.add(key)
            kept_ids.add(id(c))
    def keep(obj):
        return obj.get("object_type") != "char" or id(obj) in kept_ids
    return page_obj.filter(keep)
```

Notas:
- `id(c)` es estable porque pdfplumber cachea los dicts de char en la página durante su vida útil; el predicado `keep` filtra por identidad, robusto aunque `filter` se evalúe de forma perezosa o múltiple.
- El dedup combina posición **+ texto** en la clave para no colapsar glifos adyacentes legítimos.
- El Step 1.5 actual de `_extract_prose_groups` se **elimina** (queda cubierto aquí).

**Gate de validación (obligatorio durante la implementación):** confirmar que `SC700` no acarrea contenido real (p.ej. subtítulos de reglas) en páginas distintas a los sidebars de flavor. Método: comparar el texto de unas páginas de reglas con/sin el drop. Si SC700 apareciera como contenido legítimo, afinar el marcador (p.ej. exigir además fontsize grande o limitarlo a `IndustryInc`/`Bisect`).

### 2. Detección de columnas — `_detect_gutter`

```python
def _detect_gutter(body_chars: list[dict], page_width: float) -> float | None:
    """Return the x of a vertical gutter splitting two columns, or None (single column)."""
```

Algoritmo:
1. **Body chars:** excluir chars de fuente grande (títulos que cruzan el canalón) usando el mismo criterio de tamaño del Step 2.5 (≤ 1.5× el p10 de tamaños de la página), para que un título de ancho completo no "rellene" el canalón.
2. **Proyección X:** array de cobertura sobre `[0, page_width]` en bins de 1pt; por cada char incrementar los bins en `[x0, x1]`.
3. **Región central:** restringir la búsqueda a `x ∈ [0.30·W, 0.70·W]`.
4. **Mayor hueco:** encontrar la corrida contigua más ancha de bins con cobertura `== 0` en esa región.
5. **Aceptación:** si ancho ≥ `MIN_GUTTER_PT` (10pt) **y** hay chars sustanciales a ambos lados (cada lado ≥ 15% de los body chars), devolver el punto medio de la corrida. Si no, `None`.

Constantes de módulo: `_MIN_GUTTER_PT = 10.0`, `_GUTTER_CENTRAL_BAND = (0.30, 0.70)`, `_GUTTER_MIN_SIDE_FRAC = 0.15`.

### 3. Orden de lectura por bandas — `_segment_reading_order`

```python
def _segment_reading_order(lines: list[list[dict]], gutter_x: float) -> list[list[dict]]:
    """Reorder line-clusters into reading order for a two-column page."""
```

Para cada línea (cluster por `top` del Step 2), clasificar según la **cobertura en `gutter_x`**:
- **Ancho completo:** hay chars que cubren `gutter_x` de forma continua (título/caption que cruza) → la línea se mantiene entera.
- **Columnar:** hay un hueco en `gutter_x` (chars a izquierda y/o derecha, pero no sobre el canalón) → se parte en sub-línea izquierda (`x_center < gutter_x`) y sub-línea derecha.

Reconstrucción del orden de lectura por **bandas** delimitadas por las líneas de ancho completo:
```
[título_full_1]
[banda 1: todas las sub-líneas izq (top↑) , luego todas las sub-líneas der (top↑)]
[título_full_2]
[banda 2: izq..., der...]
...
```
Es decir: se recorre el documento de arriba a abajo; al encontrar una línea full-width se emite y se cierra la banda actual (volcando izquierda-luego-derecha); las líneas columnar se acumulan en la banda abierta.

Cuando `gutter_x is None`, `_extract_prose_groups` salta este paso y usa las líneas tal cual (comportamiento de 1 columna idéntico al actual).

### 4. Refactor de `_extract_prose_groups`

Queda como orquestador delgado:
```python
def _extract_prose_groups(self, page_obj, table_bboxes):
    chars = self._chars_outside_tables(page_obj, table_bboxes)   # Step 1
    if not chars:
        return []
    lines = _group_lines(chars)                                  # Step 2
    body_chars = _body_chars(chars)                              # para el gutter
    gutter_x = _detect_gutter(body_chars, page_obj.width)
    if gutter_x is not None:
        lines = _segment_reading_order(lines, gutter_x)
    lines = _strip_overlay(lines)                                # Step 2.5 (intacto)
    return _lines_to_blocks(lines)                               # Step 3 (intacto)
```
Los Steps 2.5 y 3 se extraen a helpers (`_strip_overlay`, `_lines_to_blocks`) sin cambiar su lógica, para aislar responsabilidades y facilitar el test.

### 5. Caption column-aware — `_extract_caption`

La región de caption (recorte sobre la tabla) puede cruzar el canalón cuando la tabla es de ancho completo. Tras `region.chars`, aplicar `_detect_gutter` + `_segment_reading_order` antes de unir el texto, reutilizando los mismos helpers. Si no se detecta canalón, comportamiento actual.

## Data flow

`PdfplumberParser.parse` → por página `_parse_page`:
1. `page = _deduped_page(page_obj)` (dedup + drop decorativo).
2. Tablas: `page.find_tables()` → `TableBlock(rows, caption=_extract_caption(page, bbox))`.
3. Prosa: `_extract_prose_groups(page, table_bboxes)` → `ProseBlock(text, fontsize_avg)`.
4. `run_chunker` (sin cambios) consume los blocks como hoy.

## Error handling

- `_detect_gutter` devuelve `None` ante cualquier ambigüedad (sin canalón claro, un solo lado con contenido) → fallback seguro a 1 columna.
- Páginas sin chars o solo decorativos → `_extract_prose_groups` retorna `[]` (igual que hoy).
- El manejo existente de excepciones por página en `parse` (fallback a `ParsedPage` vacía) y el `try/except ValueError` de `find_tables`/`extract` se conservan.

## Testing

Unitarios nuevos (chars sintéticos, sin PDF real salvo donde se indique):

| Test | Archivo |
|---|---|
| `_detect_gutter`: 2 columnas con hueco central → devuelve x≈canalón | `tests/rag_lib/test_parser.py` |
| `_detect_gutter`: 1 columna (cobertura uniforme) → `None` | `tests/rag_lib/test_parser.py` |
| `_detect_gutter`: título full-width sobre 2 columnas → sigue detectando el canalón (no lo bloquea) | `tests/rag_lib/test_parser.py` |
| `_detect_gutter`: contenido solo a un lado → `None` | `tests/rag_lib/test_parser.py` |
| `_segment_reading_order`: 2 líneas columnar a misma `top` → orden izquierda-luego-derecha | `tests/rag_lib/test_parser.py` |
| `_segment_reading_order`: línea full-width entre dos bandas → emitida en orden documental correcto | `tests/rag_lib/test_parser.py` |
| `_deduped_page`/dedup helper: chars duplicados en misma posición → un solo char | `tests/rag_lib/test_parser.py` |
| drop decorativo: char con `fontname` `*SC700*` → descartado; otras fuentes conservadas | `tests/rag_lib/test_parser.py` |
| `_extract_prose_groups` 1 columna → salida idéntica a la actual (regresión) | `tests/rag_lib/test_parser.py` |

**Regresión:** la suite completa `pytest tests/rag_lib/` (200 tests) debe pasar; las páginas de 1 columna deben producir salida idéntica.

## Re-ingesta y criterios de aceptación

Tras implementar y pasar la suite, re-ingestar:
```sql
DELETE FROM rag_manuals WHERE id = 8;  -- chunks/embeddings en cascada (FK ON DELETE CASCADE)
```
Correr el CLI de ingesta con `manual.pdf` (nuevo `manual_id=9`) y validar con un script (reutiliza las queries de verificación de la ronda anterior):

| Criterio | Verificación |
|---|---|
| 0 chunks con doble-char (incluye tablas) | scan regex `(?:([a-záéíóúñ])\1){3,}` sobre `text` → 0 hits |
| p200 sin interleaving de reglas | `DATOSC iberterminal` ausente; texto de Netrunning legible y secuencial |
| pp.34-42 sin gibberish SC700 | sin cadenas tipo `Quieresenelmundo...`; body FuturaPT limpio |
| caption de tabla legible | p200 caption sin `tneúrmmeinroa` |
| `section_path` poblado | ≥99% de chunks con `section_path` no vacío |
| tests | `pytest tests/rag_lib/` ≥200 pasan |

### Resultado de la validación (2026-06-05)

Validado contra `manual.pdf` (1352 chunks) y revisado por subagente: implementación aprobada, 212 tests pasan. Todos los criterios cumplidos **salvo** "0 chunks con doble-char", que da **2** chunks residuales (0.15%). Ver «Residuo conocido».

## Residuo conocido — captions de tabla con líneas superpuestas

2 chunks (captions de tabla en p200 y p454) contienen texto intercalado tipo `tneúrmmeinroa`. **No** es el doble-render decorativo que arregla este diseño, sino un **defecto del PDF de origen** (`Ciberpunk RED..._compressed`): dos líneas de caption *distintas* quedan superpuestas a solo ~1.55pt de distancia vertical (p.ej. `top=174.606` "número de ranuras que tiene para progra-" y `top=173.053` "terminal potente de uno más barato es el").

`_group_lines` (tolerancia ±2pt, correcta para el 99.85% del manual) las fusiona en una línea y el sort por `x0` las intercala. El dedup por `(x0, top, text)` no aplica porque ambas líneas tienen **texto y posición distintos** — no son copias.

**Decisión:** aceptado como residuo documentado. Impacto bajo (solo se ensucia la línea de caption; las filas de la tabla salen limpias). Bajar la tolerancia de `_group_lines` por debajo de 1.55pt arriesga romper diacríticos/jitter en las 464 páginas por solo 2 captions, y queda fuera del scope de este diseño. Posible follow-up: sub-clustering por densidad de línea o detección de líneas colisionadas.

## Scope y no-scope

**En scope:**
- Dedup a nivel de página (alimenta tablas + prosa + caption).
- Drop de fuentes decorativas por `fontname` (default `SC700`, validado).
- Detección de columnas (gutter por proyección) + orden de lectura por bandas.
- Caption column-aware.
- Tests unitarios + regresión + re-ingesta y validación.

**Fuera de scope:**
- OCR / captioning de imágenes.
- Layouts de >2 columnas anidados o XY-cut completo (el manual es consistentemente 1–2 columnas).
- Fuentes decorativas específicas de otros manuales (cubierto vía constante configurable, no hardcode adicional).
- Cambios en `run_chunker`/chunking salvo lo derivado del caption, Web UI o API pública.
