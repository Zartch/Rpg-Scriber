"""Tests for the SQLite async database wrapper."""

from __future__ import annotations

import pytest

from rpg_scribe.core.database import Database


@pytest.fixture
async def db(tmp_path):
    """Create a temporary database for testing."""
    db_path = tmp_path / "test.db"
    database = Database(str(db_path))
    await database.connect()
    yield database
    await database.close()


class TestDatabaseCampaigns:
    async def test_upsert_and_get_campaign(self, db: Database) -> None:
        await db.upsert_campaign(
            campaign_id="c1",
            name="Test Campaign",
            game_system="D&D 5e",
            language="en",
            description="A test",
            speaker_map={"111": "Aria"},
        )
        result = await db.get_campaign("c1")
        assert result is not None
        assert result["name"] == "Test Campaign"
        assert result["game_system"] == "D&D 5e"
        assert result["speaker_map"] == {"111": "Aria"}

    async def test_get_nonexistent_campaign(self, db: Database) -> None:
        result = await db.get_campaign("nonexistent")
        assert result is None

    async def test_upsert_updates_existing(self, db: Database) -> None:
        await db.upsert_campaign(campaign_id="c1", name="V1")
        await db.upsert_campaign(campaign_id="c1", name="V2")
        result = await db.get_campaign("c1")
        assert result is not None
        assert result["name"] == "V2"

    async def test_update_campaign_summary(self, db: Database) -> None:
        await db.upsert_campaign(campaign_id="c1", name="Test")
        await db.update_campaign_summary("c1", "The party traveled east.")
        result = await db.get_campaign("c1")
        assert result is not None
        assert result["campaign_summary"] == "The party traveled east."


class TestDatabaseSessions:
    async def test_create_and_get_session(self, db: Database) -> None:
        await db.upsert_campaign(campaign_id="c1", name="Test")
        await db.create_session("s1", "c1")
        session = await db.get_session("s1")
        assert session is not None
        assert session["campaign_id"] == "c1"
        assert session["status"] == "active"

    async def test_end_session(self, db: Database) -> None:
        await db.upsert_campaign(campaign_id="c1", name="Test")
        await db.create_session("s1", "c1")
        await db.end_session("s1", "Final summary text")
        session = await db.get_session("s1")
        assert session is not None
        assert session["status"] == "completed"
        assert session["session_summary"] == "Final summary text"
        assert session["ended_at"] is not None

    async def test_list_sessions(self, db: Database) -> None:
        await db.upsert_campaign(campaign_id="c1", name="Test")
        await db.create_session("s1", "c1")
        await db.create_session("s2", "c1")
        sessions = await db.list_sessions("c1")
        assert len(sessions) == 2

    async def test_get_nonexistent_session(self, db: Database) -> None:
        result = await db.get_session("nope")
        assert result is None


class TestDatabaseTranscriptions:
    async def test_save_and_get_transcriptions(self, db: Database) -> None:
        await db.upsert_campaign(campaign_id="c1", name="Test")
        await db.create_session("s1", "c1")

        row_id = await db.save_transcription(
            session_id="s1",
            speaker_id="111",
            speaker_name="Alice",
            text="Hello world",
            timestamp=1000.0,
            confidence=0.95,
        )
        assert row_id > 0

        transcriptions = await db.get_transcriptions("s1")
        assert len(transcriptions) == 1
        assert transcriptions[0]["text"] == "Hello world"
        assert transcriptions[0]["speaker_name"] == "Alice"
        assert transcriptions[0]["confidence"] == 0.95

    async def test_transcriptions_ordered_by_timestamp(self, db: Database) -> None:
        await db.upsert_campaign(campaign_id="c1", name="Test")
        await db.create_session("s1", "c1")

        await db.save_transcription("s1", "1", "A", "Second", 2000.0, 0.9)
        await db.save_transcription("s1", "1", "A", "First", 1000.0, 0.9)
        await db.save_transcription("s1", "1", "A", "Third", 3000.0, 0.9)

        transcriptions = await db.get_transcriptions("s1")
        texts = [t["text"] for t in transcriptions]
        assert texts == ["First", "Second", "Third"]

    async def test_empty_transcriptions(self, db: Database) -> None:
        result = await db.get_transcriptions("no-session")
        assert result == []


class TestDatabaseQuestions:
    async def test_save_and_get_questions(self, db: Database) -> None:
        await db.upsert_campaign(campaign_id="c1", name="Test")
        await db.create_session("s1", "c1")

        qid = await db.save_question("s1", "Who is the villain?")
        assert qid > 0

        pending = await db.get_pending_questions("s1")
        assert len(pending) == 1
        assert pending[0]["question"] == "Who is the villain?"
        assert pending[0]["status"] == "pending"

    async def test_answer_question(self, db: Database) -> None:
        await db.upsert_campaign(campaign_id="c1", name="Test")
        await db.create_session("s1", "c1")

        qid = await db.save_question("s1", "Who?")
        await db.answer_question(qid, "The dragon")

        pending = await db.get_pending_questions("s1")
        assert len(pending) == 0


class TestDatabaseConnection:
    async def test_conn_raises_when_not_connected(self, tmp_path) -> None:
        database = Database(str(tmp_path / "nope.db"))
        with pytest.raises(RuntimeError, match="not connected"):
            _ = database.conn

    async def test_connect_and_close(self, tmp_path) -> None:
        database = Database(str(tmp_path / "test.db"))
        await database.connect()
        assert database._conn is not None
        await database.close()
        assert database._conn is None
