"""Canonical catalogs for RPG Scribe entity and relationship model.

Defines closed vocabularies for relation types, entity types, certainty levels,
and origin tracking. Provides Spanish-to-canonical normalization for LLM output.
"""

from __future__ import annotations

import re
import unicodedata
from enum import Enum


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RelationFamily(str, Enum):
    """High-level grouping of relationship types for filtering and visualization."""

    IDENTITY = "identity"
    SOCIAL = "social"
    HIERARCHY = "hierarchy"
    CONFLICT = "conflict"
    AFFILIATION = "affiliation"
    LOCATION = "location"
    OWNERSHIP = "ownership"
    OBJECTIVE = "objective"
    KNOWLEDGE = "knowledge"
    EVENT_PARTICIPATION = "event_participation"
    TRANSACTION = "transaction"
    EMOTIONAL = "emotional"
    NARRATIVE = "narrative"
    TEMPORAL = "temporal"


class EntityType(str, Enum):
    """Canonical entity types for the campaign world graph."""

    PLAYER_CHARACTER = "player_character"
    NPC = "npc"
    FACTION = "faction"
    LOCATION = "location"
    ITEM = "item"
    ORGANIZATION = "organization"
    EVENT = "event"
    OBJECTIVE = "objective"
    TECHNOLOGY = "technology"
    OTHER = "other"


class Certainty(str, Enum):
    """Epistemological certainty of a relationship."""

    EXPLICIT = "explicit"       # Stated as fact in narrative
    INFERRED = "inferred"       # Deduced from context by the model
    RUMOR = "rumor"             # Heard second-hand, unverified
    SUSPECTED = "suspected"     # Character believes/suspects but not confirmed
    CLAIMED = "claimed"         # Someone claims it, reliability unknown
    UNCERTAIN = "uncertain"     # Insufficient evidence


class RelationOrigin(str, Enum):
    """How this relationship was created."""

    EXTRACTED = "extracted"     # Extracted directly from session summary by LLM
    INFERRED = "inferred"       # Deduced by the model beyond what was stated
    CURATED = "curated"         # Added or corrected manually by a user
    IMPORTED = "imported"       # Loaded from an external structured source


# ---------------------------------------------------------------------------
# Relation type definitions
# Each entry: (canonical_key, family, polarity, label_es)
# polarity: "positive" | "negative" | "neutral" | "mixed"
# ---------------------------------------------------------------------------

