# Diseño: Inyección de Cronología en el Resumen Narrativo

**Fecha:** 2026-03-28
**Rama:** refactor_solid

## Problema

El resumen narrativo (`_session_summary`) nunca recibe la cronología (`_session_chronology`) como contexto. Ambos se generan en `finalize_session()`, pero la cronología se genera **después** del narrativo, por lo que el LLM no puede aprovecharse de ella al escribir el resumen final. Tampoco está disponible en regeneraciones manuales on-demand post-sesión.

## Objetivo

Inyectar la cronología en el prompt del resumen narrativo cuando esté disponible, tanto en la finalización de sesión como en actualizaciones on-demand posteriores.

## Alcance

### Cambios en `finalize_session()` — orden invertido

Actualmente:
1. Genera resumen narrativo final
2. Genera cronología

Nuevo orden:
1. Genera cronología desde `all_entries` → `self._session_chronology`
2. Genera resumen narrativo final con cronología como contexto
3. `_publish_summary("final")`
4. `_extract_entities()`

Si la generación de cronología falla, se continúa con `self._session_chronology = ""` (igual que ahora).

### Cambios en prompts — bloque opcional

`FINALIZE_USER` y `SESSION_UPDATE_USER` reciben un nuevo placeholder `{chronology_block}`.

El valor se construye en Python antes de formatear el prompt:
- Si `self._session_chronology` es no-vacío → `"CRONOLOGÍA DE LA SESIÓN:\n{chronology}\n\n"`
- Si está vacío → `""`

Posición en `FINALIZE_USER`: entre `TRANSCRIPCIÓN PENDIENTE` y la instrucción "Genera:".

Posición en `SESSION_UPDATE_USER`: entre `TRANSCRIPCIÓN RECIENTE` y `RESUMEN ACTUAL`.

### Cambios en `_update_summary()`

Al construir `user_msg` con `SESSION_UPDATE_USER`, añadir el `chronology_block` usando `self._session_chronology`. Durante una sesión activa estará vacío; tras una finalización previa (regeneración manual post-sesión) contendrá la cronología.

### Sin cambios en actualizaciones automáticas

No existen actualizaciones incrementales automáticas en el código actual. `_update_summary()` solo se invoca desde `refresh_summary_on_demand()` (UI manual) y `finalize_session()`.

## Archivos afectados

| Archivo | Cambio |
|---------|--------|
| `src/rpg_scribe/summarizers/prompts.py` | Añadir `{chronology_block}` a `FINALIZE_USER` y `SESSION_UPDATE_USER` |
| `src/rpg_scribe/summarizers/claude_summarizer.py` | Invertir orden en `finalize_session()`; inyectar `chronology_block` en `_update_summary()` y `finalize_session()` |

## Tests afectados

Los tests que construyen `SESSION_UPDATE_USER` o `FINALIZE_USER` directamente necesitarán incluir `chronology_block=""` en el formato. Los tests de `finalize_session()` que verifican el orden de llamadas API deberán actualizarse para reflejar el nuevo orden (cronología primero).
