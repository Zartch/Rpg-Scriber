"""Claude-based summarizer using the Anthropic API."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time

from rpg_scribe.core.database import Database
from rpg_scribe.core.event_bus import EventBus
from rpg_scribe.core.events import SystemStatusEvent, TranscriptionEvent
from rpg_scribe.core.models import CampaignContext, SummarizerConfig
from rpg_scribe.summarizers.base import BaseSummarizer, TranscriptionEntry

logger = logging.getLogger(__name__)

# Regex for extracting [PREGUNTA: ...] markers from LLM responses
QUESTION_PATTERN = re.compile(r"\[PREGUNTA:\s*(.+?)\]")

# ---------------------------------------------------------------------------
# System prompt template
# ---------------------------------------------------------------------------

GENERIC_SYSTEM_PROMPT = """\
Eres un cronista que resume conversaciones de voz en tiempo real.

INSTRUCCIONES:
1. Escribe un resumen claro y estructurado de lo que dicen los participantes.
2. Usa los nombres de los hablantes tal como aparecen.
3. Distingue entre temas diferentes si la conversación cambia de asunto.
4. Mantén el resumen coherente y fluido.
5. Si algo no está claro, márcalo con [PREGUNTA: ...].
"""

SESSION_SYSTEM_PROMPT = """\
Eres un cronista experto de partidas de rol. Tu trabajo es escribir \
un resumen narrativo de lo que ocurre en la sesión.

CONTEXTO DE LA CAMPAÑA:
- Sistema: {game_system}
- Campaña: {name} — {description}
- Resumen hasta ahora: {campaign_summary}

JUGADORES:
{players_block}

PNJS CONOCIDOS:
{npcs_block}

LOCALIZACIONES CONOCIDAS:
{locations_block}

ENTIDADES CONOCIDAS:
{entities_block}

RELACIONES CONOCIDAS:
{relationships_block}

{custom_instructions}

INSTRUCCIONES:
1. Escribe en tercera persona, estilo narrativo.
2. Distingue entre lo que dicen los personajes (in-game) y las \
conversaciones de los jugadores (meta-rol). El meta-rol NO va \
en el resumen narrativo, pero puedes anotarlo como [META] si \
es relevante (decisiones de grupo, dudas de reglas, etc.).
3. El DM ({dm_name}) habla como múltiples PNJs y también como narrador \
de escena. Cuando habla el DM, su texto puede ser ambientación, \
resultados de tiradas, consecuencias de acciones, eventos del mundo \
o interpretación de distintos PNJs. No lo atribuyas automáticamente \
a un único PNJ sin evidencia contextual.
4. Mantén el resumen coherente y fluido. Reescribe secciones \
anteriores si nueva información las clarifica.
5. Si algo no está claro, márcalo con [PREGUNTA: ...].
"""

SESSION_UPDATE_USER = """\
TRANSCRIPCIÓN RECIENTE:
{recent_transcriptions}

RESUMEN ACTUAL DE LA SESIÓN:
{current_session_summary}
{user_answers_block}\
Actualiza el resumen incorporando la nueva transcripción. \
Devuelve ÚNICAMENTE el resumen actualizado, sin explicaciones adicionales."""

FINALIZE_USER = """\
La sesión ha terminado. A continuación tienes el resumen de sesión \
y la transcripción completa pendiente.

RESUMEN DE SESIÓN ACTUAL:
{session_summary}

TRANSCRIPCIÓN PENDIENTE:
{pending_transcriptions}

Genera:
1. Un resumen final pulido de la sesión (narrativo, detallado).
2. Una actualización del resumen de campaña incorporando esta sesión.

Responde con el siguiente formato exacto:

---SESSION_SUMMARY---
(resumen final de la sesión)

---CAMPAIGN_SUMMARY---
(resumen actualizado de la campaña)
"""

CAMPAIGN_SUMMARY_SYSTEM = """\
Eres un cronista experto de campañas de rol. Tu trabajo es escribir un resumen \
narrativo global de toda la campaña hasta la fecha, a partir de los resúmenes \
de cada sesión jugada.

CONTEXTO DE LA CAMPAÑA:
- Sistema: {game_system}
- Campaña: {name} — {description}

JUGADORES:
{players_block}

PNJS CONOCIDOS:
{npcs_block}

ENTIDADES CONOCIDAS:
{entities_block}

RELACIONES CONOCIDAS:
{relationships_block}

{custom_instructions}

