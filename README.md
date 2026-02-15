# RPG Scribe

Herramienta que escucha partidas de rol en tiempo real a través de Discord, transcribe automáticamente quién dice qué, y genera un resumen narrativo vivo de la sesión usando inteligencia artificial.

RPG Scribe distingue entre diálogo in-game (lo que dicen los personajes) y meta-rol (conversaciones de los jugadores sobre reglas, estrategia, etc.), soporta múltiples campañas con diferentes sistemas de juego, y mantiene un resumen acumulado por campaña.

## Características

- **Transcripción en tiempo real** — Captura audio de Discord con separación automática por usuario (sin necesidad de diarización externa)
- **Resumen narrativo con IA** — Claude genera resúmenes incrementales cada ~2 minutos, distinguiendo in-game vs meta-rol
- **Doble resumen** — Resumen de sesión (detallado, en vivo) + resumen de campaña (acumulativo)
- **Dashboard web** — Interfaz FastAPI con WebSocket para ver transcripciones y resúmenes en tiempo real
- **Integración Discord** — Comandos slash (`/scribe start/stop/status`) y publicación de resúmenes como embeds
- **Multi-campaña** — Configuración TOML por campaña con jugadores, personajes, PNJs y sistema de juego
- **Resiliencia** — Retry con backoff exponencial, circuit breaker y reconexión automática

## Arquitectura

```
Listener (Discord/File) → Transcriber (OpenAI/Whisper) → Summarizer (Claude)
         │                          │                           │
         └──────────── Event Bus (async pub/sub) ──────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
                Database        Web UI         Discord Bot
                (SQLite)       (FastAPI)       (Publisher)
```

### Componentes principales

| Componente | Descripción |
|---|---|
| **Listener** | Captura audio de Discord (por usuario via SSRC) con VAD para chunking inteligente |
| **Transcriber** | Envía chunks de audio a OpenAI API (`gpt-4o-transcribe`). Fallback local con `faster-whisper` |
| **Summarizer** | Usa Claude Sonnet para generar resúmenes narrativos incrementales |
| **Event Bus** | Bus de eventos async que desacopla todos los componentes |
| **Web UI** | Dashboard FastAPI con WebSocket para visualización en tiempo real |
| **Discord Bot** | Comandos slash y publicación de resúmenes en canales de texto |
| **Database** | SQLite async para persistencia de campañas, sesiones y transcripciones |

## Requisitos

