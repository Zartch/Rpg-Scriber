# Diseño: `RulesBot` — consulta de reglas con RAG

Fecha: 2026-05-29
Estado: aprobado (pendiente de plan de implementación)

## Objetivo

Un bot activado por voz que, ante una pregunta de reglas, busca en los manuales
configurados (RAG), sigue referencias de página dentro del manual, redacta la
respuesta con Claude **citando siempre la fuente**, la **habla** por el canal de
voz (vía la infraestructura TTS existente) y además la **escribe** en un canal de
texto de Discord.

## Contexto del código existente

- **Framework de bots** (`src/rpg_scribe/bots/`): `BaseBot` (ABC con `keyword`,
  `voice`, `close_word`, `timeout_s`), `discover_bots()` (instancia cada subclase
  con `cls()` sin argumentos), `EchoBot` (referencia trivial), y `TriggerWatcher`
  (`watcher.py`) que detecta la keyword en `TranscriptionEvent`, captura el comando
  multi-chunk, llama a `bot.handle()` y reproduce la respuesta por TTS mediante
  `DiscordTTSPlayer`.
- **RAG** (`src/rag_lib/`): módulo standalone. API pública async en
  `rag_lib/__init__.py`: `search()` (semántica), `search_fts()` (FTS5),
  `list_chunks()`, `get_chunk()`, `list_manuals()`. Los `Chunk` exponen
  `manual_id`, `page`, `page_end`, `section_path`, `text`. **No existe** función
  para obtener chunks por número de página.
- **Config** (`src/rpg_scribe/config.py`): `AppConfig` centraliza secretos
  (`openai_api_key`, `anthropic_api_key`) cargados una vez desde env, y
  `rag_db_path = "data/rag.db"`. La config por campaña vive en el TOML de campaña
  → `CampaignContext`.
- **Publicación en Discord** (`src/rpg_scribe/discord_bot/publisher.py`):
  `DiscordSummaryPublisher` se suscribe a `SummaryUpdateEvent` y postea/edita un
  embed en un canal de texto. Patrón a replicar.

### Estrategia anti-duplicación de configuración

- **Secretos**: el bot nunca lee env ni keys. El framework construye las
  dependencias (búsqueda RAG, cliente Claude) reusando `AppConfig` y se las
  **inyecta**. Igual que hoy el `EchoBot` no toca la key de OpenAI: el
  `TriggerWatcher` recibe el `OpenAITTSProvider` ya montado desde `main.py`.
- **Ajustes por campaña** (qué manuales, qué canal de texto): sección nueva
  `[campaign.rag]` en el TOML de campaña, junto al resto de config de la partida.
- **Defaults del bot** (keyword, voz): atributos de clase, como `EchoBot`.

## Flujo general

```
Voz: "bot reglas, ¿cómo funciona el hackeo?"
  → TriggerWatcher (ya existe) captura la pregunta tras la keyword
  → RulesBot.handle():
        1. Búsqueda híbrida (semántica + FTS5) en los manuales configurados
        2. Follow de página (1 salto): si un chunk referencia "ver pág. 45"
           → trae los chunks de esa página del mismo manual
        3. Claude redacta la respuesta citando manual + página
        4. devuelve BotResponse(spoken, written, citations)
  → TriggerWatcher habla `spoken` por TTS (ya existe)
  → publica BotTextResponseEvent
  → DiscordBotResponsePublisher postea un embed con la cita en rules_channel_id
```

## Componentes

### 1. Inyección de dependencias en los bots *(cambio al framework)*

- `BaseBot` gana un hook opcional:
  ```python
  async def setup(self, services: BotServices) -> None:
      """Inyección de dependencias. Default: no-op."""
  ```
  Default no-op → `EchoBot` y cualquier bot existente quedan intactos.
- `BotServices` (dataclass, nuevo): transporta lo que el framework inyecta una
  sola vez:
  - `rag_db_path: str`
  - `anthropic_api_key: str`
  - `summarizer_model: str` (modelo de Claude a reutilizar)
  - `campaign: CampaignContext | None`
  - `event_bus: EventBus`
  - `rag: RagCampaignConfig | None` (la sub-config `[campaign.rag]` ya resuelta)
- `main.py` construye `BotServices` reusando `AppConfig` y, tras
  `discover_bots()`, llama `await bot.setup(services)` para cada bot **antes** de
  arrancar el `TriggerWatcher`. La key de Anthropic sigue viviendo solo en
  `AppConfig`/env.

### 2. Retorno estructurado de `handle()`

- Nuevo dataclass `BotResponse`:
  ```python
  @dataclass(frozen=True)
  class BotResponse:
      spoken: str
      written: str | None = None      # markdown para el canal de texto
      citations: list[Citation] | None = None
  ```
- `BaseBot.handle()` pasa a devolver `str | BotResponse`.
- `TriggerWatcher` normaliza: si recibe `str` → `BotResponse(spoken=str)`.
  Retro-compatible con `EchoBot`.
- Tras hablar `spoken`, si `written` no es `None`, el watcher publica un
  `BotTextResponseEvent` en el event bus.

### 3. Recuperación — `RuleRetriever` (`integrations/rag_retrieval.py`)

Pieza pura, sin dependencias de Discord, testeable de forma aislada.

- **Búsqueda híbrida**: lanza `rag_lib.search()` y `rag_lib.search_fts()` en
  paralelo con `manual_ids`; fusiona resultados por `chunk_id` combinando los
  scores normalizados; devuelve top-k. (Mismo espíritu que la Web UI híbrida.)
