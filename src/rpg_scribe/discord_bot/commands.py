"""Slash commands for RPG Scribe Discord bot."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid

import discord
from discord import app_commands
from discord.ext import commands

from rpg_scribe.core.database import Database
from rpg_scribe.core.event_bus import EventBus
from rpg_scribe.core.events import (
    ListenerRecoverRequestEvent,
    SessionEndRequestEvent,
    SessionStartRequestEvent,
)
from rpg_scribe.core.models import ListenerConfig
from rpg_scribe.listeners.discord_listener import DiscordListener

logger = logging.getLogger(__name__)
_LISTENER_RECOVERY_COOLDOWN_S = 90.0
# Cooldown when the listener is already dead: just enough to avoid tight loops.
_LISTENER_DEAD_RECOVERY_COOLDOWN_S = 15.0
# Delay before attempt N+1 (the last value repeats). ~16 min total with 20 attempts.
_LISTENER_RECOVERY_BACKOFF_S: tuple[float, ...] = (5.0, 10.0, 20.0, 30.0, 60.0)
_LISTENER_RECOVERY_MAX_ATTEMPTS = 20
_GATEWAY_WAIT_TIMEOUT_S = 60.0
_GATEWAY_WAIT_POLL_S = 1.0
# How long to wait for the member_disconnect audit entry after a voice leave.
_MANUAL_KICK_AUDIT_WAIT_S = 3.0
_MANUAL_KICK_AUDIT_POLL_S = 1.0
# Silent drops wait this long before reconnecting, so a manual kick can be
# identified (and the recovery cancelled) before the bot jumps back in.
_SILENT_DROP_GRACE_S = 5.0

# Discord embed description limit
_EMBED_DESC_LIMIT = 4096
_TRUNCATION_SUFFIX = "\n\n…*(resumen truncado — ver versión completa en la web)*"



def _recovery_delay(attempt: int) -> float:
    """Backoff before ``attempt`` (attempt 1 runs immediately)."""
    idx = min(max(attempt - 2, 0), len(_LISTENER_RECOVERY_BACKOFF_S) - 1)
    return _LISTENER_RECOVERY_BACKOFF_S[idx]


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
        await self.database.entities.answer_question(self.question_id, self.answer.value)
        await interaction.response.send_message(
            "Respuesta guardada. Gracias!",
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
        self._voice_channel: discord.VoiceChannel | None = None
        self._listener_recovery_in_progress = False
        self._last_listener_recovery_ts = 0.0
        self._recovery_task: asyncio.Task[None] | None = None
        self._voice_leave_task: asyncio.Task[None] | None = None
        self._audit_disconnect_baseline: dict[int, int] | None = None
        self.event_bus.subscribe(
            ListenerRecoverRequestEvent, self._on_listener_recover_request
        )

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
        self._voice_channel = voice_channel
        self.listener = DiscordListener(self.event_bus, self.config)

        # Log del inicio de sesión con contexto completo
        members_in_channel = [m for m in voice_channel.members if not m.bot]
        logger.info(
            "▶️  /scribe start | usuario='%s' (id=%s) | canal='%s' (id=%s) | sesión=%s",
            member.display_name,
            member.id,
            voice_channel.name,
            voice_channel.id,
            self.session_id,
        )
        logger.info(
            "   Participantes en el canal (%d): %s",
            len(members_in_channel),
            ", ".join(f"{m.display_name}(id={m.id})" for m in members_in_channel) or "—",
        )

        await interaction.response.defer()
        try:
            await self.listener.connect(
                session_id=self.session_id,
                voice_channel=voice_channel,
            )
            # Notify Application via EventBus so it starts summarizer + DB session
            await self.event_bus.publish(
                SessionStartRequestEvent(
                    session_id=self.session_id, source="discord"
                )
            )
            await interaction.followup.send(
                f"Recording started in **{voice_channel.name}**.\n"
                f"Session: `{self.session_id}`"
            )
            logger.info("Sesión %s grabando en '%s'", self.session_id, voice_channel.name)
            self._audit_disconnect_baseline = await self._disconnect_audit_counts(
                voice_channel.guild
            )
        except Exception as exc:
            self.listener = None
            self.session_id = None
            self._voice_channel = None
            logger.error(
                "Error al iniciar grabación en '%s': [%s] %s",
                voice_channel.name, type(exc).__name__, exc,
                exc_info=True,
            )
            await interaction.followup.send(
                f"Failed to start recording: {exc}",
                ephemeral=True,
            )

    @scribe_group.command(name="stop", description="Stop recording")
    async def scribe_stop(self, interaction: discord.Interaction) -> None:
        if self.listener is None or self.session_id is None:
            await interaction.response.send_message(
                "Not currently recording.", ephemeral=True
            )
            return

        await interaction.response.defer()
        sid = self.session_id
        listener = self.listener
        logger.info("⏹️  /scribe stop | sesión=%s | solicitado por '%s' (id=%s)",
                    sid, interaction.user.display_name, interaction.user.id)
        self.listener = None
        self.session_id = None
        self._voice_channel = None
        await listener.disconnect()
        # Notify Application via EventBus — finalization runs in background
        await self.event_bus.publish(
            SessionEndRequestEvent(session_id=sid, source="discord")
        )
        logger.info("Sesión %s detenida correctamente", sid)
        await interaction.followup.send(
            f"Recording stopped. Session `{sid}` ended. Finalizing summary..."
        )

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        """React when the bot leaves the voice channel during a session.

        A manual kick (moderator "Disconnect") ends the session; any other
        leave is treated as a drop and goes through listener recovery. The
        audit-log lookup can take seconds, so it runs off the gateway handler.

        Guarded by ``self.session_id`` (not by ``listener.is_connected()``) so
        we still react when ``_periodic_flush`` already flipped the
        ``_connected`` flag after detecting a silent voice-connection drop.
        """
        if self.bot.user is None:
            return
        if before.channel is None or after.channel is not None:
            return
        if self.session_id is None or self.listener is None:
            return
        if member.id != self.bot.user.id:
            # A moderator may have disconnected this player: refresh the
            # baseline so that kick isn't later attributed to the bot.
            if self._audit_disconnect_baseline is not None:
                asyncio.create_task(
                    self._refresh_audit_baseline(before.channel.guild),
                    name="audit-baseline-refresh",
                )
            return

        self._voice_leave_task = asyncio.create_task(
            self._handle_bot_voice_leave(self.session_id, before.channel),
            name=f"voice-leave-{self.session_id}",
        )

    async def _handle_bot_voice_leave(
        self, sid: str, channel: discord.VoiceChannel
    ) -> None:
        in_recovery = self._listener_recovery_in_progress
        logger.info(
            "🔎 Bot fuera del canal '%s' (sesión %s, recovery_en_curso=%s) — "
            "consultando audit log para distinguir expulsión manual de caída",
            channel.name,
            sid,
            in_recovery,
        )
        manual = await self._was_manual_disconnect(channel.guild)
        if self.session_id != sid:
            return

        if manual is True:
            logger.warning(
                "👢 Bot expulsado manualmente del canal '%s' (audit log "
                "member_disconnect) — cerrando sesión %s sin reconectar",
                channel.name,
                sid,
            )
            await self._end_session_after_manual_kick(sid)
            return

        if self._listener_recovery_in_progress or in_recovery:
            # Most likely the leave caused by recovery's own old_listener.disconnect()
            logger.info(
                "Salida del canal durante recovery gestionado de la sesión %s "
                "(manual=%s) — la gestiona el recovery",
                sid,
                manual,
            )
            return

        if manual is None:
            logger.warning(
                "⚠️  Bot desconectado del canal '%s' y no se puede consultar el "
                "audit log (¿falta el permiso 'View Audit Log'?) — se trata como "
                "expulsión manual: cerrando sesión %s sin reconectar",
                channel.name,
                sid,
            )
            await self._end_session_after_manual_kick(sid)
            return

        logger.warning(
            "⚠️  Bot desconectado inesperadamente del canal '%s' sin expulsión "
            "en el audit log — tratando como caída, iniciando recovery de la "
            "sesión %s",
            channel.name,
            sid,
        )
        self._start_recovery(sid, reason="voice_state_leave")

    async def _disconnect_audit_counts(
        self, guild: discord.Guild
    ) -> dict[int, int] | None:
        """Return ``{entry_id: count}`` of recent member_disconnect entries.

        Discord does not record *who* was disconnected, only a counter, and it
        folds repeated disconnects by the same moderator into one entry by
        bumping ``count`` — hence the comparison against a baseline.
        ``None`` means the audit log could not be read.
        """
        try:
            counts: dict[int, int] = {}
            async for entry in guild.audit_logs(
                limit=10, action=discord.AuditLogAction.member_disconnect
            ):
                counts[entry.id] = int(getattr(entry.extra, "count", 1) or 1)
            return counts
        except discord.Forbidden:
            logger.warning(
                "Sin permiso 'View Audit Log' en el servidor: no se podrá "
                "distinguir una expulsión manual de una caída (se tratará "
                "cualquier salida del canal como expulsión manual)"
            )
        except Exception:
            logger.warning("No se pudo leer el audit log del servidor", exc_info=True)
        return None

    async def _refresh_audit_baseline(self, guild: discord.Guild) -> None:
        # Let the audit entry for the player's disconnect land first.
        await asyncio.sleep(_MANUAL_KICK_AUDIT_WAIT_S)
        if self.session_id is None or self._audit_disconnect_baseline is None:
            return
        counts = await self._disconnect_audit_counts(guild)
        if counts is not None:
            self._audit_disconnect_baseline = counts

    async def _was_manual_disconnect(self, guild: discord.Guild) -> bool | None:
        baseline = self._audit_disconnect_baseline
        if baseline is None:
            return None
        # The audit entry can lag a moment behind the voice state update.
        deadline = time.monotonic() + _MANUAL_KICK_AUDIT_WAIT_S
        while True:
            counts = await self._disconnect_audit_counts(guild)
            if counts is None:
                return None
            if any(
                entry_id not in baseline or count > baseline[entry_id]
                for entry_id, count in counts.items()
            ):
                return True
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(_MANUAL_KICK_AUDIT_POLL_S)

    async def _end_session_after_manual_kick(self, sid: str) -> None:
        recovery = self._recovery_task
        if recovery is not None and not recovery.done():
            logger.info("Cancelando recovery en curso de la sesión %s", sid)
            recovery.cancel()
        listener = self.listener
        self.listener = None
        self.session_id = None
        self._voice_channel = None
        self._audit_disconnect_baseline = None
        if listener is not None:
            try:
                await listener.disconnect()
            except Exception:
                logger.exception("Error al desconectar listener tras expulsión")
        await self.event_bus.publish(
            SessionEndRequestEvent(session_id=sid, source="discord")
        )

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

    async def _on_listener_recover_request(
        self, event: ListenerRecoverRequestEvent
    ) -> None:
        if event.session_id != self.session_id or self.listener is None:
            return
        if self._listener_recovery_in_progress:
            logger.debug(
                "Recovery ya en curso para sesión %s — ignorando petición (reason=%s)",
                event.session_id,
                event.reason,
            )
            return
        # A dead listener emits no more chunks, so the stall detector will never
        # ask again: only a short anti-loop cooldown applies in that case.
        listener_dead = not self.listener.is_connected()
        cooldown = (
            _LISTENER_DEAD_RECOVERY_COOLDOWN_S
            if listener_dead
            else _LISTENER_RECOVERY_COOLDOWN_S
        )
        elapsed = time.monotonic() - self._last_listener_recovery_ts
        if elapsed < cooldown:
            logger.info(
                "Recovery para sesión %s en cooldown (reason=%s, listener_dead=%s, "
                "%.0fs/%.0fs) — ignorando",
                event.session_id,
                event.reason,
                listener_dead,
                elapsed,
                cooldown,
            )
            return
        self._start_recovery(event.session_id, reason=event.reason)

    def _start_recovery(self, session_id: str, *, reason: str) -> None:
        self._last_listener_recovery_ts = time.monotonic()
        # Keep a strong reference: the event loop only holds weak refs to tasks.
        self._recovery_task = asyncio.create_task(
            self._recover_listener(session_id, reason=reason),
            name=f"listener-recovery-{session_id}",
        )

    async def _recover_listener(self, session_id: str, *, reason: str) -> None:
        if self.listener is None or self.session_id != session_id:
            return
        voice_channel = self._resolve_recovery_voice_channel(self.listener)
        if voice_channel is None:
            logger.warning(
                "Recovery ignorado para sesión %s: canal de voz desconocido",
                session_id,
            )
            return

        old_listener = self.listener
        self._listener_recovery_in_progress = True
        started = time.monotonic()
        logger.warning(
            "♻️  Recuperando listener de la sesión %s sin rotar session_id "
            "(reason=%s, channel='%s', max_intentos=%d)",
            session_id,
            reason,
            voice_channel.name,
            _LISTENER_RECOVERY_MAX_ATTEMPTS,
        )
        try:
            try:
                await old_listener.disconnect()
            except Exception:
                logger.exception(
                    "Error al desconectar el listener antiguo de la sesión %s "
                    "(se continúa con la reconexión)",
                    session_id,
                )
            if reason == "voice_silent_drop":
                logger.info(
                    "Esperando %.0fs antes de reconectar la sesión %s por si la "
                    "caída es una expulsión manual",
                    _SILENT_DROP_GRACE_S,
                    session_id,
                )
                await asyncio.sleep(_SILENT_DROP_GRACE_S)

            for attempt in range(1, _LISTENER_RECOVERY_MAX_ATTEMPTS + 1):
                if attempt > 1:
                    delay = _recovery_delay(attempt)
                    logger.info(
                        "♻️  Reintento %d/%d de recovery para sesión %s en %.0fs",
                        attempt,
                        _LISTENER_RECOVERY_MAX_ATTEMPTS,
                        session_id,
                        delay,
                    )
                    await asyncio.sleep(delay)
                if self.session_id != session_id:
                    logger.info(
                        "Recovery de sesión %s abortado: la sesión ya no está activa "
                        "(/scribe stop o nueva sesión)",
                        session_id,
                    )
                    return

                if not await self._wait_for_gateway(session_id):
                    if self.session_id == session_id:
                        logger.warning(
                            "❌ Intento %d/%d de recovery para sesión %s: gateway de "
                            "Discord sigue caído tras %.0fs de espera",
                            attempt,
                            _LISTENER_RECOVERY_MAX_ATTEMPTS,
                            session_id,
                            _GATEWAY_WAIT_TIMEOUT_S,
                        )
                    continue

                new_listener = await self._try_connect_listener(
                    session_id, voice_channel, attempt
                )
                if new_listener is None:
                    continue
                if self.session_id != session_id:
                    await new_listener.disconnect()
                    return
                self.listener = new_listener
                self._voice_channel = voice_channel
                self._last_listener_recovery_ts = time.monotonic()
                logger.info(
                    "✅ Listener recuperado para la sesión %s (intento %d/%d, "
                    "%.0fs desde el inicio del recovery)",
                    session_id,
                    attempt,
                    _LISTENER_RECOVERY_MAX_ATTEMPTS,
                    time.monotonic() - started,
                )
                return

            if self.session_id != session_id:
                return
            logger.error(
                "🛑 Recovery agotado para sesión %s tras %d intentos (%.0fs) — "
                "cerrando la sesión para finalizar el resumen. Usa /scribe start "
                "para empezar una nueva.",
                session_id,
                _LISTENER_RECOVERY_MAX_ATTEMPTS,
                time.monotonic() - started,
            )
            await self._end_session_after_failed_recovery(session_id)
        except asyncio.CancelledError:
            logger.warning("Recovery de sesión %s cancelado", session_id)
            raise
        except Exception:
            logger.exception(
                "Error inesperado en el recovery del listener para sesión %s",
                session_id,
            )
        finally:
            self._listener_recovery_in_progress = False

    async def _try_connect_listener(
        self,
        session_id: str,
        voice_channel: discord.VoiceChannel,
        attempt: int,
    ) -> DiscordListener | None:
        await self._cleanup_stale_guild_voice_client(voice_channel)
        new_listener = DiscordListener(self.event_bus, self.config)
        try:
            await new_listener.connect(session_id=session_id, voice_channel=voice_channel)
        except Exception as exc:
            logger.warning(
                "❌ Intento %d/%d de recovery para sesión %s falló: [%s] %s",
                attempt,
                _LISTENER_RECOVERY_MAX_ATTEMPTS,
                session_id,
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            return None
        if not new_listener.is_connected():
            logger.warning(
                "❌ Intento %d/%d de recovery para sesión %s: connect() terminó "
                "pero el listener no quedó conectado",
                attempt,
                _LISTENER_RECOVERY_MAX_ATTEMPTS,
                session_id,
            )
            return None
        return new_listener

    async def _cleanup_stale_guild_voice_client(
        self, voice_channel: discord.VoiceChannel
    ) -> None:
        """Drop a half-dead guild voice client left behind by a failed connect.

        Otherwise ``voice_channel.connect()`` raises "Already connected to a
        voice channel" on every retry.
        """
        guild = getattr(voice_channel, "guild", None)
        stale = getattr(guild, "voice_client", None)
        if stale is None:
            return
        logger.info(
            "Limpiando voice client residual del servidor antes de reconectar "
            "(connected=%s)",
            stale.is_connected(),
        )
        try:
            await stale.disconnect(force=True)
        except Exception:
            logger.warning("No se pudo limpiar el voice client residual", exc_info=True)

    def _gateway_is_up(self) -> bool:
        # bot.is_ready() stays True while discord.py retries the gateway,
        # so look at the websocket itself.
        ws = getattr(self.bot, "ws", None)
        return ws is not None and bool(getattr(ws, "open", False))

    async def _wait_for_gateway(self, session_id: str) -> bool:
        if self._gateway_is_up():
            return True
        logger.warning(
            "⏳ Gateway de Discord caído — esperando hasta %.0fs antes de "
            "reconectar la voz de la sesión %s",
            _GATEWAY_WAIT_TIMEOUT_S,
            session_id,
        )
        started = time.monotonic()
        deadline = started + _GATEWAY_WAIT_TIMEOUT_S
        while time.monotonic() < deadline:
            await asyncio.sleep(_GATEWAY_WAIT_POLL_S)
            if self.session_id != session_id:
                return False
            if self._gateway_is_up():
                logger.info(
                    "🔌 Gateway de Discord disponible de nuevo tras %.0fs",
                    time.monotonic() - started,
                )
                return True
        return False

    async def _end_session_after_failed_recovery(self, session_id: str) -> None:
        # The old listener was already disconnected at the start of recovery.
        self.listener = None
        self.session_id = None
        self._voice_channel = None
        await self.event_bus.publish(
            SessionEndRequestEvent(session_id=session_id, source="discord")
        )

    def _maybe_recover_after_gateway(self, trigger: str) -> None:
        listener = self.listener
        if self.session_id is None or listener is None:
            logger.info("🔌 Gateway de Discord %s (sin sesión activa)", trigger)
            return
        connected = listener.is_connected()
        logger.info(
            "🔌 Gateway de Discord %s | sesión=%s listener_conectado=%s "
            "recovery_en_curso=%s",
            trigger,
            self.session_id,
            connected,
            self._listener_recovery_in_progress,
        )
        if connected or self._listener_recovery_in_progress:
            return
        self._start_recovery(self.session_id, reason=f"gateway_{trigger}")

    @commands.Cog.listener()
    async def on_disconnect(self) -> None:
        logger.warning(
            "🔌 Gateway de Discord desconectado | sesión=%s — discord.py "
            "reintentará la conexión",
            self.session_id,
        )

    @commands.Cog.listener()
    async def on_resumed(self) -> None:
        self._maybe_recover_after_gateway("resumed")

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        self._maybe_recover_after_gateway("ready")

    def _resolve_recovery_voice_channel(
        self, listener: DiscordListener
    ) -> discord.VoiceChannel | None:
        vc = getattr(listener, "_voice_client", None)
        channel = getattr(vc, "channel", None)
        if channel is not None:
            return channel
        return self._voice_channel

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

        session = await self.database.sessions.get_session(self.session_id)
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

        pending = await self.database.entities.get_pending_questions(self.session_id)
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
