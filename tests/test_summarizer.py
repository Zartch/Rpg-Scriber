"""Tests for the Summarizer module (Phase 3)."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rpg_scribe.core.event_bus import EventBus
from rpg_scribe.core.events import (
    SummaryUpdateEvent,
    SystemStatusEvent,
    TranscriptionEvent,
)
from rpg_scribe.core.models import (
    CampaignContext,
    NPCInfo,
    PlayerInfo,
    SummarizerConfig,
)
from rpg_scribe.summarizers.base import BaseSummarizer, TranscriptionEntry
from rpg_scribe.summarizers.claude_summarizer import (
    ClaudeSummarizer,
    FINALIZE_USER,
    SESSION_SYSTEM_PROMPT,
    SESSION_UPDATE_USER,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_campaign(**overrides) -> CampaignContext:
    defaults = dict(
        campaign_id="test-campaign",
        name="Test Campaign",
        game_system="D&D 5e",
        language="es",
        description="A test campaign",
        players=[
            PlayerInfo(
                discord_id="user1",
                discord_name="Alice",
                character_name="Aelar",
                character_description="Elf ranger",
            ),
            PlayerInfo(
                discord_id="user2",
                discord_name="Bob",
                character_name="Brog",
                character_description="Dwarf fighter",
            ),
        ],
        known_npcs=[
            NPCInfo(name="Tabernero", description="Dueño de la taberna"),
        ],
        speaker_map={"user1": "Aelar", "user2": "Brog"},
        dm_speaker_id="dm1",
        campaign_summary="The party arrived at the village.",
        custom_instructions="Focus on combat details.",
    )
    defaults.update(overrides)
    return CampaignContext(**defaults)


def _make_config(**overrides) -> SummarizerConfig:
    defaults = dict(
        update_interval_s=120.0,
        max_pending_transcriptions=20,
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        api_timeout_s=60.0,
        max_retries=3,
        retry_base_delay_s=0.01,  # Fast retries for tests
    )
    defaults.update(overrides)
    return SummarizerConfig(**defaults)


def _make_transcription(
    session_id: str = "session-1",
    speaker_id: str = "user1",
    speaker_name: str = "Alice",
    text: str = "Hello world",
    **kwargs,
) -> TranscriptionEvent:
    defaults = dict(
        session_id=session_id,
        speaker_id=speaker_id,
        speaker_name=speaker_name,
        text=text,
        timestamp=time.time(),
        confidence=0.95,
        is_partial=False,
    )
    defaults.update(kwargs)
    return TranscriptionEvent(**defaults)


def _mock_anthropic_response(text: str) -> MagicMock:
    """Create a mock Anthropic API response."""
    content_block = MagicMock()
    content_block.text = text
    response = MagicMock()
    response.content = [content_block]
    return response


# ---------------------------------------------------------------------------
# Concrete test summarizer for BaseSummarizer tests
# ---------------------------------------------------------------------------


class MockSummarizer(BaseSummarizer):
    """Concrete summarizer for testing the base class."""

    def __init__(self, event_bus, config, campaign):
        super().__init__(event_bus, config, campaign)
        self.processed: list[TranscriptionEvent] = []
        self.update_called = False

    async def process_transcription(self, event: TranscriptionEvent) -> None:
        self.processed.append(event)
        self._pending.append(
            TranscriptionEntry(
                speaker_id=event.speaker_id,
                speaker_name=event.speaker_name,
                text=event.text,
                timestamp=event.timestamp,
            )
        )

    async def get_session_summary(self) -> str:
        return self._session_summary

    async def get_campaign_summary(self) -> str:
        return self._campaign_summary

    async def finalize_session(self) -> str:
        self._session_summary = "Final summary"
        await self._publish_summary("final")
        return self._session_summary


# ===================================================================
# BaseSummarizer tests
# ===================================================================


class TestBaseSummarizer:
    """Tests for the BaseSummarizer abstract base class."""

    @pytest.fixture
    def bus(self):
        return EventBus()

    @pytest.fixture
    def config(self):
        return _make_config()

    @pytest.fixture
    def campaign(self):
        return _make_campaign()

    @pytest.fixture
    def summarizer(self, bus, config, campaign):
        return MockSummarizer(bus, config, campaign)

    @pytest.mark.asyncio
    async def test_start_subscribes_and_publishes_status(self, summarizer, bus):
        statuses: list[SystemStatusEvent] = []
        bus.subscribe(SystemStatusEvent, _collect(statuses))

        await summarizer.start("session-1")

        assert summarizer._session_id == "session-1"
        assert len(statuses) == 1
        assert statuses[0].component == "summarizer"
        assert statuses[0].status == "running"

    @pytest.mark.asyncio
    async def test_stop_unsubscribes_and_publishes_status(self, summarizer, bus):
        statuses: list[SystemStatusEvent] = []
        bus.subscribe(SystemStatusEvent, _collect(statuses))

        await summarizer.start("session-1")
        await summarizer.stop()

        assert statuses[-1].status == "idle"

    @pytest.mark.asyncio
    async def test_handle_transcription_filters_partial(self, summarizer, bus):
        await summarizer.start("session-1")
        partial = _make_transcription(is_partial=True)
        await bus.publish(partial)
        assert len(summarizer.processed) == 0

    @pytest.mark.asyncio
    async def test_handle_transcription_filters_other_session(self, summarizer, bus):
        await summarizer.start("session-1")
        other = _make_transcription(session_id="session-other")
        await bus.publish(other)
        assert len(summarizer.processed) == 0

    @pytest.mark.asyncio
    async def test_handle_transcription_processes_valid(self, summarizer, bus):
        await summarizer.start("session-1")
        event = _make_transcription(session_id="session-1")
        await bus.publish(event)
        assert len(summarizer.processed) == 1
        assert summarizer.processed[0].text == "Hello world"

    @pytest.mark.asyncio
    async def test_should_update_max_pending(self, summarizer):
        summarizer.config.max_pending_transcriptions = 3
        for i in range(3):
            summarizer._pending.append(
                TranscriptionEntry(
                    speaker_id="u", speaker_name="N", text=f"t{i}", timestamp=0
                )
            )
        assert summarizer._should_update() is True

    @pytest.mark.asyncio
    async def test_should_update_time_elapsed(self, summarizer):
        summarizer.config.update_interval_s = 0.0  # immediate
        summarizer._pending.append(
            TranscriptionEntry(speaker_id="u", speaker_name="N", text="t", timestamp=0)
        )
        summarizer._last_update_time = 0.0
        assert summarizer._should_update() is True

    @pytest.mark.asyncio
    async def test_should_update_empty_pending(self, summarizer):
        assert summarizer._should_update() is False

    @pytest.mark.asyncio
    async def test_publish_summary(self, summarizer, bus):
        summaries: list[SummaryUpdateEvent] = []
        bus.subscribe(SummaryUpdateEvent, _collect(summaries))

        summarizer._session_id = "session-1"
        summarizer._session_summary = "A summary"
        summarizer._campaign_summary = "Campaign so far"

        await summarizer._publish_summary("incremental")

        assert len(summaries) == 1
        assert summaries[0].session_summary == "A summary"
        assert summaries[0].campaign_summary == "Campaign so far"
        assert summaries[0].update_type == "incremental"

    @pytest.mark.asyncio
    async def test_finalize_publishes_final(self, summarizer, bus):
        summaries: list[SummaryUpdateEvent] = []
        bus.subscribe(SummaryUpdateEvent, _collect(summaries))

        summarizer._session_id = "session-1"
        result = await summarizer.finalize_session()

        assert result == "Final summary"
        assert len(summaries) == 1
        assert summaries[0].update_type == "final"

    @pytest.mark.asyncio
    async def test_start_resets_state(self, summarizer):
        summarizer._session_summary = "old"
        summarizer._pending.append(
            TranscriptionEntry(speaker_id="u", speaker_name="N", text="t", timestamp=0)
        )
        await summarizer.start("session-2")
        assert summarizer._session_summary == ""
        assert len(summarizer._pending) == 0
        assert summarizer._session_id == "session-2"

    @pytest.mark.asyncio
    async def test_campaign_summary_initialized_from_context(self, bus, config):
        campaign = _make_campaign(campaign_summary="Previous adventures")
        s = MockSummarizer(bus, config, campaign)
        assert s._campaign_summary == "Previous adventures"


# ===================================================================
# ClaudeSummarizer tests
# ===================================================================


class TestClaudeSummarizer:
    """Tests for the ClaudeSummarizer implementation."""

    @pytest.fixture
    def bus(self):
        return EventBus()

    @pytest.fixture
    def config(self):
        return _make_config()

    @pytest.fixture
    def campaign(self):
        return _make_campaign()

    @pytest.fixture
    def mock_client(self):
        client = AsyncMock()
        return client

    @pytest.fixture
    def summarizer(self, bus, config, campaign, mock_client):
        return ClaudeSummarizer(bus, config, campaign, client=mock_client)

    # --- System prompt building ---

    def test_build_system_prompt_contains_campaign_info(self, summarizer):
        prompt = summarizer._build_system_prompt()
        assert "D&D 5e" in prompt
        assert "Test Campaign" in prompt
        assert "A test campaign" in prompt
        assert "The party arrived at the village." in prompt

    def test_build_system_prompt_contains_players(self, summarizer):
        prompt = summarizer._build_system_prompt()
        assert "Alice" in prompt
        assert "Aelar" in prompt
        assert "Elf ranger" in prompt
        assert "Bob" in prompt
        assert "Brog" in prompt

    def test_build_system_prompt_contains_npcs(self, summarizer):
        prompt = summarizer._build_system_prompt()
        assert "Tabernero" in prompt

    def test_build_system_prompt_contains_custom_instructions(self, summarizer):
        prompt = summarizer._build_system_prompt()
        assert "Focus on combat details." in prompt

    def test_build_system_prompt_no_npcs(self, bus, config):
        campaign = _make_campaign(known_npcs=[])
        s = ClaudeSummarizer(bus, config, campaign, client=AsyncMock())
        prompt = s._build_system_prompt()
        assert "(ninguno conocido)" in prompt

    def test_build_system_prompt_dm_name(self, bus, config):
        campaign = _make_campaign(
            dm_speaker_id="user1",
            players=[
                PlayerInfo("user1", "Carlos", "DM_char", ""),
                PlayerInfo("user2", "Ana", "Aelar", ""),
            ],
        )
        s = ClaudeSummarizer(bus, config, campaign, client=AsyncMock())
        prompt = s._build_system_prompt()
        assert "Carlos" in prompt

    def test_build_system_prompt_first_session(self, bus, config):
        campaign = _make_campaign(campaign_summary="")
        s = ClaudeSummarizer(bus, config, campaign, client=AsyncMock())
        prompt = s._build_system_prompt()
        assert "(primera sesión)" in prompt

    # --- Format transcriptions ---

    def test_format_transcriptions(self):
        entries = [
            TranscriptionEntry("u1", "Aelar", "I open the door.", 1.0),
            TranscriptionEntry("u2", "Brog", "I follow behind.", 2.0),
        ]
        result = ClaudeSummarizer._format_transcriptions(entries)
        assert "[Aelar]: I open the door." in result
        assert "[Brog]: I follow behind." in result

    # --- API call with retry ---

    @pytest.mark.asyncio
    async def test_call_api_success(self, summarizer, mock_client):
        mock_client.messages.create = AsyncMock(
            return_value=_mock_anthropic_response("Summary text")
        )
        result = await summarizer._call_api("system", "user msg")
        assert result == "Summary text"
        mock_client.messages.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_call_api_retry_on_failure(self, summarizer, mock_client):
        mock_client.messages.create = AsyncMock(
            side_effect=[
                RuntimeError("API error"),
                _mock_anthropic_response("Success after retry"),
            ]
        )
        result = await summarizer._call_api("system", "user msg")
        assert result == "Success after retry"
        assert mock_client.messages.create.call_count == 2

    @pytest.mark.asyncio
    async def test_call_api_all_retries_exhausted(self, summarizer, mock_client):
        mock_client.messages.create = AsyncMock(
            side_effect=RuntimeError("Persistent error")
        )
        with pytest.raises(RuntimeError, match="Claude API failed after 3 attempts"):
            await summarizer._call_api("system", "user msg")
        assert mock_client.messages.create.call_count == 3

    @pytest.mark.asyncio
    async def test_call_api_uses_config_model(self, summarizer, mock_client):
        mock_client.messages.create = AsyncMock(
            return_value=_mock_anthropic_response("ok")
        )
        await summarizer._call_api("sys", "usr")
        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["model"] == "claude-sonnet-4-20250514"
        assert call_kwargs["max_tokens"] == 4096

    # --- process_transcription ---

    @pytest.mark.asyncio
    async def test_process_transcription_buffers(self, summarizer, mock_client):
        """Transcriptions are buffered without triggering update below threshold."""
        await summarizer.start("session-1")
        event = _make_transcription(session_id="session-1")
        await summarizer.process_transcription(event)
        assert len(summarizer._pending) == 1
        assert summarizer._pending[0].speaker_name == "Aelar"  # mapped via speaker_map

    @pytest.mark.asyncio
    async def test_process_transcription_uses_speaker_map(self, summarizer):
        await summarizer.start("session-1")
        event = _make_transcription(
            session_id="session-1", speaker_id="user2", speaker_name="Bob"
        )
        await summarizer.process_transcription(event)
        assert summarizer._pending[0].speaker_name == "Brog"

    @pytest.mark.asyncio
    async def test_process_transcription_unknown_speaker(self, summarizer):
        await summarizer.start("session-1")
        event = _make_transcription(
            session_id="session-1", speaker_id="unknown", speaker_name="Mystery"
        )
        await summarizer.process_transcription(event)
        assert summarizer._pending[0].speaker_name == "Mystery"

    @pytest.mark.asyncio
    async def test_process_transcription_triggers_update(self, summarizer, mock_client):
        """When max_pending_transcriptions is reached, update is triggered."""
        summarizer.config.max_pending_transcriptions = 2
        mock_client.messages.create = AsyncMock(
            return_value=_mock_anthropic_response("Updated summary")
        )
        await summarizer.start("session-1")

        for i in range(2):
            event = _make_transcription(
                session_id="session-1", text=f"Line {i}"
            )
            await summarizer.process_transcription(event)

        assert summarizer._session_summary == "Updated summary"
        assert len(summarizer._pending) == 0

    @pytest.mark.asyncio
    async def test_update_summary_publishes_event(self, summarizer, bus, mock_client):
        summaries: list[SummaryUpdateEvent] = []
        bus.subscribe(SummaryUpdateEvent, _collect(summaries))

        mock_client.messages.create = AsyncMock(
            return_value=_mock_anthropic_response("New summary")
        )

        await summarizer.start("session-1")
        summarizer._pending.append(
            TranscriptionEntry("u1", "Aelar", "Test", time.time())
        )
        await summarizer._update_summary()

        assert len(summaries) == 1
        assert summaries[0].session_summary == "New summary"
        assert summaries[0].update_type == "incremental"

    @pytest.mark.asyncio
    async def test_update_summary_restores_pending_on_failure(
        self, summarizer, mock_client
    ):
        mock_client.messages.create = AsyncMock(
            side_effect=RuntimeError("API down")
        )
        summarizer.config.max_retries = 1
        summarizer.config.retry_base_delay_s = 0.001

        await summarizer.start("session-1")
        summarizer._pending.append(
            TranscriptionEntry("u1", "Aelar", "Important text", time.time())
        )
        await summarizer._update_summary()

        # Pending entries should be restored
        assert len(summarizer._pending) == 1
        assert summarizer._pending[0].text == "Important text"

    @pytest.mark.asyncio
    async def test_update_summary_empty_pending_noop(self, summarizer, mock_client):
        await summarizer.start("session-1")
        await summarizer._update_summary()
        mock_client.messages.create.assert_not_called()

    # --- finalize_session ---

    @pytest.mark.asyncio
    async def test_finalize_session_parses_response(self, summarizer, bus, mock_client):
        response_text = (
            "---SESSION_SUMMARY---\n"
            "The party defeated the dragon.\n\n"
            "---CAMPAIGN_SUMMARY---\n"
            "After many adventures, the party defeated the dragon."
        )
        mock_client.messages.create = AsyncMock(
            return_value=_mock_anthropic_response(response_text)
        )

        summaries: list[SummaryUpdateEvent] = []
        bus.subscribe(SummaryUpdateEvent, _collect(summaries))

        await summarizer.start("session-1")
        result = await summarizer.finalize_session()

        assert result == "The party defeated the dragon."
        assert summarizer._campaign_summary == "After many adventures, the party defeated the dragon."
        assert len(summaries) == 1
        assert summaries[0].update_type == "final"

    @pytest.mark.asyncio
    async def test_finalize_session_includes_remaining_pending(
        self, summarizer, mock_client
    ):
        mock_client.messages.create = AsyncMock(
            return_value=_mock_anthropic_response(
                "---SESSION_SUMMARY---\nDone\n---CAMPAIGN_SUMMARY---\nAll done"
            )
        )
        await summarizer.start("session-1")
        summarizer._pending.append(
            TranscriptionEntry("u1", "Aelar", "Last words", time.time())
        )

        await summarizer.finalize_session()

        # Verify the API was called with the pending text
        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert "Last words" in call_kwargs["messages"][0]["content"]
        assert len(summarizer._pending) == 0

    @pytest.mark.asyncio
    async def test_finalize_session_no_markers(self, summarizer, mock_client):
        """If the model doesn't use markers, the whole response is the session summary."""
        mock_client.messages.create = AsyncMock(
            return_value=_mock_anthropic_response("Just a plain summary.")
        )
        await summarizer.start("session-1")
        result = await summarizer.finalize_session()
        assert result == "Just a plain summary."

    # --- Integration with event bus ---

    @pytest.mark.asyncio
    async def test_full_flow_via_event_bus(self, summarizer, bus, mock_client):
        """End-to-end: publish TranscriptionEvents → trigger update → SummaryUpdateEvent."""
        summarizer.config.max_pending_transcriptions = 3
        mock_client.messages.create = AsyncMock(
            return_value=_mock_anthropic_response("Integrated summary")
        )

        summaries: list[SummaryUpdateEvent] = []
        bus.subscribe(SummaryUpdateEvent, _collect(summaries))

        await summarizer.start("session-1")

        for i in range(3):
            event = _make_transcription(session_id="session-1", text=f"Turn {i}")
            await bus.publish(event)

        assert len(summaries) == 1
        assert summaries[0].session_summary == "Integrated summary"

    @pytest.mark.asyncio
    async def test_error_in_process_publishes_error_status(self, bus, config, campaign):
        """If process_transcription raises, an error status is published."""
        # Use a summarizer whose process_transcription always fails
        client = AsyncMock()

        class FailingSummarizer(BaseSummarizer):
            async def process_transcription(self, event):
                raise ValueError("oops")

            async def get_session_summary(self):
                return ""

            async def get_campaign_summary(self):
                return ""

            async def finalize_session(self):
                return ""

        s = FailingSummarizer(bus, config, campaign)
        statuses: list[SystemStatusEvent] = []
        bus.subscribe(SystemStatusEvent, _collect(statuses))

        await s.start("session-1")
        event = _make_transcription(session_id="session-1")
        await bus.publish(event)

        error_statuses = [st for st in statuses if st.status == "error"]
        assert len(error_statuses) == 1
        assert "oops" in error_statuses[0].message

    # --- Lazy client ---

    def test_get_client_with_injected(self, summarizer, mock_client):
        assert summarizer._get_client() is mock_client

    def test_get_client_lazy_import_error(self, bus, config, campaign):
        s = ClaudeSummarizer(bus, config, campaign, client=None)
        with patch.dict("sys.modules", {"anthropic": None}):
            with pytest.raises(ImportError, match="anthropic"):
                s._get_client()


# ===================================================================
# TranscriptionEntry tests
# ===================================================================


class TestTranscriptionEntry:
    def test_creation(self):
        e = TranscriptionEntry("u1", "Alice", "Hello", 123.0)
        assert e.speaker_id == "u1"
        assert e.speaker_name == "Alice"
        assert e.text == "Hello"
        assert e.timestamp == 123.0


# ===================================================================
# SummarizerConfig tests
# ===================================================================


class TestSummarizerConfig:
    def test_defaults(self):
        cfg = SummarizerConfig()
        assert cfg.update_interval_s == 120.0
        assert cfg.max_pending_transcriptions == 20
        assert cfg.model == "claude-sonnet-4-20250514"
        assert cfg.max_tokens == 4096
        assert cfg.max_retries == 3


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _collect(target: list):
    """Return an async handler that appends events to a list."""

    async def handler(event):
        target.append(event)

    return handler