INSTRUCCIONES:
1. Escribe en tercera persona, estilo crónica narrativa.
2. Organiza la información por grandes arcos o temas si los hay.
3. Incluye: eventos clave, PNJs relevantes, localizaciones importantes, \
relaciones entre personajes y el estado actual de la trama.
4. El resumen debe ser completo pero conciso — útil para retomar la campaña \
tras un parón largo.
5. NO incluyas meta-conversaciones de los jugadores.
"""

CAMPAIGN_SUMMARY_USER = """\
A continuación tienes los resúmenes de las {session_count} sesiones jugadas \
hasta ahora, en orden cronológico.

{sessions_block}

Genera el resumen global de la campaña incorporando toda esta información. \
Devuelve ÚNICAMENTE el resumen, sin explicaciones adicionales.
"""

CAMPAIGN_SUMMARY_COMPRESS_USER = """\
Los resúmenes de sesión son demasiado extensos para procesarlos de una vez. \
A continuación tienes resúmenes de las sesiones más antiguas que necesitas \
condensar antes de combinarlos con las sesiones recientes.

{sessions_block}

Genera un resumen condensado de estas sesiones que preserve los eventos clave, \
PNJs, localizaciones y arcos narrativos. Devuelve ÚNICAMENTE el resumen condensado.
"""

EXTRACTION_USER = """\
A partir del siguiente resumen de sesión, extrae:
- PNJs nuevos
- Localizaciones nuevas
- Entidades nuevas (clanes, corporaciones, facciones, grupos...)
- Relaciones nuevas entre entidades de campaña

RESUMEN DE LA SESIÓN:
{session_summary}

PNJS YA CONOCIDOS (NO los incluyas de nuevo):
{known_npcs}

LOCALIZACIONES YA CONOCIDAS (NO las incluyas de nuevo):
{known_locations}

ENTIDADES YA CONOCIDAS (NO las incluyas de nuevo):
{known_entities}

RELACIONES YA CONOCIDAS (NO las repitas):
{known_relationships}

Responde ÚNICAMENTE con un JSON válido con este formato exacto, sin \
texto adicional antes o después:

{{"npcs": [{{"name": "Nombre del PNJ", "description": "Breve descripción"}}], \
"locations": [{{"name": "Nombre del lugar", "description": "Breve descripción"}}], \
"entities": [{{"name": "Nombre de la entidad", "entity_type": "clan|corporacion|faccion|grupo", "description": "Breve descripción"}}], \
"relationships": [{{"source_key": "player:123|npc:Nombre|loc:Lugar|ent:Entidad", "target_key": "player:123|npc:Nombre|loc:Lugar|ent:Entidad", "relation_type": "aliado de|enemigo de|miembro de...", "category": "general|politica|familiar|social", "notes": "opcional"}}]}}

