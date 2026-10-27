# RAG Ingestion Quality — Design Spec

**Date:** 2026-05-29
**Status:** Approved

## Problema

La ingesta del manual `Ciberpunk RED - Libro básico_compressed` produce chunks con tres tipos de ruido:

1. **Caracteres duplicados** (`ppaassaarr...`): el PDF renderiza texto decorativo (sidebars de flavor text) con fuentes `IndustryInc-Base-SC700` y `BisectModificadaRegular-SC700` **dos veces en las mismas coordenadas exactas**. pdfplumber extrae ambas capas y `_extract_prose_groups` las concatena.  
   - 46 páginas afectadas de 464 (~10%), hasta 22% de chars duplicados por página.
   - El filtro por fontsize del paso 2.5 no ayuda: ambas capas tienen el mismo fontsize exacto.

2. **Páginas de índice ingestadas como body text**: las páginas 6–7 (tabla de contenidos) producen chunks con texto tipo `Sala de trauma ....................................................6`. Son ruido puro para RAG.

3. **`should_merge_across_pages` con docstring obsoleto**: la función ya está implementada pero el docstring dice "placeholder / TODO". También le faltan terminadores de cierre (`)`, `»`, `]`) comunes en manuales de rol.

## Objetivo

Tres fixes quirúrgicos sin abstracciones nuevas. Tras aplicarlos, re-ingestar el manual produce chunks limpios.

## Cambios por archivo

### 1. `src/rag_lib/parsing/pdfplumber_parser.py`

#### `_extract_prose_groups` — Step 1.5: dedup por posición

Tras el Step 1 (filtrar chars fuera de tables) y antes del Step 2 (agrupar en líneas), insertar:

```python
# Step 1.5: dedup chars at same position (PDF decorative double-render)
seen_pos: set[tuple] = set()
deduped: list[dict] = []
for c in chars:
    pos = (round(float(c["x0"]), 1), round(float(c["top"]), 1))
    if pos not in seen_pos:
        seen_pos.add(pos)
        deduped.append(c)
chars = deduped
```

El análisis del PDF confirma que los duplicados están en posiciones exactamente iguales (mismo `x0`, `top`, fuente y tamaño). El round a 1 decimal cubre sub-pixel drift sin riesgo de colapsar chars adyacentes (spacing mínimo entre chars en FuturaPT-Book: ~3pt).

### 2. `src/rag_lib/chunking.py`

#### Helper `_is_toc_noise`

Nuevo helper al nivel de módulo:

```python
def _is_toc_noise(text: str) -> bool:
    if len(text) < 20:
        return False
    return text.count(".") / len(text) > 0.30
```

Threshold 30% conservador: chunks de TOC reales tienen ratios 40–60%; body text raramente supera 3%.

#### Main loop — skip TOC blocks

En el procesado de `ProseBlock` dentro de `run_chunker`, añadir antes de `_add_prose` (y antes de las comprobaciones de `is_large_font`):

```python
elif isinstance(block, ProseBlock):
    if _is_toc_noise(block.text):
        continue
    # ... código existente
```

#### `should_merge_across_pages` — terminadores y docstring

Ampliar `TERMINATORS`:

```python
TERMINATORS = {'.', '!', '?', '…', ':', ')', ']', '»'}
```

Reemplazar el docstring por uno que describa el comportamiento real (sin "placeholder" ni "TODO").

## Testing

| Test | Archivo |
|---|---|
| `_extract_prose_groups` con chars duplicados en misma posición → output sin duplicados | `tests/rag_lib/test_parser.py` |
| `_extract_prose_groups` con chars en posiciones distintas → todos conservados | `tests/rag_lib/test_parser.py` |
| `_is_toc_noise("")` → False (texto corto) | `tests/rag_lib/test_chunker.py` |
| `_is_toc_noise("Sala de trauma ....................6")` → True | `tests/rag_lib/test_chunker.py` |
| `_is_toc_noise("El netrunner atacó al guardia.")` → False | `tests/rag_lib/test_chunker.py` |
| `run_chunker` no genera chunks de TOC noise | `tests/rag_lib/test_chunker.py` |
| `should_merge_across_pages` con last_char=`)` → False | `tests/rag_lib/test_chunker.py` |
| `should_merge_across_pages` con last_char=`»` → False | `tests/rag_lib/test_chunker.py` |

Los tests de parser con chars duplicados se construyen creando dicts de char sintéticos (no se necesita un PDF real).

## Re-ingesta

Tras aplicar los cambios, borrar el manual de la DB y re-ingestar:

```sql
DELETE FROM rag_manuals WHERE id = 6;
-- rag_chunks y rag_embeddings se borran en cascada (FK con ON DELETE CASCADE)
```

Después correr el CLI de ingesta con `manual.pdf`.

## Scope y no-scope

**En scope:**
- Dedup de chars por posición en `_extract_prose_groups`
- Filtro de TOC-noise en `run_chunker`
- Fix de terminadores y docstring en `should_merge_across_pages`
- Tests unitarios para los tres cambios

**Fuera de scope:**
- Limpieza de la DB existente sin re-ingestar (no necesario si se re-ingesta)
- Otros manuales (el fix es genérico, beneficia cualquier PDF futuro)
- Cambios en la Web UI o en la API pública
