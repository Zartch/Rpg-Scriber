#!/usr/bin/env python3
"""Generate a campaign TOML configuration file for RPG Scribe.

Supports two modes:

  Interactive (default):
    python scripts/import_campaign.py

  Non-interactive (CLI arguments):
    python scripts/import_campaign.py --name "My Campaign" --system "D&D 5e" \\
        --language en --output config/campaigns/my_campaign.toml
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def _slugify(name: str) -> str:
    """Convert a campaign name to a safe filename slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-") or "campaign"


def _prompt(label: str, default: str = "") -> str:
    """Prompt the user for input with an optional default."""
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


def _prompt_players_interactive() -> list[dict[str, str]]:
    """Interactively collect player information."""
    players: list[dict[str, str]] = []
    print("\n--- Players (leave discord_id empty to finish) ---")
    while True:
        discord_id = input("  Discord ID (blank to stop): ").strip()
        if not discord_id:
            break
        discord_name = input("  Discord display name: ").strip()
        character_name = input("  Character name: ").strip()
        character_description = input("  Character description (optional): ").strip()
        players.append({
            "discord_id": discord_id,
            "discord_name": discord_name,
            "character_name": character_name,
            "character_description": character_description,
        })
    return players


def _prompt_npcs_interactive() -> list[dict[str, str]]:
    """Interactively collect initial NPC information."""
    npcs: list[dict[str, str]] = []
    print("\n--- Initial NPCs (leave name empty to finish) ---")
    while True:
        name = input("  NPC name (blank to stop): ").strip()
        if not name:
            break
        description = input("  NPC description (optional): ").strip()
        npcs.append({"name": name, "description": description})
    return npcs


def _escape_toml_string(s: str) -> str:
    """Escape a string for use as a TOML basic string value."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def generate_toml(
    *,
    name: str,
    game_system: str,
    language: str = "es",
    description: str = "",
    dm_discord_id: str = "",
    players: list[dict[str, str]] | None = None,
    npcs: list[dict[str, str]] | None = None,
    custom_instructions: str = "",
) -> str:
    """Generate the TOML content for a campaign configuration file."""
    campaign_id = _slugify(name)
    players = players or []
    npcs = npcs or []

    lines: list[str] = []
    lines.append("# RPG Scribe campaign configuration")
    lines.append(f"# Generated for: {name}")
    lines.append("")
    lines.append("[campaign]")
    lines.append(f'id = "{_escape_toml_string(campaign_id)}"')
    lines.append(f'name = "{_escape_toml_string(name)}"')
    lines.append(f'game_system = "{_escape_toml_string(game_system)}"')
    lines.append(f'language = "{_escape_toml_string(language)}"')
    if description:
        lines.append(f'description = """\n{description}\n"""')
    else:
        lines.append('description = ""')
    lines.append('campaign_summary = ""')
    lines.append("locations = []")

    if dm_discord_id:
        lines.append("")
        lines.append("[campaign.dm]")
        lines.append(f'discord_id = "{_escape_toml_string(dm_discord_id)}"')

    for p in players:
        lines.append("")
        lines.append("[[campaign.players]]")
        lines.append(f'discord_id = "{_escape_toml_string(p["discord_id"])}"')
        lines.append(f'discord_name = "{_escape_toml_string(p["discord_name"])}"')
        lines.append(f'character_name = "{_escape_toml_string(p["character_name"])}"')
        if p.get("character_description"):
            lines.append(
                f'character_description = "{_escape_toml_string(p["character_description"])}"'
            )

    for n in npcs:
        lines.append("")
        lines.append("[[campaign.npcs]]")
        lines.append(f'name = "{_escape_toml_string(n["name"])}"')
        if n.get("description"):
            lines.append(f'description = "{_escape_toml_string(n["description"])}"')

    if custom_instructions:
        lines.append("")
        lines.append("[campaign.custom_instructions]")
        lines.append(f'text = """\n{custom_instructions}\n"""')

    lines.append("")  # trailing newline
    return "\n".join(lines)


def interactive_mode() -> None:
    """Run the interactive campaign import wizard."""
    print("=== RPG Scribe Campaign Import ===\n")

    name = _prompt("Campaign name")
    if not name:
        print("Error: campaign name is required.", file=sys.stderr)
        sys.exit(1)

    game_system = _prompt("Game system (e.g. D&D 5e, Pathfinder)")
    language = _prompt("Language (ISO 639-1)", "es")
    description = _prompt("Campaign description (optional)")
    dm_discord_id = _prompt("DM Discord ID (optional)")

    players = _prompt_players_interactive()
    npcs = _prompt_npcs_interactive()

    custom_instructions = _prompt("Custom instructions for the AI (optional)")

    toml_content = generate_toml(
        name=name,
        game_system=game_system,
        language=language,
        description=description,
        dm_discord_id=dm_discord_id,
        players=players,
        npcs=npcs,
        custom_instructions=custom_instructions,
    )

    slug = _slugify(name)
    default_output = f"config/campaigns/{slug}.toml"
    output_path = _prompt("Output file", default_output)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(toml_content, encoding="utf-8")
    print(f"\nCampaign file written to: {path}")


def cli_mode(args: argparse.Namespace) -> None:
    """Run in non-interactive mode from CLI arguments."""
    toml_content = generate_toml(
        name=args.name,
        game_system=args.system or "",
        language=args.language,
        description=args.description or "",
        dm_discord_id=args.dm_id or "",
    )

    if args.output:
        path = Path(args.output)
    else:
        slug = _slugify(args.name)
        path = Path(f"config/campaigns/{slug}.toml")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(toml_content, encoding="utf-8")
    print(f"Campaign file written to: {path}")


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        description="Generate a campaign TOML configuration file for RPG Scribe."
    )
    parser.add_argument("--name", help="Campaign name (required for non-interactive mode)")
    parser.add_argument("--system", help="Game system (e.g. 'D&D 5e')")
    parser.add_argument("--language", default="es", help="Language code (default: es)")
    parser.add_argument("--description", help="Campaign description")
    parser.add_argument("--dm-id", help="DM Discord ID")
    parser.add_argument("--output", "-o", help="Output file path")
    return parser


def main() -> None:
    """Entry point."""
    parser = build_parser()
    args = parser.parse_args()

    if args.name:
        # Non-interactive mode
        cli_mode(args)
    else:
        # Interactive mode
        interactive_mode()


if __name__ == "__main__":
    main()
