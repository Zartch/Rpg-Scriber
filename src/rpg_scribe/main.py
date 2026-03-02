"""Entry point that orchestrates all RPG Scribe components.

Usage:
    python -m rpg_scribe --campaign config/campaigns/my-campaign.toml
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import logging
import os
import signal
import sys
import time
from pathlib import Path

from rpg_scribe.config import AppConfig, load_app_config
from rpg_scribe.core.database import Database
from rpg_scribe.core.event_bus import EventBus
from rpg_scribe.core.events import (
    AudioChunkEvent,
    SummaryUpdateEvent,
    SystemStatusEvent,
    TranscriptionEvent,
)
from rpg_scribe.logging_config import setup_logging

logger = logging.getLogger(__name__)

# Maximum size for a single transcription file before rotating (5 MB)
_MAX_TRANSCRIPTION_FILE_MB = 5


class TranscriptionFileWriter:
    """Writes transcriptions to text files inside the logs directory.

    Each log run (identified by a unix-timestamp folder) gets its own
    ``transcriptions_NNN.txt`` file.  When a file exceeds
    ``_MAX_TRANSCRIPTION_FILE_MB`` a new numbered file is created.
    """

    def __init__(self, log_dir: Path, max_size_mb: float = _MAX_TRANSCRIPTION_FILE_MB) -> None:
        self._dir = log_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._max_bytes = int(max_size_mb * 1024 * 1024)
        self._file_index = 0
        self._path = self._next_path()

    def _next_path(self) -> Path:
        """Return the next numbered transcription file path."""
        while True:
            suffix = f"_{self._file_index}" if self._file_index > 0 else ""
            path = self._dir / f"transcriptions{suffix}.txt"
            if not path.exists() or path.stat().st_size < self._max_bytes:
                return path
            self._file_index += 1

    def write(self, event: "TranscriptionEvent") -> None:
        """Append a transcription line to the current file.

        Format:  [HH:MM:SS] Speaker: text
        """
        if not event.text.strip():
            return

        # Rotate if current file is too large
        if self._path.exists() and self._path.stat().st_size >= self._max_bytes:
            self._file_index += 1
            self._path = self._next_path()
            logger.info(
                "📄 Transcription file rotated to %s", self._path.name,
            )

        ts = datetime.datetime.fromtimestamp(event.timestamp).strftime("%H:%M:%S")
        line = f"[{ts}] {event.speaker_name}: {event.text}\n"
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(line)


class AudioDiagnosticSaver:
    """Saves audio chunks as WAV files for manual inspection.

    Saves the first ``max_files`` chunks per user as mono WAV files
    under ``<log_dir>/audio/``.
    """

    def __init__(self, log_dir: Path, max_files_per_user: int = 3) -> None:
        self._audio_dir = log_dir / "audio"
        self._audio_dir.mkdir(parents=True, exist_ok=True)
        self._max_per_user = max_files_per_user
        self._counts: dict[str, int] = {}

    async def save(self, event: AudioChunkEvent) -> None:
        """Save an audio chunk as a mono WAV file."""
        uid = event.speaker_id
        count = self._counts.get(uid, 0)
        if count >= self._max_per_user:
            return

        import io
        import wave

        safe_name = "".join(
            c if c.isalnum() or c in "-_" else "_"
            for c in event.speaker_name
        )
        filepath = self._audio_dir / f"{safe_name}_{uid}_{count:03d}.wav"

        try:
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(48000)
                wf.writeframes(event.audio_data)
            filepath.write_bytes(buf.getvalue())
            self._counts[uid] = count + 1
            logger.info(
                "🔍 Audio diagnóstico: %s (%.1fKB, %.1fs)",
                filepath.name,
                len(event.audio_data) / 1024,
                event.duration_ms / 1000,
            )
        except Exception as exc:
            logger.error("Error guardando audio diagnóstico: %s", exc)


class Application:
    """Coordinates all RPG Scribe modules.

    Lifecycle:
        1. Load configuration and set up event bus.
        2. Connect to the database and persist the campaign.
        3. Start the transcriber & summarizer (subscribe to events).
        4. Start the web UI server.
        5. Start the Discord bot (blocking).
        6. On shutdown, finalize the session and tear down cleanly.
    """

    def __init__(self, config: AppConfig, log_dir: Path | None = None) -> None:
        self.config = config
        self.event_bus = EventBus()
        self.db = Database(config.database_path)
        self._log_dir = log_dir

        # Components (initialised in start())
        self._transcriber: object | None = None
        self._summarizer: object | None = None
        self._web_task: asyncio.Task[None] | None = None
        self._web_server: object | None = None  # uvicorn.Server
        self._bot_task: asyncio.Task[None] | None = None
        self._bot: object | None = None  # discord.py Bot
        self._discord_publisher: object | None = None
        self._transcription_writer: TranscriptionFileWriter | None = None
        self._audio_diagnostic: AudioDiagnosticSaver | None = None
        self._shutdown_event = asyncio.Event()

    # ── Database persistence handlers ──────────────────────────────

    async def _persist_transcription(self, event: TranscriptionEvent) -> None:
        """Save every transcription to the database."""
        if event.is_partial:
            return
        try:
            await self.db.save_transcription(
                session_id=event.session_id,
                speaker_id=event.speaker_id,
                speaker_name=event.speaker_name,
                text=event.text,
                timestamp=event.timestamp,
                confidence=event.confidence,
            )
        except Exception as exc:
            logger.error("Failed to persist transcription: %s", exc)

    async def _write_transcription_to_file(self, event: TranscriptionEvent) -> None:
        """Write transcription to the log directory text file."""
        if event.is_partial or not event.text.strip():
            return
        if self._transcription_writer is not None:
            try:
                self._transcription_writer.write(event)
            except Exception as exc:
                logger.error("Failed to write transcription to file: %s", exc)

    async def _persist_summary(self, event: SummaryUpdateEvent) -> None:
        """Save summary updates to the database."""
        try:
            if event.session_summary:
                session = await self.db.get_session(event.session_id)
                if session:
                    await self.db.conn.execute(
                        "UPDATE sessions SET session_summary = ? WHERE id = ?",
                        (event.session_summary, event.session_id),
                    )
                    await self.db.conn.commit()
            if event.campaign_summary and self.config.campaign:
                await self.db.update_campaign_summary(
                    self.config.campaign.campaign_id,
                    event.campaign_summary,
                )
        except Exception as exc:
            logger.error("Failed to persist summary: %s", exc)

    # ── Component setup ────────────────────────────────────────────

    async def _setup_transcriber(self) -> None:
        """Create and start the transcriber."""
        from rpg_scribe.transcribers.openai_transcriber import OpenAITranscriber

        self._transcriber = OpenAITranscriber(
            self.event_bus, self.config.transcriber
        )
        await self._transcriber.start()  # type: ignore[union-attr]

    async def _setup_summarizer(self, session_id: str) -> None:
        """Create and start the summarizer."""
        from rpg_scribe.core.models import CampaignContext
        from rpg_scribe.summarizers.claude_summarizer import ClaudeSummarizer

        campaign = self.config.campaign
        if campaign is None:
            campaign = CampaignContext.create_generic(
                language=self.config.transcriber.language,
            )
            logger.info(
                "No campaign configured — using generic summarization mode"
            )

        self._summarizer = ClaudeSummarizer(
            self.event_bus, self.config.summarizer, campaign, database=self.db
        )
        await self._summarizer.start(session_id)  # type: ignore[union-attr]

    async def _start_web(self) -> None:
        """Start the FastAPI web server as a background task."""
        import uvicorn

        from rpg_scribe.web.app import create_app

        app = create_app(self.event_bus, database=self.db, config=self.config)
        uv_config = uvicorn.Config(
            app,
            host=self.config.web_host,
            port=self.config.web_port,
            log_level="warning",
        )
        server = uvicorn.Server(uv_config)
        # Desactivar los signal handlers de uvicorn: en Windows instala handlers
        # que interfieren con el ProactorEventLoop y causan que el servidor se
        # pare solo a los pocos segundos. El ciclo de vida lo gestiona Application.
        server.install_signal_handlers = lambda: None  # type: ignore[assignment]
        self._web_server = server
        self._web_task = asyncio.create_task(server.serve(), name="web-server")
        # Dar un momento para que uvicorn arranque y detectar errores tempranos
        await asyncio.sleep(0.5)
        if self._web_task.done():
            exc = self._web_task.exception()
            if exc:
                logger.error("❌ Web UI failed to start: %s", exc)
            else:
                logger.warning("Web UI task finished unexpectedly")
        else:
            logger.info(
                "Web UI available at http://%s:%d",
                self.config.web_host,
                self.config.web_port,
            )

    async def _start_discord_bot(self) -> None:
        """Start the Discord bot as a background task."""
        if not self.config.discord_bot_token:
            logger.warning("DISCORD_BOT_TOKEN not set — Discord bot not started")
            return

        from rpg_scribe.discord_bot.bot import create_bot
        from rpg_scribe.discord_bot.publisher import DiscordSummaryPublisher

        bot = create_bot(self.event_bus, self.config.listener)
        self._bot = bot

        # Set up the summary publisher if a channel is configured
        if self.config.discord_summary_channel_id:
            self._discord_publisher = DiscordSummaryPublisher(
                bot=bot,
                event_bus=self.event_bus,
                channel_id=int(self.config.discord_summary_channel_id),
            )

        async def _run_bot() -> None:
            try:
                await bot.start(self.config.discord_bot_token)
            except Exception as exc:
                logger.error("Discord bot failed: %s", exc)
                await self.event_bus.publish(
                    SystemStatusEvent(
                        component="listener",
                        status="error",
                        message=f"Discord bot error: {exc}",
                    )
                )

        self._bot_task = asyncio.create_task(_run_bot(), name="discord-bot")

    # ── Lifecycle ──────────────────────────────────────────────────

    async def start(self) -> None:
        """Start all components."""
        # NOTA: NO llamar a setup_logging() aquí — ya se configuró en async_main
        # incluyendo el FileHandler. Llamarlo otra vez borraría los handlers.
        logger.info("RPG Scribe starting up")

        # Database
        await self.db.connect()

        # Persist campaign to DB if provided
        if self.config.campaign:
            c = self.config.campaign
            await self.db.upsert_campaign(
                campaign_id=c.campaign_id,
                name=c.name,
                game_system=c.game_system,
                language=c.language,
                description=c.description,
                campaign_summary=c.campaign_summary,
                speaker_map=c.speaker_map,
                dm_speaker_id=c.dm_speaker_id,
                custom_instructions=c.custom_instructions,
            )

        # Subscribe persistence handlers
        self.event_bus.subscribe(TranscriptionEvent, self._persist_transcription)
        self.event_bus.subscribe(SummaryUpdateEvent, self._persist_summary)

        # Transcription file writer (logs/<timestamp>/transcriptions.txt)
        if self._log_dir is not None:
            self._transcription_writer = TranscriptionFileWriter(self._log_dir)
            self.event_bus.subscribe(
                TranscriptionEvent, self._write_transcription_to_file
            )
            logger.info(
                "📄 Transcripciones se guardarán en: %s", self._log_dir,
            )

            # Audio diagnostic: save first chunks per user as WAV for inspection
            self._audio_diagnostic = AudioDiagnosticSaver(self._log_dir)
            self.event_bus.subscribe(AudioChunkEvent, self._audio_diagnostic.save)

        # Start transcriber
        await self._setup_transcriber()

        # Start web UI
        await self._start_web()

        # Start Discord bot
        await self._start_discord_bot()

        await self.event_bus.publish(
            SystemStatusEvent(
                component="system",
                status="running",
                message="RPG Scribe is ready",
            )
        )
        logger.info("RPG Scribe is ready — waiting for session to begin")

    async def on_session_start(self, session_id: str) -> None:
        """Called when a new recording session begins."""
        campaign_id = ""
        if self.config.campaign:
            campaign_id = self.config.campaign.campaign_id
        await self.db.create_session(session_id, campaign_id)
        await self._setup_summarizer(session_id)
        logger.info("Session %s started", session_id)

    async def on_session_end(self, session_id: str) -> None:
        """Called when a recording session ends."""
        summary = ""
        if self._summarizer is not None:
            try:
                summary = await self._summarizer.finalize_session()  # type: ignore[union-attr]
                await self._summarizer.stop()  # type: ignore[union-attr]
            except Exception as exc:
                logger.error("Failed to finalize session: %s", exc)
        await self.db.end_session(session_id, summary)
        logger.info("Session %s ended", session_id)

    async def shutdown(self) -> None:
        """Gracefully shut down all components."""
        logger.info("RPG Scribe shutting down")
        self._shutdown_event.set()

        if self._transcriber is not None:
            try:
                await self._transcriber.stop()  # type: ignore[union-attr]
            except Exception:
                pass

        if self._summarizer is not None:
            try:
                await self._summarizer.stop()  # type: ignore[union-attr]
            except Exception:
                pass

        # Close Discord bot gracefully before cancelling the task
        if self._bot is not None:
            try:
                await asyncio.wait_for(self._bot.close(), timeout=5.0)  # type: ignore[union-attr]
            except Exception:
                pass

        if self._bot_task is not None:
            self._bot_task.cancel()
            try:
                await self._bot_task
            except (asyncio.CancelledError, Exception):
                pass

        # Signal uvicorn to stop, then wait with a timeout
        if self._web_server is not None:
            self._web_server.should_exit = True  # type: ignore[union-attr]

        if self._web_task is not None:
            try:
                await asyncio.wait_for(self._web_task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                self._web_task.cancel()

        await self.db.close()

        # Cancelar cualquier tarea asyncio residual (e.g. hilos internos de discord.py)
        # para que asyncio.run() pueda terminar limpiamente y devolver el prompt.
        current = asyncio.current_task()
        remaining = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
        if remaining:
            logger.debug("Cancelando %d tarea(s) asyncio residual(es)...", len(remaining))
            for task in remaining:
                task.cancel()
            await asyncio.gather(*remaining, return_exceptions=True)

        logger.info("RPG Scribe stopped")

    async def run_forever(self) -> None:
        """Run until a shutdown signal is received."""
        await self.start()
        try:
            await self._shutdown_event.wait()
        except asyncio.CancelledError:
            pass
        finally:
            try:
                await asyncio.wait_for(self.shutdown(), timeout=8.0)
            except (asyncio.TimeoutError, Exception):
                logger.warning("Shutdown timed out — forzando salida")


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="rpg-scribe",
        description="RPG Scribe — live RPG session transcriber and summarizer",
    )
    parser.add_argument(
        "--campaign", "-c",
        type=str,
        default=None,
        help="Path to campaign TOML configuration file",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="Web UI host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Web UI port (default: 8000)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level (default: INFO)",
    )
    parser.add_argument(
        "--json-logs",
        action="store_true",
        help="Output logs as JSON lines",
    )
    return parser


async def async_main(args: argparse.Namespace) -> None:
    """Async entry point."""
    log_timestamp = str(int(time.time()))
    log_file = Path("logs") / f"{log_timestamp}.log"
    # Directory for transcription files: logs/<timestamp>/
    log_dir = Path("logs") / log_timestamp
    setup_logging(level=args.log_level, json_output=args.json_logs, log_file=log_file)
    logger.info("Logs guardados en: %s", log_file)

    config = load_app_config(campaign_path=args.campaign)
    if args.host:
        config.web_host = args.host
    if args.port:
        config.web_port = args.port

    app = Application(config, log_dir=log_dir)

    if sys.platform != "win32":
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(app.shutdown()))

    # En Windows, el handler de SIGINT (instalado en cli_main) llama a os._exit(0)
    # directamente, porque el ProactorEventLoop no permite inyectar excepciones.

    await app.run_forever()


def cli_main() -> None:
    """CLI entry point (used by pyproject.toml [project.scripts])."""
    parser = build_parser()
    args = parser.parse_args()

    # En Windows, asyncio.run() queda bloqueado en I/O del ProactorEventLoop
    # (_overlapped.GetQueuedCompletionStatusEx) donde Python no puede inyectar
    # excepciones. La única salida fiable es os._exit() directo desde el handler.
    if sys.platform == "win32":
        def _win_sigint(signum: int, frame: object) -> None:
            # Flush log handlers para que el fichero quede completo
            for handler in logging.getLogger().handlers:
                try:
                    handler.flush()
                except Exception:
                    pass
            os._exit(0)

        signal.signal(signal.SIGINT, _win_sigint)

    try:
        asyncio.run(async_main(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    cli_main()
