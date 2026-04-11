"""Claude-based summarizer using the Anthropic API."""

from __future__ import annotations

import asyncio
import logging
import re
import time

from rpg_scribe.core.database import Database
from rpg_scribe.core.event_bus import EventBus
from rpg_scribe.core.events import (
    SystemStatusEvent,
    TranscriptionEvent,
)
from rpg_scribe.core.models import (
    CampaignContext,
    SummarizerConfig,
)
from rpg_scribe.summarizers.base import BaseSummarizer, TranscriptionEntry
from rpg_scribe.summarizers.entity_extractor import EntityExtractor
from rpg_scribe.summarizers.prompts import (
    CAMPAIGN_SUMMARY_COMPRESS_USER,
    CAMPAIGN_SUMMARY_SYSTEM,
    CAMPAIGN_SUMMARY_USER,
    CHRONOLOGY_SYSTEM_PROMPT,
    CHRONOLOGY_UPDATE_USER,
    CHRONOLOGY_USER,
    FINALIZE_USER,
    GENERIC_SYSTEM_PROMPT,
    QUESTION_PATTERN,
    SESSION_SYSTEM_PROMPT,
    SESSION_UPDATE_USER,
)

logger = logging.getLogger(__name__)


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
        self._extraction_counter: int = (
            0  # Count of _update_summary() calls for periodic extraction
        )
        self._extractor: EntityExtractor | None = None

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

    def _get_extractor(self) -> EntityExtractor:
        """Return the EntityExtractor, creating it lazily."""
        if self._extractor is None:
            self._extractor = EntityExtractor(
                client=self._get_client(),
                model=self.config.model,
                campaign_context=self.campaign,
                entity_repo=self._database,
                event_bus=self.event_bus,
            )
        return self._extractor

    # ------------------------------------------------------------------
    # Shared block builders
    # ------------------------------------------------------------------

    def _build_players_block(self) -> str:
        """Build player→character mapping lines.

        Separates the DM/master from player characters (protagonists) so the
        summariser clearly understands who drives the narrative vs. who narrates.
        """
        dm_id = self.campaign.dm_speaker_id or ""
        dm_lines: list[str] = []
        pc_lines: list[str] = []

        for p in self.campaign.players:
            desc = f" — {p.character_description}" if p.character_description else ""
            if dm_id and p.discord_id == dm_id:
                dm_lines.append(
                    f"- {p.discord_name} es el Director de Juego (DM/Master). "
                    "Narra las escenas, describe el entorno, interpreta a todos "
                    "los PNJs y controla los eventos del mundo."
                )
            else:
                pc_lines.append(
                    f"- {p.discord_name} juega como {p.character_name} "
                    f"(personaje jugador / protagonista){desc}"
                )

        if not pc_lines:
            pc_lines = ["(ninguno registrado)"]

        parts: list[str] = []
        if dm_lines:
            parts.append("DIRECTOR DE JUEGO:\n" + "\n".join(dm_lines))
        parts.append(
            "PERSONAJES JUGADORES (protagonistas de la historia):\n"
            + "\n".join(pc_lines)
        )
        return "\n".join(parts)

    def _build_npcs_block(self) -> str:
        """Build known NPC lines."""
        lines = [
            f"- {n.name}: {n.description}" for n in self.campaign.known_npcs
        ] or ["(ninguno conocido)"]
        return "\n".join(lines)

    def _build_locations_block(self) -> str:
        """Build known location lines."""
        lines = [
            f"- {loc.name}: {loc.description}" if loc.description else f"- {loc.name}"
            for loc in self.campaign.locations
        ] or ["(ninguna conocida)"]
        return "\n".join(lines)

    def _build_entity_name_map(self) -> dict[str, str]:
        """Map entity keys to display names for relationship resolution."""
        c = self.campaign
        name_map: dict[str, str] = {
            f"player:{p.discord_id}": p.character_name or p.discord_name
            for p in c.players
            if p.discord_id
        }
        for n in c.known_npcs:
            if n.name:
                name_map[f"npc:{n.name}"] = n.name
        for loc in c.locations:
            if loc.name:
                name_map[f"loc:{loc.name}"] = loc.name
                name_map[f"location:{loc.name}"] = loc.name
        for ent in c.entities:
            if ent.name:
                name_map[f"ent:{ent.name}"] = ent.name
                name_map[f"entity:{ent.name}"] = ent.name
        return name_map

    def _build_relationships_block(self) -> str:
        """Build known relationship lines."""
        entity_name_map = self._build_entity_name_map()
        lines: list[str] = []
        for rel in self.campaign.relationships:
            source = entity_name_map.get(rel.source_key, rel.source_key)
            target = entity_name_map.get(rel.target_key, rel.target_key)
            label = rel.relation_type_label or rel.relation_type_key
            line = f"- {source} -> {target}: {label}"
            if rel.notes:
                line += f" ({rel.notes})"
            lines.append(line)
        if not lines:
            lines = ["(ninguna registrada)"]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Prompt helpers
    # ------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        """Build the system prompt with campaign context."""
        c = self.campaign

        if c.is_generic:
            return GENERIC_SYSTEM_PROMPT

        dm_name = "DM"
        for p in c.players:
            if p.discord_id == c.dm_speaker_id:
                dm_name = p.discord_name
                break

        entities_lines = [
            f"- {ent.name} [{ent.entity_type}]: {ent.description}"
            if ent.description
            else f"- {ent.name} [{ent.entity_type}]"
            for ent in c.entities
        ] or ["(ninguna conocida)"]

        custom = ""
        if c.custom_instructions:
            custom = f"INSTRUCCIONES ADICIONALES:\n{c.custom_instructions}"

        return SESSION_SYSTEM_PROMPT.format(
            game_system=c.game_system,
            name=c.name,
            description=c.description,
            campaign_summary=c.campaign_summary or "(primera sesión)",
            players_block=self._build_players_block(),
            dm_name=dm_name,
            npcs_block=self._build_npcs_block(),
            locations_block=self._build_locations_block(),
            entities_block="\n".join(entities_lines),
            relationships_block=self._build_relationships_block(),
            custom_instructions=custom,
        )

    # Heuristic patterns that signal a scene change when spoken by the DM.
    _SCENE_CHANGE_PATTERNS: list[str] = [
        "mientras tanto",
        "por otro lado",
        "en otro lugar",
        "meanwhile",
        "al mismo tiempo",
        "en ese mismo momento",
    ]

    def _format_transcriptions(self, entries: list[TranscriptionEntry]) -> str:
        """Format transcription entries as readable text.

        The configured DM/master speaker is explicitly tagged so the model
        can treat those lines as narration/scene control or multi-NPC speech.
        Scene-change markers are inserted when the DM uses transition phrases
        that signal parallel or simultaneous scenes.
        """
        dm_id = ""
        if not self.campaign.is_generic:
            dm_id = self.campaign.dm_speaker_id or ""
        lines: list[str] = []
        for e in entries:
            speaker = e.speaker_name
            is_dm = dm_id and e.speaker_id == dm_id
            if is_dm:
                speaker = f"{speaker} [MASTER]"
                text_lower = e.text.lower()
                if any(p in text_lower for p in self._SCENE_CHANGE_PATTERNS):
                    lines.append("--- [CAMBIO DE ESCENA] ---")
            prefix = "[META]" if not e.is_ingame else ""
            lines.append(f"{prefix}[{speaker}]: {e.text}")
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
        await self._database.mark_questions_processed([row["id"] for row in answered])
        return "\nRESPUESTAS DEL USUARIO:\n" + "\n".join(lines) + "\n\n"

    # ------------------------------------------------------------------
    # API call with retry
    # ------------------------------------------------------------------

    async def _call_api(
        self, system: str, user_message: str, *, purpose: str = ""
    ) -> str:
        """Call the Claude API with retry and exponential backoff."""
        label = purpose or "api_call"
        logger.info(
            "Calling Claude API [%s] (model=%s, max_tokens=%d, input≈%d chars)",
            label,
            self.config.model,
            self.config.max_tokens,
            len(system) + len(user_message),
        )
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

    async def generate_title_from_summary(self, summary: str) -> str:
        """Generate a short session title (≤60 chars) from an existing summary.

        Returns a generic fallback if the summary is empty or the LLM call fails.
        """
        import datetime

        if not summary or not summary.strip():
            today = datetime.date.today().strftime("%Y-%m-%d")
            return f"Sesión {today}"

        system = (
            "Eres un asistente que genera títulos cortos y descriptivos para sesiones de rol. "
            "El título debe tener máximo 60 caracteres. "
            "Responde ÚNICAMENTE con el título, sin comillas ni explicaciones."
        )
        user = f"Resumen de la sesión:\n\n{summary[:2000]}"
        try:
            title = await self._call_api(system, user, purpose="generate_title")
            title = title.strip().strip('"').strip("'")
            return title[:60] if title else f"Sesión {datetime.date.today():%Y-%m-%d}"
        except Exception:
            import datetime as _dt
            return f"Sesión {_dt.date.today():%Y-%m-%d}"

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
            chronology_block = (
                f"CRONOLOGÍA DE LA SESIÓN:\n{self._session_chronology}\n\n"
                if self._session_chronology
                else ""
            )
            user_msg = SESSION_UPDATE_USER.format(
                recent_transcriptions=self._format_transcriptions(entries),
                current_session_summary=self._session_summary or "(inicio de sesión)",
                user_answers_block=user_answers_block if user_answers_block else "\n",
                chronology_block=chronology_block,
            )

            try:
                result = await self._call_api(
                    system, user_msg, purpose="session_summary_update"
                )

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

                # Periodic entity extraction (non-blocking background task)
                self._extraction_counter += 1
                n = self.config.extraction_every_n_updates
                if n > 0 and self._extraction_counter % n == 0:
                    asyncio.create_task(
                        self._extract_entities(),
                        name=f"entity-extraction-{self._session_id}-{self._extraction_counter}",
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
        """Buffer the transcription for on-demand or finalization summary."""
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

        # Step 1: Generate chronology first so the final narrative can use it as context
        if all_entries:
            try:
                self._session_chronology = await self.generate_chronology(
                    entries=all_entries,
                )
                logger.info("Session chronology generated")
            except Exception as exc:
                logger.error("Chronology generation failed: %s", exc)
                self._session_chronology = ""

        chronology_block = (
            f"CRONOLOGÍA DE LA SESIÓN:\n{self._session_chronology}\n\n"
            if self._session_chronology
            else ""
        )

        # Step 2: Generate final narrative summary (with chronology as context)
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
                    chronology_block=chronology_block,
                ),
                purpose="finalize_session",
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
                        chronology_block=chronology_block,
                    )
                    result = await self._call_api(
                        system, user_msg, purpose="finalize_session_last_batch"
                    )
                    session_part, campaign_part = self._parse_finalize_response(result)
                else:
                    # Intermediate batch: use SESSION_UPDATE_USER for incremental
                    user_msg = SESSION_UPDATE_USER.format(
                        recent_transcriptions=batch_text,
                        current_session_summary=running_summary,
                        user_answers_block="\n",
                        chronology_block="",
                    )
                    result = await self._call_api(
                        system, user_msg, purpose=f"finalize_session_batch_{i + 1}"
                    )
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
        await self._extract_entities()

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
                is_ingame=r.get("is_ingame", True)
                if r.get("is_ingame") is not None
                else True,
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
                    chronology_block="",
                ),
                purpose="posthoc_session_summary",
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
                            chronology_block="",
                        ),
                        purpose="posthoc_session_summary_last_batch",
                    )
                    session_part, _ = self._parse_finalize_response(result)
                else:
                    result = await self._call_api(
                        system,
                        SESSION_UPDATE_USER.format(
                            recent_transcriptions=batch_text,
                            current_session_summary=running_summary,
                            user_answers_block="\n",
                            chronology_block="",
                        ),
                        purpose=f"posthoc_session_summary_batch_{i + 1}",
                    )
                    running_summary = result.strip()

        return session_part or ""

    # ------------------------------------------------------------------
    # Chronology generation
    # ------------------------------------------------------------------

    def _build_chronology_system_prompt(self) -> str:
        """Build the system prompt for chronological timeline generation.

        Includes game_system, description, players, locations, NPCs, and
        relationships. Does not include entities or campaign summary.
        """
        c = self.campaign
        if c.is_generic:
            return CHRONOLOGY_SYSTEM_PROMPT.format(
                game_system="(genérico)",
                name="(sin campaña)",
                description="Resumen genérico de conversación",
                players_block="(desconocidos)",
                locations_block="(ninguna conocida)",
                npcs_block="(ninguno conocido)",
                relationships_block="(ninguna registrada)",
            )

        return CHRONOLOGY_SYSTEM_PROMPT.format(
            game_system=c.game_system,
            name=c.name,
            description=c.description,
            players_block=self._build_players_block(),
            locations_block=self._build_locations_block(),
            npcs_block=self._build_npcs_block(),
            relationships_block=self._build_relationships_block(),
        )

    async def generate_chronology(
        self,
        entries: list[TranscriptionEntry],
    ) -> str:
        """Generate a chronological timeline using progressive batching.

        If all transcriptions fit in a single API call, generates in one shot.
        Otherwise, splits into batches and builds the chronology progressively,
        extending it with each new batch of transcriptions.
        """
        if not entries:
            return ""

        system = self._build_chronology_system_prompt()
        template_overhead = len(CHRONOLOGY_USER) + 200
        max_chars = max(self.config.max_input_chars - template_overhead, 1000)

        transcription_text = self._format_transcriptions(entries)

        if len(transcription_text) <= max_chars:
            result = await self._call_api(
                system,
                CHRONOLOGY_USER.format(
                    transcriptions=transcription_text,
                ),
                purpose="chronology",
            )
            return result.strip()

        # Multi-batch: progressive chronology building
        batches = self._split_into_batches(entries, max_chars)
        logger.info(
            "Transcriptions too large for single chronology call (%d chars, max %d). "
            "Split into %d batch(es).",
            len(transcription_text),
            max_chars,
            len(batches),
        )

        parts: list[str] = []
        for i, batch in enumerate(batches):
            batch_text = self._format_transcriptions(batch)
            if not parts:
                # First batch: generate initial chronology
                result = await self._call_api(
                    system,
                    CHRONOLOGY_USER.format(
                        transcriptions=batch_text,
                    ),
                    purpose=f"chronology_batch_{i + 1}",
                )
            else:
                # Subsequent batches: pass only last scene for continuity
                last_scene = self._extract_last_scene(parts[-1])
                result = await self._call_api(
                    system,
                    CHRONOLOGY_UPDATE_USER.format(
                        last_scene=last_scene,
                        transcriptions=batch_text,
                    ),
                    purpose=f"chronology_batch_{i + 1}",
                )
            parts.append(result.strip())
            logger.info(
                "Chronology batch %d/%d processed (%d transcriptions)",
                i + 1,
                len(batches),
                len(batch),
            )

        return "\n\n".join(parts)

    @staticmethod
    def _extract_last_scene(chronology: str) -> str:
        """Extract the last scene/paragraph block from a chronology text.

        Splits on double newlines and returns the last non-empty block.
        """
        blocks = [b.strip() for b in chronology.split("\n\n") if b.strip()]
        return blocks[-1] if blocks else chronology

    async def generate_chronology_from_transcriptions(
        self, transcription_rows: list[dict], session_summary: str = ""
    ) -> str:
        """Generate a chronology from DB transcription rows (post-hoc).

        Stateless: does not modify instance state.
        """
        entries = [
            TranscriptionEntry(
                speaker_id=r.get("speaker_id", ""),
                speaker_name=r.get("speaker_name", "") or r.get("speaker_id", ""),
                text=r.get("text", ""),
                timestamp=r.get("timestamp", 0.0),
                is_ingame=r.get("is_ingame", True)
                if r.get("is_ingame") is not None
                else True,
            )
            for r in transcription_rows
            if r.get("text", "").strip()
        ]
        if not entries:
            return ""

        return await self.generate_chronology(entries=entries)

    # ------------------------------------------------------------------
    # Campaign summary generation
    # ------------------------------------------------------------------

    def _build_campaign_system_prompt(self) -> str:
        """Build the system prompt for campaign-level summarization."""
        c = self.campaign

        entities_lines = [
            f"- {ent.name} [{ent.entity_type}]: {ent.description}"
            if ent.description
            else f"- {ent.name} [{ent.entity_type}]"
            for ent in c.entities
        ] or ["(ninguna conocida)"]

        custom = (
            f"INSTRUCCIONES ADICIONALES:\n{c.custom_instructions}"
            if c.custom_instructions
            else ""
        )

        return CAMPAIGN_SUMMARY_SYSTEM.format(
            game_system=c.game_system,
            name=c.name,
            description=c.description,
            players_block=self._build_players_block(),
            npcs_block=self._build_npcs_block(),
            entities_block="\n".join(entities_lines),
            relationships_block=self._build_relationships_block(),
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

                        date_str = (
                            " ("
                            + datetime.datetime.fromtimestamp(float(started)).strftime(
                                "%Y-%m-%d"
                            )
                            + ")"
                        )
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
            return await self._call_api(
                system, user_msg, purpose="campaign_summary"
            )

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

            compress_user = CAMPAIGN_SUMMARY_COMPRESS_USER.format(
                sessions_block=older_text
            )
            compressed_summary = await self._call_api(
                system, compress_user, purpose="campaign_summary_compress"
            )
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
        result = await self._call_api(
            system, user_msg, purpose="campaign_summary"
        )
        logger.info(
            "Campaign summary generated from %d session(s)", len(session_summaries)
        )
        return result

    # ------------------------------------------------------------------
    # Structured entity extraction (delegated to EntityExtractor)
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_extraction_response(text: str) -> dict:
        """Parse the JSON extraction response. Delegates to EntityExtractor."""
        return EntityExtractor._parse_extraction_response(text)

    async def extract_entities_from_summary(
        self,
        session_id: str,
        session_summary: str,
    ) -> dict[str, list[str]]:
        """Extract and persist new NPCs, locations, entities and relationships.

        Delegates to EntityExtractor. Public interface kept for backward compat.
        """
        return await self._get_extractor().extract_from_summary(session_id, session_summary)

    async def _extract_entities(self) -> None:
        """Run entity extraction for the current session and publish EntitiesUpdatedEvent."""
        await self._get_extractor().extract_and_publish(
            self._session_id, self._session_summary
        )
