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
from rpg_scribe.core.database import Database
from rpg_scribe.summarizers.claude_summarizer import (
    ClaudeSummarizer,
    FINALIZE_USER,
    QUESTION_PATTERN,
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

    # --- Question extraction ---

    def test_extract_questions_single(self):
        text = "El grupo entró en la taberna. [PREGUNTA: ¿Quién es el líder del grupo?] Pidieron cerveza."
        cleaned, questions = ClaudeSummarizer._extract_questions(text)
        assert questions == ["¿Quién es el líder del grupo?"]
        assert "[PREGUNTA:" not in cleaned
        assert "taberna" in cleaned
        assert "cerveza" in cleaned

    def test_extract_questions_multiple(self):
        text = (
            "Resumen. [PREGUNTA: ¿Aelar habló como jugador o personaje?] "
            "Más texto. [PREGUNTA: ¿El tabernero es amigo o enemigo?]"
        )
        cleaned, questions = ClaudeSummarizer._extract_questions(text)
        assert len(questions) == 2
        assert "¿Aelar habló como jugador o personaje?" in questions
        assert "¿El tabernero es amigo o enemigo?" in questions
        assert "[PREGUNTA:" not in cleaned

    def test_extract_questions_none(self):
        text = "El grupo descansó en la posada sin incidentes."
        cleaned, questions = ClaudeSummarizer._extract_questions(text)
        assert questions == []
        assert cleaned == text

    def test_extract_questions_cleans_extra_whitespace(self):
        text = "Inicio.\n\n[PREGUNTA: ¿Algo?]\n\n\n\nFin."
        cleaned, _ = ClaudeSummarizer._extract_questions(text)
        assert "\n\n\n" not in cleaned

    @pytest.mark.asyncio
    async def test_questions_saved_to_database(self, bus, config, campaign, mock_client):
        """Questions extracted from LLM response are saved to the database."""
        db = AsyncMock(spec=Database)
        db.save_question = AsyncMock(return_value=1)
        db.get_answered_unprocessed_questions = AsyncMock(return_value=[])

        summarizer = ClaudeSummarizer(
            bus, config, campaign, client=mock_client, database=db
        )

        mock_client.messages.create = AsyncMock(
            return_value=_mock_anthropic_response(
                "Resumen actualizado. [PREGUNTA: ¿Quién habló?] Fin."
            )
        )

        await summarizer.start("session-1")
        summarizer._pending.append(
            TranscriptionEntry("u1", "Aelar", "Test", time.time())
        )
        await summarizer._update_summary()

        db.save_question.assert_called_once_with("session-1", "¿Quién habló?")

    @pytest.mark.asyncio
    async def test_summary_clean_after_question_extraction(
        self, bus, config, campaign, mock_client
    ):
        """The published summary should not contain [PREGUNTA: ...] markers."""
        db = AsyncMock(spec=Database)
        db.save_question = AsyncMock(return_value=1)
        db.get_answered_unprocessed_questions = AsyncMock(return_value=[])

        summarizer = ClaudeSummarizer(
            bus, config, campaign, client=mock_client, database=db
        )

        mock_client.messages.create = AsyncMock(
            return_value=_mock_anthropic_response(
                "El grupo viajó al norte. [PREGUNTA: ¿Era de día o de noche?] Llegaron al bosque."
            )
        )

        summaries: list[SummaryUpdateEvent] = []
        bus.subscribe(SummaryUpdateEvent, _collect(summaries))

        await summarizer.start("session-1")
        summarizer._pending.append(
            TranscriptionEntry("u1", "Aelar", "Vamos al norte", time.time())
        )
        await summarizer._update_summary()

        assert "[PREGUNTA:" not in summarizer._session_summary
        assert "[PREGUNTA:" not in summaries[0].session_summary
        assert "bosque" in summarizer._session_summary

    @pytest.mark.asyncio
    async def test_answered_questions_injected_in_context(
        self, bus, config, campaign, mock_client
    ):
        """Answered questions should be included in the LLM prompt context."""
        db = AsyncMock(spec=Database)
        db.save_question = AsyncMock(return_value=1)
        db.get_answered_unprocessed_questions = AsyncMock(
            return_value=[
                {"id": 1, "question": "¿Quién es el líder?", "answer": "Aelar es el líder"},
            ]
        )
        db.mark_questions_processed = AsyncMock()

        summarizer = ClaudeSummarizer(
            bus, config, campaign, client=mock_client, database=db
        )

        mock_client.messages.create = AsyncMock(
            return_value=_mock_anthropic_response("Resumen con contexto.")
        )

        await summarizer.start("session-1")
        summarizer._pending.append(
            TranscriptionEntry("u1", "Aelar", "Avanzamos", time.time())
        )
        await summarizer._update_summary()

        # Verify the API was called with answers in the prompt
        call_kwargs = mock_client.messages.create.call_args.kwargs
        user_content = call_kwargs["messages"][0]["content"]
        assert "RESPUESTAS DEL USUARIO" in user_content
        assert "¿Quién es el líder?" in user_content
        assert "Aelar es el líder" in user_content

        # Verify questions were marked as processed
        db.mark_questions_processed.assert_called_once_with([1])

    @pytest.mark.asyncio
    async def test_no_answers_block_when_no_answered_questions(
        self, bus, config, campaign, mock_client
    ):
        """When there are no answered questions, the prompt should not contain RESPUESTAS."""
        db = AsyncMock(spec=Database)
        db.save_question = AsyncMock(return_value=1)
        db.get_answered_unprocessed_questions = AsyncMock(return_value=[])

        summarizer = ClaudeSummarizer(
            bus, config, campaign, client=mock_client, database=db
        )

        mock_client.messages.create = AsyncMock(
            return_value=_mock_anthropic_response("Resumen limpio.")
        )

        await summarizer.start("session-1")
        summarizer._pending.append(
            TranscriptionEntry("u1", "Aelar", "Hola", time.time())
        )
        await summarizer._update_summary()

        call_kwargs = mock_client.messages.create.call_args.kwargs
        user_content = call_kwargs["messages"][0]["content"]
        assert "RESPUESTAS DEL USUARIO" not in user_content

    # --- Lazy client ---

    def test_get_client_with_injected(self, summarizer, mock_client):
        assert summarizer._get_client() is mock_client

    def test_get_client_lazy_import_error(self, bus, config, campaign):
        s = ClaudeSummarizer(bus, config, campaign, client=None)
        with patch.dict("sys.modules", {"anthropic": None}):
            with pytest.raises(ImportError, match="anthropic"):
                s._get_client()


# ===================================================================
# NPC/Location extraction tests
# ===================================================================


class TestExtractionParsing:
    """Tests for _parse_extraction_response."""

    def test_parse_valid_json(self):
        text = '{"npcs": [{"name": "Gareth", "description": "Un mercader ambulante"}], "locations": [{"name": "Bosque Oscuro", "description": "Un bosque tenebroso"}]}'
        result = ClaudeSummarizer._parse_extraction_response(text)
        assert len(result["npcs"]) == 1
        assert result["npcs"][0]["name"] == "Gareth"
        assert len(result["locations"]) == 1
        assert result["locations"][0]["name"] == "Bosque Oscuro"

    def test_parse_empty_lists(self):
        text = '{"npcs": [], "locations": []}'
        result = ClaudeSummarizer._parse_extraction_response(text)
        assert result["npcs"] == []
        assert result["locations"] == []

    def test_parse_json_with_surrounding_text(self):
        text = 'Aquí tienes el resultado:\n{"npcs": [{"name": "Elara", "description": "Elfa sanadora"}], "locations": []}\nEspero que sea útil.'
        result = ClaudeSummarizer._parse_extraction_response(text)
        assert len(result["npcs"]) == 1
        assert result["npcs"][0]["name"] == "Elara"

    def test_parse_invalid_json(self):
        text = "Esto no es JSON válido"
        result = ClaudeSummarizer._parse_extraction_response(text)
        assert result == {"npcs": [], "locations": []}

    def test_parse_malformed_json(self):
        text = '{"npcs": "not a list", "locations": 42}'
        result = ClaudeSummarizer._parse_extraction_response(text)
        assert result["npcs"] == []
        assert result["locations"] == []

    def test_parse_missing_keys(self):
        text = '{"other": "data"}'
        result = ClaudeSummarizer._parse_extraction_response(text)
        assert result["npcs"] == []
        assert result["locations"] == []


class TestFinalizeSessionWithExtraction:
    """Tests for finalize_session with NPC/location extraction."""

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
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_finalize_extracts_and_saves_npcs(
        self, bus, config, campaign, mock_client
    ):
        """finalize_session should extract NPCs via a second LLM call and save them."""
        db = AsyncMock(spec=Database)
        db.npc_exists = AsyncMock(return_value=False)
        db.save_npc = AsyncMock()

        summarizer = ClaudeSummarizer(
            bus, config, campaign, client=mock_client, database=db
        )

        finalize_response = (
            "---SESSION_SUMMARY---\n"
            "El grupo conoció a Gareth en la taberna.\n\n"
            "---CAMPAIGN_SUMMARY---\n"
            "La campaña continúa."
        )
        extraction_response = (
            '{"npcs": [{"name": "Gareth", "description": "Mercader ambulante"}], '
            '"locations": [{"name": "Cueva del Dragón", "description": "Cueva peligrosa"}]}'
        )
        mock_client.messages.create = AsyncMock(
            side_effect=[
                _mock_anthropic_response(finalize_response),
                _mock_anthropic_response(extraction_response),
            ]
        )

        await summarizer.start("session-1")
        await summarizer.finalize_session()

        # Verify NPC was saved
        db.save_npc.assert_called_once_with(
            campaign_id="test-campaign",
            name="Gareth",
            description="Mercader ambulante",
            first_seen_session="session-1",
        )

    @pytest.mark.asyncio
    async def test_finalize_skips_known_npcs(
        self, bus, config, campaign, mock_client
    ):
        """Known NPCs should not be saved again."""
        db = AsyncMock(spec=Database)
        db.npc_exists = AsyncMock(return_value=True)
        db.save_npc = AsyncMock()

        summarizer = ClaudeSummarizer(
            bus, config, campaign, client=mock_client, database=db
        )

        finalize_response = (
            "---SESSION_SUMMARY---\nResumen.\n\n---CAMPAIGN_SUMMARY---\nCampaña."
        )
        extraction_response = (
            '{"npcs": [{"name": "Tabernero", "description": "Ya conocido"}], "locations": []}'
        )
        mock_client.messages.create = AsyncMock(
            side_effect=[
                _mock_anthropic_response(finalize_response),
                _mock_anthropic_response(extraction_response),
            ]
        )

        await summarizer.start("session-1")
        await summarizer.finalize_session()

        db.save_npc.assert_not_called()

    @pytest.mark.asyncio
    async def test_finalize_no_database_skips_extraction(
        self, bus, config, campaign, mock_client
    ):
        """Without a database, extraction should be skipped."""
        summarizer = ClaudeSummarizer(
            bus, config, campaign, client=mock_client, database=None
        )

        finalize_response = (
            "---SESSION_SUMMARY---\nResumen.\n\n---CAMPAIGN_SUMMARY---\nCampaña."
        )
        mock_client.messages.create = AsyncMock(
            return_value=_mock_anthropic_response(finalize_response)
        )

        await summarizer.start("session-1")
        await summarizer.finalize_session()

        # Only one API call (finalize), no extraction call
        assert mock_client.messages.create.call_count == 1

    @pytest.mark.asyncio
    async def test_finalize_extraction_failure_does_not_crash(
        self, bus, config, campaign, mock_client
    ):
        """If extraction LLM call fails, finalize_session should still complete."""
        db = AsyncMock(spec=Database)

        summarizer = ClaudeSummarizer(
            bus, config, campaign, client=mock_client, database=db
        )

        finalize_response = (
            "---SESSION_SUMMARY---\nResumen.\n\n---CAMPAIGN_SUMMARY---\nCampaña."
        )
        mock_client.messages.create = AsyncMock(
            side_effect=[
                _mock_anthropic_response(finalize_response),
                RuntimeError("Extraction API failed"),
            ]
        )
        # max_retries=1 so the extraction fails fast
        summarizer.config.max_retries = 1

        await summarizer.start("session-1")
        result = await summarizer.finalize_session()

        # Should still return the session summary despite extraction failure
        assert result == "Resumen."

    @pytest.mark.asyncio
    async def test_finalize_extraction_skips_empty_names(
        self, bus, config, campaign, mock_client
    ):
        """NPCs with empty names should be skipped."""
        db = AsyncMock(spec=Database)
        db.npc_exists = AsyncMock(return_value=False)
        db.save_npc = AsyncMock()

        summarizer = ClaudeSummarizer(
            bus, config, campaign, client=mock_client, database=db
        )

        finalize_response = (
            "---SESSION_SUMMARY---\nResumen.\n\n---CAMPAIGN_SUMMARY---\nCampaña."
        )
        extraction_response = (
            '{"npcs": [{"name": "", "description": "Sin nombre"}, '
            '{"name": "Valida", "description": "NPC válida"}], "locations": []}'
        )
        mock_client.messages.create = AsyncMock(
            side_effect=[
                _mock_anthropic_response(finalize_response),
                _mock_anthropic_response(extraction_response),
            ]
        )

        await summarizer.start("session-1")
        await summarizer.finalize_session()

        # Only the valid NPC should be saved
        db.save_npc.assert_called_once_with(
            campaign_id="test-campaign",
            name="Valida",
            description="NPC válida",
            first_seen_session="session-1",
        )


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
