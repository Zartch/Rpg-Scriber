"""Discord bot setup for RPG Scribe."""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

from rpg_scribe.core.database import Database
from rpg_scribe.core.event_bus import EventBus
from rpg_scribe.core.models import ListenerConfig
from rpg_scribe.discord_bot.commands import ScribeCog

logger = logging.getLogger(__name__)


def _ensure_opus() -> None:
    """Load the opus codec if it isn't loaded already.

    discord.py ships the DLL on Windows but the automatic loading can
    fail depending on how the package was installed.  We load it
    explicitly so voice connections always work.
    """
    if discord.opus.is_loaded():
        return
    try:
        discord.opus.load_opus("opus")
    except OSError:
        import os
        import sys

        _basedir = os.path.dirname(os.path.abspath(discord.opus.__file__))
        _bitness = "x64" if sys.maxsize > 2**32 else "x86"
        _path = os.path.join(_basedir, "bin", f"libopus-0.{_bitness}.dll")
        try:
            discord.opus.load_opus(_path)
        except Exception as exc:
            logger.warning("No se pudo cargar opus: %s", exc)
            return
    logger.info("Opus cargado correctamente (is_loaded=%s)", discord.opus.is_loaded())


def create_bot(
    event_bus: EventBus,
    listener_config: ListenerConfig | None = None,
    database: Database | None = None,
) -> commands.Bot:
    """Create and configure the Discord bot with slash commands."""
    _ensure_opus()

    intents = discord.Intents.default()
    intents.message_content = True
    intents.voice_states = True

    bot = commands.Bot(
        command_prefix="!",
        intents=intents,
        description="RPG Scribe – live session transcriber and summarizer.",
    )

    config = listener_config or ListenerConfig()

    @bot.event
    async def on_ready() -> None:
        logger.info("Bot ready as %s (id=%s)", bot.user, bot.user.id if bot.user else "?")
        await bot.add_cog(ScribeCog(bot, event_bus, config, database=database))
        try:
            synced = await bot.tree.sync()
            logger.info("Synced %d slash commands", len(synced))
        except Exception:
            logger.exception("Failed to sync slash commands")

    return bot
