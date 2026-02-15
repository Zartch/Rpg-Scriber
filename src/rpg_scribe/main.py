"""Entry point that orchestrates all RPG Scribe components.

Usage:
    python -m rpg_scribe --campaign config/campaigns/my-campaign.toml
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

from rpg_scribe.config import AppConfig, load_app_config
from rpg_scribe.core.database import Database
from rpg_scribe.core.event_bus import EventBus
from rpg_scribe.core.events import (
    SummaryUpdateEvent,
    SystemStatusEvent,
    TranscriptionEvent,
)
from rpg_scribe.logging_config import setup_logging

logger = logging.getLogger(__name__)


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

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.event_bus = EventBus()
        self.db = Database(config.database_path)

        # Components (initialised in start())
        self._transcriber: object | None = None
        self._summarizer: object | None = None
        self._web_task: asyncio.Task[None] | None = None
        self._bot_task: asyncio.Task[None] | None = None
        self._discord_publisher: object | None = None
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
        if self.config.campaign is None:
            logger.warning("No campaign configured — summarizer not started")
            return
        from rpg_scribe.summarizers.claude_summarizer import ClaudeSummarizer

        self._summarizer = ClaudeSummarizer(
            self.event_bus, self.config.summarizer, self.config.campaign
        )
        await self._summarizer.start(session_id)  # type: ignore[union-attr]

    async def _start_web(self) -> None:
        """Start the FastAPI web server as a background task."""
        import uvicorn

        from rpg_scribe.web.app import create_app

        app = create_app(self.event_bus)
        uv_config = uvicorn.Config(
            app,
            host=self.config.web_host,
            port=self.config.web_port,
            log_level="warning",
        )
        server = uvicorn.Server(uv_config)
        self._web_task = asyncio.create_task(server.serve(), name="web-server")
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
        setup_logging(level="INFO")
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

        if self._bot_task is not None:
            self._bot_task.cancel()
            try:
                await self._bot_task
            except (asyncio.CancelledError, Exception):
                pass

        if self._web_task is not None:
            self._web_task.cancel()
            try:
                await self._web_task
            except (asyncio.CancelledError, Exception):
                pass

        await self.db.close()
        logger.info("RPG Scribe stopped")

    async def run_forever(self) -> None:
        """Run until a shutdown signal is received."""
        await self.start()
        try:
            await self._shutdown_event.wait()
        finally:
            await self.shutdown()


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
    setup_logging(level=args.log_level, json_output=args.json_logs)

    config = load_app_config(campaign_path=args.campaign)
    if args.host:
        config.web_host = args.host
    if args.port:
        config.web_port = args.port

    app = Application(config)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(app.shutdown()))

    await app.run_forever()


def cli_main() -> None:
    """CLI entry point (used by pyproject.toml [project.scripts])."""
    parser = build_parser()
    args = parser.parse_args()
    try:
        asyncio.run(async_main(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    cli_main()