Si no hay nuevos elementos, devuelve listas vacías.
"""


class ClaudeSummarizer(BaseSummarizer):
    """Summarizer that uses Anthropic's Claude API.

    Accumulates transcriptions in a buffer and periodically sends them
    to Claude for incremental summary updates.  At session end, produces
    a final polished summary and integrates it into the campaign summary.
    """

    def __init__(
        self,
        event_bus: EventBus,
        config: SummarizerConfig,
        campaign: CampaignContext,
        *,
        client: object | None = None,
        database: Database | None = None,
    ) -> None:
        super().__init__(event_bus, config, campaign)
        # Allow injecting a client for testing; lazy-load otherwise.
        self._client = client
        self._database = database
        self._update_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Lazy client
    # ------------------------------------------------------------------

    def _get_client(self):  # noqa: ANN202
        """Return the Anthropic async client, creating it lazily."""
        if self._client is None:
            try:
                from anthropic import AsyncAnthropic
            except ImportError as exc:
                raise ImportError(
                    "The 'anthropic' package is required. "
                    "Install it with: pip install anthropic"
                ) from exc
            self._client = AsyncAnthropic()
        return self._client

    # ------------------------------------------------------------------
    # Prompt helpers
    # ------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        """Build the system prompt with campaign context."""
        c = self.campaign

        if c.is_generic:
            return GENERIC_SYSTEM_PROMPT

        players_lines: list[str] = []
        for p in c.players:
            line = f"- {p.discord_name} juega como {p.character_name}"
            if p.character_description:
                line += f" ({p.character_description})"
            players_lines.append(line)

        dm_name = "DM"
        for p in c.players:
            if p.discord_id == c.dm_speaker_id:
                dm_name = p.discord_name
                break

        npcs_lines = [f"- {n.name}: {n.description}" for n in c.known_npcs] or [
            "(ninguno conocido)"
        ]

        locations_lines = [
            f"- {loc.name}: {loc.description}" if loc.description else f"- {loc.name}"
            for loc in c.locations
        ] or ["(ninguna conocida)"]

        entities_lines = [
            f"- {ent.name} [{ent.entity_type}]: {ent.description}"
            if ent.description else f"- {ent.name} [{ent.entity_type}]"
            for ent in c.entities
        ] or ["(ninguna conocida)"]

        entity_name_map: dict[str, str] = {
            f"player:{p.discord_id}": p.character_name or p.discord_name
            for p in c.players if p.discord_id
        }
        for n in c.known_npcs:
            if n.name:
                entity_name_map[f"npc:{n.name}"] = n.name
        for loc in c.locations:
            if loc.name:
                entity_name_map[f"loc:{loc.name}"] = loc.name
                entity_name_map[f"location:{loc.name}"] = loc.name
        for ent in c.entities:
            if ent.name:
                entity_name_map[f"ent:{ent.name}"] = ent.name
                entity_name_map[f"entity:{ent.name}"] = ent.name

        relationships_lines: list[str] = []
        for rel in c.relationships:
            source_name = entity_name_map.get(rel.source_key, rel.source_key)
            target_name = entity_name_map.get(rel.target_key, rel.target_key)
            rel_label = rel.relation_type_label or rel.relation_type_key
            line = f"- {source_name} -> {target_name}: {rel_label}"
            if rel.notes:
                line += f" ({rel.notes})"
            relationships_lines.append(line)
        if not relationships_lines:
            relationships_lines = ["(ninguna registrada)"]

        custom = ""
        if c.custom_instructions:
            custom = f"INSTRUCCIONES ADICIONALES:\n{c.custom_instructions}"

        return SESSION_SYSTEM_PROMPT.format(
            game_system=c.game_system,
            name=c.name,
            description=c.description,
            campaign_summary=c.campaign_summary or "(primera sesión)",
            players_block="\n".join(players_lines),
            dm_name=dm_name,
            npcs_block="\n".join(npcs_lines),
            locations_block="\n".join(locations_lines),
            entities_block="\n".join(entities_lines),
            relationships_block="\n".join(relationships_lines),
            custom_instructions=custom,
        )

    def _format_transcriptions(self, entries: list[TranscriptionEntry]) -> str:
        """Format transcription entries as readable text.

        The configured DM/master speaker is explicitly tagged so the model
        can treat those lines as narration/scene control or multi-NPC speech.
        """
        dm_id = ""
        if not self.campaign.is_generic:
            dm_id = self.campaign.dm_speaker_id or ""
        lines: list[str] = []
        for e in entries:
            speaker = e.speaker_name
            if dm_id and e.speaker_id == dm_id:
                speaker = f"{speaker} [MASTER]"
            lines.append(f"[{speaker}]: {e.text}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Question extraction & answer injection
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_questions(text: str) -> tuple[str, list[str]]:
        """Extract [PREGUNTA: ...] markers from text.

        Returns the cleaned text and a list of extracted question strings.
        """
        questions = QUESTION_PATTERN.findall(text)
        cleaned = QUESTION_PATTERN.sub("", text).strip()
        # Collapse multiple blank lines left by removal
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned, questions

    async def _save_questions(self, questions: list[str]) -> None:
        """Persist extracted questions to the database."""
        if not self._database or not questions:
            return
        for q in questions:
            await self._database.save_question(self._session_id, q)
        logger.info("Saved %d question(s) to database", len(questions))

    async def _build_user_answers_block(self) -> str:
        """Fetch answered-but-unprocessed questions and format them for the prompt.

        Returns an empty string if there are no answers or no database.
        """
        if not self._database:
            return ""
        answered = await self._database.get_answered_unprocessed_questions(
            self._session_id
        )
        if not answered:
            return ""
        lines: list[str] = []
        for row in answered:
            lines.append(f"- Pregunta: {row['question']}\n  Respuesta: {row['answer']}")
        # Mark them as processed so they aren't injected again
        await self._database.mark_questions_processed(
            [row["id"] for row in answered]
        )
        return (
            "\nRESPUESTAS DEL USUARIO:\n"
            + "\n".join(lines)
            + "\n\n"
        )

    # ------------------------------------------------------------------
    # API call with retry
    # ------------------------------------------------------------------

    async def _call_api(self, system: str, user_message: str) -> str:
        """Call the Claude API with retry and exponential backoff."""
        client = self._get_client()
        last_exc: Exception | None = None
        for attempt in range(self.config.max_retries):
            try:
                response = await client.messages.create(
                    model=self.config.model,
                    max_tokens=self.config.max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user_message}],
                )
                # Extract text from the response
                return response.content[0].text
            except Exception as exc:
                last_exc = exc
                if attempt < self.config.max_retries - 1:
                    delay = self.config.retry_base_delay_s * (2**attempt)
                    logger.warning(
                        "Claude API call failed (attempt %d/%d): %s — retrying in %.1fs",
                        attempt + 1,
                        self.config.max_retries,
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)
        raise RuntimeError(
            f"Claude API failed after {self.config.max_retries} attempts: {last_exc}"
        ) from last_exc

    # ------------------------------------------------------------------
    # Core summarization logic
    # ------------------------------------------------------------------

    async def _update_summary(self) -> None:
        """Send pending transcriptions to Claude and update the session summary."""
        if not self._pending:
            return

        async with self._update_lock:
            # Snapshot and clear pending
            entries = list(self._pending)
            self._pending.clear()

            # Fetch answered questions to inject into the prompt
            user_answers_block = await self._build_user_answers_block()

            system = self._build_system_prompt()
            user_msg = SESSION_UPDATE_USER.format(
                recent_transcriptions=self._format_transcriptions(entries),
                current_session_summary=self._session_summary or "(inicio de sesión)",
                user_answers_block=user_answers_block if user_answers_block else "\n",
            )

            try:
                result = await self._call_api(system, user_msg)

                # Extract questions and clean the summary
                cleaned, questions = self._extract_questions(result.strip())
                await self._save_questions(questions)

                self._session_summary = cleaned
                self._last_update_time = time.time()
                await self._publish_summary("incremental")
                logger.info(
                    "Session summary updated (%d transcriptions processed)",
                    len(entries),
                )
            except Exception as exc:
                # Put entries back so they aren't lost
                self._pending = entries + self._pending
                logger.error("Summary update failed: %s", exc)
                await self.event_bus.publish(
                    SystemStatusEvent(
                        component="summarizer",
                        status="error",
                        message=f"Summary update failed: {exc}",
                    )
                )

    # ------------------------------------------------------------------
    # BaseSummarizer interface
    # ------------------------------------------------------------------

    async def process_transcription(self, event: TranscriptionEvent) -> None:
        """Buffer the transcription and trigger update if thresholds met."""
        if self.campaign.is_generic:
            character_name = event.speaker_name
        else:
            character_name = self.campaign.speaker_map.get(
                event.speaker_id, event.speaker_name
            )
        self._pending.append(
            TranscriptionEntry(
                speaker_id=event.speaker_id,
                speaker_name=character_name,
                text=event.text,
                timestamp=event.timestamp,
            )
        )

        if self._should_update():
            await self._update_summary()

    async def get_session_summary(self) -> str:
        return self._session_summary

    async def get_campaign_summary(self) -> str:
        return self._campaign_summary
    async def refresh_summary_on_demand(self) -> bool:
        """Generate an on-demand summary snapshot from current pending entries."""
        if self._pending:
            await self._update_summary()
            await self._publish_summary("on_demand")
            return True

        # No new transcriptions: still publish current snapshot so the caller can
        # persist/log the current state as an explicit checkpoint.
        await self._publish_summary("on_demand")
        return True

    # ------------------------------------------------------------------
    # Batch helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Rough token estimate: ~4 characters per token for mixed lang text."""
        return len(text) // 4

    def _split_into_batches(
        self, entries: list[TranscriptionEntry], max_chars: int
    ) -> list[list[TranscriptionEntry]]:
        """Split transcription entries into batches that fit within *max_chars*.

        Each batch is sized so that its formatted text is at most *max_chars*.
        """
        if not entries:
            return []

        batches: list[list[TranscriptionEntry]] = []
        current_batch: list[TranscriptionEntry] = []
        current_chars = 0

        for entry in entries:
            entry_text = f"[{entry.speaker_name}]: {entry.text}\n"
            entry_len = len(entry_text)

            # If a single entry exceeds max_chars, put it alone in a batch
            if entry_len >= max_chars:
                if current_batch:
                    batches.append(current_batch)
                    current_batch = []
                    current_chars = 0
                batches.append([entry])
                continue

            if current_chars + entry_len > max_chars and current_batch:
                batches.append(current_batch)
                current_batch = []
                current_chars = 0

            current_batch.append(entry)
            current_chars += entry_len

        if current_batch:
            batches.append(current_batch)

        return batches

    @staticmethod
    def _parse_finalize_response(result: str) -> tuple[str, str]:
        """Parse the ---SESSION_SUMMARY--- / ---CAMPAIGN_SUMMARY--- response.

        Returns (session_summary, campaign_summary).
        """
        session_part = result
        campaign_part = ""

        if "---SESSION_SUMMARY---" in result and "---CAMPAIGN_SUMMARY---" in result:
            parts = result.split("---CAMPAIGN_SUMMARY---")
            session_part = parts[0].replace("---SESSION_SUMMARY---", "").strip()
            campaign_part = parts[1].strip() if len(parts) > 1 else ""

        return session_part, campaign_part

    # ------------------------------------------------------------------
    # Finalization
    # ------------------------------------------------------------------

    async def finalize_session(self) -> str:
        """Generate a final polished summary and update the campaign summary.

        For long sessions where all transcriptions don't fit in a single API
        call, the pending text is split into batches.  Intermediate batches
        use ``SESSION_UPDATE_USER`` to produce a running summary; the last
        batch uses ``FINALIZE_USER`` to produce the final summary + campaign
        update.
        """
        # Gather all remaining pending transcriptions
        all_entries = list(self._pending)
        self._pending.clear()

        system = self._build_system_prompt()

        # Calculate overhead from the finalize template (without dynamic content)
        template_overhead = len(FINALIZE_USER) + len(self._session_summary or "") + 200
        # Max chars available for transcriptions in a single call
        max_chars_for_transcriptions = self.config.max_input_chars - template_overhead

        if max_chars_for_transcriptions < 1000:
            max_chars_for_transcriptions = 1000  # Absolute minimum

        pending_text = self._format_transcriptions(all_entries) if all_entries else ""

        # Check whether everything fits in a single API call
        if not pending_text or len(pending_text) <= max_chars_for_transcriptions:
            # Single batch — original behavior
            result = await self._call_api(
                system,
                FINALIZE_USER.format(
                    session_summary=self._session_summary or "(sin resumen todavía)",
                    pending_transcriptions=pending_text or "(ninguna)",
                ),
            )
            session_part, campaign_part = self._parse_finalize_response(result)
        else:
            # Multi-batch — progressive summarization
            logger.info(
                "Transcriptions too large for single call (%d chars, max %d). "
                "Using batched finalization.",
                len(pending_text),
                max_chars_for_transcriptions,
            )
            batches = self._split_into_batches(
                all_entries, max_chars_for_transcriptions
            )
            logger.info("Split into %d batch(es)", len(batches))

            running_summary = self._session_summary or "(inicio de sesión)"
            session_part = running_summary
            campaign_part = ""

            for i, batch in enumerate(batches):
                batch_text = self._format_transcriptions(batch)
                is_last = i == len(batches) - 1

                if is_last:
                    # Last batch: use FINALIZE_USER for final + campaign summary
                    user_msg = FINALIZE_USER.format(
                        session_summary=running_summary,
                        pending_transcriptions=batch_text,
                    )
                    result = await self._call_api(system, user_msg)
                    session_part, campaign_part = self._parse_finalize_response(
                        result
                    )
                else:
                    # Intermediate batch: use SESSION_UPDATE_USER for incremental
                    user_msg = SESSION_UPDATE_USER.format(
                        recent_transcriptions=batch_text,
                        current_session_summary=running_summary,
                        user_answers_block="\n",
                    )
                    result = await self._call_api(system, user_msg)
                    running_summary = result.strip()
                    logger.info(
                        "Batch %d/%d processed (%d transcriptions)",
                        i + 1,
                        len(batches),
                        len(batch),
                    )

        self._session_summary = session_part
        if campaign_part:
            self._campaign_summary = campaign_part

        await self._publish_summary("final")

        # Extract structured entities/relationships from the final summary
        await self._extract_entities_and_relationships()

        logger.info("Session finalized")
        return self._session_summary

    async def generate_session_summary_from_transcriptions(
        self, transcription_rows: list[dict]
    ) -> str:
        """Generate a session summary from DB transcription rows (post-hoc).

        Stateless: does not read or modify ``self._pending`` or
        ``self._session_summary``.  Used to retroactively create a session
        summary when one is missing, before generating a campaign summary.
        """
        entries = [
            TranscriptionEntry(
                speaker_id=r.get("speaker_id", ""),
                speaker_name=r.get("speaker_name", "") or r.get("speaker_id", ""),
                text=r.get("text", ""),
                timestamp=r.get("timestamp", 0.0),
            )
            for r in transcription_rows
            if r.get("text", "").strip()
        ]
        if not entries:
            return ""

        system = self._build_system_prompt()
        template_overhead = len(FINALIZE_USER) + 200
        max_chars = max(self.config.max_input_chars - template_overhead, 1000)
        pending_text = self._format_transcriptions(entries)

        if len(pending_text) <= max_chars:
            result = await self._call_api(
                system,
                FINALIZE_USER.format(
                    session_summary="(inicio de sesión)",
                    pending_transcriptions=pending_text,
                ),
            )
            session_part, _ = self._parse_finalize_response(result)
        else:
            batches = self._split_into_batches(entries, max_chars)
            running_summary = "(inicio de sesión)"
            session_part = ""
            for i, batch in enumerate(batches):
                batch_text = self._format_transcriptions(batch)
                is_last = i == len(batches) - 1
                if is_last:
                    result = await self._call_api(
                        system,
                        FINALIZE_USER.format(
                            session_summary=running_summary,
                            pending_transcriptions=batch_text,
                        ),
                    )
                    session_part, _ = self._parse_finalize_response(result)
                else:
                    result = await self._call_api(
                        system,
                        SESSION_UPDATE_USER.format(
                            recent_transcriptions=batch_text,
                            current_session_summary=running_summary,
                            user_answers_block="\n",
                        ),
                    )
                    running_summary = result.strip()

        return session_part or ""

    # ------------------------------------------------------------------
    # Campaign summary generation
    # ------------------------------------------------------------------

    def _build_campaign_system_prompt(self) -> str:
        """Build the system prompt for campaign-level summarization."""
        c = self.campaign

        players_lines = [
            f"- {p.discord_name} juega como {p.character_name}"
            + (f" ({p.character_description})" if p.character_description else "")
            for p in c.players
        ] or ["(ninguno registrado)"]

        npcs_lines = [f"- {n.name}: {n.description}" for n in c.known_npcs] or [
            "(ninguno conocido)"
        ]

        entities_lines = [
            f"- {ent.name} [{ent.entity_type}]: {ent.description}"
            if ent.description else f"- {ent.name} [{ent.entity_type}]"
            for ent in c.entities
        ] or ["(ninguna conocida)"]

        entity_name_map = {
            f"player:{p.discord_id}": p.character_name or p.discord_name
            for p in c.players if p.discord_id
        }
        for n in c.known_npcs:
            if n.name:
                entity_name_map[f"npc:{n.name}"] = n.name
        for loc in c.locations:
            if loc.name:
                entity_name_map[f"loc:{loc.name}"] = loc.name
                entity_name_map[f"location:{loc.name}"] = loc.name
        for ent in c.entities:
            if ent.name:
                entity_name_map[f"ent:{ent.name}"] = ent.name
                entity_name_map[f"entity:{ent.name}"] = ent.name

        relationships_lines = []
        for rel in c.relationships:
            source = entity_name_map.get(rel.source_key, rel.source_key)
            target = entity_name_map.get(rel.target_key, rel.target_key)
            label = rel.relation_type_label or rel.relation_type_key
            line = f"- {source} -> {target}: {label}"
            if rel.notes:
                line += f" ({rel.notes})"
            relationships_lines.append(line)
        if not relationships_lines:
            relationships_lines = ["(ninguna registrada)"]

        custom = f"INSTRUCCIONES ADICIONALES:\n{c.custom_instructions}" if c.custom_instructions else ""

        return CAMPAIGN_SUMMARY_SYSTEM.format(
            game_system=c.game_system,
            name=c.name,
            description=c.description,
            players_block="\n".join(players_lines),
            npcs_block="\n".join(npcs_lines),
            entities_block="\n".join(entities_lines),
            relationships_block="\n".join(relationships_lines),
            custom_instructions=custom,
        )

    async def generate_campaign_summary(
        self,
        session_summaries: list[dict],
        *,
        trigger_session_id: str = "",
    ) -> str:
        """Generate a full campaign summary from all session summaries.

        Handles context limits by progressively compressing older sessions
        before combining with recent ones.

        Args:
            session_summaries: List of dicts with at least 'session_summary' and
                optionally 'started_at' and 'id', ordered oldest→newest.
            trigger_session_id: The session ID that triggered this generation.

        Returns:
            The generated campaign summary text.
        """
        if not session_summaries:
            return ""

        system = self._build_campaign_system_prompt()

        def _format_sessions(sessions: list[dict]) -> str:
            lines = []
            for i, s in enumerate(sessions, 1):
                started = s.get("started_at")
                date_str = ""
                if started:
                    try:
                        import datetime
                        date_str = " (" + datetime.datetime.fromtimestamp(float(started)).strftime("%Y-%m-%d") + ")"
                    except Exception:
                        pass
                sid = s.get("id", f"sesion-{i}")
                summary_text = s.get("session_summary", "").strip()
                lines.append(f"### Sesión {i}{date_str} [{sid}]\n{summary_text}")
            return "\n\n".join(lines)

        # Estimate available chars for session content
        template_overhead = len(CAMPAIGN_SUMMARY_USER) + len(system) + 500
        max_content_chars = self.config.max_input_chars - template_overhead

        sessions_text = _format_sessions(session_summaries)

        if len(sessions_text) <= max_content_chars:
            # Everything fits — single call
            user_msg = CAMPAIGN_SUMMARY_USER.format(
                session_count=len(session_summaries),
                sessions_block=sessions_text,
            )
            return await self._call_api(system, user_msg)

        # Content too large: compress older sessions progressively
        logger.info(
            "Campaign summary: %d chars exceeds limit (%d). Using progressive compression.",
            len(sessions_text),
            max_content_chars,
        )

        # Split sessions roughly in half; compress the older half first
        compressed_summary = ""
        remaining = list(session_summaries)

        while True:
            sessions_text = _format_sessions(remaining)
            if compressed_summary:
                combined = f"### Resumen comprimido de sesiones anteriores\n{compressed_summary}\n\n{sessions_text}"
            else:
                combined = sessions_text

            if len(combined) <= max_content_chars:
                break

            # Compress the oldest half
            split = max(1, len(remaining) // 2)
            older = remaining[:split]
            remaining = remaining[split:]

            older_text = _format_sessions(older)
            if compressed_summary:
                older_text = f"### Resumen comprimido previo\n{compressed_summary}\n\n{older_text}"

            compress_user = CAMPAIGN_SUMMARY_COMPRESS_USER.format(sessions_block=older_text)
            compressed_summary = await self._call_api(system, compress_user)
            logger.info(
                "Compressed %d older session(s) into %d chars",
                len(older),
                len(compressed_summary),
            )

            if not remaining:
                # All sessions were compressed — use the compressed result directly
                return compressed_summary

        # Final call with the (possibly compressed) content
        if compressed_summary:
            sessions_block = f"### Resumen comprimido de sesiones anteriores\n{compressed_summary}\n\n{_format_sessions(remaining)}"
        else:
            sessions_block = _format_sessions(remaining)

        user_msg = CAMPAIGN_SUMMARY_USER.format(
            session_count=len(session_summaries),
            sessions_block=sessions_block,
        )
        result = await self._call_api(system, user_msg)
        logger.info("Campaign summary generated from %d session(s)", len(session_summaries))
        return result

    # ------------------------------------------------------------------
    # Structured extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_extraction_response(text: str) -> dict:
        """Parse the JSON extraction response from the LLM.

        Returns a dict with 'npcs', 'locations', 'entities', 'relationships'
        lists. Missing or invalid lists are normalized to empty lists.
        """
        # Try to find JSON in the response (the LLM may add surrounding text)
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return {"npcs": [], "locations": [], "entities": [], "relationships": []}
        try:
            data = json.loads(match.group())
        except (json.JSONDecodeError, ValueError):
            return {"npcs": [], "locations": [], "entities": [], "relationships": []}

        # Validate structure
        npcs = data.get("npcs", [])
        locations = data.get("locations", [])
        entities = data.get("entities", [])
        relationships = data.get("relationships", [])
        if not isinstance(npcs, list):
            npcs = []
        if not isinstance(locations, list):
            locations = []
        if not isinstance(entities, list):
            entities = []
        if not isinstance(relationships, list):
            relationships = []

        return {
            "npcs": npcs,
            "locations": locations,
            "entities": entities,
            "relationships": relationships,
        }

    async def _extract_entities_and_relationships(self) -> None:
        """Extract and save NPCs, locations, entities and relationships."""
        if not self._database or not self._session_summary:
            return

        known_npcs_lines = [
            f"- {n.name}: {n.description}" for n in self.campaign.known_npcs
        ] or ["(ninguno)"]

        known_locations_lines = [
            f"- {loc.name}: {loc.description}" if loc.description else f"- {loc.name}"
            for loc in self.campaign.locations
        ] or ["(ninguna)"]

        known_entities_lines = [
            f"- ent:{ent.name} [{ent.entity_type}]: {ent.description}"
            if ent.description else f"- ent:{ent.name} [{ent.entity_type}]"
            for ent in self.campaign.entities
        ] or ["(ninguna)"]

        known_relationships_lines = [
            f"- {rel.source_key} -> {rel.target_key}: {rel.relation_type_label or rel.relation_type_key}"
            for rel in self.campaign.relationships
        ] or ["(ninguna)"]

        user_msg = EXTRACTION_USER.format(
            session_summary=self._session_summary,
            known_npcs="\n".join(known_npcs_lines),
            known_locations="\n".join(known_locations_lines),
            known_entities="\n".join(known_entities_lines),
            known_relationships="\n".join(known_relationships_lines),
        )

        try:
            result = await self._call_api(
                "Eres un asistente que extrae información estructurada de "
                "resúmenes de partidas de rol. Responde solo con JSON válido.",
                user_msg,
            )
            extracted = self._parse_extraction_response(result)

            new_npcs = 0
            for npc in extracted["npcs"]:
                name = npc.get("name", "").strip()
                description = npc.get("description", "").strip()
                if not name:
                    continue
                if await self._database.npc_exists(self.campaign.campaign_id, name):
                    continue
                await self._database.save_npc(
                    campaign_id=self.campaign.campaign_id,
                    name=name,
                    description=description,
                    first_seen_session=self._session_id,
                )
                new_npcs += 1

            new_locations = 0
            for loc in extracted["locations"]:
                name = loc.get("name", "").strip()
                description = loc.get("description", "").strip()
                if not name:
                    continue
                if await self._database.location_exists(self.campaign.campaign_id, name):
                    continue
                await self._database.save_location(
                    campaign_id=self.campaign.campaign_id,
                    name=name,
                    description=description,
                    first_seen_session=self._session_id,
                )
                new_locations += 1

            new_entities = 0
            for entity in extracted["entities"]:
                name = str(entity.get("name", "")).strip()
                entity_type = str(entity.get("entity_type", "group") or "group").strip() or "group"
                description = str(entity.get("description", "")).strip()
                if not name:
                    continue
                if await self._database.entity_exists(self.campaign.campaign_id, name):
                    continue
                await self._database.save_entity(
                    campaign_id=self.campaign.campaign_id,
                    name=name,
                    entity_type=entity_type,
                    description=description,
                    first_seen_session=self._session_id,
                )
                new_entities += 1

            relation_seed_map: dict[str, str] = {}
            for p in self.campaign.players:
                if p.discord_id:
                    relation_seed_map[p.character_name.strip().casefold()] = f"player:{p.discord_id}"
            for n in self.campaign.known_npcs:
                relation_seed_map[n.name.strip().casefold()] = f"npc:{n.name}"
            for loc in self.campaign.locations:
                relation_seed_map[loc.name.strip().casefold()] = f"loc:{loc.name}"
            for ent in self.campaign.entities:
                relation_seed_map[ent.name.strip().casefold()] = f"ent:{ent.name}"
            for npc in extracted["npcs"]:
                name = str(npc.get("name", "")).strip()
                if name:
                    relation_seed_map[name.casefold()] = f"npc:{name}"
            for loc in extracted["locations"]:
                name = str(loc.get("name", "")).strip()
                if name:
                    relation_seed_map[name.casefold()] = f"loc:{name}"
            for ent in extracted["entities"]:
                name = str(ent.get("name", "")).strip()
                if name:
                    relation_seed_map[name.casefold()] = f"ent:{name}"

            def _resolve_relation_key(raw_key: str, fallback_name: str = "") -> str:
                candidate = str(raw_key or "").strip()
                if not candidate and fallback_name:
                    candidate = relation_seed_map.get(fallback_name.casefold(), "")
                if candidate.startswith("location:"):
                    candidate = "loc:" + candidate[len("location:"):]
                if candidate.startswith("entity:"):
                    candidate = "ent:" + candidate[len("entity:"):]
                if ":" in candidate:
                    return candidate
                if candidate:
                    return relation_seed_map.get(candidate.casefold(), "")
                return ""

            new_relationships = 0
            for rel in extracted["relationships"]:
                source_key = _resolve_relation_key(
                    str(rel.get("source_key", "")).strip(),
                    str(rel.get("source", "")).strip(),
                )
                target_key = _resolve_relation_key(
                    str(rel.get("target_key", "")).strip(),
                    str(rel.get("target", "")).strip(),
                )
                relation_type = str(rel.get("relation_type", "")).strip()
                category = str(rel.get("category", "general") or "general").strip() or "general"
                notes = str(rel.get("notes", "")).strip()
                if not source_key or not target_key or not relation_type:
                    continue
                try:
                    await self._database.save_character_relationship(
                        self.campaign.campaign_id,
                        source_key,
                        target_key,
                        relation_type,
                        notes=notes,
                        category=category,
                    )
                    new_relationships += 1
                except Exception:
                    continue

            logger.info(
                "Extracted %d new NPC(s), %d location(s), %d entity(s), %d relationship(s)",
                new_npcs,
                new_locations,
                new_entities,
                new_relationships,
            )
        except Exception as exc:
            logger.error("Structured extraction failed: %s", exc)
