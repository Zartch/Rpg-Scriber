"""Campaign configuration loader from TOML files."""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from rpg_scribe.core.models import (
    CampaignContext,
    ListenerConfig,
    NPCInfo,
    PlayerInfo,
    SummarizerConfig,
    TranscriberConfig,
)

logger = logging.getLogger(__name__)

# Standard location for the default config file
_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "default.toml"


@dataclass
class AppConfig:
    """Top-level application configuration."""

    # Tokens (loaded from env vars)
    discord_bot_token: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""

    # Web server
    web_host: str = "127.0.0.1"
    web_port: int = 8000

    # Component configs
    listener: ListenerConfig = field(default_factory=ListenerConfig)
    transcriber: TranscriberConfig = field(default_factory=TranscriberConfig)
    summarizer: SummarizerConfig = field(default_factory=SummarizerConfig)

    # Campaign
    campaign: CampaignContext | None = None

    # Database
    database_path: str = "rpg_scribe.db"

    # Discord summary channel
    discord_summary_channel_id: str = ""


def _load_toml(path: Path) -> dict[str, Any]:
    """Load a TOML file and return the parsed dict."""
    with open(path, "rb") as f:
        return tomllib.load(f)


def _apply_defaults_to_config(config: AppConfig, defaults: dict[str, Any]) -> None:
    """Apply values from a default.toml dict onto an AppConfig.

    Only sets values that are present in the TOML; dataclass defaults
    remain for any keys not specified.
    """
    # Listener
    listener_data = defaults.get("listener", {})
    for key, value in listener_data.items():
        if hasattr(config.listener, key):
            setattr(config.listener, key, value)

    # Transcriber
    transcriber_data = defaults.get("transcriber", {})
    for key, value in transcriber_data.items():
        if hasattr(config.transcriber, key):
            setattr(config.transcriber, key, value)

    # Summarizer
    summarizer_data = defaults.get("summarizer", {})
    for key, value in summarizer_data.items():
        if hasattr(config.summarizer, key):
            setattr(config.summarizer, key, value)

    # Web
    web_data = defaults.get("web", {})
    if "host" in web_data:
        config.web_host = web_data["host"]
    if "port" in web_data:
        config.web_port = web_data["port"]

    # Database
    db_data = defaults.get("database", {})
    if "path" in db_data:
        config.database_path = db_data["path"]


def load_campaign_toml(path: str | Path) -> CampaignContext:
    """Load a CampaignContext from a TOML campaign file.

    The file format follows the schema in the architecture document
    (section 10).
    """
    path = Path(path)
    with open(path, "rb") as f:
        data = tomllib.load(f)

    campaign_data: dict[str, Any] = data.get("campaign", data)

    # Players
    players: list[PlayerInfo] = []
    speaker_map: dict[str, str] = {}
    for p in campaign_data.get("players", []):
        player = PlayerInfo(
            discord_id=str(p["discord_id"]),
            discord_name=p["discord_name"],
            character_name=p["character_name"],
            character_description=p.get("character_description", ""),
        )
        players.append(player)
        speaker_map[player.discord_id] = player.character_name

    # NPCs
    npcs: list[NPCInfo] = []
    for n in campaign_data.get("npcs", []):
        npcs.append(NPCInfo(name=n["name"], description=n.get("description", "")))

    # DM
    dm_data = campaign_data.get("dm", {})
    dm_speaker_id = str(dm_data.get("discord_id", ""))

    # Custom instructions
    custom = campaign_data.get("custom_instructions", {})
    custom_text = custom.get("text", "") if isinstance(custom, dict) else str(custom)

    return CampaignContext(
        campaign_id=campaign_data.get("id", path.stem),
        name=campaign_data.get("name", ""),
        game_system=campaign_data.get("game_system", ""),
        language=campaign_data.get("language", "es"),
        description=campaign_data.get("description", "").strip(),
        players=players,
        known_npcs=npcs,
        locations=campaign_data.get("locations", []),
        campaign_summary=campaign_data.get("campaign_summary", ""),
        speaker_map=speaker_map,
        dm_speaker_id=dm_speaker_id,
        custom_instructions=custom_text.strip(),
    )


def load_app_config(
    campaign_path: str | Path | None = None,
    defaults_path: str | Path | None = None,
) -> AppConfig:
    """Build an AppConfig from default.toml, env vars, and an optional campaign file.

    Loading order (later wins):
      1. Dataclass defaults (hardcoded in models.py)
      2. config/default.toml (if it exists)
      3. Environment variables
      4. Campaign TOML (language propagation)
    """
    config = AppConfig()

    # 1. Load default.toml if available
    default_path = Path(defaults_path) if defaults_path else _DEFAULT_CONFIG_PATH
    if default_path.is_file():
        try:
            defaults = _load_toml(default_path)
            _apply_defaults_to_config(config, defaults)
            logger.debug("Loaded default config from %s", default_path)
        except Exception as exc:
            logger.warning("Failed to load default config %s: %s", default_path, exc)

    # 2. Environment variables override defaults
    config.discord_bot_token = os.environ.get("DISCORD_BOT_TOKEN", config.discord_bot_token)
    config.openai_api_key = os.environ.get("OPENAI_API_KEY", config.openai_api_key)
    config.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", config.anthropic_api_key)
    config.web_host = os.environ.get("RPG_SCRIBE_HOST", config.web_host)
    config.web_port = int(os.environ.get("RPG_SCRIBE_PORT", str(config.web_port)))
    config.database_path = os.environ.get("RPG_SCRIBE_DB", config.database_path)
    config.discord_summary_channel_id = os.environ.get(
        "DISCORD_SUMMARY_CHANNEL_ID", config.discord_summary_channel_id
    )

    # 3. Campaign file
    if campaign_path is not None:
        config.campaign = load_campaign_toml(campaign_path)
        # Propagate language to transcriber
        if config.campaign:
            config.transcriber.language = config.campaign.language
            # Build prompt hint from player/character names
            names = [p.character_name for p in config.campaign.players]
            if names:
                config.transcriber.prompt_hint = (
                    "Nombres esperados: " + ", ".join(names)
                )

    return config
