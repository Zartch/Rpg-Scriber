"""Slash commands for RPG Scribe Discord bot."""

from __future__ import annotations

import logging
import uuid

import discord
from discord import app_commands
from discord.ext import commands

from rpg_scribe.core.database import Database
from rpg_scribe.core.event_bus import EventBus
from rpg_scribe.core.models import ListenerConfig
from rpg_scribe.listeners.discord_listener import DiscordListener

logger = logging.getLogger(__name__)

# Discord embed description limit
_EMBED_DESC_LIMIT = 4096
_TRUNCATION_SUFFIX = "\n\n…*(resumen truncado — ver versión completa en la web)*"


class AnswerQuestionModal(discord.ui.Modal, title="Responder pregunta"):
    """Modal for answering a pending question from the summarizer."""

    answer = discord.ui.TextInput(
        label="Tu respuesta",
        style=discord.TextStyle.paragraph,
        placeholder="Escribe tu respuesta aquí...",
        required=True,
        max_length=1000,
    )

    def __init__(self, question_id: int, question_text: str, database: Database) -> None:
        super().__init__()
        self.question_id = question_id
        self.question_text = question_text
        self.database = database

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.database.answer_question(self.question_id, self.answer.value)
        await interaction.response.send_message(
            f"Respuesta guardada. Gracias!",
            ephemeral=True,
        )


class ScribeCog(commands.Cog):
    """Cog implementing /scribe start, /scribe stop, /scribe status, /scribe summary, /scribe ask."""

    def __init__(
        self,
        bot: commands.Bot,
        event_bus: EventBus,
        config: ListenerConfig,
        database: Database | None = None,
    ) -> None:
        self.bot = bot
        self.event_bus = event_bus
        self.config = config
        self.database = database
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

    @scribe_group.command(
        name="summary", description="Show the current session summary"
    )
    async def scribe_summary(self, interaction: discord.Interaction) -> None:
        if self.session_id is None:
            await interaction.response.send_message(
                "No hay sesión activa.", ephemeral=True
            )
            return

        if self.database is None:
            await interaction.response.send_message(
                "Base de datos no disponible.", ephemeral=True
            )
            return

        session = await self.database.get_session(self.session_id)
        summary_text = (session or {}).get("session_summary", "") or ""

        if not summary_text:
            await interaction.response.send_message(
                "Aún no hay resumen disponible para esta sesión.",
                ephemeral=True,
            )
            return

        # Truncate if over Discord embed limit
        if len(summary_text) > _EMBED_DESC_LIMIT:
            max_len = _EMBED_DESC_LIMIT - len(_TRUNCATION_SUFFIX)
            summary_text = summary_text[:max_len] + _TRUNCATION_SUFFIX

        embed = discord.Embed(
            title="RPG Scribe — Resumen de Sesión",
            description=summary_text,
            colour=discord.Colour.blue(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_footer(text=f"Sesión: {self.session_id}")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @scribe_group.command(
        name="ask", description="Answer a pending question from the AI"
    )
    async def scribe_ask(self, interaction: discord.Interaction) -> None:
        if self.session_id is None:
            await interaction.response.send_message(
                "No hay sesión activa.", ephemeral=True
            )
            return

        if self.database is None:
            await interaction.response.send_message(
                "Base de datos no disponible.", ephemeral=True
            )
            return

        pending = await self.database.get_pending_questions(self.session_id)
        if not pending:
            await interaction.response.send_message(
                "No hay preguntas pendientes.", ephemeral=True
            )
            return

        question = pending[0]
        modal = AnswerQuestionModal(
            question_id=question["id"],
            question_text=question["question"],
            database=self.database,
        )
        # Set the modal's first text input label to the question (truncated to 45 chars for Discord limit)
        q_text = question["question"]
        if len(q_text) > 45:
            q_text = q_text[:42] + "..."
        modal.answer.label = q_text

        await interaction.response.send_modal(modal)
