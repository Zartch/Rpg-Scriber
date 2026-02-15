"""Tests for the RPG Scribe web module (FastAPI + WebSocket)."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from rpg_scribe.core.event_bus import EventBus
from rpg_scribe.core.events import (
    SummaryUpdateEvent,
    SystemStatusEvent,
    TranscriptionEvent,
)
from rpg_scribe.web.app import create_app
from rpg_scribe.web.routes import WebState
from rpg_scribe.web.websocket import ConnectionManager, WebSocketBridge


# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def app(event_bus: EventBus):
    return create_app(event_bus)


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _make_transcription(**overrides) -> TranscriptionEvent:
    defaults = {
        "session_id": "sess-001",
        "speaker_id": "user-1",
        "speaker_name": "Ana",
        "text": "Entro en la taberna.",
        "timestamp": 1700000000.0,
        "confidence": 0.95,
        "is_partial": False,
    }
    defaults.update(overrides)
    return TranscriptionEvent(**defaults)


def _make_summary(**overrides) -> SummaryUpdateEvent:
    defaults = {
        "session_id": "sess-001",
        "session_summary": "The party entered the tavern.",
        "campaign_summary": "Campaign ongoing.",
        "last_updated": 1700000001.0,
        "update_type": "incremental",
    }
    defaults.update(overrides)
    return SummaryUpdateEvent(**defaults)


def _make_status(**overrides) -> SystemStatusEvent:
    defaults = {
        "component": "listener",
        "status": "running",
        "message": "Connected to voice channel",
        "timestamp": 1700000000.0,
    }
    defaults.update(overrides)
    return SystemStatusEvent(**defaults)


# ── WebState unit tests ──────────────────────────────────────────


class TestWebState:
    def test_add_transcription(self):
        state = WebState()
        data = asdict(_make_transcription())
        state.add_transcription(data)

        assert len(state.transcriptions) == 1
        assert state.transcriptions[0]["speaker_name"] == "Ana"

    def test_update_summary(self):
        state = WebState()
        data = asdict(_make_summary())
        state.update_summary(data)

        assert state.session_summary == "The party entered the tavern."
        assert state.campaign_summary == "Campaign ongoing."
        assert state.last_summary_update == 1700000001.0

    def test_update_component_status(self):
        state = WebState()
        data = asdict(_make_status())
        state.update_component_status(data)

        assert "listener" in state.component_status
        assert state.component_status["listener"]["status"] == "running"

    def test_add_and_answer_question(self):
        state = WebState()
        state.add_question("q1", "Is this in-game?")

        assert len(state.questions) == 1
        assert state.questions[0]["status"] == "pending"

        found = state.answer_question("q1", "Yes, it is.")
        assert found is True
        assert state.questions[0]["status"] == "answered"
        assert state.questions[0]["answer"] == "Yes, it is."

    def test_answer_nonexistent_question(self):
        state = WebState()
        found = state.answer_question("q-nope", "answer")
        assert found is False

    def test_answer_already_answered(self):
        state = WebState()
        state.add_question("q2", "Who spoke?")
        state.answer_question("q2", "Aelar")
        # Answering again should fail
        found = state.answer_question("q2", "Gandrik")
        assert found is False

    def test_multiple_transcriptions(self):
        state = WebState()
        for i in range(5):
            state.add_transcription(
                asdict(_make_transcription(speaker_name=f"Speaker{i}"))
            )
        assert len(state.transcriptions) == 5

    def test_update_summary_overwrites(self):
        state = WebState()
        state.update_summary(asdict(_make_summary(session_summary="v1")))
        state.update_summary(asdict(_make_summary(session_summary="v2")))
        assert state.session_summary == "v2"


# ── ConnectionManager unit tests ─────────────────────────────────


class TestConnectionManager:
    async def test_connect_increments(self):
        mgr = ConnectionManager()
        assert mgr.active_count == 0

        ws = AsyncMock()
        await mgr.connect(ws)
        assert mgr.active_count == 1
        ws.accept.assert_awaited_once()

    async def test_disconnect_decrements(self):
        mgr = ConnectionManager()
        ws = AsyncMock()
        await mgr.connect(ws)
        await mgr.disconnect(ws)
        assert mgr.active_count == 0

    async def test_disconnect_missing_is_safe(self):
        mgr = ConnectionManager()
        ws = AsyncMock()
        await mgr.disconnect(ws)  # Should not raise
        assert mgr.active_count == 0

    async def test_broadcast_sends_to_all(self):
        mgr = ConnectionManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        await mgr.connect(ws1)
        await mgr.connect(ws2)

        msg = {"type": "test", "data": "hello"}
        await mgr.broadcast(msg)

        expected = json.dumps(msg, ensure_ascii=False)
        ws1.send_text.assert_awaited_once_with(expected)
        ws2.send_text.assert_awaited_once_with(expected)

    async def test_broadcast_removes_stale(self):
        mgr = ConnectionManager()
        ws_good = AsyncMock()
        ws_bad = AsyncMock()
        ws_bad.send_text.side_effect = RuntimeError("gone")

        await mgr.connect(ws_good)
        await mgr.connect(ws_bad)
        assert mgr.active_count == 2

        await mgr.broadcast({"type": "ping"})
        assert mgr.active_count == 1

    async def test_broadcast_no_clients(self):
        mgr = ConnectionManager()
        # Should not raise
        await mgr.broadcast({"type": "empty"})


# ── WebSocketBridge unit tests ───────────────────────────────────


class TestWebSocketBridge:
    async def test_start_subscribes(self):
        bus = EventBus()
        mgr = ConnectionManager()
        bridge = WebSocketBridge(bus, mgr)
        await bridge.start()

        # Verify subscriptions exist by publishing events
        ws = AsyncMock()
        await mgr.connect(ws)

        event = _make_transcription()
        await bus.publish(event)

        ws.send_text.assert_awaited_once()
        payload = json.loads(ws.send_text.call_args[0][0])
        assert payload["type"] == "transcription"
        assert payload["data"]["text"] == "Entro en la taberna."

    async def test_stop_unsubscribes(self):
        bus = EventBus()
        mgr = ConnectionManager()
        bridge = WebSocketBridge(bus, mgr)
        await bridge.start()
        await bridge.stop()

        ws = AsyncMock()
        await mgr.connect(ws)

        await bus.publish(_make_transcription())
        ws.send_text.assert_not_awaited()

    async def test_broadcasts_summary(self):
        bus = EventBus()
        mgr = ConnectionManager()
        bridge = WebSocketBridge(bus, mgr)
        await bridge.start()

        ws = AsyncMock()
        await mgr.connect(ws)

        await bus.publish(_make_summary())

        payload = json.loads(ws.send_text.call_args[0][0])
        assert payload["type"] == "summary"
        assert payload["data"]["session_summary"] == "The party entered the tavern."

    async def test_broadcasts_status(self):
        bus = EventBus()
        mgr = ConnectionManager()
        bridge = WebSocketBridge(bus, mgr)
        await bridge.start()

        ws = AsyncMock()
        await mgr.connect(ws)

        await bus.publish(_make_status())

        payload = json.loads(ws.send_text.call_args[0][0])
        assert payload["type"] == "status"
        assert payload["data"]["component"] == "listener"


# ── REST endpoint tests ──────────────────────────────────────────


class TestRESTEndpoints:
    async def test_get_status_empty(self, client: AsyncClient):
        resp = await client.get("/api/status")
        assert resp.status_code == 200
        body = resp.json()
        assert "components" in body
        assert body["active_session_id"] is None

    async def test_get_transcriptions_empty(self, client: AsyncClient):
        resp = await client.get("/api/sessions/sess-001/transcriptions")
        assert resp.status_code == 200
        body = resp.json()
        assert body["transcriptions"] == []

    async def test_get_summary_empty(self, client: AsyncClient):
        resp = await client.get("/api/sessions/sess-001/summary")
        assert resp.status_code == 200
        body = resp.json()
        assert body["session_summary"] == ""
        assert body["campaign_summary"] == ""

    async def test_get_questions_empty(self, client: AsyncClient):
        resp = await client.get("/api/questions")
        assert resp.status_code == 200
        body = resp.json()
        assert body["questions"] == []

    async def test_get_campaigns_empty(self, client: AsyncClient):
        resp = await client.get("/api/campaigns")
        assert resp.status_code == 200
        body = resp.json()
        assert body["campaign"] is None

    async def test_status_after_event(self, event_bus: EventBus):
        app = create_app(event_bus)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            await event_bus.publish(
                _make_status(component="transcriber", status="running")
            )
            resp = await c.get("/api/status")
            body = resp.json()
            assert body["components"].get("transcriber", {}).get("status") == "running"

    async def test_transcriptions_after_event(self, event_bus: EventBus):
        app = create_app(event_bus)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            await event_bus.publish(_make_transcription(session_id="sess-002"))
            resp = await c.get("/api/sessions/sess-002/transcriptions")
            body = resp.json()
            assert len(body["transcriptions"]) == 1
            assert body["transcriptions"][0]["speaker_name"] == "Ana"

    async def test_summary_after_event(self, event_bus: EventBus):
        app = create_app(event_bus)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            await event_bus.publish(_make_summary(session_summary="Updated summary"))
            resp = await c.get("/api/sessions/sess-001/summary")
            body = resp.json()
            assert body["session_summary"] == "Updated summary"

    async def test_answer_question_flow(self, client: AsyncClient):
        from rpg_scribe.web.routes import router

        state = router.state  # type: ignore[attr-defined]
        state.add_question("q-test", "Who is the DM?")

        resp = await client.get("/api/questions")
        body = resp.json()
        assert len(body["questions"]) == 1
        assert body["questions"][0]["question"] == "Who is the DM?"

        resp = await client.post(
            "/api/questions/q-test/answer",
            json={"answer": "Carlos"},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        resp = await client.get("/api/questions")
        assert resp.json()["questions"] == []

    async def test_answer_question_missing(self, client: AsyncClient):
        resp = await client.post(
            "/api/questions/nonexistent/answer",
            json={"answer": "test"},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is False

    async def test_answer_question_empty(self, client: AsyncClient):
        from rpg_scribe.web.routes import router

        state = router.state  # type: ignore[attr-defined]
        state.add_question("q-empty", "Something?")

        resp = await client.post(
            "/api/questions/q-empty/answer",
            json={"answer": ""},
        )
        assert resp.json()["ok"] is False


# ── Integration: event bus → WebState ────────────────────────────


class TestEventBusIntegration:
    """Verify that publishing events on the bus updates WebState."""

    async def test_transcription_event_stored(self):
        bus = EventBus()
        app = create_app(bus)
        from rpg_scribe.web.routes import router

        await bus.publish(_make_transcription(text="Hello world"))

        state = router.state  # type: ignore[attr-defined]
        assert len(state.transcriptions) == 1
        assert state.transcriptions[0]["text"] == "Hello world"

    async def test_summary_event_stored(self):
        bus = EventBus()
        create_app(bus)
        from rpg_scribe.web.routes import router

        await bus.publish(_make_summary(session_summary="Party fought dragon"))

        state = router.state  # type: ignore[attr-defined]
        assert state.session_summary == "Party fought dragon"

    async def test_status_event_stored(self):
        bus = EventBus()
        create_app(bus)
        from rpg_scribe.web.routes import router

        await bus.publish(
            _make_status(component="summarizer", status="error", message="API down")
        )

        state = router.state  # type: ignore[attr-defined]
        assert state.component_status["summarizer"]["status"] == "error"
        assert state.component_status["summarizer"]["message"] == "API down"

    async def test_multiple_events_accumulate(self):
        bus = EventBus()
        create_app(bus)
        from rpg_scribe.web.routes import router

        for i in range(3):
            await bus.publish(
                _make_transcription(text=f"Line {i}", speaker_name=f"Speaker{i}")
            )

        state = router.state  # type: ignore[attr-defined]
        assert len(state.transcriptions) == 3


# ── Session list endpoint tests ──────────────────────────────────


class TestSessionListEndpoint:
    async def test_list_sessions_no_database(self, event_bus: EventBus):
        """Without a database, the endpoint returns an empty list."""
        app = create_app(event_bus, database=None)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/api/campaigns/camp-1/sessions")
            assert resp.status_code == 200
            body = resp.json()
            assert body["sessions"] == []

    async def test_list_sessions_returns_sessions(self, event_bus: EventBus):
        """With a database, sessions are returned with truncated summaries."""
        db = AsyncMock()
        db.list_sessions = AsyncMock(return_value=[
            {
                "id": "sess-001",
                "campaign_id": "camp-1",
                "started_at": "2025-01-15T20:00:00",
                "ended_at": "2025-01-15T23:00:00",
                "status": "completed",
                "session_summary": "The party entered the tavern and met a stranger.",
            },
            {
                "id": "sess-002",
                "campaign_id": "camp-1",
                "started_at": "2025-01-22T20:00:00",
                "ended_at": None,
                "status": "active",
                "session_summary": "",
            },
        ])
        app = create_app(event_bus, database=db)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/api/campaigns/camp-1/sessions")
            assert resp.status_code == 200
            body = resp.json()
            assert len(body["sessions"]) == 2
            # First session has summary preview
            assert body["sessions"][0]["id"] == "sess-001"
            assert body["sessions"][0]["status"] == "completed"
            assert "tavern" in body["sessions"][0]["summary_preview"]
            # Second session has empty summary
            assert body["sessions"][1]["summary_preview"] == ""

    async def test_list_sessions_ordered_by_date(self, event_bus: EventBus):
        """Sessions should be returned in the order provided by database (desc by started_at)."""
        db = AsyncMock()
        db.list_sessions = AsyncMock(return_value=[
            {
                "id": "sess-new",
                "campaign_id": "camp-1",
                "started_at": "2025-02-01T20:00:00",
                "ended_at": "2025-02-01T23:00:00",
                "status": "completed",
                "session_summary": "New session.",
            },
            {
                "id": "sess-old",
                "campaign_id": "camp-1",
                "started_at": "2025-01-01T20:00:00",
                "ended_at": "2025-01-01T23:00:00",
                "status": "completed",
                "session_summary": "Old session.",
            },
        ])
        app = create_app(event_bus, database=db)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/api/campaigns/camp-1/sessions")
            body = resp.json()
            ids = [s["id"] for s in body["sessions"]]
            assert ids == ["sess-new", "sess-old"]

    async def test_list_sessions_truncates_long_summary(self, event_bus: EventBus):
        """Long summaries should be truncated to 150 chars with ellipsis."""
        long_summary = "A" * 200
        db = AsyncMock()
        db.list_sessions = AsyncMock(return_value=[
            {
                "id": "sess-long",
                "campaign_id": "camp-1",
                "started_at": "2025-01-15T20:00:00",
                "ended_at": "2025-01-15T23:00:00",
                "status": "completed",
                "session_summary": long_summary,
            },
        ])
        app = create_app(event_bus, database=db)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/api/campaigns/camp-1/sessions")
            body = resp.json()
            preview = body["sessions"][0]["summary_preview"]
            assert len(preview) == 153  # 150 + "..."
            assert preview.endswith("...")


# ── create_app factory tests ─────────────────────────────────────


class TestCreateApp:
    def test_app_has_routes(self, app):
        paths = [r.path for r in app.routes]
        assert "/api/status" in paths
        assert "/api/questions" in paths
        assert "/ws/live" in paths
        assert "/api/campaigns/{campaign_id}/sessions" in paths

    def test_app_title(self, app):
        assert app.title == "RPG Scribe"
