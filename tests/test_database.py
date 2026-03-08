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


class TestDatabaseNPCs:
    async def test_save_and_get_npcs(self, db: Database) -> None:
        await db.upsert_campaign(campaign_id="c1", name="Test")
        await db.save_npc("c1", "Tabernero", "Dueño de la taberna", "s1")
        npcs = await db.get_npcs("c1")
        assert len(npcs) == 1
        assert npcs[0]["name"] == "Tabernero"
        assert npcs[0]["description"] == "Dueño de la taberna"
        assert npcs[0]["first_seen_session"] == "s1"

    async def test_get_npcs_empty(self, db: Database) -> None:
        npcs = await db.get_npcs("nonexistent")
        assert npcs == []

    async def test_npc_exists_true(self, db: Database) -> None:
        await db.upsert_campaign(campaign_id="c1", name="Test")
        await db.save_npc("c1", "Tabernero", "Dueño", "s1")
        assert await db.npc_exists("c1", "Tabernero") is True

    async def test_npc_exists_false(self, db: Database) -> None:
        await db.upsert_campaign(campaign_id="c1", name="Test")
        assert await db.npc_exists("c1", "Desconocido") is False

    async def test_multiple_npcs_ordered_by_name(self, db: Database) -> None:
        await db.upsert_campaign(campaign_id="c1", name="Test")
        await db.save_npc("c1", "Zara", "Maga", "s1")
        await db.save_npc("c1", "Aldric", "Guerrero", "s1")
        await db.save_npc("c1", "Marco", "Mercader", "s2")
        npcs = await db.get_npcs("c1")
        assert len(npcs) == 3
        names = [n["name"] for n in npcs]
        assert names == ["Aldric", "Marco", "Zara"]

    async def test_npcs_isolated_by_campaign(self, db: Database) -> None:
        await db.upsert_campaign(campaign_id="c1", name="Campaign 1")
        await db.upsert_campaign(campaign_id="c2", name="Campaign 2")
        await db.save_npc("c1", "NPC1", "Desc1", "s1")
        await db.save_npc("c2", "NPC2", "Desc2", "s1")
        assert len(await db.get_npcs("c1")) == 1
        assert len(await db.get_npcs("c2")) == 1
        assert await db.npc_exists("c1", "NPC2") is False

    async def test_update_npc(self, db: Database) -> None:
        await db.upsert_campaign(campaign_id="c1", name="Test")
        await db.save_npc("c1", "Tabernero", "Dueño", "s1")
        npcs = await db.get_npcs("c1")
        npc_id = npcs[0]["id"]
        await db.update_npc(npc_id, description="Dueño de la taberna del pueblo")
        npcs = await db.get_npcs("c1")
        assert npcs[0]["description"] == "Dueño de la taberna del pueblo"

    async def test_update_npc_name(self, db: Database) -> None:
        await db.upsert_campaign(campaign_id="c1", name="Test")
        await db.save_npc("c1", "OldName", "desc")
        npcs = await db.get_npcs("c1")
        npc_id = npcs[0]["id"]
        await db.update_npc(npc_id, name="NewName")
        npcs = await db.get_npcs("c1")
        assert npcs[0]["name"] == "NewName"


class TestDatabasePlayers:
    async def test_save_and_get_players(self, db: Database) -> None:
        await db.upsert_campaign(campaign_id="c1", name="Test")
        pid = await db.save_player("c1", "111", "Juan", "Rodrigo", "Guerrero")
        assert pid  # UUID string
        players = await db.get_players("c1")
        assert len(players) == 1
        assert players[0]["discord_name"] == "Juan"
        assert players[0]["character_name"] == "Rodrigo"
        assert players[0]["character_description"] == "Guerrero"

    async def test_get_players_empty(self, db: Database) -> None:
        players = await db.get_players("nonexistent")
        assert players == []

    async def test_player_exists(self, db: Database) -> None:
        await db.upsert_campaign(campaign_id="c1", name="Test")
        await db.save_player("c1", "111", "Juan", "Rodrigo", "")
        assert await db.player_exists("c1", "111") is True
        assert await db.player_exists("c1", "999") is False

    async def test_update_player(self, db: Database) -> None:
        await db.upsert_campaign(campaign_id="c1", name="Test")
        pid = await db.save_player("c1", "111", "Juan", "Rodrigo", "Guerrero")
        await db.update_player(pid, character_name="Rodrigo el Valiente")
        players = await db.get_players("c1")
        assert players[0]["character_name"] == "Rodrigo el Valiente"
        # Other fields unchanged
        assert players[0]["discord_name"] == "Juan"
        assert players[0]["character_description"] == "Guerrero"

    async def test_update_player_multiple_fields(self, db: Database) -> None:
        await db.upsert_campaign(campaign_id="c1", name="Test")
        pid = await db.save_player("c1", "111", "Juan", "Rodrigo", "Guerrero")
        await db.update_player(
            pid, discord_name="JuanUpdated", character_description="Mago",
        )
        players = await db.get_players("c1")
        assert players[0]["discord_name"] == "JuanUpdated"
        assert players[0]["character_description"] == "Mago"

    async def test_players_isolated_by_campaign(self, db: Database) -> None:
        await db.upsert_campaign(campaign_id="c1", name="Campaign 1")
        await db.upsert_campaign(campaign_id="c2", name="Campaign 2")
        await db.save_player("c1", "111", "Juan", "Rodrigo", "")
        await db.save_player("c2", "222", "Maria", "Aelar", "")
        assert len(await db.get_players("c1")) == 1
        assert len(await db.get_players("c2")) == 1


