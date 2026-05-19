# REST API Endpoints

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/api/status` | Estado de componentes y sesión activa |
| GET | `/api/campaigns` | Info campaña activa + players + NPCs |
| PATCH | `/api/campaigns/{id}` | Editar campaña |
| PUT | `/api/campaigns/{id}/players/{pid}` | Editar jugador |
| POST | `/api/campaigns/{id}/npcs` | Crear NPC |
| PUT | `/api/campaigns/{id}/npcs/{nid}` | Editar NPC |
| POST | `/api/campaigns/{id}/locations` | Crear localización |
| PUT | `/api/campaigns/{id}/locations/{lid}` | Editar localización |
| POST | `/api/campaigns/{id}/relationships` | Crear relación entre personajes |
| POST | `/api/campaigns/{id}/campaign-summaries/generate` | Generar resumen de campaña bajo demanda (también genera resúmenes de sesión faltantes) |
| GET | `/api/campaigns/{id}/campaign-summaries` | Listar todos los resúmenes de campaña (más reciente primero) |
| GET | `/api/campaigns/{id}/campaign-summaries/latest` | Resumen de campaña más reciente |
| GET | `/api/campaigns/{id}/campaign-summaries/{sid}` | Resumen de campaña por ID |
| GET | `/api/sessions` | Listar todas las sesiones |
| GET | `/api/campaigns/{id}/sessions` | Sesiones de una campaña |
| GET | `/api/sessions/{id}/transcriptions` | Transcripciones (memoria o DB) |
| GET | `/api/sessions/{id}/summary` | Resumen (memoria o DB) |
| POST | `/api/sessions/merge` | Fusionar dos sesiones (source_id + target_id) |
| GET | `/api/questions` | Preguntas pendientes |
| POST | `/api/questions/{id}/answer` | Responder pregunta |
| GET | `/api/browse/campaigns` | Listar todas las campañas (modo browse) |
| GET | `/api/browse/campaigns/{id}` | Detalle de campaña (modo browse) |
| GET | `/api/browse/sessions/uncategorized` | Sesiones sin campaña |
| POST | `/api/tts/narrate` | Generar audio TTS (NDJSON streaming). Cachea como WAV 48 kHz stereo |
| POST | `/api/tts/narrate-discord` | Generar + emitir narración por el canal de voz del bot (NDJSON) |
| POST | `/api/tts/discord/pause` | Pausar reproducción en Discord |
| POST | `/api/tts/discord/resume` | Reanudar reproducción en Discord |
| POST | `/api/tts/discord/stop` | Detener y limpiar la cola en Discord |
| POST | `/api/tts/discord/play-at` | Saltar a un chunk concreto (`{"index": N}`) |
| GET | `/api/tts/discord/status` | Estado actual del player Discord (para polling) |
| GET | `/api/tts/voices` | Voces TTS disponibles para el provider activo |
| GET | `/api/tts/cache/{hash}.wav` | WAV cacheado (servido como estático) |
| WS | `/ws/live` | WebSocket para eventos en tiempo real |

Detalles del flujo TTS (caché compartida entre navegador y Discord, controles de transporte, drivers frontend) en [`tts-narration.md`](tts-narration.md).
