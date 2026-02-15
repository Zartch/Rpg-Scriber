"""Campaign configuration loader from TOML files."""

from __future__ import annotations

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


def load_app_config(campaign_path: str | Path | None = None) -> AppConfig:
    """Build an AppConfig from environment variables and an optional campaign file."""
    config = AppConfig(
        discord_bot_token=os.environ.get("DISCORD_BOT_TOKEN", ""),
        openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        web_host=os.environ.get("RPG_SCRIBE_HOST", "127.0.0.1"),
        web_port=int(os.environ.get("RPG_SCRIBE_PORT", "8000")),
        database_path=os.environ.get("RPG_SCRIBE_DB", "rpg_scribe.db"),
        discord_summary_channel_id=os.environ.get("DISCORD_SUMMARY_CHANNEL_ID", ""),
    )

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