class TestDatabaseEntities:
    async def test_save_and_get_entities(self, db: Database) -> None:
        await db.upsert_campaign(campaign_id="c1", name="Test")
        await db.save_entity("c1", "Hermandad", "clan", "Sociedad secreta", "s1")
        entities = await db.get_entities("c1")
        assert len(entities) == 1
        assert entities[0]["name"] == "Hermandad"
        assert entities[0]["entity_type"] == "clan"
        assert entities[0]["description"] == "Sociedad secreta"

    async def test_entity_exists(self, db: Database) -> None:
        await db.upsert_campaign(campaign_id="c1", name="Test")
        await db.save_entity("c1", "Consorcio", "corporacion", "")
        assert await db.entity_exists("c1", "consorcio") is True
        assert await db.entity_exists("c1", "otra") is False

    async def test_update_entity(self, db: Database) -> None:
        await db.upsert_campaign(campaign_id="c1", name="Test")
        await db.save_entity("c1", "Viejo", "grupo", "desc")
        entities = await db.get_entities("c1")
        entity_id = entities[0]["id"]
        await db.update_entity(entity_id, name="Nuevo", entity_type="faccion")
        entities = await db.get_entities("c1")
        assert entities[0]["name"] == "Nuevo"
        assert entities[0]["entity_type"] == "faccion"


class TestDatabaseMerges:
    async def test_merge_npcs_hides_child_and_rewrites_relationships(self, db: Database) -> None:
        await db.upsert_campaign(campaign_id="c1", name="Test")
        await db.save_npc("c1", "Johnny", "Solo")
        await db.save_npc("c1", "J. Silverhand", "Alias")
        await db.save_character_relationship(
            "c1",
            "npc:J. Silverhand",
            "npc:Johnny",
            "ally",
        )

        await db.merge_npcs("c1", "J. Silverhand", "Johnny")

        npcs = await db.get_npcs("c1")
        assert [n["name"] for n in npcs] == ["Johnny"]
        relationships = await db.get_character_relationships("c1")
        assert relationships == []

    async def test_merge_locations_rewrites_legacy_and_short_prefixes(self, db: Database) -> None:
        await db.upsert_campaign(campaign_id="c1", name="Test")
        await db.save_location("c1", "Night City", "City")
        await db.save_location("c1", "Ciudad Nocturna", "ES alias")
        await db.save_character_relationship(
            "c1",
            "location:Ciudad Nocturna",
            "loc:Night City",
            "same place as",
        )

        await db.merge_locations("c1", "Ciudad Nocturna", "Night City")

        locations = await db.get_locations("c1")
        assert [l["name"] for l in locations] == ["Night City"]
        relationships = await db.get_character_relationships("c1")
        assert relationships == []

    async def test_merge_entities_combines_descriptions(self, db: Database) -> None:
        await db.upsert_campaign(campaign_id="c1", name="Test")
        await db.save_entity("c1", "Arasaka", "corp", "Corp")
        await db.save_entity("c1", "Arasaka Corp", "corp", "Alias")

        await db.merge_entities("c1", "Arasaka Corp", "Arasaka")

        entities = await db.get_entities("c1")
        assert len(entities) == 1
        assert entities[0]["name"] == "Arasaka"
        assert "Corp" in entities[0]["description"]
        assert "Alias" in entities[0]["description"]

    async def test_merge_relationship_types_collapses_duplicate_edges(self, db: Database) -> None:
        await db.upsert_campaign(campaign_id="c1", name="Test")
        await db.save_character_relationship("c1", "npc:V", "ent:Afterlife", "allied with")
        await db.save_character_relationship("c1", "npc:V", "ent:Afterlife", "ally")
        types_before = await db.get_relationship_types("c1")
        assert len(types_before) == 2

        await db.merge_relationship_types("c1", "ally", "allied with")

        relationships = await db.get_character_relationships("c1")
        assert len(relationships) == 1
        assert relationships[0]["type_key"] == "allied with"
        types_after = await db.get_relationship_types("c1")
        assert len(types_after) == 1


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
