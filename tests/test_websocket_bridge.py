"""Tests for WebSocketBridge broadcasting the bot speech event."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from rpg_scribe.core.event_bus import EventBus
from rpg_scribe.core.events import BotSpeechEvent
from rpg_scribe.web.websocket import ConnectionManager, WebSocketBridge


@pytest.mark.asyncio
async def test_bot_speech_event_is_broadcast() -> None:
    bus = EventBus()
    manager = ConnectionManager()
    manager.broadcast = AsyncMock()  # capture broadcasts without real sockets
    bridge = WebSocketBridge(bus, manager)
    await bridge.start()

    await bus.publish(
        BotSpeechEvent(
            session_id="s-1",
            bot_keyword="bot reglas",
            speaker_name="Alice",
            question="¿cómo funciona el netrunning?",
            answer_md="Respuesta con cita...",
            total_chunks=3,
            timestamp=0.0,
        )
    )

    manager.broadcast.assert_awaited_once()
    msg = manager.broadcast.await_args.args[0]
    assert msg["type"] == "bot_speech"
    assert msg["data"]["bot_keyword"] == "bot reglas"
    assert msg["data"]["total_chunks"] == 3
    assert msg["data"]["question"] == "¿cómo funciona el netrunning?"
