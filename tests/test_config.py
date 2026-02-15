"""Tests for the TOML configuration loader."""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

import pytest

from rpg_scribe.config import AppConfig, load_app_config, load_campaign_toml, _apply_defaults_to_config


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


CUSTOM_DEFAULTS_TOML = """\
[listener]
chunk_duration_s = 15.0
vad_aggressiveness = 3

[transcriber]
language = "en"
max_concurrent_requests = 8

[summarizer]
update_interval_s = 60.0
model = "claude-opus-4-20250514"

[web]
host = "0.0.0.0"
port = 9090

[database]
path = "custom.db"
"""


class TestDefaultTomlLoading:
    def test_defaults_from_toml_override_dataclass_defaults(self, tmp_path: Path) -> None:
        """Values from default.toml should override dataclass defaults."""
        defaults_file = tmp_path / "default.toml"
        defaults_file.write_text(CUSTOM_DEFAULTS_TOML)

        config = load_app_config(defaults_path=defaults_file)

        assert config.listener.chunk_duration_s == 15.0
        assert config.listener.vad_aggressiveness == 3
        assert config.transcriber.language == "en"
        assert config.transcriber.max_concurrent_requests == 8
        assert config.summarizer.update_interval_s == 60.0
        assert config.summarizer.model == "claude-opus-4-20250514"
        assert config.web_host == "0.0.0.0"
        assert config.web_port == 9090
        assert config.database_path == "custom.db"

    def test_unset_fields_keep_dataclass_defaults(self, tmp_path: Path) -> None:
        """Fields not in default.toml should retain their dataclass defaults."""
        # Minimal TOML that only sets one field
        defaults_file = tmp_path / "default.toml"
        defaults_file.write_text("[listener]\nchunk_duration_s = 20.0\n")

        config = load_app_config(defaults_path=defaults_file)

        assert config.listener.chunk_duration_s == 20.0
        # These should still be dataclass defaults
        assert config.listener.silence_threshold_s == 1.5
        assert config.transcriber.language == "es"
        assert config.web_port == 8000

    def test_env_vars_override_default_toml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Environment variables should take precedence over default.toml."""
        defaults_file = tmp_path / "default.toml"
        defaults_file.write_text("[web]\nhost = \"0.0.0.0\"\nport = 9090\n")

        monkeypatch.setenv("RPG_SCRIBE_HOST", "10.0.0.1")
        monkeypatch.setenv("RPG_SCRIBE_PORT", "5555")

        config = load_app_config(defaults_path=defaults_file)

        assert config.web_host == "10.0.0.1"
        assert config.web_port == 5555

    def test_without_default_toml_uses_dataclass_defaults(self, tmp_path: Path) -> None:
        """If default.toml doesn't exist, dataclass defaults are used."""
        nonexistent = tmp_path / "nonexistent.toml"

        config = load_app_config(defaults_path=nonexistent)

        assert config.listener.chunk_duration_s == 10.0
        assert config.transcriber.language == "es"
        assert config.web_host == "127.0.0.1"
        assert config.web_port == 8000
        assert config.database_path == "rpg_scribe.db"

    def test_default_toml_merged_with_campaign(
        self, tmp_path: Path, campaign_toml_file: Path
    ) -> None:
        """default.toml values are loaded, then campaign overrides language."""
        defaults_file = tmp_path / "default.toml"
        defaults_file.write_text("[transcriber]\nlanguage = \"fr\"\n")

        config = load_app_config(
            campaign_path=campaign_toml_file,
            defaults_path=defaults_file,
        )

        # Campaign language ("en") should override default.toml ("fr")
        assert config.transcriber.language == "en"
        assert config.campaign is not None
        assert config.campaign.name == "Test Campaign"

    def test_malformed_default_toml_does_not_crash(self, tmp_path: Path) -> None:
        """A malformed default.toml should log a warning but not crash."""
        defaults_file = tmp_path / "default.toml"
        defaults_file.write_bytes(b"this is not valid toml {{{")

        # Should not raise
        config = load_app_config(defaults_path=defaults_file)
        # Falls back to dataclass defaults
        assert config.listener.chunk_duration_s == 10.0


class TestImportCampaignScript:
    def test_generate_toml_basic(self) -> None:
        from scripts.import_campaign import generate_toml

        result = generate_toml(
            name="Test Campaign",
            game_system="D&D 5e",
            language="en",
        )
        assert 'name = "Test Campaign"' in result
        assert 'game_system = "D&D 5e"' in result
        assert 'language = "en"' in result
        assert 'id = "test-campaign"' in result

    def test_generate_toml_with_players_and_npcs(self) -> None:
        from scripts.import_campaign import generate_toml

        result = generate_toml(
            name="My Game",
            game_system="Pathfinder",
            players=[
                {
                    "discord_id": "111",
                    "discord_name": "Alice",
                    "character_name": "Aria",
                    "character_description": "Elf ranger",
                },
            ],
            npcs=[{"name": "Gandalf", "description": "A wizard"}],
        )
        assert "[[campaign.players]]" in result
        assert 'discord_id = "111"' in result
        assert 'character_name = "Aria"' in result
        assert "[[campaign.npcs]]" in result
        assert 'name = "Gandalf"' in result

    def test_generate_toml_is_valid_toml(self) -> None:
        """The generated TOML should be parseable."""
        from scripts.import_campaign import generate_toml

        result = generate_toml(
            name="Parseable Campaign",
            game_system="OSR",
            description="A test.",
            dm_discord_id="999",
            players=[
                {
                    "discord_id": "111",
                    "discord_name": "Bob",
                    "character_name": "Brom",
                    "character_description": "",
                }
            ],
            npcs=[{"name": "NPC1", "description": ""}],
            custom_instructions="Be concise.",
        )
        import tomllib

        data = tomllib.loads(result)
        assert data["campaign"]["name"] == "Parseable Campaign"
        assert data["campaign"]["game_system"] == "OSR"
        assert len(data["campaign"]["players"]) == 1

    def test_cli_mode_writes_file(self, tmp_path: Path) -> None:
        from scripts.import_campaign import cli_mode

        output_path = tmp_path / "test.toml"
        args = argparse.Namespace(
            name="CLI Campaign",
            system="Fate",
            language="es",
            description="Test desc",
            dm_id="",
            output=str(output_path),
        )
        cli_mode(args)

        assert output_path.exists()
        content = output_path.read_text()
        assert 'name = "CLI Campaign"' in content

    def test_slugify(self) -> None:
        from scripts.import_campaign import _slugify

        assert _slugify("My Cool Campaign!") == "my-cool-campaign"
        assert _slugify("  spaces  ") == "spaces"
        assert _slugify("D&D 5e Game") == "d-d-5e-game"
