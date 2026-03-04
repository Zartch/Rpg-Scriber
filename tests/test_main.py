"""Tests for the main application orchestrator."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rpg_scribe.config import AppConfig, load_app_config
from rpg_scribe.core.event_bus import EventBus
from rpg_scribe.core.events import (
    SessionEndRequestEvent,
    SessionStartRequestEvent,
    SummaryUpdateEvent,
    TranscriptionEvent,
)
from rpg_scribe.main import Application, build_parser


SAMPLE_CAMPAIGN_TOML = """\
[campaign]
id = "integration-test"
name = "Integration Test"
game_system = "Test System"
language = "en"

[[campaign.players]]
discord_id = "111"
discord_name = "Tester"
character_name = "TestChar"
"""


class TestBuildParser:
    def test_default_args(self) -> None:
        parser = build_parser()
        args = parser.parse_args([])
        assert args.campaign is None
        assert args.host is None
        assert args.port is None
        assert args.log_level == "INFO"
        assert args.json_logs is False

    def test_campaign_arg(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--campaign", "my.toml"])
        assert args.campaign == "my.toml"

    def test_host_port_args(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--host", "0.0.0.0", "--port", "9000"])
        assert args.host == "0.0.0.0"
        assert args.port == 9000

    def test_log_level(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--log-level", "DEBUG"])
        assert args.log_level == "DEBUG"

    def test_json_logs(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--json-logs"])
        assert args.json_logs is True


class TestApplication:
    @pytest.fixture
    def config(self, tmp_path: Path) -> AppConfig:
        toml_file = tmp_path / "campaign.toml"
        toml_file.write_text(SAMPLE_CAMPAIGN_TOML)
        cfg = load_app_config(campaign_path=toml_file)
        cfg.database_path = str(tmp_path / "test.db")
        cfg.discord_bot_token = ""  # Skip Discord bot
        return cfg

    async def test_application_lifecycle(self, config: AppConfig) -> None:
        """Test that the application can start and shutdown cleanly."""
        app = Application(config)

        # Mock transcriber to avoid real API calls
        with patch(
            "rpg_scribe.transcribers.openai_transcriber.OpenAITranscriber"
        ) as MockTranscriber, patch(
            "uvicorn.Config"
        ), patch(
            "uvicorn.Server"
        ) as MockServer:
            mock_transcriber = AsyncMock()
            MockTranscriber.return_value = mock_transcriber
            mock_server_instance = AsyncMock()
            MockServer.return_value = mock_server_instance

            await app.start()

            # Verify DB is connected
            assert app.db._conn is not None

            # Verify transcriber started
            mock_transcriber.start.assert_called_once()

            await app.shutdown()
            assert app.db._conn is None

    async def test_persist_transcription(self, config: AppConfig) -> None:
        """Test that transcriptions are persisted to the database."""
        app = Application(config)
        await app.db.connect()
        await app.db.upsert_campaign(
            campaign_id="integration-test", name="Test"
        )
        await app.db.create_session("s1", "integration-test")

        event = TranscriptionEvent(
            session_id="s1",
            speaker_id="111",
            speaker_name="Tester",
            text="Hello world",
            timestamp=1000.0,
            confidence=0.95,
            is_partial=False,
        )
        await app._persist_transcription(event)

        rows = await app.db.get_transcriptions("s1")
        assert len(rows) == 1
        assert rows[0]["text"] == "Hello world"

        await app.db.close()

    async def test_persist_transcription_skips_partial(self, config: AppConfig) -> None:
        """Partial transcriptions should not be persisted."""
        app = Application(config)
        await app.db.connect()
        await app.db.upsert_campaign(
            campaign_id="integration-test", name="Test"
        )
        await app.db.create_session("s1", "integration-test")

        event = TranscriptionEvent(
            session_id="s1",
            speaker_id="111",
            speaker_name="Tester",
            text="partial text",
            timestamp=1000.0,
            confidence=0.5,
            is_partial=True,
        )
        await app._persist_transcription(event)

        rows = await app.db.get_transcriptions("s1")
        assert len(rows) == 0

        await app.db.close()

    async def test_session_lifecycle(self, config: AppConfig) -> None:
        """Test session start and end flows."""
        app = Application(config)
        await app.db.connect()
        await app.db.upsert_campaign(
            campaign_id="integration-test", name="Test"
        )

        await app.on_session_start("s1")
        session = await app.db.get_session("s1")
        assert session is not None
        assert session["status"] == "active"

        # Mock summarizer for finalize
        app._summarizer = AsyncMock()
        app._summarizer.finalize_session = AsyncMock(return_value="Final summary")
        app._summarizer.stop = AsyncMock()

        await app.on_session_end("s1")
        session = await app.db.get_session("s1")
        assert session is not None
        assert session["status"] == "completed"
        assert session["session_summary"] == "Final summary"

        await app.db.close()

    async def test_session_start_event_triggers_on_session_start(
        self, config: AppConfig
    ) -> None:
        """SessionStartRequestEvent should trigger on_session_start."""
        app = Application(config)
        await app.db.connect()
        await app.db.upsert_campaign(
            campaign_id="integration-test", name="Test"
        )

        # Subscribe the handler
        app.event_bus.subscribe(
            SessionStartRequestEvent, app._on_session_start_request
        )

        # Mock summarizer setup to avoid real API calls
        with patch.object(app, "_setup_summarizer", new_callable=AsyncMock):
            await app.event_bus.publish(
                SessionStartRequestEvent(session_id="evt-s1", source="discord")
            )

        assert app._active_session_id == "evt-s1"
        session = await app.db.get_session("evt-s1")
        assert session is not None
        assert session["status"] == "active"

        await app.db.close()

    async def test_session_end_event_triggers_background_finalization(
        self, config: AppConfig, tmp_path: Path
    ) -> None:
        """SessionEndRequestEvent should trigger on_session_end via background task."""
        app = Application(config, log_dir=tmp_path)
        await app.db.connect()
        await app.db.upsert_campaign(
            campaign_id="integration-test", name="Test"
        )
        await app.db.create_session("evt-s2", "integration-test")
        app._active_session_id = "evt-s2"

        # Mock summarizer
        app._summarizer = AsyncMock()
        app._summarizer.finalize_session = AsyncMock(return_value="Final")
        app._summarizer.get_campaign_summary = AsyncMock(return_value="Campaign")
        app._summarizer.stop = AsyncMock()

        # Subscribe the handler
        app.event_bus.subscribe(
            SessionEndRequestEvent, app._on_session_end_request
        )

        await app.event_bus.publish(
            SessionEndRequestEvent(session_id="evt-s2", source="discord")
        )

        # Wait for background task to complete
        assert app._finalize_task is not None
        await app._finalize_task

        assert app._active_session_id is None
        session = await app.db.get_session("evt-s2")
        assert session["status"] == "completed"
        assert session["session_summary"] == "Final"

        await app.db.close()

    async def test_save_summary_to_file(
        self, config: AppConfig, tmp_path: Path
    ) -> None:
        """Summary should be written to session_summary.md in log dir."""
        app = Application(config, log_dir=tmp_path)
        app._save_summary_to_file("test-s1", "Session text", "Campaign text")

        summary_file = tmp_path / "session_summary.md"
        assert summary_file.exists()
        content = summary_file.read_text(encoding="utf-8")
        assert "test-s1" in content
        assert "Session text" in content
        assert "Campaign text" in content

    async def test_save_summary_no_log_dir(self, config: AppConfig) -> None:
        """When log_dir is None, no file should be written."""
        app = Application(config, log_dir=None)
        # Should not raise
        app._save_summary_to_file("s1", "text", "camp")
