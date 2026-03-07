"""Campaign configuration loader from TOML files."""

from __future__ import annotations

import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from rpg_scribe.core.models import (
    CharacterRelationshipInfo,
    CampaignContext,
    EntityInfo,
    ListenerConfig,
    LocationInfo,
    NPCInfo,
    PlayerInfo,
    RelationshipTypeInfo,
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
    # Web UI limits
    web_transcriptions_max_items: int = 5000
    web_feed_max_items: int = 1000
    # Component configs
    listener: ListenerConfig = field(default_factory=ListenerConfig)
    transcriber: TranscriberConfig = field(default_factory=TranscriberConfig)
    summarizer: SummarizerConfig = field(default_factory=SummarizerConfig)

    # Campaign
    campaign: CampaignContext | None = None
    campaign_path: str = ""

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
    if "transcriptions_max_items" in web_data:
        config.web_transcriptions_max_items = int(web_data["transcriptions_max_items"])
    if "feed_max_items" in web_data:
        config.web_feed_max_items = int(web_data["feed_max_items"])
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

    # Locations — supports both legacy list[str] and new [[locations]] table format
    locations: list[LocationInfo] = []
    for loc in campaign_data.get("locations", []):
        if isinstance(loc, str):
            locations.append(LocationInfo(name=loc))
        elif isinstance(loc, dict):
            locations.append(
                LocationInfo(name=loc["name"], description=loc.get("description", ""))
            )

    entities: list[EntityInfo] = []
    for entity in campaign_data.get("entities", []):
        if not isinstance(entity, dict):
            continue
        name = str(entity.get("name", "")).strip()
        if not name:
            continue
        entities.append(
            EntityInfo(
                name=name,
                entity_type=str(entity.get("entity_type", "group") or "group").strip() or "group",
                description=str(entity.get("description", "")).strip(),
            )
        )

    # Relationship types (thesaurus)
    relation_types: list[RelationshipTypeInfo] = []
    for rt in campaign_data.get("relationship_types", []):
        label = str(rt.get("label", rt.get("key", ""))).strip()
        key = str(rt.get("key", "")).strip()
        if not label and not key:
            continue
        if not key:
            key = label
        relation_types.append(
            RelationshipTypeInfo(
                key=key,
                label=label or key,
                category=str(rt.get("category", "general") or "general"),
            )
        )

    # Character relationships
    relationships: list[CharacterRelationshipInfo] = []
    for rel in campaign_data.get("relationships", []):
        source_key = str(rel.get("source_key", "")).strip()
        target_key = str(rel.get("target_key", "")).strip()
        relation_type_key = str(rel.get("relation_type_key", "")).strip()
        relation_type_label = str(rel.get("relation_type_label", "")).strip()
        if not source_key or not target_key:
            continue
        if not relation_type_key and not relation_type_label:
            continue
        relationships.append(
            CharacterRelationshipInfo(
                source_key=source_key,
                target_key=target_key,
                relation_type_key=relation_type_key or relation_type_label,
                relation_type_label=relation_type_label or relation_type_key,
                notes=str(rel.get("notes", "")).strip(),
            )
        )

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
        entities=entities,
        relation_types=relation_types,
        relationships=relationships,
        locations=locations,
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
    config.web_transcriptions_max_items = int(
        os.environ.get(
            "RPG_SCRIBE_WEB_TRANSCRIPTIONS_MAX_ITEMS",
            str(config.web_transcriptions_max_items),
        )
    )
    config.web_feed_max_items = int(
        os.environ.get(
            "RPG_SCRIBE_WEB_FEED_MAX_ITEMS",
            str(config.web_feed_max_items),
        )
    )
    config.database_path = os.environ.get("RPG_SCRIBE_DB", config.database_path)
    config.discord_summary_channel_id = os.environ.get(
        "DISCORD_SUMMARY_CHANNEL_ID", config.discord_summary_channel_id
    )
    # Summarizer configuration via env:
    # - RPG_SCRIBE_SUMMARIZER_MODEL controls the Claude model ID.
    # - RPG_SCRIBE_SUMMARIZER_MAX_TOKENS controls max output tokens per call.
    # - RPG_SCRIBE_SUMMARIZER_MAX_INPUT_CHARS controls input text budget in chars
    #   (project uses ~4 chars/token estimate).
    config.summarizer.model = os.environ.get(
        "RPG_SCRIBE_SUMMARIZER_MODEL", config.summarizer.model
    )
    summarizer_max_tokens = os.environ.get("RPG_SCRIBE_SUMMARIZER_MAX_TOKENS")
    if summarizer_max_tokens is not None:
        config.summarizer.max_tokens = int(summarizer_max_tokens)
    summarizer_max_input_chars = os.environ.get("RPG_SCRIBE_SUMMARIZER_MAX_INPUT_CHARS")
    if summarizer_max_input_chars is not None:
        config.summarizer.max_input_chars = int(summarizer_max_input_chars)

    # 3. Campaign file
    if campaign_path is not None:
        config.campaign = load_campaign_toml(campaign_path)
        config.campaign_path = str(Path(campaign_path).resolve())
        # Propagate language to transcriber
        if config.campaign:
            config.transcriber.language = config.campaign.language

    return config


def _escape_toml_string(value: str) -> str:
    """Escape a string for use as a TOML basic string."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _render_toml_text_field(key: str, value: str) -> str:
    """Render a text field, using multiline TOML for long values."""
    text = value.strip()
    if not text:
        return f'{key} = ""'
    if "\n" in text:
        return f'{key} = """\n{text}\n"""'
    return f'{key} = "{_escape_toml_string(text)}"'


def campaign_to_toml(campaign: CampaignContext) -> str:
    """Serialize CampaignContext to campaign TOML format."""
    lines: list[str] = []
    lines.append("[campaign]")
    lines.append(f'id = "{_escape_toml_string(campaign.campaign_id)}"')
    lines.append(f'name = "{_escape_toml_string(campaign.name)}"')
    lines.append(f'game_system = "{_escape_toml_string(campaign.game_system)}"')
    lines.append(f'language = "{_escape_toml_string(campaign.language)}"')
    lines.append(_render_toml_text_field("description", campaign.description))
    lines.append(_render_toml_text_field("campaign_summary", campaign.campaign_summary))

    for loc in campaign.locations:
        if not loc.name.strip():
            continue
        lines.append("")
        lines.append("[[campaign.locations]]")
        lines.append(f'name = "{_escape_toml_string(loc.name)}"')
        if loc.description.strip():
            lines.append(f'description = "{_escape_toml_string(loc.description)}"')

    if campaign.dm_speaker_id:
        lines.append("")
        lines.append("[campaign.dm]")
        lines.append(f'discord_id = "{_escape_toml_string(campaign.dm_speaker_id)}"')

    for player in campaign.players:
        lines.append("")
        lines.append("[[campaign.players]]")
        lines.append(f'discord_id = "{_escape_toml_string(player.discord_id)}"')
        lines.append(f'discord_name = "{_escape_toml_string(player.discord_name)}"')
        lines.append(f'character_name = "{_escape_toml_string(player.character_name)}"')
        if player.character_description.strip():
            lines.append(
                f'character_description = "{_escape_toml_string(player.character_description)}"'
            )

    for npc in campaign.known_npcs:
        lines.append("")
        lines.append("[[campaign.npcs]]")
        lines.append(f'name = "{_escape_toml_string(npc.name)}"')
        if npc.description.strip():
            lines.append(f'description = "{_escape_toml_string(npc.description)}"')

    for entity in campaign.entities:
        if not entity.name.strip():
            continue
        lines.append("")
        lines.append("[[campaign.entities]]")
        lines.append(f'name = "{_escape_toml_string(entity.name)}"')
        lines.append(
            f'entity_type = "{_escape_toml_string(entity.entity_type.strip() or "group")}"'
        )
        if entity.description.strip():
            lines.append(f'description = "{_escape_toml_string(entity.description)}"')

    for relation_type in campaign.relation_types:
        lines.append("")
        lines.append("[[campaign.relationship_types]]")
        lines.append(f'key = "{_escape_toml_string(relation_type.key)}"')
        lines.append(f'label = "{_escape_toml_string(relation_type.label)}"')
        if relation_type.category.strip():
            lines.append(f'category = "{_escape_toml_string(relation_type.category)}"')

    for relation in campaign.relationships:
        lines.append("")
        lines.append("[[campaign.relationships]]")
        lines.append(f'source_key = "{_escape_toml_string(relation.source_key)}"')
        lines.append(f'target_key = "{_escape_toml_string(relation.target_key)}"')
        lines.append(f'relation_type_key = "{_escape_toml_string(relation.relation_type_key)}"')
        lines.append(f'relation_type_label = "{_escape_toml_string(relation.relation_type_label)}"')
        if relation.notes.strip():
            lines.append(_render_toml_text_field("notes", relation.notes))

    if campaign.custom_instructions.strip():
        lines.append("")
        lines.append("[campaign.custom_instructions]")
        lines.append(_render_toml_text_field("text", campaign.custom_instructions))

    lines.append("")
    return "\n".join(lines)


def save_campaign_toml(campaign: CampaignContext, path: str | Path) -> None:
    """Persist CampaignContext to a TOML file path."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(campaign_to_toml(campaign), encoding="utf-8")





