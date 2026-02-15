"""Tests for the Discord summary publisher."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rpg_scribe.core.event_bus import EventBus
from rpg_scribe.core.events import SummaryUpdateEvent
from rpg_scribe.discord_bot.publisher import (
    DiscordSummaryPublisher,
    _truncate,
)


class TestTruncate:
    def test_short_text_unchanged(self) -> None:
        assert _truncate("hello", 10) == "hello"

    def test_exact_limit(self) -> None:
        assert _truncate("hello", 5) == "hello"

    def test_truncated_with_ellipsis(self) -> None:
        result = _truncate("hello world", 8)
        assert result == "hello..."
        assert len(result) == 8

    def test_very_short_limit(self) -> None:
        result = _truncate("hello world", 4)
        assert result == "h..."
        assert len(result) == 4


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.get_channel = MagicMock(return_value=None)
    bot.fetch_channel = AsyncMock(return_value=None)
    return bot


class TestDiscordSummaryPublisher:
    async def test_subscribes_to_summary_events(self, event_bus: EventBus, mock_bot) -> None:
        publisher = DiscordSummaryPublisher(mock_bot, event_bus, channel_id=12345)
        # Verify handler is subscribed
        handlers = event_bus._handlers.get(SummaryUpdateEvent, [])
        assert publisher._on_summary in handlers

    async def test_stop_unsubscribes(self, event_bus: EventBus, mock_bot) -> None:
        publisher = DiscordSummaryPublisher(mock_bot, event_bus, channel_id=12345)
        await publisher.stop()
        handlers = event_bus._handlers.get(SummaryUpdateEvent, [])
        assert publisher._on_summary not in handlers

    async def test_build_embed_incremental(self, event_bus: EventBus, mock_bot) -> None:
        publisher = DiscordSummaryPublisher(mock_bot, event_bus, channel_id=12345)
        event = SummaryUpdateEvent(
            session_id="s1",
            session_summary="The party entered the dungeon.",
            campaign_summary="",
            last_updated=time.time(),
            update_type="incremental",
        )
        embed = publisher._build_embed(event)
        assert "Resumen en Vivo" in embed.title
        assert "dungeon" in embed.description

    async def test_build_embed_final(self, event_bus: EventBus, mock_bot) -> None:
        publisher = DiscordSummaryPublisher(mock_bot, event_bus, channel_id=12345)
        event = SummaryUpdateEvent(
            session_id="s1",
            session_summary="Final summary.",
            campaign_summary="Campaign overview.",
            last_updated=time.time(),
            update_type="final",
        )
        embed = publisher._build_embed(event)
        assert "Final" in embed.title
        assert len(embed.fields) == 1
        assert "Campana" in embed.fields[0].name

    async def test_build_embed_no_campaign_summary(self, event_bus: EventBus, mock_bot) -> None:
        publisher = DiscordSummaryPublisher(mock_bot, event_bus, channel_id=12345)
        event = SummaryUpdateEvent(
            session_id="s1",
            session_summary="Session text.",
            campaign_summary="",
            last_updated=time.time(),
            update_type="incremental",
        )
        embed = publisher._build_embed(event)
        assert len(embed.fields) == 0

    async def test_rate_limiting(self, event_bus: EventBus, mock_bot) -> None:
        """Non-final events should be rate-limited."""
        mock_channel = MagicMock()
        mock_channel.__class__ = type("TextChannel", (), {})
        mock_bot.get_channel.return_value = None
        mock_bot.fetch_channel.return_value = None

        publisher = DiscordSummaryPublisher(mock_bot, event_bus, channel_id=12345)
        publisher._last_update = time.time()  # Mark as just updated

        event = SummaryUpdateEvent(
            session_id="s1",
            session_summary="Update.",
            campaign_summary="",
            last_updated=time.time(),
            update_type="incremental",
        )
        # Should return early due to rate limiting (less than 5s since last)
        await publisher._on_summary(event)
        # fetch_channel should not be called since rate-limited
        mock_bot.fetch_channel.assert_not_called()
