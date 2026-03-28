"""EntityRepository — players, NPCs, locations, campaign entities, relationships, questions."""

from __future__ import annotations

import difflib
import json
import re
import time
import unicodedata
from typing import Any


def normalize_relationship_type_label(value: str) -> str:
    """Normalize a relationship type label for matching/deduplication."""
    text = value.strip().lower()
    text = text.replace("_", " ").replace("-", " ")
    text = "".join(
        ch
        for ch in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(ch)
    )
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"^(es|era|fue|son|esta|estaba|estuvieron)\s+", "", text)
    text = re.sub(r"^(el|la|los|las|un|una)\s+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or "relacion"


def _relation_similarity(a: str, b: str) -> float:
    """Compute a robust fuzzy similarity between canonical labels."""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    seq = difflib.SequenceMatcher(None, a, b).ratio()
    if a in b or b in a:
        seq = max(seq, min(len(a), len(b)) / max(len(a), len(b)))
    a_tokens = set(a.split())
    b_tokens = set(b.split())
    if a_tokens and b_tokens:
        jaccard = len(a_tokens & b_tokens) / len(a_tokens | b_tokens)
        return max(seq, jaccard)
    return seq


class EntityRepository:
    def __init__(self, db) -> None:
        self._db = db

    @property
    def conn(self):
        return self._db.conn

    # ── Players ─────────────────────────────────────────────────────

    async def save_player(
        self,
        campaign_id: str,
        discord_id: str,
        discord_name: str,
        character_name: str,
        character_description: str = "",
    ) -> str:
        """Insert a new player record and return its ID."""
        import uuid

        player_id = str(uuid.uuid4())
        await self.conn.execute(
            "INSERT INTO players (id, campaign_id, discord_id, discord_name, "
            "character_name, character_description) VALUES (?, ?, ?, ?, ?, ?)",
            (
                player_id,
                campaign_id,
                discord_id,
                discord_name,
                character_name,
                character_description,
            ),
        )
        await self.conn.commit()
        return player_id

    async def get_players(self, campaign_id: str) -> list[dict[str, Any]]:
        """Get all players for a campaign."""
        cursor = await self.conn.execute(
            "SELECT * FROM players WHERE campaign_id = ? ORDER BY discord_name",
            (campaign_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def player_exists(self, campaign_id: str, discord_id: str) -> bool:
        """Check if a player with the given discord_id already exists."""
        cursor = await self.conn.execute(
            "SELECT 1 FROM players WHERE campaign_id = ? AND discord_id = ? LIMIT 1",
            (campaign_id, discord_id),
        )
        return await cursor.fetchone() is not None

    async def update_player(self, player_id: str, **fields: Any) -> None:
        """Update specific fields of a player record.

        Accepted fields: discord_name, character_name, character_description.
        """
        allowed = {"discord_name", "character_name", "character_description"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [player_id]
        await self.conn.execute(f"UPDATE players SET {set_clause} WHERE id = ?", values)
        await self.conn.commit()

    # ── NPCs ─────────────────────────────────────────────────────────

    async def save_npc(
        self,
        campaign_id: str,
        name: str,
        description: str = "",
        first_seen_session: str = "",
    ) -> None:
        """Insert a new NPC record."""
        import uuid

        npc_id = str(uuid.uuid4())
        await self.conn.execute(
            "INSERT INTO npcs (id, campaign_id, name, description, first_seen_session) "
            "VALUES (?, ?, ?, ?, ?)",
            (npc_id, campaign_id, name, description, first_seen_session),
        )
        await self.conn.commit()

    async def get_npcs(self, campaign_id: str) -> list[dict[str, Any]]:
        """Get all NPCs for a campaign."""
        cursor = await self.conn.execute(
            "SELECT * FROM npcs WHERE campaign_id = ? "
            "AND (merged_into IS NULL OR merged_into = '') "
            "ORDER BY name",
            (campaign_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def get_merged_npcs_map(
        self, campaign_id: str
    ) -> dict[str, list[dict[str, Any]]]:
        """Get merged NPC children grouped by parent NPC name."""
        cursor = await self.conn.execute(
            "SELECT * FROM npcs WHERE campaign_id = ? "
            "AND (merged_into IS NOT NULL AND merged_into != '') "
            "ORDER BY merged_into, name",
            (campaign_id,),
        )
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in await cursor.fetchall():
            item = dict(row)
            parent = str(item.get("merged_into", "") or "")
            if not parent:
                continue
            grouped.setdefault(parent, []).append(item)
        return grouped

    async def npc_exists(self, campaign_id: str, name: str) -> bool:
        """Check if an NPC with the given name already exists in a campaign.

        Uses case-insensitive comparison so "Gareth" and "gareth"
        are treated as the same NPC (consistent with location_exists/entity_exists).
        """
        cursor = await self.conn.execute(
            "SELECT 1 FROM npcs WHERE campaign_id = ? AND lower(name) = lower(?) LIMIT 1",
            (campaign_id, name),
        )
        return await cursor.fetchone() is not None

    async def update_npc(self, npc_id: str, **fields: Any) -> None:
        """Update specific fields of an NPC record.

        Accepted fields: name, description.
        """
        allowed = {"name", "description"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [npc_id]
        await self.conn.execute(f"UPDATE npcs SET {set_clause} WHERE id = ?", values)
        await self.conn.commit()

    async def update_merged_npc(
        self,
        campaign_id: str,
        npc_id: str,
        *,
        name: str,
        description: str,
        merged_into: str,
    ) -> None:
        """Update a merged NPC child and optionally move/unmerge it."""
        target_parent = merged_into.strip()
        new_name = name.strip()
        if not new_name:
            raise ValueError("name is required")

        cursor = await self.conn.execute(
            "SELECT * FROM npcs WHERE id = ? AND campaign_id = ? LIMIT 1",
            (npc_id, campaign_id),
        )
        row = await cursor.fetchone()
        if row is None:
            raise ValueError("Merged NPC not found")
        current_name = str(row["name"])

        cursor = await self.conn.execute(
            "SELECT 1 FROM npcs WHERE campaign_id = ? AND lower(name) = lower(?) AND id != ? LIMIT 1",
            (campaign_id, new_name, npc_id),
        )
        if await cursor.fetchone():
            raise ValueError("Another NPC already has that name")

        if target_parent:
            cursor = await self.conn.execute(
                "SELECT 1 FROM npcs WHERE campaign_id = ? AND lower(name) = lower(?) "
                "AND (merged_into IS NULL OR merged_into = '') LIMIT 1",
                (campaign_id, target_parent),
            )
            if await cursor.fetchone() is None:
                raise ValueError("Parent NPC not found")
            if new_name.casefold() == target_parent.casefold():
                raise ValueError("Child NPC name cannot match parent name")

        await self.conn.execute(
            "UPDATE npcs SET name = ?, description = ?, merged_into = ? WHERE id = ? AND campaign_id = ?",
            (new_name, description.strip(), target_parent, npc_id, campaign_id),
        )
        await self._rewrite_relationship_entity_keys(
            campaign_id,
            {f"npc:{current_name}": f"npc:{new_name}"},
        )
        await self.conn.commit()

    async def merge_npcs(
        self,
        campaign_id: str,
        source_name: str,
        target_name: str,
    ) -> None:
        """Merge one NPC into another NPC of the same campaign."""
        source = source_name.strip()
        target = target_name.strip()
        if not source or not target or source.casefold() == target.casefold():
            raise ValueError("source_name and target_name must be different")

        cursor = await self.conn.execute(
            "SELECT * FROM npcs WHERE campaign_id = ? AND lower(name) = lower(?) LIMIT 1",
            (campaign_id, source),
        )
        source_row = await cursor.fetchone()
        cursor = await self.conn.execute(
            "SELECT * FROM npcs WHERE campaign_id = ? AND lower(name) = lower(?) LIMIT 1",
            (campaign_id, target),
        )
        target_row = await cursor.fetchone()
        if source_row is None or target_row is None:
            raise ValueError("NPC source or target not found")

        target_desc = self._merge_text_fields(
            str(target_row["description"] or ""),
            str(source_row["description"] or ""),
        )
        await self.conn.execute(
            "UPDATE npcs SET description = ? WHERE id = ?",
            (target_desc, str(target_row["id"])),
        )
        await self.conn.execute(
            "UPDATE npcs SET merged_into = ? WHERE id = ?",
            (str(target_row["name"]), str(source_row["id"])),
        )
        await self._rewrite_relationship_entity_keys(
            campaign_id,
            {
                f"npc:{source_row['name']}": f"npc:{target_row['name']}",
            },
        )
        await self.conn.commit()

    # ── Locations ────────────────────────────────────────────────────

    async def save_location(
        self,
        campaign_id: str,
        name: str,
        description: str = "",
        first_seen_session: str = "",
    ) -> None:
        """Insert a new location record."""
        import uuid

        loc_id = str(uuid.uuid4())
        await self.conn.execute(
            "INSERT INTO locations (id, campaign_id, name, description, first_seen_session) "
            "VALUES (?, ?, ?, ?, ?)",
            (loc_id, campaign_id, name, description, first_seen_session),
        )
        await self.conn.commit()

    async def get_locations(self, campaign_id: str) -> list[dict[str, Any]]:
        """Get all locations for a campaign."""
        cursor = await self.conn.execute(
            "SELECT * FROM locations WHERE campaign_id = ? "
            "AND (merged_into IS NULL OR merged_into = '') "
            "ORDER BY name",
            (campaign_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def get_merged_locations_map(
        self, campaign_id: str
    ) -> dict[str, list[dict[str, Any]]]:
        """Get merged location children grouped by parent location name."""
        cursor = await self.conn.execute(
            "SELECT * FROM locations WHERE campaign_id = ? "
            "AND (merged_into IS NOT NULL AND merged_into != '') "
            "ORDER BY merged_into, name",
            (campaign_id,),
        )
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in await cursor.fetchall():
            item = dict(row)
            parent = str(item.get("merged_into", "") or "")
            if not parent:
                continue
            grouped.setdefault(parent, []).append(item)
        return grouped

    async def location_exists(self, campaign_id: str, name: str) -> bool:
        """Check if a location with the given name already exists in a campaign.

        Uses case-insensitive comparison so "el bosque negro" and "El Bosque Negro"
        are treated as the same location.
        """
        cursor = await self.conn.execute(
            "SELECT 1 FROM locations WHERE campaign_id = ? AND lower(name) = lower(?) LIMIT 1",
            (campaign_id, name),
        )
        return await cursor.fetchone() is not None

    async def update_location(self, location_id: str, **fields: Any) -> None:
        """Update specific fields of a location record.

        Accepted fields: name, description.
        """
        allowed = {"name", "description"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [location_id]
        await self.conn.execute(
            f"UPDATE locations SET {set_clause} WHERE id = ?", values
        )
        await self.conn.commit()

    async def update_merged_location(
        self,
        campaign_id: str,
        location_id: str,
        *,
        name: str,
        description: str,
        merged_into: str,
    ) -> None:
        """Update a merged location child and optionally move/unmerge it."""
        target_parent = merged_into.strip()
        new_name = name.strip()
        if not new_name:
            raise ValueError("name is required")

        cursor = await self.conn.execute(
            "SELECT * FROM locations WHERE id = ? AND campaign_id = ? LIMIT 1",
            (location_id, campaign_id),
        )
        row = await cursor.fetchone()
        if row is None:
            raise ValueError("Merged location not found")
        current_name = str(row["name"])

        cursor = await self.conn.execute(
            "SELECT 1 FROM locations WHERE campaign_id = ? AND lower(name) = lower(?) AND id != ? LIMIT 1",
            (campaign_id, new_name, location_id),
        )
        if await cursor.fetchone():
            raise ValueError("Another location already has that name")

        if target_parent:
            cursor = await self.conn.execute(
                "SELECT 1 FROM locations WHERE campaign_id = ? AND lower(name) = lower(?) "
                "AND (merged_into IS NULL OR merged_into = '') LIMIT 1",
                (campaign_id, target_parent),
            )
            if await cursor.fetchone() is None:
                raise ValueError("Parent location not found")
            if new_name.casefold() == target_parent.casefold():
                raise ValueError("Child location name cannot match parent name")

        await self.conn.execute(
            "UPDATE locations SET name = ?, description = ?, merged_into = ? WHERE id = ? AND campaign_id = ?",
            (new_name, description.strip(), target_parent, location_id, campaign_id),
        )
        await self._rewrite_relationship_entity_keys(
            campaign_id,
            {
                f"loc:{current_name}": f"loc:{new_name}",
                f"location:{current_name}": f"loc:{new_name}",
            },
        )
        await self.conn.commit()

    async def merge_locations(
        self,
        campaign_id: str,
        source_name: str,
        target_name: str,
    ) -> None:
        """Merge one location into another location of the same campaign."""
        source = source_name.strip()
        target = target_name.strip()
        if not source or not target or source.casefold() == target.casefold():
            raise ValueError("source_name and target_name must be different")

        cursor = await self.conn.execute(
            "SELECT * FROM locations WHERE campaign_id = ? AND lower(name) = lower(?) LIMIT 1",
            (campaign_id, source),
        )
        source_row = await cursor.fetchone()
        cursor = await self.conn.execute(
            "SELECT * FROM locations WHERE campaign_id = ? AND lower(name) = lower(?) LIMIT 1",
            (campaign_id, target),
        )
        target_row = await cursor.fetchone()
        if source_row is None or target_row is None:
            raise ValueError("Location source or target not found")

        target_desc = self._merge_text_fields(
            str(target_row["description"] or ""),
            str(source_row["description"] or ""),
        )
        await self.conn.execute(
            "UPDATE locations SET description = ? WHERE id = ?",
            (target_desc, str(target_row["id"])),
        )
        await self.conn.execute(
            "UPDATE locations SET merged_into = ? WHERE id = ?",
            (str(target_row["name"]), str(source_row["id"])),
        )
        await self._rewrite_relationship_entity_keys(
            campaign_id,
            {
                f"loc:{source_row['name']}": f"loc:{target_row['name']}",
                f"location:{source_row['name']}": f"loc:{target_row['name']}",
            },
        )
        await self.conn.commit()

    # ── Campaign entities ─────────────────────────────────────────────

    async def save_entity(
        self,
        campaign_id: str,
        name: str,
        entity_type: str = "group",
        description: str = "",
        first_seen_session: str = "",
    ) -> None:
        """Insert a new campaign entity record."""
        import uuid

        entity_id = str(uuid.uuid4())
        await self.conn.execute(
            "INSERT INTO campaign_entities "
            "(id, campaign_id, name, entity_type, description, first_seen_session) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                entity_id,
                campaign_id,
                name,
                entity_type or "group",
                description,
                first_seen_session,
            ),
        )
        await self.conn.commit()

    async def get_entities(self, campaign_id: str) -> list[dict[str, Any]]:
        """Get all campaign entities for a campaign."""
        cursor = await self.conn.execute(
            "SELECT * FROM campaign_entities WHERE campaign_id = ? "
            "AND (merged_into IS NULL OR merged_into = '') "
            "ORDER BY name",
            (campaign_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def get_merged_entities_map(
        self, campaign_id: str
    ) -> dict[str, list[dict[str, Any]]]:
        """Get merged entity children grouped by parent entity name."""
        cursor = await self.conn.execute(
            "SELECT * FROM campaign_entities WHERE campaign_id = ? "
            "AND (merged_into IS NOT NULL AND merged_into != '') "
            "ORDER BY merged_into, name",
            (campaign_id,),
        )
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in await cursor.fetchall():
            item = dict(row)
            parent = str(item.get("merged_into", "") or "")
            if not parent:
                continue
            grouped.setdefault(parent, []).append(item)
        return grouped

    async def entity_exists(self, campaign_id: str, name: str) -> bool:
        """Check if an entity with the given name already exists in a campaign."""
        cursor = await self.conn.execute(
            "SELECT 1 FROM campaign_entities "
            "WHERE campaign_id = ? AND lower(name) = lower(?) LIMIT 1",
            (campaign_id, name),
        )
        return await cursor.fetchone() is not None

    async def update_entity(self, entity_id: str, **fields: Any) -> None:
        """Update specific fields of a campaign entity record.

        Accepted fields: name, entity_type, description.
        """
        allowed = {"name", "entity_type", "description"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [entity_id]
        await self.conn.execute(
            f"UPDATE campaign_entities SET {set_clause} WHERE id = ?", values
        )
        await self.conn.commit()

    async def update_merged_entity(
        self,
        campaign_id: str,
        entity_id: str,
        *,
        name: str,
        description: str,
        entity_type: str,
        merged_into: str,
    ) -> None:
        """Update a merged campaign entity child and optionally move/unmerge it."""
        target_parent = merged_into.strip()
        new_name = name.strip()
        normalized_type = entity_type.strip() or "group"
        if not new_name:
            raise ValueError("name is required")

        cursor = await self.conn.execute(
            "SELECT * FROM campaign_entities WHERE id = ? AND campaign_id = ? LIMIT 1",
            (entity_id, campaign_id),
        )
        row = await cursor.fetchone()
        if row is None:
            raise ValueError("Merged entity not found")
        current_name = str(row["name"])

        cursor = await self.conn.execute(
            "SELECT 1 FROM campaign_entities WHERE campaign_id = ? AND lower(name) = lower(?) AND id != ? LIMIT 1",
            (campaign_id, new_name, entity_id),
        )
        if await cursor.fetchone():
            raise ValueError("Another entity already has that name")

        if target_parent:
            cursor = await self.conn.execute(
                "SELECT 1 FROM campaign_entities WHERE campaign_id = ? AND lower(name) = lower(?) "
                "AND (merged_into IS NULL OR merged_into = '') LIMIT 1",
                (campaign_id, target_parent),
            )
            if await cursor.fetchone() is None:
                raise ValueError("Parent entity not found")
            if new_name.casefold() == target_parent.casefold():
                raise ValueError("Child entity name cannot match parent name")

        await self.conn.execute(
            "UPDATE campaign_entities SET name = ?, entity_type = ?, description = ?, merged_into = ? "
            "WHERE id = ? AND campaign_id = ?",
            (
                new_name,
                normalized_type,
                description.strip(),
                target_parent,
                entity_id,
                campaign_id,
            ),
        )
        await self._rewrite_relationship_entity_keys(
            campaign_id,
            {
                f"ent:{current_name}": f"ent:{new_name}",
                f"entity:{current_name}": f"ent:{new_name}",
            },
        )
        await self.conn.commit()

    async def merge_entities(
        self,
        campaign_id: str,
        source_name: str,
        target_name: str,
    ) -> None:
        """Merge one campaign entity into another entity of same campaign."""
        source = source_name.strip()
        target = target_name.strip()
        if not source or not target or source.casefold() == target.casefold():
            raise ValueError("source_name and target_name must be different")

        cursor = await self.conn.execute(
            "SELECT * FROM campaign_entities WHERE campaign_id = ? AND lower(name) = lower(?) LIMIT 1",
            (campaign_id, source),
        )
        source_row = await cursor.fetchone()
        cursor = await self.conn.execute(
            "SELECT * FROM campaign_entities WHERE campaign_id = ? AND lower(name) = lower(?) LIMIT 1",
            (campaign_id, target),
        )
        target_row = await cursor.fetchone()
        if source_row is None or target_row is None:
            raise ValueError("Entity source or target not found")

        target_desc = self._merge_text_fields(
            str(target_row["description"] or ""),
            str(source_row["description"] or ""),
        )
        await self.conn.execute(
            "UPDATE campaign_entities SET description = ? WHERE id = ?",
            (target_desc, str(target_row["id"])),
        )
        await self.conn.execute(
            "UPDATE campaign_entities SET merged_into = ? WHERE id = ?",
            (str(target_row["name"]), str(source_row["id"])),
        )
        await self._rewrite_relationship_entity_keys(
            campaign_id,
            {
                f"ent:{source_row['name']}": f"ent:{target_row['name']}",
                f"entity:{source_row['name']}": f"ent:{target_row['name']}",
            },
        )
        await self.conn.commit()

    # ── Relationships ─────────────────────────────────────────────────

    async def get_relationship_types(self, campaign_id: str) -> list[dict[str, Any]]:
        """List known relationship types for a campaign thesaurus."""
        cursor = await self.conn.execute(
            "SELECT * FROM relationship_types WHERE campaign_id = ? "
            "ORDER BY usage_count DESC, label ASC",
            (campaign_id,),
        )
        rows = [dict(r) for r in await cursor.fetchall()]
        for row in rows:
            aliases = row.get("aliases_json") or "[]"
            try:
                row["aliases"] = json.loads(aliases)
            except Exception:
                row["aliases"] = []
        return rows

    async def resolve_relationship_type(
        self,
        campaign_id: str,
        relation_label: str,
        *,
        category: str = "general",
    ) -> dict[str, Any]:
        """Resolve or create a canonical relationship type with fuzzy dedupe."""
        raw_label = relation_label.strip()
        canonical = normalize_relationship_type_label(raw_label)
        existing = await self.get_relationship_types(campaign_id)

        for row in existing:
            if row.get("canonical_key", "") == canonical:
                return row

        best: dict[str, Any] | None = None
        best_score = 0.0
        for row in existing:
            key = str(row.get("canonical_key", ""))
            score = _relation_similarity(canonical, key)
            if score > best_score:
                best_score = score
                best = row

        if best is not None and best_score >= 0.88:
            aliases = list(best.get("aliases") or [])
            if raw_label and raw_label not in aliases:
                aliases.append(raw_label)
                await self.conn.execute(
                    "UPDATE relationship_types SET aliases_json = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(sorted(set(aliases))), time.time(), best["id"]),
                )
                await self.conn.commit()
                best["aliases"] = sorted(set(aliases))
            return best

        import uuid

        type_id = str(uuid.uuid4())
        now = time.time()
        display_label = raw_label or canonical
        aliases = [raw_label] if raw_label and raw_label != display_label else []
        await self.conn.execute(
            "INSERT INTO relationship_types "
            "(id, campaign_id, canonical_key, label, category, aliases_json, usage_count, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)",
            (
                type_id,
                campaign_id,
                canonical,
                display_label,
                category or "general",
                json.dumps(aliases),
                now,
                now,
            ),
        )
        await self.conn.commit()
        return {
            "id": type_id,
            "campaign_id": campaign_id,
            "canonical_key": canonical,
            "label": display_label,
            "category": category or "general",
            "aliases": aliases,
            "usage_count": 0,
            "created_at": now,
            "updated_at": now,
        }

    async def merge_relationship_types(
        self,
        campaign_id: str,
        source_type_key: str,
        target_type_key: str,
    ) -> None:
        """Merge one relationship type into another canonical relationship type."""
        source_key = source_type_key.strip()
        target_key = target_type_key.strip()
        if not source_key or not target_key or source_key == target_key:
            raise ValueError("source_type_key and target_type_key must be different")

        cursor = await self.conn.execute(
            "SELECT * FROM relationship_types WHERE campaign_id = ? AND canonical_key = ? LIMIT 1",
            (campaign_id, source_key),
        )
        source = await cursor.fetchone()
        cursor = await self.conn.execute(
            "SELECT * FROM relationship_types WHERE campaign_id = ? AND canonical_key = ? LIMIT 1",
            (campaign_id, target_key),
        )
        target = await cursor.fetchone()
        if source is None or target is None:
            raise ValueError("relationship type source or target not found")

        source_aliases = []
        target_aliases = []
        try:
            source_aliases = json.loads(str(source["aliases_json"] or "[]"))
        except Exception:
            source_aliases = []
        try:
            target_aliases = json.loads(str(target["aliases_json"] or "[]"))
        except Exception:
            target_aliases = []

        merged_aliases = sorted(
            set(
                [str(source["label"])]
                + [str(a) for a in source_aliases]
                + [str(a) for a in target_aliases]
            )
        )

        cursor = await self.conn.execute(
            "SELECT * FROM character_relationships WHERE campaign_id = ? AND type_key = ?",
            (campaign_id, source_key),
        )
        source_relationships = [dict(r) for r in await cursor.fetchall()]
        for rel in source_relationships:
            source_rel_key = str(rel.get("source_key", ""))
            target_rel_key = str(rel.get("target_key", ""))
            source_notes = str(rel.get("notes", "") or "")
            cursor = await self.conn.execute(
                "SELECT notes FROM character_relationships "
                "WHERE campaign_id = ? AND source_key = ? AND target_key = ? AND type_key = ? LIMIT 1",
                (campaign_id, source_rel_key, target_rel_key, target_key),
            )
            existing_target = await cursor.fetchone()
            merged_notes = source_notes
            if existing_target is not None:
                merged_notes = self._merge_text_fields(
                    str(existing_target["notes"] or ""),
                    source_notes,
                )
            await self.conn.execute(
                "DELETE FROM character_relationships WHERE id = ?",
                (rel["id"],),
            )
            await self._upsert_relationship_row(
                campaign_id=campaign_id,
                source_key=source_rel_key,
                target_key=target_rel_key,
                type_key=target_key,
                type_label=str(target["label"]),
                notes=merged_notes,
            )
        await self.conn.execute(
            "UPDATE relationship_types SET aliases_json = ?, updated_at = ? "
            "WHERE campaign_id = ? AND canonical_key = ?",
            (json.dumps(merged_aliases), time.time(), campaign_id, target_key),
        )
        await self.conn.execute(
            "DELETE FROM relationship_types WHERE campaign_id = ? AND canonical_key = ?",
            (campaign_id, source_key),
        )
        await self._recompute_relationship_type_usage(campaign_id, target_key)

    async def _upsert_relationship_row(
        self,
        campaign_id: str,
        source_key: str,
        target_key: str,
        type_key: str,
        type_label: str,
        notes: str,
    ) -> None:
        """Insert/update one relationship row by natural key."""
        import uuid

        now = time.time()
        await self.conn.execute(
            "INSERT INTO character_relationships "
            "(id, campaign_id, source_key, target_key, type_key, type_label, notes, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(campaign_id, source_key, target_key, type_key) DO UPDATE SET "
            "type_label=excluded.type_label, notes=excluded.notes, updated_at=excluded.updated_at",
            (
                str(uuid.uuid4()),
                campaign_id,
                source_key,
                target_key,
                type_key,
                type_label,
                notes,
                now,
                now,
            ),
        )

    async def _rewrite_relationship_entity_keys(
        self,
        campaign_id: str,
        key_mapping: dict[str, str],
    ) -> None:
        """Rewrite relationship source/target keys, collapsing duplicates safely."""
        if not key_mapping:
            return

        keys = list(key_mapping.keys())
        placeholders = ", ".join("?" for _ in keys)
        cursor = await self.conn.execute(
            "SELECT * FROM character_relationships "
            f"WHERE campaign_id = ? AND (source_key IN ({placeholders}) OR target_key IN ({placeholders}))",
            [campaign_id, *keys, *keys],
        )
        rows = [dict(r) for r in await cursor.fetchall()]
        if not rows:
            return

        for row in rows:
            source_key = str(row.get("source_key", ""))
            target_key = str(row.get("target_key", ""))
            new_source = key_mapping.get(source_key, source_key)
            new_target = key_mapping.get(target_key, target_key)
            if new_source == source_key and new_target == target_key:
                continue

            await self.conn.execute(
                "DELETE FROM character_relationships WHERE id = ?",
                (row["id"],),
            )
            if new_source == new_target:
                continue
            await self._upsert_relationship_row(
                campaign_id=campaign_id,
                source_key=new_source,
                target_key=new_target,
                type_key=str(row.get("type_key", "")),
                type_label=str(row.get("type_label", "")),
                notes=str(row.get("notes", "") or ""),
            )

    async def save_character_relationship(
        self,
        campaign_id: str,
        source_key: str,
        target_key: str,
        relation_label: str,
        *,
        notes: str = "",
        category: str = "general",
    ) -> dict[str, Any]:
        """Create or update a typed relationship between two entities."""
        source = source_key.strip()
        target = target_key.strip()
        if not source or not target:
            raise ValueError("source_key and target_key are required")
        if source == target:
            raise ValueError("source and target cannot be the same entity")

        relation_type = await self.resolve_relationship_type(
            campaign_id,
            relation_label,
            category=category,
        )

        import uuid

        rel_id = str(uuid.uuid4())
        now = time.time()
        await self.conn.execute(
            "INSERT INTO character_relationships "
            "(id, campaign_id, source_key, target_key, type_key, type_label, notes, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(campaign_id, source_key, target_key, type_key) DO UPDATE SET "
            "type_label=excluded.type_label, notes=excluded.notes, updated_at=excluded.updated_at",
            (
                rel_id,
                campaign_id,
                source,
                target,
                relation_type["canonical_key"],
                relation_type["label"],
                notes.strip(),
                now,
                now,
            ),
        )
        await self.conn.execute(
            "UPDATE relationship_types SET usage_count = ("
            "SELECT COUNT(*) FROM character_relationships "
            "WHERE campaign_id = ? AND type_key = ?"
            "), updated_at = ? "
            "WHERE campaign_id = ? AND canonical_key = ?",
            (
                campaign_id,
                relation_type["canonical_key"],
                now,
                campaign_id,
                relation_type["canonical_key"],
            ),
        )
        await self.conn.commit()

        cursor = await self.conn.execute(
            "SELECT r.*, t.category AS type_category "
            "FROM character_relationships r "
            "LEFT JOIN relationship_types t "
            "ON t.campaign_id = r.campaign_id AND t.canonical_key = r.type_key "
            "WHERE r.campaign_id = ? AND r.source_key = ? AND r.target_key = ? AND r.type_key = ?",
            (campaign_id, source, target, relation_type["canonical_key"]),
        )
        row = await cursor.fetchone()
        return (
            dict(row)
            if row
            else {
                "campaign_id": campaign_id,
                "source_key": source,
                "target_key": target,
                "type_key": relation_type["canonical_key"],
                "type_label": relation_type["label"],
                "notes": notes.strip(),
                "type_category": relation_type.get("category", "general"),
            }
        )

    async def _recompute_relationship_type_usage(
        self,
        campaign_id: str,
        type_key: str,
    ) -> None:
        """Recompute usage count for one relationship type key."""
        await self.conn.execute(
            "UPDATE relationship_types SET usage_count = ("
            "SELECT COUNT(*) FROM character_relationships "
            "WHERE campaign_id = ? AND type_key = ?"
            "), updated_at = ? "
            "WHERE campaign_id = ? AND canonical_key = ?",
            (campaign_id, type_key, time.time(), campaign_id, type_key),
        )
        await self.conn.commit()

    async def delete_character_relationship(
        self,
        campaign_id: str,
        source_key: str,
        target_key: str,
        type_key: str,
    ) -> None:
        """Delete one relationship by its natural key triple."""
        await self.conn.execute(
            "DELETE FROM character_relationships "
            "WHERE campaign_id = ? AND source_key = ? AND target_key = ? AND type_key = ?",
            (campaign_id, source_key, target_key, type_key),
        )
        await self._recompute_relationship_type_usage(campaign_id, type_key)

    async def relationship_exists(
        self,
        campaign_id: str,
        source_key: str,
        target_key: str,
        type_key: str,
    ) -> bool:
        """Check if a specific typed relationship already exists."""
        cursor = await self.conn.execute(
            "SELECT 1 FROM character_relationships "
            "WHERE campaign_id = ? AND source_key = ? AND target_key = ? AND type_key = ? LIMIT 1",
            (campaign_id, source_key, target_key, type_key),
        )
        return await cursor.fetchone() is not None

    async def get_character_relationships(
        self, campaign_id: str
    ) -> list[dict[str, Any]]:
        """List character relationships for a campaign."""
        cursor = await self.conn.execute(
            "SELECT r.*, t.category AS type_category "
            "FROM character_relationships r "
            "LEFT JOIN relationship_types t "
            "ON t.campaign_id = r.campaign_id AND t.canonical_key = r.type_key "
            "WHERE r.campaign_id = ? ORDER BY r.updated_at DESC, r.created_at DESC",
            (campaign_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def rename_relationship_entity_key(
        self,
        campaign_id: str,
        old_key: str,
        new_key: str,
    ) -> None:
        """Rename an entity key in relationships (source and target sides)."""
        if not old_key or not new_key or old_key == new_key:
            return
        await self.conn.execute(
            "UPDATE character_relationships SET "
            "source_key = CASE WHEN source_key = ? THEN ? ELSE source_key END, "
            "target_key = CASE WHEN target_key = ? THEN ? ELSE target_key END, "
            "updated_at = ? "
            "WHERE campaign_id = ? AND (source_key = ? OR target_key = ?)",
            (
                old_key,
                new_key,
                old_key,
                new_key,
                time.time(),
                campaign_id,
                old_key,
                old_key,
            ),
        )
        await self.conn.commit()

    # ── Questions ─────────────────────────────────────────────────────

    async def save_question(self, session_id: str, question: str) -> int:
        """Save a question from the summarizer."""
        cursor = await self.conn.execute(
            "INSERT INTO questions (session_id, question, status) VALUES (?, ?, ?)",
            (session_id, question, "pending"),
        )
        await self.conn.commit()
        return cursor.lastrowid or 0

    async def answer_question(self, question_id: int, answer: str) -> None:
        """Answer a pending question."""
        await self.conn.execute(
            "UPDATE questions SET answer = ?, answered_at = ?, status = ? WHERE id = ?",
            (answer, time.time(), "answered", question_id),
        )
        await self.conn.commit()

    async def get_pending_questions(self, session_id: str) -> list[dict[str, Any]]:
        """Get all pending questions for a session."""
        cursor = await self.conn.execute(
            "SELECT * FROM questions WHERE session_id = ? AND status = 'pending'",
            (session_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def get_answered_unprocessed_questions(
        self, session_id: str
    ) -> list[dict[str, Any]]:
        """Get questions that have been answered but not yet processed by the summarizer."""
        cursor = await self.conn.execute(
            "SELECT * FROM questions WHERE session_id = ? AND status = 'answered'",
            (session_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def mark_questions_processed(self, question_ids: list[int]) -> None:
        """Mark answered questions as processed after the summarizer has consumed them."""
        if not question_ids:
            return
        placeholders = ",".join("?" for _ in question_ids)
        await self.conn.execute(
            f"UPDATE questions SET status = 'processed' WHERE id IN ({placeholders})",
            question_ids,
        )
        await self.conn.commit()

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _merge_text_fields(primary: str, secondary: str) -> str:
        """Merge two description-like fields without losing unique text."""
        a = (primary or "").strip()
        b = (secondary or "").strip()
        if not a:
            return b
        if not b:
            return a
        if b.casefold() in a.casefold():
            return a
        return f"{a}\n{b}"
