"""Discord embed publisher para respuestas de bots (BotTextResponseEvent).

Elige el canal destino por orden de preferencia:
  1. ``channel_id`` configurado ([campaign.rag].rules_channel_id).
  2. ``event.voice_channel_id`` — el chat integrado del canal de voz donde se
     invocó al bot (un VoiceChannel es messageable en discord.py 2.x).
  3. Ninguno → no postea (solo quedó la respuesta hablada).
"""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

from rpg_scribe.core.event_bus import EventBus
from rpg_scribe.core.events import BotTextResponseEvent

logger = logging.getLogger(__name__)

_EMBED_TITLE_LIMIT = 256
_EMBED_DESC_LIMIT = 4096
_EMBED_FIELD_LIMIT = 1024

# Canales a los que sabemos enviar (todos messageable en discord.py 2.x).
_SENDABLE = (discord.TextChannel, discord.VoiceChannel, discord.Thread)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


class DiscordBotResponsePublisher:
    """Postea cada respuesta escrita de un bot como embed en un canal de texto."""

    def __init__(
        self,
        bot: commands.Bot,
        event_bus: EventBus,
        channel_id: int | None,
    ) -> None:
        self._bot = bot
        self._event_bus = event_bus
        self._channel_id = channel_id
        self._event_bus.subscribe(BotTextResponseEvent, self._on_response)

    async def _on_response(self, event: BotTextResponseEvent) -> None:
        target_id = self._channel_id or event.voice_channel_id
        if target_id is None:
            logger.info("Respuesta de bot no publicada: sin canal de reglas ni de voz")
            return

        channel = self._bot.get_channel(target_id)
        if channel is None:
            try:
                channel = await self._bot.fetch_channel(target_id)
            except Exception as exc:
                logger.error("No se pudo obtener el canal %d: %s", target_id, exc)
                return

        if not isinstance(channel, _SENDABLE):
            logger.error("El canal %d no admite mensajes de texto", target_id)
            return

        embed = self._build_embed(event)
        try:
            await channel.send(embed=embed)
        except Exception as exc:
            logger.error("Fallo al publicar el embed de respuesta: %s", exc)

    def _build_embed(self, event: BotTextResponseEvent) -> discord.Embed:
        embed = discord.Embed(
            title=_truncate(f"\U0001f4d6 {event.question}", _EMBED_TITLE_LIMIT),
            description=_truncate(event.answer_md, _EMBED_DESC_LIMIT),
            colour=discord.Colour.teal(),
            timestamp=discord.utils.utcnow(),
        )
        if event.citations:
            sources = "\n".join(
                f"*{c.manual}*, p. {c.page}"
                + (f" — {c.section_path}" if c.section_path else "")
                for c in event.citations
            )
            embed.add_field(
                name="Fuentes",
                value=_truncate(sources, _EMBED_FIELD_LIMIT),
                inline=False,
            )
        embed.set_footer(text=f"{event.bot_keyword} · preguntó {event.speaker_name}")
        return embed

    async def stop(self) -> None:
        self._event_bus.unsubscribe(BotTextResponseEvent, self._on_response)