- **Follow de página (1 salto)**: aplica regex
  `(?:pág(?:ina)?\.?|p\.)\s*(\d+)` (case-insensitive) sobre el texto de los
  chunks top. Para cada `(manual_id, page)` referida, llama a la nueva
  `rag_lib.list_chunks_by_page(manual_id, page, db_path)` y añade esos chunks al
  contexto, deduplicando por `chunk_id`. Solo un nivel de profundidad.

### 4. Función nueva en `rag_lib` — `list_chunks_by_page`

- API pública en `rag_lib/__init__.py`:
  ```python
  async def list_chunks_by_page(
      manual_id: int, page: int, db_path: str | Path
  ) -> list[Chunk]: ...
  ```
- Implementada con un método nuevo en `ChunkRepo` (en `store.py`): selecciona
  chunks donde `page <= ? AND COALESCE(page_end, page) >= ?`, ordenados por `seq`.
- Tests unitarios propios en `tests/rag_lib/`.

### 5. Redacción — `RuleAnswerer` (`bots/rules/answerer.py`)

- Construye el prompt para Claude con la pregunta + los chunks recuperados, cada
  uno anotado con su metadata (`manual`, `page`, `section_path`).
- Instrucciones del sistema: responder **solo** con lo que aparece en los
  manuales; si la información no está, decirlo explícitamente; mantener el idioma
  de la campaña; citar manual y página inline.
- **Citas deterministas**: además de la cita inline del LLM, se construye un
  bloque "Fuentes" a partir de los chunks realmente usados (manual + página +
  section_path). No dependemos del LLM para la exactitud de las páginas.
- Salidas:
  - `spoken`: respuesta hablada con cita corta ("según *Cyberpunk RED*, página 45…").
  - `written`: respuesta completa + bloque **Fuentes** en markdown.

### 6. `RulesBot` (`bots/rules/bot.py`)

- `keyword = "bot reglas"` (el matcher de `TriggerWatcher` usa
  `\b{keyword}\b`, que detecta la frase completa).
- `setup()`: lee `[campaign.rag]`; resuelve los nombres de manual a `manual_id`
  vía `rag_lib.list_manuals()`; construye `RuleRetriever` y `RuleAnswerer`. Si no
  hay manuales o falta `rag.db`, se auto-desactiva (log) y `handle()` devuelve un
  aviso.
- `handle()`: orquesta retriever → answerer → `BotResponse`.

### 7. Salida a canal de texto *(pieza nueva)*

- Evento `BotTextResponseEvent` (`frozen`) en `core/events.py`:
  `session_id`, `bot_keyword`, `speaker_name`, `question`, `answer_md`,
  `citations`.
- `DiscordBotResponsePublisher` (`discord_bot/`): se suscribe al evento y postea
  un embed en `rules_channel_id`. Sin canal configurado → no postea (log). Reusa
  el patrón y la lógica `_truncate` de `DiscordSummaryPublisher`.
- Cableado en `main.py` análogo a `DiscordSummaryPublisher`.

### 8. Configuración — `[campaign.rag]`

```toml
[campaign.rag]
manuals = ["Cyberpunk RED — Core"]   # por nombre (resuelto a ids en setup)
rules_channel_id = "123456789012345678"
keyword = "bot reglas"   # opcional; default del bot
top_k = 8                # opcional
```

- `config.py` parsea esto en un `RagCampaignConfig` (dataclass nuevo) colgado de
  `CampaignContext`. Si la sección no existe, queda `None`.

## Casos límite y errores

- Sin manuales / sin resultados de búsqueda → respuesta "No encontré esa regla en
  los manuales."
- `rag.db` ausente o `[campaign.rag]` vacío → el bot se auto-desactiva en
  `setup()` (log); no responde a la keyword.
- Fallo de Claude → degradación: devuelve el chunk top en bruto + cita
  determinista.
- Página referida inexistente → se ignora (no rompe el follow).
- Límites de embed de Discord → truncado (lógica ya existente).

## Testing

- `rag_lib.list_chunks_by_page`: unit (rangos `page`/`page_end`).
- `RuleRetriever`: con `fake_embedder` (fixture ya existe en
  `tests/rag_lib/conftest.py`) + DB en memoria — fusión híbrida y follow de
  página.
- `RuleAnswerer`: construcción de prompt + bloque de citas deterministas (mock
  Anthropic).
- Normalización `str → BotResponse` en `TriggerWatcher` (EchoBot sigue
  funcionando).
- `DiscordBotResponsePublisher`: canal de Discord mockeado.

## Fases (para el plan de implementación)

- **Fase 1** — `rag_lib.list_chunks_by_page` + tests. (Independiente.)
- **Fase 2** (paralelizable con Fase 1) — Framework: `BotServices`, `setup()`,
  `BotResponse`, normalización en `TriggerWatcher`, cableado en `main.py`. Verificar
  que `EchoBot` sigue funcionando.
- **Fase 3** (requiere Fase 1) — `RuleRetriever` (híbrido + follow) + tests.
- **Fase 4** (requiere Fase 2) — `BotTextResponseEvent` +
  `DiscordBotResponsePublisher` + cableado + tests.
- **Fase 5** (requiere Fases 2 y 3) — `RuleAnswerer` + tests.
- **Fase 6** (requiere Fases 3, 4, 5) — `RulesBot` + `[campaign.rag]` en
  `config.py` + integración extremo a extremo.

## Fuera de alcance (futuro)

- Trigger por comando de texto (escribir "bot reglas …" en un canal).
- Follow de página recursivo / multi-salto.
- Configuración de manuales/canal desde la Web UI.
- Atributos `include_in_feed` / `include_in_summarizer` para las respuestas del bot.
