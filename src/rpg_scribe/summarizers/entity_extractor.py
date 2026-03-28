"""Entity extraction from session summaries using Claude."""

from __future__ import annotations

import asyncio
import json
import logging
import re

from rpg_scribe.core.event_bus import EventBus
from rpg_scribe.core.events import EntitiesUpdatedEvent
from rpg_scribe.core.models import CampaignContext, EntityInfo, LocationInfo, NPCInfo
from rpg_scribe.summarizers.prompts import EXTRACTION_USER

logger = logging.getLogger(__name__)


class EntityExtractor:
    def __init__(
        self,
        client,  # anthropic AsyncAnthropic client
        model: str,
        campaign_context: CampaignContext,
        entity_repo,  # EntityRepository, Database, or any duck-typed equivalent
        event_bus: EventBus,
    ) -> None:
        self._client = client
        self._model = model
        self._campaign = campaign_context
        self._repo = entity_repo
        self._event_bus = event_bus

    @staticmethod
    def _parse_extraction_response(text: str) -> dict:
        """Parse the JSON extraction response from the LLM.

        Returns a dict with 'npcs', 'locations', 'entities', 'relationships'
        lists. Missing or invalid lists are normalized to empty lists.
        """
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return {"npcs": [], "locations": [], "entities": [], "relationships": []}
        try:
            data = json.loads(match.group())
        except (json.JSONDecodeError, ValueError):
            return {"npcs": [], "locations": [], "entities": [], "relationships": []}

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

    async def _call_api(self, system: str, user_message: str) -> str:
        """Call the Claude API with minimal retry logic."""
        max_retries = 3
        retry_base_delay_s = 1.0
        max_tokens = 4096
        last_exc: Exception | None = None
        for attempt in range(max_retries):
            try:
                response = await self._client.messages.create(
                    model=self._model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user_message}],
                )
                return response.content[0].text
            except Exception as exc:
                last_exc = exc
                if attempt < max_retries - 1:
                    delay = retry_base_delay_s * (2**attempt)
                    logger.warning(
                        "Claude API call failed (attempt %d/%d): %s — retrying in %.1fs",
                        attempt + 1,
                        max_retries,
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)
        raise RuntimeError(
            f"Claude API failed after {max_retries} attempts: {last_exc}"
        ) from last_exc

    async def extract_from_summary(
        self,
        session_id: str,
        session_summary: str,
    ) -> dict[str, list[str]]:
        """Extract and persist new NPCs, locations, entities and relationships.

        Public interface usable both during live sessions and for retroactive
        processing of historical sessions. Updates the in-memory campaign
        context after saving so subsequent system prompts include new entities.

        Returns:
            dict with 'new_npcs', 'new_locations', 'new_entities', 'new_relationships'.
        """
        results: dict[str, list[str]] = {
            "new_npcs": [],
            "new_locations": [],
            "new_entities": [],
            "new_relationships": [],
        }

        if not self._repo or not session_summary:
            return results
        if self._campaign.is_generic:
            return results

        # Build known-context blocks for the prompt (dedup layer 1: LLM skips known)
        known_npcs_lines = [
            f"- {n.name}: {n.description}" for n in self._campaign.known_npcs
        ] or ["(ninguno)"]

        known_locations_lines = [
            f"- {loc.name}: {loc.description}" if loc.description else f"- {loc.name}"
            for loc in self._campaign.locations
        ] or ["(ninguna)"]

        known_entities_lines = [
            f"- ent:{ent.name} [{ent.entity_type}]: {ent.description}"
            if ent.description
            else f"- ent:{ent.name} [{ent.entity_type}]"
            for ent in self._campaign.entities
        ] or ["(ninguna)"]

        known_relationships_lines = [
            f"- {rel.source_key} -> {rel.target_key}: {rel.relation_type_label or rel.relation_type_key}"
            for rel in self._campaign.relationships
        ] or ["(ninguna)"]

        # Build a simple player list so the LLM knows who is a PC (not NPC)
        players_lines = [
            f"- {p.discord_name} juega como {p.character_name}"
            for p in self._campaign.players
            if p.character_name
        ] or ["(ninguno registrado)"]

        user_msg = EXTRACTION_USER.format(
            session_summary=session_summary,
            players_block="\n".join(players_lines),
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

            # ── NPCs ───────────────────────────────────────────────
            for npc in extracted["npcs"]:
                name = npc.get("name", "").strip()
                description = npc.get("description", "").strip()
                if not name:
                    continue
                if await self._repo.npc_exists(self._campaign.campaign_id, name):
                    continue
                await self._repo.save_npc(
                    campaign_id=self._campaign.campaign_id,
                    name=name,
                    description=description,
                    first_seen_session=session_id,
                )
                self._campaign.known_npcs.append(
                    NPCInfo(name=name, description=description)
                )
                results["new_npcs"].append(name)

            # ── Locations ──────────────────────────────────────────
            for loc in extracted["locations"]:
                name = loc.get("name", "").strip()
                description = loc.get("description", "").strip()
                if not name:
                    continue
                if await self._repo.location_exists(
                    self._campaign.campaign_id, name
                ):
                    continue
                await self._repo.save_location(
                    campaign_id=self._campaign.campaign_id,
                    name=name,
                    description=description,
                    first_seen_session=session_id,
                )
                self._campaign.locations.append(
                    LocationInfo(name=name, description=description)
                )
                results["new_locations"].append(name)

            # ── Entities ───────────────────────────────────────────
            for entity in extracted["entities"]:
                name = str(entity.get("name", "")).strip()
                entity_type = (
                    str(entity.get("entity_type", "group") or "group").strip()
                    or "group"
                )
                description = str(entity.get("description", "")).strip()
                if not name:
                    continue
                if await self._repo.entity_exists(self._campaign.campaign_id, name):
                    continue
                await self._repo.save_entity(
                    campaign_id=self._campaign.campaign_id,
                    name=name,
                    entity_type=entity_type,
                    description=description,
                    first_seen_session=session_id,
                )
                self._campaign.entities.append(
                    EntityInfo(
                        name=name, entity_type=entity_type, description=description
                    )
                )
                results["new_entities"].append(name)

            # ── Build relation seed map (all known + newly saved) ──
            relation_seed_map: dict[str, str] = {}
            for p in self._campaign.players:
                if p.discord_id:
                    relation_seed_map[p.character_name.strip().casefold()] = (
                        f"player:{p.discord_id}"
                    )
            for n in self._campaign.known_npcs:
                relation_seed_map[n.name.strip().casefold()] = f"npc:{n.name}"
            for loc in self._campaign.locations:
                relation_seed_map[loc.name.strip().casefold()] = f"loc:{loc.name}"
            for ent in self._campaign.entities:
                relation_seed_map[ent.name.strip().casefold()] = f"ent:{ent.name}"

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

            # ── Auto-create entities referenced in relationships ──
            async def _ensure_entity_from_key(key: str) -> None:
                """If key is ent:Name and the entity doesn't exist, create it."""
                if not key.startswith("ent:"):
                    return
                ent_name = key[4:].strip()
                if not ent_name:
                    return
                if await self._repo.entity_exists(
                    self._campaign.campaign_id, ent_name
                ):
                    return
                await self._repo.save_entity(
                    campaign_id=self._campaign.campaign_id,
                    name=ent_name,
                    entity_type="group",
                    description="",
                    first_seen_session=session_id,
                )
                self._campaign.entities.append(
                    EntityInfo(name=ent_name, entity_type="group", description="")
                )
                relation_seed_map[ent_name.casefold()] = f"ent:{ent_name}"
                results["new_entities"].append(ent_name)

            # ── Relationships ──────────────────────────────────────
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
                category = (
                    str(rel.get("category", "general") or "general").strip()
                    or "general"
                )
                notes = str(rel.get("notes", "")).strip()
                if not source_key or not target_key or not relation_type:
                    continue
                try:
                    # Auto-create entities referenced in relationships
                    await _ensure_entity_from_key(source_key)
                    await _ensure_entity_from_key(target_key)
                    await self._repo.save_character_relationship(
                        self._campaign.campaign_id,
                        source_key,
                        target_key,
                        relation_type,
                        notes=notes,
                        category=category,
                    )
                    results["new_relationships"].append(
                        f"{source_key} -> {target_key}: {relation_type}"
                    )
                except Exception:
                    continue

            logger.info(
                "Extraction: %d new NPC(s), %d new location(s), %d new entity(s), %d new relationship(s)",
                len(results["new_npcs"]),
                len(results["new_locations"]),
                len(results["new_entities"]),
                len(results["new_relationships"]),
            )
        except Exception as exc:
            logger.error("Entity extraction failed: %s", exc)

        return results

    async def extract_and_publish(self, session_id: str, summary: str) -> None:
        """Run entity extraction for the given session and publish EntitiesUpdatedEvent."""
        results = await self.extract_from_summary(session_id, summary)
        if any(results.values()):
            await self._event_bus.publish(
                EntitiesUpdatedEvent(
                    campaign_id=self._campaign.campaign_id,
                    session_id=session_id,
                    new_npcs=tuple(results["new_npcs"]),
                    new_locations=tuple(results["new_locations"]),
                    new_entities=tuple(results["new_entities"]),
                    new_relationships=tuple(results["new_relationships"]),
                )
            )
