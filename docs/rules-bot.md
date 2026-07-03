# Bot de Reglas (RAG)

Bot activado por voz que responde preguntas de reglas consultando los manuales
ingeridos en `rag_lib`, citando siempre la fuente. Habla la respuesta por el
canal de voz (TTS) y la escribe como embed en un canal de texto.

## Flujo

```
Voz: "bot reglas, ¿cómo funciona el hackeo?"
  → TriggerWatcher capta la pregunta tras la keyword (multi-chunk)
  → RulesBot.handle():
        1. RuleRetriever: búsqueda híbrida (semántica + FTS5) en los manuales
           configurados + follow de página (1 salto: "ver pág. N")
        2. RuleAnswerer: Claude redacta citando manual + página; citas
           deterministas construidas a partir de los chunks usados
        3. devuelve BotResponse(spoken, written, citations)
  → TriggerWatcher habla `spoken` por TTS
  → publica BotTextResponseEvent (con el canal de voz adjunto)
  → DiscordBotResponsePublisher postea el embed con la cita
```

## Framework de bots (base)

Los bots activados por voz viven en `src/rpg_scribe/bots/` y los descubre
`discover_bots()` al arrancar (cualquier submódulo del paquete se auto-importa;
los subpaquetes deben re-exportar su clase en `__init__.py`).

- `BaseBot` (ABC): declara `keyword` (única, lowercase) y opcionalmente `name`,
  `voice`, `close_word`, `timeout_s`.
- `setup(services: BotServices)`: hook opcional de **inyección de dependencias**
  (default no-op). El framework lo llama una vez tras el discovery y antes de
  arrancar el `TriggerWatcher`. Aquí el bot recibe rutas/secretos/config sin
  leer env directamente.
- `handle(command, *, session_id, speaker_id, speaker_name) -> str | BotResponse`:
  procesa el comando. Devolver `str` equivale a `BotResponse(spoken=str)`.
- `BotResponse(spoken, written=None, citations=None)`: lo que se habla
  (`spoken`) y lo que se escribe en texto (`written`, markdown).
- `TriggerWatcher`: detecta la keyword en `TranscriptionEvent`, captura el
  comando, llama a `handle`, sintetiza `spoken` por TTS y, si hay `written`,
  publica `BotTextResponseEvent`.

`EchoBot` es la referencia mínima (devuelve un `str`).

## Configuración

La config se reparte en tres fuentes (estrategia anti-duplicación):

| Qué | Dónde | Cómo llega al bot |
|---|---|---|
| `anthropic_api_key` | env `ANTHROPIC_API_KEY` → `AppConfig` | `BotServices.anthropic_api_key` |
| `rag_db_path` | `AppConfig.rag_db_path` (default `data/rag.db`) | `BotServices.rag_db_path` |
| modelo de Claude | `summarizer.model` (reutilizado) | `BotServices.summarizer_model` |
| manuales, canal, keyword, top_k | `[campaign.rag]` del TOML de campaña | `BotServices.rag` (`RagCampaignConfig`) |
| keyword por defecto | atributo de clase `RulesBot.keyword` | overridable por `[campaign.rag].keyword` |

El bot **nunca lee env**: el framework construye `BotServices` reusando
`AppConfig` y se lo inyecta en `setup()`.

### Sección `[campaign.rag]`

```toml
[campaign.rag]
manuals = ["Cyberpunk RED — Core"]   # por nombre; se resuelven a ids en setup()
rules_channel_id = "123456789012345678"  # opcional (ver "Canal de respuesta")
keyword = "bot reglas"               # opcional; default del bot
top_k = 8                            # opcional
debug = false                        # opcional; logs de diagnóstico (ver abajo)
```

Si la sección no existe o no resuelve ningún manual de `rag.db`, el bot se
**auto-desactiva** en `setup()` (log) y no responde a la keyword.

La keyword es **case-insensitive**: "bot reglas", "Bot Reglas" o "BOT REGLAS"
disparan igual (el `TriggerWatcher` normaliza a minúsculas y casa con
`re.IGNORECASE`).

## Logging y depuración

- **Disparo (siempre):** cada vez que se activa, `RulesBot` registra a nivel
  INFO `RulesBot disparado por <hablante>: '<pregunta>'`. Útil para confirmar
  que la keyword se detectó.
- **Diagnóstico (`debug = true`):** activa logs adicionales a INFO:
  - `RuleRetriever[debug]`: la pregunta, cada chunk recuperado
    (`chunk_id`, `manual_id`, `página`, `score`) y las páginas seguidas en el
    follow.
  - `RulesBot[debug]`: la respuesta redactada (recortada) y las fuentes citadas
    (manual + página).

  Se controla por campaña en `[campaign.rag].debug`; por defecto está apagado
  para no ensuciar la salida.

## Canal de la respuesta escrita

La respuesta hablada va al canal de **voz** (TTS). La respuesta escrita (embed
con la cita) se publica por **orden de preferencia**:

1. `[campaign.rag].rules_channel_id` si está configurado (canal dedicado).
2. En su defecto, el **chat integrado del canal de voz** donde se invocó al bot
   (un `VoiceChannel` es *messageable* en discord.py 2.x). El `TriggerWatcher`
   resuelve ese id desde el cliente de voz y lo adjunta a `BotTextResponseEvent`.
3. Si ninguno está disponible, no se escribe (solo queda la respuesta hablada).

Es un canal **independiente** del de resúmenes (`DISCORD_SUMMARY_CHANNEL_ID`).

## Componentes

| Pieza | Archivo | Responsabilidad |
|---|---|---|
| `RuleRetriever` | `bots/rules/retriever.py` | Búsqueda híbrida + follow de página (puro, sin Discord) |
| `RuleAnswerer` | `bots/rules/answerer.py` | Prompt a Claude + citas deterministas + fallback |
| `RulesBot` | `bots/rules/bot.py` | Orquesta retriever → answerer; auto-desactivación |
| `BotTextResponseEvent` | `core/events.py` | Transporta la respuesta escrita + canal de voz |
| `DiscordBotResponsePublisher` | `discord_bot/bot_response_publisher.py` | Embed con la cita en el canal destino |
| `rag_lib.list_chunks_by_page` | `rag_lib/__init__.py` | Trae los chunks que cubren una página (follow) |

## Degradación y casos límite

- Sin manuales / sin resultados → "No encontré esa regla en los manuales."
- `rag.db` ausente o `[campaign.rag]` vacío → bot auto-desactivado en `setup()`.
- Fallo de Claude → fallback: chunk top en bruto + cita determinista.
- Página referida inexistente → se ignora (no rompe el follow).
- Límites de embed de Discord → truncado.

## Fuera de alcance (futuro)

- Trigger por comando de texto.
- Follow de página recursivo / multi-salto.
- Configuración de manuales/canal desde la Web UI.
