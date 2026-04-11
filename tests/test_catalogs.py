"""Tests for the canonical entity/relationship catalog."""

from __future__ import annotations

from rpg_scribe.core.catalogs import (
    CANONICAL_RELATION_KEYS,
    RELATION_TYPE_MAP,
    SPANISH_EQUIVALENCES,
    Certainty,
    EntityType,
    RelationFamily,
    RelationOrigin,
    build_catalog_prompt_block,
    normalize_entity_type,
    resolve_spanish_to_canonical,
)


class TestEnums:
    def test_relation_family_values(self) -> None:
        assert RelationFamily.SOCIAL == "social"
        assert RelationFamily.HIERARCHY == "hierarchy"
        assert RelationFamily.CONFLICT == "conflict"

    def test_entity_type_values(self) -> None:
        assert EntityType.NPC == "npc"
        assert EntityType.ORGANIZATION == "organization"
        assert EntityType.OTHER == "other"

    def test_certainty_values(self) -> None:
        assert Certainty.EXPLICIT == "explicit"
        assert Certainty.RUMOR == "rumor"
        assert Certainty.SUSPECTED == "suspected"

    def test_relation_origin_values(self) -> None:
        assert RelationOrigin.EXTRACTED == "extracted"
        assert RelationOrigin.CURATED == "curated"

    def test_enums_are_str_subclasses(self) -> None:
        # Can compare to plain strings without .value
        assert RelationFamily.SOCIAL == "social"
        assert EntityType.NPC == "npc"


class TestRelationTypeCatalog:
    def test_catalog_has_reasonable_size(self) -> None:
        assert 30 <= len(CANONICAL_RELATION_KEYS) <= 60

    def test_canonical_keys_are_unique(self) -> None:
        assert len(CANONICAL_RELATION_KEYS) == len(RELATION_TYPE_MAP)

    def test_known_types_present(self) -> None:
        assert "works_for" in CANONICAL_RELATION_KEYS
        assert "member_of" in CANONICAL_RELATION_KEYS
        assert "ally_of" in CANONICAL_RELATION_KEYS
        assert "conflicts_with" in CANONICAL_RELATION_KEYS
        assert "knows" in CANONICAL_RELATION_KEYS
        assert "betrayed" in CANONICAL_RELATION_KEYS

    def test_relation_type_map_structure(self) -> None:
        family, polarity, label_es = RELATION_TYPE_MAP["works_for"]
        assert family == RelationFamily.HIERARCHY
        assert polarity == "neutral"
        assert isinstance(label_es, str)
        assert len(label_es) > 0

    def test_all_keys_have_valid_family(self) -> None:
        valid_families = {f.value for f in RelationFamily}
        for key, (family, polarity, _) in RELATION_TYPE_MAP.items():
            assert family.value in valid_families, f"{key} has unknown family {family}"

    def test_all_keys_have_valid_polarity(self) -> None:
        valid_polarities = {"positive", "negative", "neutral", "mixed"}
        for key, (_, polarity, _) in RELATION_TYPE_MAP.items():
            assert polarity in valid_polarities, f"{key} has invalid polarity {polarity}"


class TestSpanishEquivalences:
    def test_known_equivalences(self) -> None:
        assert SPANISH_EQUIVALENCES["trabaja para"] == "works_for"
        assert SPANISH_EQUIVALENCES["aliado de"] == "ally_of"
        assert SPANISH_EQUIVALENCES["enemigo de"] == "conflicts_with"
        assert SPANISH_EQUIVALENCES["miembro de"] == "member_of"
        assert SPANISH_EQUIVALENCES["pertenece a"] == "belongs_to"

    def test_all_equivalence_targets_are_canonical(self) -> None:
        for spanish, canonical in SPANISH_EQUIVALENCES.items():
            assert canonical in CANONICAL_RELATION_KEYS, (
                f"'{spanish}' maps to '{canonical}' which is not in the catalog"
            )


class TestResolveSpanishToCanonical:
    def test_exact_spanish_phrase(self) -> None:
        assert resolve_spanish_to_canonical("trabaja para") == "works_for"
        assert resolve_spanish_to_canonical("aliado de") == "ally_of"
        assert resolve_spanish_to_canonical("miembro de") == "member_of"

    def test_already_canonical_key_returned_as_is(self) -> None:
        assert resolve_spanish_to_canonical("works_for") == "works_for"
        assert resolve_spanish_to_canonical("ally_of") == "ally_of"
        assert resolve_spanish_to_canonical("member_of") == "member_of"

    def test_case_insensitive(self) -> None:
        assert resolve_spanish_to_canonical("Trabaja Para") is not None
        assert resolve_spanish_to_canonical("ALIADO DE") is not None

    def test_with_diacritics(self) -> None:
        result = resolve_spanish_to_canonical("traicionó a")
        assert result == "betrayed"

    def test_unknown_phrase_returns_none(self) -> None:
        assert resolve_spanish_to_canonical("blah blah nonsense xyz") is None
        assert resolve_spanish_to_canonical("totally unknown phrase 123") is None

    def test_empty_string_returns_none(self) -> None:
        assert resolve_spanish_to_canonical("") is None

    def test_common_variations(self) -> None:
        assert resolve_spanish_to_canonical("enemigos") == "conflicts_with"
        assert resolve_spanish_to_canonical("teme a") == "fears"
        assert resolve_spanish_to_canonical("sospecha de") == "suspects"


class TestNormalizeEntityType:
    def test_canonical_values_returned_unchanged(self) -> None:
        assert normalize_entity_type("npc") == EntityType.NPC
        assert normalize_entity_type("organization") == EntityType.ORGANIZATION
        assert normalize_entity_type("faction") == EntityType.FACTION

    def test_legacy_spanish_values(self) -> None:
        assert normalize_entity_type("corporacion") == EntityType.ORGANIZATION
        assert normalize_entity_type("faccion") == EntityType.FACTION
        assert normalize_entity_type("clan") == EntityType.FACTION
        assert normalize_entity_type("grupo") == EntityType.OTHER
        assert normalize_entity_type("fuerza") == EntityType.ORGANIZATION

    def test_corporation_gang_aliases(self) -> None:
        assert normalize_entity_type("corporation") == EntityType.ORGANIZATION
        assert normalize_entity_type("gang") == EntityType.ORGANIZATION

    def test_unknown_falls_back_to_other(self) -> None:
        assert normalize_entity_type("xyz_unknown") == EntityType.OTHER
        assert normalize_entity_type("") == EntityType.OTHER

    def test_case_insensitive(self) -> None:
        assert normalize_entity_type("NPC") == EntityType.NPC
        assert normalize_entity_type("Faction") == EntityType.FACTION


class TestBuildCatalogPromptBlock:
    def test_returns_non_empty_string(self) -> None:
        block = build_catalog_prompt_block()
        assert isinstance(block, str)
        assert len(block) > 100

    def test_contains_known_keys(self) -> None:
        block = build_catalog_prompt_block()
        assert "works_for" in block
        assert "ally_of" in block
        assert "member_of" in block

    def test_contains_family_headers(self) -> None:
        block = build_catalog_prompt_block()
        assert "SOCIAL" in block
        assert "HIERARCHY" in block
        assert "CONFLICT" in block
