# Web UI Features

## Campaign Details

- Panel colapsable con tabs internas (Players, NPCs, Locations, Entities, Relationships)
- Documentación detallada de entidades, locations y relationships en [`web-ui-entities.md`](web-ui-entities.md)

## Campaign Bar

- Muestra/edita nombre, sistema, descripción, instrucciones (PATCH `/api/campaigns/{id}`)

## Players

- Tab con edición inline (PUT `/api/campaigns/{id}/players/{pid}`)

## NPCs

- Tab con edición inline + crear + merge (POST/PUT `/api/campaigns/{id}/npcs`)

## Locations

- Tab con edición inline + crear + merge (POST/PUT `/api/campaigns/{id}/locations`)

## Entities

- Tab con edición inline + crear + merge (POST/PUT `/api/campaigns/{id}/entities`)

## Relationships

- Tab con grafo de relaciones entre personajes (POST `/api/campaigns/{id}/relationships`)

## Sessions

- **Session sidebar**: lista sesiones con duración, indicador de resumen, preview
- **Session history**: click en sesión histórica carga transcripciones + resumen desde DB
- **Live mode**: WebSocket para transcripciones y resúmenes en tiempo real
- **Browse mode**: navegar y editar sesiones de cualquier campaña sin estar en sesión activa
- **Merge sessions**: seleccionar 2 sesiones completadas y fusionarlas en una (transcripciones + resúmenes concatenados); patrón tombstone con `merged_into`

## Questions

- Panel de preguntas pendientes del summarizer con respuesta inline

## Campaign Summaries

- Resumen acumulado de campaña; botón "Generate" para generar bajo demanda (también genera resúmenes de sesión faltantes)
- "View all" abre `campaign-summaries.html` con historial completo
