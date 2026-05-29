# Diseño: Cronología con contexto de sesión anterior

## Problema

Cuando el Director (DM) repasa verbalmente la sesión anterior al inicio de una partida, esas transcripciones entran en `generate_chronology()` como eventos nuevos. El LLM los incluye en la nueva cronología como si ocurrieran ahora, causando duplicación de eventos entre sesiones consecutivas.

## Solución

Al solicitar la cronología de una sesión, inyectar la `session_chronology` de la sesión anterior como contexto en el system prompt. El LLM puede así:

1. Omitir eventos que ya aparecen en la sesión anterior
2. Detectar correcciones del DM y marcarlas al principio como discrepancias

## Flujo

```
generate_chronology(entries) es llamado
  → self._database disponible y campaign no genérica?
    → sí: db.sessions.get_previous_session_chronology(campaign_id, current_session_id)
    → no: previous_chronology = ""
  → _build_chronology_system_prompt(previous_session_chronology)
  → LLM genera cronología solo con eventos nuevos
```

## Cambios

### `src/rpg_scribe/core/database/repositories/session_repo.py`

Nuevo método:

```python
async def get_previous_session_chronology(
    self, campaign_id: str, current_session_id: str
) -> str:
```

Busca la sesión completada más reciente de la campaña (filtro: `status = 'completed'`,
`merged_into IS NULL`, `ended_at IS NOT NULL`, ordenado por `ended_at DESC`) excluyendo
`current_session_id`. Devuelve `session_chronology` o `""` si no existe o está vacía.

### `src/rpg_scribe/summarizers/prompts.py`

`CHRONOLOGY_SYSTEM_PROMPT` recibe un bloque opcional `{previous_session_block}`:

- Cuando no está vacío: sección `CRONOLOGÍA DE LA SESIÓN ANTERIOR:` con el texto completo
- Instrucciones añadidas al prompt:
  - "Si la transcripción incluye un repaso verbal de la sesión anterior, NO repitas esos eventos en la nueva cronología."
  - "Si el Master corrige o contradice algo respecto a la cronología anterior, incluye al principio del texto una sección `## Discrepancias con la sesión anterior` con cada corrección detectada."
- Cuando está vacío: el bloque se omite y el comportamiento no cambia

### `src/rpg_scribe/summarizers/claude_summarizer.py`

**`_build_chronology_system_prompt(previous_session_chronology: str = "")`**

Acepta el nuevo parámetro. Cuando no es vacío, renderiza la sección
`CRONOLOGÍA DE LA SESIÓN ANTERIOR:` en el prompt.

**`generate_chronology(entries, *, include_previous: bool = True)`**

Cuando `include_previous=True` y `self._database` no es `None` y la campaña no es
genérica: llama a `db.sessions.get_previous_session_chronology(campaign_id, session_id)`.
Pasa el resultado a `_build_chronology_system_prompt`.

**`generate_chronology_from_transcriptions()`**

Llama a `generate_chronology(..., include_previous=False)`. Este método es post-hoc
(regeneración histórica), el contexto de sesión anterior no aplica.

## Formato de discrepancias

El LLM decide si hay discrepancias. Si las detecta, abre la cronología con:

```
## Discrepancias con la sesión anterior
- [descripción de la corrección]
...

[resto de la cronología de la nueva sesión]
```

No se parsea por código — es texto libre al principio del campo `session_chronology`.
La Web UI ya renderiza markdown, por lo que se muestra correctamente sin cambios adicionales.

## Edge cases

| Situación | Comportamiento |
|---|---|
| Sin sesión anterior | `previous_chronology = ""`, sin cambios en el prompt |
| Sesión anterior sin cronología (sesión antigua) | Igual que arriba |
| Campaña genérica (`is_generic=True`) | Sin consulta a DB |
| Post-hoc (`generate_chronology_from_transcriptions`) | `include_previous=False` |
| DM no hace recap | El LLM ignora el bloque de sesión anterior sin efecto |

## Fuera de alcance

- Resumen incremental de sesión (`SESSION_UPDATE_USER`): no se modifica
- Actualización del resumen de sesión anterior en DB a partir de discrepancias: no se implementa
