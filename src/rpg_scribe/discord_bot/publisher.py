"""Discord embed publisher for summary updates.

Posts and updates a rich embed message in a designated text channel
whenever the summarizer produces a new summary.
"""

from __future__ import annotations

import logging
import time

import discord
from discord.ext import commands

from rpg_scribe.core.event_bus import EventBus
from rpg_scribe.core.events import SummaryUpdateEvent

logger = logging.getLogger(__name__)

# Discord embed description limit
_EMBED_DESC_LIMIT = 4096
# Discord embed field value limit
_EMBED_FIELD_LIMIT = 1024


def _truncate(text: str, limit: int) -> str:
    """Truncate text to fit within a limit, adding an ellipsis if needed."""
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


class DiscordSummaryPublisher:
    """Publishes summary updates as Discord embeds.

    Subscribes to ``SummaryUpdateEvent`` on the event bus and either
    creates a new embed message or edits the existing one in the
    configured text channel.
    """

    def __init__(
        self,
        bot: commands.Bot,
        event_bus: EventBus,
        channel_id: int,
    ) -> None:
        self._bot = bot
        self._event_bus = event_bus
        self._channel_id = channel_id
        self._message: discord.Message | None = None
        self._last_update: float = 0.0

        # Subscribe to summary events
        self._event_bus.subscribe(SummaryUpdateEvent, self._on_summary)

    async def _on_summary(self, event: SummaryUpdateEvent) -> None:
        """Handle a SummaryUpdateEvent by posting/updating a Discord embed."""
        # Rate-limit updates to at most once every 5 seconds
        now = time.time()
        if now - self._last_update < 5.0 and event.update_type != "final":
            return
        self._last_update = now

        channel = self._bot.get_channel(self._channel_id)
        if channel is None:
            try:
                channel = await self._bot.fetch_channel(self._channel_id)
            except Exception as exc:
                logger.error("Cannot fetch summary channel %d: %s", self._channel_id, exc)
                return

        if not isinstance(channel, discord.TextChannel):
            logger.error("Channel %d is not a text channel", self._channel_id)
            return

        embed = self._build_embed(event)

        try:
            if self._message is not None:
                try:
                    await self._message.edit(embed=embed)
                    return
                except (discord.NotFound, discord.HTTPException):
                    # Message was deleted or edit failed — send a new one
                    self._message = None

            self._message = await channel.send(embed=embed)
        except Exception as exc:
            logger.error("Failed to publish summary embed: %s", exc)

    def _build_embed(self, event: SummaryUpdateEvent) -> discord.Embed:
        """Build a Discord embed from a SummaryUpdateEvent."""
        if event.update_type == "final":
            title = "RPG Scribe — Resumen Final de Sesion"
            colour = discord.Colour.gold()
        else:
            title = "RPG Scribe — Resumen en Vivo"
            colour = discord.Colour.blue()

        description = _truncate(
            event.session_summary or "(sin resumen todavia)",
            _EMBED_DESC_LIMIT,
        )
        embed = discord.Embed(
            title=title,
            description=description,
            colour=colour,
            timestamp=discord.utils.utcnow(),
        )

        if event.campaign_summary:
            embed.add_field(
                name="Resumen de Campana",
                value=_truncate(event.campaign_summary, _EMBED_FIELD_LIMIT),
                inline=False,
            )

        embed.set_footer(text=f"Sesion: {event.session_id} | {event.update_type}")
        return embed

    async def stop(self) -> None:
        """Unsubscribe from the event bus."""
        self._event_bus.unsubscribe(SummaryUpdateEvent, self._on_summary)