_RELATION_CATALOG: list[tuple[str, RelationFamily, str, str]] = [
    # ── Identity ──────────────────────────────────────────────────────────
    ("alias_of",          RelationFamily.IDENTITY,           "neutral",  "alias de"),
    ("disguised_as",      RelationFamily.IDENTITY,           "neutral",  "disfrazado como"),

    # ── Social ────────────────────────────────────────────────────────────
    ("knows",             RelationFamily.SOCIAL,             "neutral",  "conoce a"),
    ("ally_of",           RelationFamily.SOCIAL,             "positive", "aliado de"),
    ("friend_of",         RelationFamily.SOCIAL,             "positive", "amigo de"),
    ("protects",          RelationFamily.SOCIAL,             "positive", "protege a"),
    ("mentors",           RelationFamily.SOCIAL,             "positive", "mentoriza a"),
    ("trusts",            RelationFamily.SOCIAL,             "positive", "confía en"),
    ("distrusts",         RelationFamily.SOCIAL,             "negative", "desconfía de"),
    ("fears",             RelationFamily.SOCIAL,             "negative", "teme a"),

    # ── Hierarchy ─────────────────────────────────────────────────────────
    ("commands",          RelationFamily.HIERARCHY,          "neutral",  "manda a"),
    ("reports_to",        RelationFamily.HIERARCHY,          "neutral",  "reporta a"),
    ("works_for",         RelationFamily.HIERARCHY,          "neutral",  "trabaja para"),
    ("controls",          RelationFamily.HIERARCHY,          "neutral",  "controla a"),
    ("serves",            RelationFamily.HIERARCHY,          "neutral",  "sirve a"),

    # ── Conflict ──────────────────────────────────────────────────────────
    ("conflicts_with",    RelationFamily.CONFLICT,           "negative", "en conflicto con"),
    ("hunts",             RelationFamily.CONFLICT,           "negative", "caza a"),
    ("betrayed",          RelationFamily.CONFLICT,           "negative", "traicionó a"),
    ("threatens",         RelationFamily.CONFLICT,           "negative", "amenaza a"),
    ("pursues",           RelationFamily.CONFLICT,           "negative", "persigue a"),

    # ── Affiliation ───────────────────────────────────────────────────────
    ("member_of",         RelationFamily.AFFILIATION,        "neutral",  "miembro de"),
    ("belongs_to",        RelationFamily.AFFILIATION,        "neutral",  "pertenece a"),
    ("aligned_with",      RelationFamily.AFFILIATION,        "neutral",  "alineado con"),
    ("associated_with",   RelationFamily.AFFILIATION,        "neutral",  "asociado con"),

    # ── Location ──────────────────────────────────────────────────────────
    ("located_in",        RelationFamily.LOCATION,           "neutral",  "ubicado en"),
    ("lives_in",          RelationFamily.LOCATION,           "neutral",  "vive en"),
    ("operates_in",       RelationFamily.LOCATION,           "neutral",  "opera en"),
    ("last_seen_in",      RelationFamily.LOCATION,           "neutral",  "visto por última vez en"),
    ("hides_in",          RelationFamily.LOCATION,           "neutral",  "se esconde en"),

    # ── Ownership ─────────────────────────────────────────────────────────
    ("owns",              RelationFamily.OWNERSHIP,          "neutral",  "posee"),
    ("uses",              RelationFamily.OWNERSHIP,          "neutral",  "usa"),
    ("has_access_to",     RelationFamily.OWNERSHIP,          "neutral",  "tiene acceso a"),

    # ── Objective ─────────────────────────────────────────────────────────
    ("wants",             RelationFamily.OBJECTIVE,          "neutral",  "quiere"),
    ("investigates",      RelationFamily.OBJECTIVE,          "neutral",  "investiga"),
    ("searches_for",      RelationFamily.OBJECTIVE,          "neutral",  "busca"),
    ("is_target_of",      RelationFamily.OBJECTIVE,          "negative", "es objetivo de"),

    # ── Knowledge ─────────────────────────────────────────────────────────
    ("knows_about",       RelationFamily.KNOWLEDGE,          "neutral",  "sabe sobre"),
    ("suspects",          RelationFamily.KNOWLEDGE,          "neutral",  "sospecha de"),
    ("rumors_about",      RelationFamily.KNOWLEDGE,          "neutral",  "hay rumores sobre"),

    # ── Event participation ────────────────────────────────────────────────
    ("participated_in",   RelationFamily.EVENT_PARTICIPATION,"neutral",  "participó en"),
    ("caused",            RelationFamily.EVENT_PARTICIPATION,"neutral",  "causó"),
    ("witnessed",         RelationFamily.EVENT_PARTICIPATION,"neutral",  "fue testigo de"),

    # ── Transaction ───────────────────────────────────────────────────────
    ("hired",             RelationFamily.TRANSACTION,        "neutral",  "contrató a"),
    ("paid",              RelationFamily.TRANSACTION,        "neutral",  "pagó a"),
    ("blackmailed",       RelationFamily.TRANSACTION,        "negative", "chantajeó a"),

    # ── Narrative ─────────────────────────────────────────────────────────
    ("connected_to_theme",RelationFamily.NARRATIVE,          "neutral",  "conectado al tema"),
]