- Python 3.11 o superior
- Cuenta de Discord con un bot configurado (ver [Configuración del Bot](#configuración-del-bot-de-discord))
- API key de OpenAI (para transcripción)
- API key de Anthropic (para resúmenes con Claude)
- (Opcional) GPU con CUDA para transcripción local con faster-whisper

## Instalación

### 1. Clonar el repositorio

```bash
git clone https://github.com/Zartch/Rpg-Scriber.git
cd Rpg-Scriber
```

### 2. Crear un entorno virtual

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows
```

### 3. Instalar dependencias

```bash
# Instalación estándar (transcripción vía API)
pip install -e .

# Con dependencias de desarrollo (tests, linter)
pip install -e ".[dev]"

# Con transcripción local (faster-whisper, requiere GPU)
pip install -e ".[local]"
```

### 4. Configurar variables de entorno

RPG Scribe necesita 3 API keys para funcionar. Crear un archivo `.env` o exportar las variables:

```bash
export DISCORD_BOT_TOKEN="tu_token_de_discord"
export OPENAI_API_KEY="tu_api_key_de_openai"
export ANTHROPIC_API_KEY="tu_api_key_de_anthropic"

# Opcionales
export RPG_SCRIBE_HOST="127.0.0.1"     # Host del dashboard web
export RPG_SCRIBE_PORT="8000"           # Puerto del dashboard web
export RPG_SCRIBE_DB="rpg_scribe.db"    # Ruta de la base de datos
export DISCORD_SUMMARY_CHANNEL_ID=""    # Canal para publicar resúmenes
```

**Cómo obtener cada key:**

- **`DISCORD_BOT_TOKEN`** — Ir a [Discord Developer Portal](https://discord.com/developers/applications), crear una aplicación, ir a la sección **Bot** y copiar el token. Ver la sección [Configuración del Bot de Discord](#configuración-del-bot-de-discord) para los permisos necesarios.

- **`OPENAI_API_KEY`** — Crear una cuenta en [platform.openai.com](https://platform.openai.com), ir a **API Keys** en el menú lateral y generar una nueva key. Se necesita un método de pago configurado (la transcripción usa `gpt-4o-transcribe`).

- **`ANTHROPIC_API_KEY`** — Crear una cuenta en [console.anthropic.com](https://console.anthropic.com), ir a **API Keys** y generar una nueva key. Se necesita un método de pago configurado (los resúmenes usan Claude Sonnet).

### 5. Configurar una campaña

Copiar y editar el archivo de ejemplo:

```bash
cp config/campaigns/example.toml config/campaigns/mi-campana.toml
```

El archivo TOML define la campaña, jugadores, personajes y PNJs:

```toml
[campaign]
id = "mi-campana-2025"
name = "El Aquelarre de las Sombras"
game_system = "Akelarre"
language = "es"
description = "Castilla, 1342. Un grupo de viajeros investiga sucesos oscuros."

[campaign.dm]
discord_id = "123456789"
discord_name = "Carlos"

[[campaign.players]]
discord_id = "234567890"
discord_name = "Ana"
character_name = "María de Tordesillas"
character_description = "Curandera castellana, 28 años."

[[campaign.npcs]]
name = "Don Alfonso"
description = "Alcalde de Tordesillas. Nervioso y con secretos."
```

## Uso

### Iniciar RPG Scribe

```bash
rpg-scribe --campaign config/campaigns/mi-campana.toml
```

O directamente con Python:

```bash
python -m rpg_scribe --campaign config/campaigns/mi-campana.toml
```

### Opciones de línea de comandos

```
rpg-scribe [opciones]

  --campaign, -c PATH    Ruta al archivo TOML de campaña
  --host HOST            Host del Web UI (default: 127.0.0.1)
  --port PORT            Puerto del Web UI (default: 8000)
  --log-level LEVEL      Nivel de log: DEBUG, INFO, WARNING, ERROR (default: INFO)
  --json-logs            Activar salida de logs en formato JSON
```

### Comandos de Discord

Una vez que el bot está conectado, usar estos comandos slash en Discord:

| Comando | Descripción |
|---|---|
| `/scribe start` | Inicia la grabación en el canal de voz actual |
| `/scribe stop` | Detiene la grabación y finaliza la sesión |
| `/scribe status` | Muestra el estado actual de la grabación |

### Dashboard Web

Al iniciar RPG Scribe, el dashboard web estará disponible en `http://127.0.0.1:8000` (por defecto). Muestra:

- Estado de los componentes del sistema
- Transcripciones en vivo
- Resumen de sesión actualizado incrementalmente
- Resumen acumulado de campaña

## Configuración del Bot de Discord

1. Ir a [Discord Developer Portal](https://discord.com/developers/applications)
2. Crear una nueva aplicación
3. En la sección **Bot**, crear un bot y copiar el token
4. Habilitar los siguientes **Privileged Gateway Intents**:
   - Message Content Intent
   - Server Members Intent (opcional)
5. En **OAuth2 > URL Generator**, seleccionar los scopes:
   - `bot`
   - `applications.commands`
6. Seleccionar los permisos del bot:
   - Connect (conectarse a canales de voz)
   - Speak (necesario para la conexión de voz)
   - Send Messages (para publicar resúmenes)
   - Embed Links (para los embeds de resumen)
7. Usar la URL generada para invitar el bot a tu servidor

El script auxiliar `scripts/setup_discord_bot.py` puede ayudar con la configuración inicial.

## Desarrollo

### Ejecutar tests

```bash
pytest
pytest -v              # Verbose
pytest -k test_nombre  # Test específico
```

### Linter y formato

```bash
ruff check src/ tests/        # Verificar estilo
ruff format src/ tests/       # Formatear código
```

### Estructura del código

```
src/rpg_scribe/
├── main.py                # CLI y orquestador (Application)
├── config.py              # Carga de configuración
├── logging_config.py      # Logging estructurado
├── core/                  # Event bus, eventos, modelos, DB, resiliencia
├── listeners/             # Captura de audio (Discord, archivos)
├── transcribers/          # Speech-to-text (OpenAI API, faster-whisper)
├── summarizers/           # Resumen narrativo (Claude API)
├── discord_bot/           # Bot, comandos slash, publisher
└── web/                   # FastAPI, WebSocket, frontend estático
```

## Stack Tecnológico

| Capa | Tecnología |
|---|---|
| Lenguaje | Python 3.11+ |
| Bot Discord | discord.py + discord-ext-voice-recv |
| Detección de voz | webrtcvad |
| Transcripción (API) | OpenAI API (gpt-4o-transcribe) |
| Transcripción (local) | faster-whisper |
| Resumen | Anthropic API (Claude Sonnet) |
| Web | FastAPI + WebSocket + uvicorn |
| Base de datos | SQLite (aiosqlite) |
| Logging | structlog |
| Testing | pytest + pytest-asyncio |
| Linter | ruff |

## Coste Estimado por Sesión

Para una sesión de 4-6 horas con 4-5 jugadores:

| Servicio | Coste estimado |
|---|---|
| Transcripción (OpenAI) | ~$5-15 |
| Resumen (Claude Sonnet) | ~$2-5 |
| **Total** | **~$10-20/sesión** |

## Privacidad

- El audio se procesa y descarta inmediatamente. Solo se almacenan las transcripciones en texto.
- La base de datos SQLite es local.
- Las API keys no se almacenan en el código (usar variables de entorno).

## Consideraciones de Seguridad

### Basicas (hacer antes de poner en uso)

#### Proteger las API keys

Nunca commitear las keys al repositorio. Usar un archivo `.env` y asegurarse de que esté en `.gitignore`:

```bash
# Verificar que .env está ignorado
grep -q ".env" .gitignore || echo ".env" >> .gitignore
```

Restringir permisos del archivo `.env`:

**Linux/macOS:**
```bash
chmod 600 .env
```

**Windows (PowerShell):**
```powershell
icacls .env /inheritance:r /grant:r "$($env:USERNAME):(R)"
```

#### Proteger la base de datos

La base de datos SQLite contiene transcripciones de las sesiones (conversaciones de los jugadores). Restringir acceso:

**Linux/macOS:**
```bash
chmod 600 rpg_scribe.db
```

**Windows (PowerShell):**
```powershell
icacls rpg_scribe.db /inheritance:r /grant:r "$($env:USERNAME):(M)"
```

#### Limitar el acceso al dashboard web

Por defecto el dashboard escucha en `127.0.0.1` (solo local). **No exponer a `0.0.0.0` sin protección**, ya que no tiene autenticación. Si necesitas acceso remoto durante desarrollo, limitar por IP con firewall:

**Linux (ufw):**
```bash
# Permitir solo una IP específica al puerto 8000
sudo ufw allow from 192.168.1.100 to any port 8000
```

**Windows (PowerShell como admin):**
```powershell
# Permitir solo una IP específica al puerto 8000
New-NetFirewallRule -DisplayName "RPG Scribe" -Direction Inbound `
  -LocalPort 8000 -Protocol TCP -RemoteAddress 192.168.1.100 -Action Allow
```

#### Permisos mínimos del bot de Discord

Invitar el bot solo con los permisos listados en [Configuración del Bot de Discord](#configuración-del-bot-de-discord). No marcar "Administrator". El bot solo necesita: Connect, Speak, Send Messages y Embed Links.

### Avanzadas (recomendadas para producción)

#### Reverse proxy con HTTPS

Si se expone el dashboard fuera de localhost, colocarlo detrás de un reverse proxy con TLS:

**Linux (nginx):**
```nginx
server {
    listen 443 ssl;
    server_name rpg-scribe.tu-dominio.com;

    ssl_certificate     /etc/letsencrypt/live/rpg-scribe.tu-dominio.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/rpg-scribe.tu-dominio.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
}
```

**Windows:** usar IIS como reverse proxy con un certificado, o Caddy (`caddy reverse-proxy --from rpg-scribe.tu-dominio.com --to localhost:8000`) que gestiona TLS automáticamente.

#### Rotación de API keys

Rotar las keys periódicamente desde los respectivos paneles de cada proveedor. Al rotar, actualizar `.env` y reiniciar RPG Scribe. Si una key se compromete, revocarla inmediatamente desde:
- Discord: Developer Portal > Bot > Reset Token
- OpenAI: platform.openai.com > API Keys > revocar
- Anthropic: console.anthropic.com > API Keys > revocar

#### Limitar gasto en APIs externas

Configurar límites de uso mensual para evitar costes inesperados:
- **OpenAI**: Settings > Limits > establecer un hard limit mensual
- **Anthropic**: Settings > Plans and billing > configurar spending limit

#### Backups de la base de datos

Programar backups periódicos de la base de datos SQLite:

**Linux (cron, backup diario):**
```bash
# Añadir a crontab -e
0 3 * * * cp /ruta/a/rpg_scribe.db /ruta/a/backups/rpg_scribe_$(date +\%Y\%m\%d).db
```

**Windows (Task Scheduler, PowerShell):**
```powershell
# Crear script backup_db.ps1
Copy-Item "C:\ruta\a\rpg_scribe.db" "C:\ruta\a\backups\rpg_scribe_$(Get-Date -Format yyyyMMdd).db"
# Programarlo con: schtasks /create /tn "RPG Scribe Backup" /tr "powershell C:\ruta\backup_db.ps1" /sc daily /st 03:00
```

#### Ejecutar como servicio dedicado

Evitar ejecutar como root/administrador. Crear un usuario sin privilegios:

**Linux (systemd):**
```ini
# /etc/systemd/system/rpg-scribe.service
[Unit]
Description=RPG Scribe
After=network.target

[Service]
Type=simple
User=rpg-scribe
WorkingDirectory=/opt/rpg-scribe
EnvironmentFile=/opt/rpg-scribe/.env
ExecStart=/opt/rpg-scribe/.venv/bin/rpg-scribe --campaign config/campaigns/mi-campana.toml
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo useradd -r -s /usr/sbin/nologin rpg-scribe
sudo systemctl enable --now rpg-scribe
```

**Windows (NSSM):**
```powershell
# Instalar NSSM (https://nssm.cc) y registrar como servicio
nssm install RPGScribe "C:\ruta\.venv\Scripts\rpg-scribe.exe"
nssm set RPGScribe AppParameters "--campaign config\campaigns\mi-campana.toml"
nssm set RPGScribe AppDirectory "C:\ruta\Rpg-Scriber"
nssm set RPGScribe ObjectName ".\rpg-scribe-user"
nssm start RPGScribe
```

## Licencia

Este proyecto es software privado. Todos los derechos reservados.
