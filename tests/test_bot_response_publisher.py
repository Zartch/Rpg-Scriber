"""Tests de DiscordBotResponsePublisher (canal configurado + fallback a voz)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import discord

from rpg_scribe.core.event_bus import EventBus
from rpg_scribe.core.events import BotTextResponseEvent, Citation
from rpg_scribe.discord_bot.bot_response_publisher import DiscordBotResponsePublisher


def _event(voice_channel_id: int | None = None) -> BotTextResponseEvent:
    return BotTextResponseEvent(
        session_id="s1",
        bot_keyword="bot reglas",
        speaker_name="Alice",
        question="¿Cómo funciona el hackeo?",
        answer_md="El hackeo requiere una tirada de Interface.\n\n**Fuentes:**\n- *Manual A*, p. 2",
        citations=(Citation(manual="Manual A", page=2, section_path="Hackeo"),),
        voice_channel_id=voice_channel_id,
    )


async def test_publishes_to_configured_channel():
    channel = MagicMock(spec=discord.TextChannel)
    channel.send = AsyncMock(return_value=MagicMock())
    bot = MagicMock()
    bot.get_channel.return_value = channel

    bus = EventBus()
    DiscordBotResponsePublisher(bot=bot, event_bus=bus, channel_id=123)

    await bus.publish(_event(voice_channel_id=456))

    bot.get_channel.assert_called_once_with(123)  # prioriza el canal configurado
    channel.send.assert_awaited_once()
    embed = channel.send.call_args.kwargs["embed"]
    assert "hackeo" in embed.description.lower()


async def test_fallback_to_voice_channel_when_no_configured_channel():
    voice_chan = MagicMock(spec=discord.VoiceChannel)
    voice_chan.send = AsyncMock(return_value=MagicMock())
    bot = MagicMock()
    bot.get_channel.return_value = voice_chan

    bus = EventBus()
    DiscordBotResponsePublisher(bot=bot, event_bus=bus, channel_id=None)

    await bus.publish(_event(voice_channel_id=456))

    bot.get_channel.assert_called_once_with(456)  # usa el canal de voz
    voice_chan.send.assert_awaited_once()


async def test_no_target_does_not_post():
    bot = MagicMock()
    bus = EventBus()
    DiscordBotResponsePublisher(bot=bot, event_bus=bus, channel_id=None)

    await bus.publish(_event(voice_channel_id=None))

    bot.get_channel.assert_not_called()


async def test_unfetchable_channel_does_not_raise():
    bot = MagicMock()
    bot.get_channel.return_value = None
    bot.fetch_channel = AsyncMock(side_effect=RuntimeError("no channel"))

    bus = EventBus()
    DiscordBotResponsePublisher(bot=bot, event_bus=bus, channel_id=999)

    # No debe propagar la excepción al bus.
    await bus.publish(_event())


async def test_publishes_without_citations():
    channel = MagicMock(spec=discord.TextChannel)
    channel.send = AsyncMock(return_value=MagicMock())
    bot = MagicMock()
    bot.get_channel.return_value = channel

    bus = EventBus()
    DiscordBotResponsePublisher(bot=bot, event_bus=bus, channel_id=123)

    event = BotTextResponseEvent(
        session_id="s1",
        bot_keyword="bot reglas",
        speaker_name="Alice",
        question="¿pregunta?",
        answer_md="respuesta sin fuentes",
        citations=(),
        voice_channel_id=None,
    )
    await bus.publish(event)

    channel.send.assert_awaited_once()
    embed = channel.send.call_args.kwargs["embed"]
    # Sin citations no debe haber campo "Fuentes"
    assert all(f.name != "Fuentes" for f in embed.fields)