# Build lookup dict: canonical_key → (family, polarity, label_es)
RELATION_TYPE_MAP: dict[str, tuple[RelationFamily, str, str]] = {
    key: (family, polarity, label_es)
    for key, family, polarity, label_es in _RELATION_CATALOG
}

CANONICAL_RELATION_KEYS: frozenset[str] = frozenset(RELATION_TYPE_MAP.keys())

# Legacy aliases: corporation/gang → organization
ENTITY_TYPE_ALIASES: dict[str, EntityType] = {
    "corporacion": EntityType.ORGANIZATION,
    "corporation": EntityType.ORGANIZATION,
    "corp": EntityType.ORGANIZATION,
    "gang": EntityType.ORGANIZATION,
    "faccion": EntityType.FACTION,
    "faction": EntityType.FACTION,
    "clan": EntityType.FACTION,
    "grupo": EntityType.OTHER,
    "group": EntityType.OTHER,
    "fuerza": EntityType.ORGANIZATION,
    "otro": EntityType.OTHER,
    "other": EntityType.OTHER,
}


# ---------------------------------------------------------------------------
# Spanish equivalences map
# Keys are normalized Spanish phrases → canonical relation keys
# ---------------------------------------------------------------------------

SPANISH_EQUIVALENCES: dict[str, str] = {
    # identity
    "alias de": "alias_of",
    "conocido como": "alias_of",
    "tambien llamado": "alias_of",
    "disfrazado como": "disguised_as",
    "se hace pasar por": "disguised_as",

    # social
    "conoce a": "knows",
    "conoce": "knows",
    "aliado de": "ally_of",
    "aliados": "ally_of",
    "aliado": "ally_of",
    "amigo de": "friend_of",
    "amigos": "friend_of",
    "protege a": "protects",
    "protege": "protects",
    "mentoriza a": "mentors",
    "mentor de": "mentors",
    "confia en": "trusts",
    "confian": "trusts",
    "desconfia de": "distrusts",
    "no confia en": "distrusts",
    "teme a": "fears",
    "teme": "fears",

    # hierarchy
    "manda a": "commands",
    "lidera a": "commands",
    "lider de": "commands",
    "jefe de": "commands",
    "dirige a": "commands",
    "reporta a": "reports_to",
    "trabaja para": "works_for",
    "trabaja bajo las ordenes de": "works_for",
    "empleado de": "works_for",
    "controla a": "controls",
    "controla": "controls",
    "sirve a": "serves",
    "sirve": "serves",
    "subordinado de": "reports_to",
    "bajo el mando de": "reports_to",

    # conflict
    "en conflicto con": "conflicts_with",
    "enemigo de": "conflicts_with",
    "enemigos": "conflicts_with",
    "rival de": "conflicts_with",
    "rivalidad con": "conflicts_with",
    "caza a": "hunts",
    "busca matar a": "hunts",
    "traiciono a": "betrayed",
    "traiciono": "betrayed",
    "traicion de": "betrayed",
    "amenaza a": "threatens",
    "amenaza": "threatens",
    "persigue a": "pursues",
    "persigue": "pursues",

    # affiliation
    "miembro de": "member_of",
    "pertenece a": "belongs_to",
    "pertenecen a": "belongs_to",
    "alineado con": "aligned_with",
    "asociado con": "associated_with",
    "asociado a": "associated_with",
    "vinculado a": "associated_with",
    "vinculado con": "associated_with",
    "parte de": "member_of",

    # location
    "ubicado en": "located_in",
    "vive en": "lives_in",
    "habita en": "lives_in",
    "reside en": "lives_in",
    "opera en": "operates_in",
    "tiene base en": "operates_in",
    "visto por ultima vez en": "last_seen_in",
    "ultima vez en": "last_seen_in",
    "se esconde en": "hides_in",
    "se oculta en": "hides_in",

    # ownership
    "posee": "owns",
    "tiene": "owns",
    "es dueno de": "owns",
    "usa": "uses",
    "utiliza": "uses",
    "tiene acceso a": "has_access_to",

    # objective
    "quiere": "wants",
    "quiere a": "wants",
    "necesita": "wants",
    "investiga": "investigates",
    "investiga a": "investigates",
    "busca": "searches_for",
    "busca a": "searches_for",
    "es objetivo de": "is_target_of",
    "objetivo de": "is_target_of",
    "blanco de": "is_target_of",

    # knowledge
    "sabe sobre": "knows_about",
    "conoce informacion sobre": "knows_about",
    "tiene informacion de": "knows_about",
    "sospecha de": "suspects",
    "sospecha que": "suspects",
    "hay rumores sobre": "rumors_about",
    "se rumorea que": "rumors_about",
    "rumores sobre": "rumors_about",

    # event participation
    "participo en": "participated_in",
    "estuvo en": "participated_in",
    "causo": "caused",
    "provocó": "caused",
    "provoco": "caused",
    "fue testigo de": "witnessed",
    "presencio": "witnessed",

    # transaction
    "contrato a": "hired",
    "contrato": "hired",
    "pago a": "paid",
    "pago": "paid",
    "chantajeo a": "blackmailed",
    "chantajea a": "blackmailed",

    # narrative
    "conectado al tema": "connected_to_theme",
    "relacionado con el tema": "connected_to_theme",
}


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

