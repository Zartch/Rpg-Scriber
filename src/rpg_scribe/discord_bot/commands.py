"""Slash commands for RPG Scribe Discord bot."""

from __future__ import annotations

import logging
import uuid

import discord
from discord import app_commands
from discord.ext import commands

from rpg_scribe.core.event_bus import EventBus
from rpg_scribe.core.models import ListenerConfig
from rpg_scribe.listeners.discord_listener import DiscordListener

logger = logging.getLogger(__name__)


class ScribeCog(commands.Cog):
    """Cog implementing /scribe start, /scribe stop, /scribe status."""

    def __init__(
        self,
        bot: commands.Bot,
        event_bus: EventBus,
        config: ListenerConfig,
    ) -> None:
        self.bot = bot
        self.event_bus = event_bus
        self.config = config
        self.listener: DiscordListener | None = None
        self.session_id: str | None = None

    scribe_group = app_commands.Group(
        name="scribe", description="RPG Scribe session commands"
    )

    @scribe_group.command(name="start", description="Start recording the voice channel")
    async def scribe_start(self, interaction: discord.Interaction) -> None:
        if self.listener is not None and self.listener.is_connected():
            await interaction.response.send_message(
                "Already recording! Use `/scribe stop` first.",
                ephemeral=True,
            )
            return

        member = interaction.user
        if not isinstance(member, discord.Member) or member.voice is None:
            await interaction.response.send_message(
                "You must be in a voice channel to start recording.",
                ephemeral=True,
            )
            return

        voice_channel = member.voice.channel
        self.session_id = uuid.uuid4().hex[:12]
        self.listener = DiscordListener(self.event_bus, self.config)

        await interaction.response.defer()
        try:
            await self.listener.connect(
                session_id=self.session_id,
                voice_channel=voice_channel,
            )
            await interaction.followup.send(
                f"Recording started in **{voice_channel.name}**.\n"
                f"Session: `{self.session_id}`"
            )
        except Exception as exc:
            self.listener = None
            self.session_id = None
            await interaction.followup.send(
                f"Failed to start recording: {exc}",
                ephemeral=True,
            )

    @scribe_group.command(name="stop", description="Stop recording")
    async def scribe_stop(self, interaction: discord.Interaction) -> None:
        if self.listener is None or not self.listener.is_connected():
            await interaction.response.send_message(
                "Not currently recording.", ephemeral=True
            )
            return

        await interaction.response.defer()
        await self.listener.disconnect()
        sid = self.session_id
        self.listener = None
        self.session_id = None
        await interaction.followup.send(f"Recording stopped. Session `{sid}` ended.")

    @scribe_group.command(
        name="status", description="Show current recording status"
    )
    async def scribe_status(self, interaction: discord.Interaction) -> None:
        if self.listener is not None and self.listener.is_connected():
            await interaction.response.send_message(
                f"Recording session `{self.session_id}` is active.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "Not recording.", ephemeral=True
            )
