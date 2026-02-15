"""Tests for the TOML configuration loader."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from rpg_scribe.config import AppConfig, load_app_config, load_campaign_toml


SAMPLE_CAMPAIGN_TOML = """\
[campaign]
id = "test-campaign"
name = "Test Campaign"
game_system = "D&D 5e"
language = "en"
description = "A test campaign for unit tests."
campaign_summary = "Previously the party defeated a dragon."
locations = ["Tavern", "Dungeon"]

[campaign.dm]
discord_id = "999"

[[campaign.players]]
discord_id = "111"
discord_name = "Alice"
character_name = "Aria"
character_description = "Elf ranger"

[[campaign.players]]
discord_id = "222"
discord_name = "Bob"
character_name = "Brom"

[[campaign.npcs]]
name = "Gandalf"
description = "A mysterious wizard"

[campaign.custom_instructions]
text = "Keep it serious."
"""


@pytest.fixture
def campaign_toml_file(tmp_path: Path) -> Path:
    p = tmp_path / "campaign.toml"
    p.write_text(SAMPLE_CAMPAIGN_TOML)
    return p


class TestLoadCampaignToml:
    def test_basic_fields(self, campaign_toml_file: Path) -> None:
        ctx = load_campaign_toml(campaign_toml_file)
        assert ctx.campaign_id == "test-campaign"
        assert ctx.name == "Test Campaign"
        assert ctx.game_system == "D&D 5e"
        assert ctx.language == "en"
        assert "test campaign" in ctx.description.lower()

    def test_players_loaded(self, campaign_toml_file: Path) -> None:
        ctx = load_campaign_toml(campaign_toml_file)
        assert len(ctx.players) == 2
        assert ctx.players[0].discord_id == "111"
        assert ctx.players[0].character_name == "Aria"
        assert ctx.players[1].character_description == ""

    def test_speaker_map_built(self, campaign_toml_file: Path) -> None:
        ctx = load_campaign_toml(campaign_toml_file)
        assert ctx.speaker_map == {"111": "Aria", "222": "Brom"}

    def test_npcs_loaded(self, campaign_toml_file: Path) -> None:
        ctx = load_campaign_toml(campaign_toml_file)
        assert len(ctx.known_npcs) == 1
        assert ctx.known_npcs[0].name == "Gandalf"

    def test_dm_speaker_id(self, campaign_toml_file: Path) -> None:
        ctx = load_campaign_toml(campaign_toml_file)
        assert ctx.dm_speaker_id == "999"

    def test_custom_instructions(self, campaign_toml_file: Path) -> None:
        ctx = load_campaign_toml(campaign_toml_file)
        assert "serious" in ctx.custom_instructions.lower()

    def test_locations(self, campaign_toml_file: Path) -> None:
        ctx = load_campaign_toml(campaign_toml_file)
        assert ctx.locations == ["Tavern", "Dungeon"]

    def test_campaign_summary_preserved(self, campaign_toml_file: Path) -> None:
        ctx = load_campaign_toml(campaign_toml_file)
        assert "dragon" in ctx.campaign_summary.lower()

    def test_fallback_campaign_id_from_filename(self, tmp_path: Path) -> None:
        """When no id is set, the filename stem should be used."""
        p = tmp_path / "my-awesome-campaign.toml"
        p.write_text("[campaign]\nname = 'Test'\ngame_system = 'OSR'\n")
        ctx = load_campaign_toml(p)
        assert ctx.campaign_id == "my-awesome-campaign"


class TestLoadAppConfig:
    def test_defaults(self) -> None:
        config = load_app_config()
        assert isinstance(config, AppConfig)
        assert config.web_host == "127.0.0.1"
        assert config.web_port == 8000
        assert config.campaign is None

    def test_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")
        monkeypatch.setenv("RPG_SCRIBE_PORT", "9000")
        monkeypatch.setenv("DISCORD_SUMMARY_CHANNEL_ID", "12345")
        config = load_app_config()
        assert config.discord_bot_token == "test-token"
        assert config.web_port == 9000
        assert config.discord_summary_channel_id == "12345"

    def test_with_campaign_file(self, campaign_toml_file: Path) -> None:
        config = load_app_config(campaign_path=campaign_toml_file)
        assert config.campaign is not None
        assert config.campaign.name == "Test Campaign"
        # Language should propagate to transcriber
        assert config.transcriber.language == "en"
        # Prompt hint should contain character names
        assert "Aria" in config.transcriber.prompt_hint
        assert "Brom" in config.transcriber.prompt_hint
