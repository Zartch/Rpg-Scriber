# Discord Voice & DAVE E2EE

## DAVE E2EE

- discord.py 2.7+ incluye DAVE (Discord Audio-Visual Experience) E2EE para voz
- `discord-ext-voice-recv` NO soporta descifrado DAVE → audio es ruido, no silencio
- **Fix**: monkey-patch `_patch_disable_dave()` en `discord_listener.py` que fuerza `max_dave_protocol_version = 0`
- También hay `_patch_packet_router()` que hace PacketRouter resiliente a OpusError por paquete

## Particularidades Windows

- asyncio ProactorEventLoop requiere `os._exit(0)` para SIGINT handler
- uvicorn signal handlers deben ser `lambda: None` (no `False`)
- Python 3.10: no tiene `tomllib` → se usa `tomli` como fallback
