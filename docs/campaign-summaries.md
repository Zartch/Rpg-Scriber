# Campaign Summaries

## Modelo de datos

- Tabla `campaign_summaries`: historial append-only de resúmenes de campaña (no se sobreescriben)
- `campaigns.campaign_summary`: columna cache con el último resumen, usada por el prompt del summarizer

## Generación

- Se generan automáticamente al finalizar cada sesión (si la sesión tiene resumen)
- Se pueden generar bajo demanda desde el Web UI (botón "Generate")
- El endpoint `POST /generate` genera primero resúmenes de sesión faltantes (post-hoc desde transcripciones), luego el resumen de campaña

## Visualización

- La página `campaign-summaries.html` muestra el historial completo con navegación lateral

## Sync TOML → DB

- Al arrancar con `--campaign`, los players, NPCs y locations del TOML se persisten idempotentemente a la DB
- Si ya existen (por discord_id / name), no se duplican
- Cambios hechos via Web UI se guardan en DB y en memoria (no modifican el TOML)
