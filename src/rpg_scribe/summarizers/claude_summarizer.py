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

{custom_instructions}

INSTRUCCIONES:
1. Escribe en tercera persona, estilo narrativo.
2. Distingue entre lo que dicen los personajes (in-game) y las \
conversaciones de los jugadores (meta-rol). El meta-rol NO va \
en el resumen narrativo, pero puedes anotarlo como [META] si \
es relevante (decisiones de grupo, dudas de reglas, etc.).
3. El DM ({dm_name}) habla como múltiples PNJs. Intenta identificar \
qué PNJ habla basándote en el contexto.
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

EXTRACTION_USER = """\
A partir del siguiente resumen de sesión, extrae los PNJs nuevos y \
localizaciones nuevas que hayan aparecido.

RESUMEN DE LA SESIÓN:
{session_summary}

PNJS YA CONOCIDOS (NO los incluyas de nuevo):
{known_npcs}

Responde ÚNICAMENTE con un JSON válido con este formato exacto, sin \
texto adicional antes o después:

{{"npcs": [{{"name": "Nombre del PNJ", "description": "Breve descripción"}}], \
"locations": [{{"name": "Nombre del lugar", "description": "Breve descripción"}}]}}

Si no hay PNJs o localizaciones nuevas, devuelve listas vacías.
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
            custom_instructions=custom,
        )

    @staticmethod
    def _format_transcriptions(entries: list[TranscriptionEntry]) -> str:
        """Format transcription entries as readable text."""
        lines: list[str] = []
        for e in entries:
            lines.append(f"[{e.speaker_name}]: {e.text}")
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

        # Extract NPCs and locations from the final summary
        await self._extract_npcs_and_locations()

        logger.info("Session finalized")
        return self._session_summary

    # ------------------------------------------------------------------
    # NPC / location extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_extraction_response(text: str) -> dict:
        """Parse the JSON extraction response from the LLM.

        Returns a dict with 'npcs' and 'locations' lists, or empty lists
        if parsing fails.
        """
        # Try to find JSON in the response (the LLM may add surrounding text)
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return {"npcs": [], "locations": []}
        try:
            data = json.loads(match.group())
        except (json.JSONDecodeError, ValueError):
            return {"npcs": [], "locations": []}

        # Validate structure
        npcs = data.get("npcs", [])
        locations = data.get("locations", [])
        if not isinstance(npcs, list):
            npcs = []
        if not isinstance(locations, list):
            locations = []

        return {"npcs": npcs, "locations": locations}

    async def _extract_npcs_and_locations(self) -> None:
        """Make a second LLM call to extract new NPCs and locations, then save them."""
        if not self._database or not self._session_summary:
            return

        known_npcs_lines = [
            f"- {n.name}: {n.description}" for n in self.campaign.known_npcs
        ] or ["(ninguno)"]

        user_msg = EXTRACTION_USER.format(
            session_summary=self._session_summary,
            known_npcs="\n".join(known_npcs_lines),
        )

        try:
            result = await self._call_api(
                "Eres un asistente que extrae información estructurada de "
                "resúmenes de partidas de rol. Responde solo con JSON válido.",
                user_msg,
            )
            extracted = self._parse_extraction_response(result)

            for npc in extracted["npcs"]:
                name = npc.get("name", "").strip()
                description = npc.get("description", "").strip()
                if not name:
                    continue
                if await self._database.npc_exists(
                    self.campaign.campaign_id, name
                ):
                    continue
                await self._database.save_npc(
                    campaign_id=self.campaign.campaign_id,
                    name=name,
                    description=description,
                    first_seen_session=self._session_id,
                )

            logger.info(
                "Extracted %d new NPC(s) and %d location(s)",
                len(extracted["npcs"]),
                len(extracted["locations"]),
            )
        except Exception as exc:
            logger.error("NPC/location extraction failed: %s", exc)