def _normalize_for_lookup(text: str) -> str:
    """Normalize a string for catalog lookup.

    Lowercases, removes diacritics, strips non-alphanumeric except spaces,
    removes common Spanish articles/aux verbs, collapses whitespace.
    """
    text = text.lower().strip()
    # Remove diacritics
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    # Keep only alphanumeric + spaces
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    # Remove Spanish aux verbs and articles (standalone words only)
    stopwords = {
        "es", "era", "fue", "son", "esta", "estaba", "estuvieron",
        "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del",
    }
    words = [w for w in text.split() if w not in stopwords]
    return " ".join(words).strip()


def resolve_spanish_to_canonical(raw: str) -> str | None:
    """Try to map a free-text Spanish relation phrase to a canonical key.

    Returns the canonical key string (e.g. "works_for") or None if no match.
    First tries exact match after normalization, then tries partial key lookups.
    """
    if not raw:
        return None

    # Direct canonical key check (LLM may already return canonical keys)
    normalized_raw = raw.strip().lower()
    if normalized_raw in CANONICAL_RELATION_KEYS:
        return normalized_raw

    # Normalize and look up in Spanish equivalences
    normalized = _normalize_for_lookup(raw)
    if normalized in SPANISH_EQUIVALENCES:
        return SPANISH_EQUIVALENCES[normalized]

    # Try the original (un-normalized) in equivalences
    if raw.strip().lower() in SPANISH_EQUIVALENCES:
        return SPANISH_EQUIVALENCES[raw.strip().lower()]

    return None


def normalize_entity_type(raw: str) -> EntityType:
    """Map a raw entity_type string (including legacy Spanish values) to EntityType."""
    if not raw:
        return EntityType.OTHER
    normalized = raw.strip().lower()
    # Try exact EntityType match
    try:
        return EntityType(normalized)
    except ValueError:
        pass
    # Try legacy alias map
    return ENTITY_TYPE_ALIASES.get(normalized, EntityType.OTHER)


def build_catalog_prompt_block() -> str:
    """Build a formatted string listing all relation types for LLM prompts."""
    lines = ["TIPOS DE RELACIÓN PERMITIDOS (usa SOLO estos valores en relation_type):"]
    current_family = None
    for key, family, polarity, label_es in _RELATION_CATALOG:
        if family != current_family:
            current_family = family
            lines.append(f"\n  [{family.value.upper()}]")
        lines.append(f"  - {key}  (ej: \"{label_es}\")")
    lines.append("\nSi ningún tipo encaja, usa el más cercano y baja strength a 0.3.")
    return "\n".join(lines)
