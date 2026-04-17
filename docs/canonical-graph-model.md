# Modelo de Entidades y Relaciones (Grafo Canónico)

El sistema usa un modelo canónico normalizado para entidades y relaciones, con catálogo cerrado de tipos.

## Catálogos centralizados: `src/rpg_scribe/core/catalogs.py`

- **`RelationType`** — ~45 tipos de relación agrupados en 14 familias (`social`, `hierarchy`, `conflict`, `affiliation`, `location`, `ownership`, `objective`, `knowledge`, `event_participation`, `transaction`, `emotional`, `narrative`, `temporal`, `identity`)
- **`EntityType`** — player_character, npc, faction, location, item, organization, event, objective, technology, other
- **`Certainty`** — explicit, inferred, rumor, suspected, claimed, uncertain
- **`RelationOrigin`** — extracted, inferred, curated, imported
- **`SPANISH_EQUIVALENCES`** — mapeo de frases libres en español a claves canónicas
- **`resolve_spanish_to_canonical()`** — normaliza texto libre a clave canónica
- **`normalize_entity_type()`** — mapea valores legacy (`corporacion`, `faccion`, `grupo`) al enum canónico
- **`build_catalog_prompt_block()`** — genera bloque de texto para inyectar en prompts LLM

## Resolución de tipos de relación

`EntityRepository.resolve_relationship_type()` usa tres capas en orden:
1. **Catálogo** — lookup exacto vía `resolve_spanish_to_canonical()` (O(1))
2. **DB exacta** — match por `canonical_key` normalizado
3. **Fuzzy** — SequenceMatcher + Jaccard (threshold 0.88)

Si no hay match, se crea un tipo nuevo con `is_canonical=0`.

## Campos enriquecidos en relaciones

Cada relación incluye: `relation_family`, `strength`, `confidence`, `polarity`, `certainty`, `origin`, `is_active`, `source_session_id`, `evidence_snippets`, `tags`, `type_label_raw`.

## Seed de tipos canónicos

Al cargar una campaña, se puebla `relationship_types` con las entradas del catálogo del sistema (`is_canonical=1`). Los tipos creados por usuario coexisten (`is_canonical=0`).

## API de catálogos

`GET /api/campaigns/{id}/catalogs` — devuelve el catálogo completo (relation_types, families, entity_types, certainty_levels, origins) para uso del frontend.

## Diseño futuro (no implementado aún)

- Capa derivada ponderada (grafo agregado para visualización)
- Vistas temporales (evolución de relaciones entre sesiones)
- Cola de revisión manual para relaciones de baja confianza
- Eventos como entidades de primer nivel
- Toggle frontend canónico/ponderado

Ver documento de diseño completo: [`../implementacion_grafo_rol.md`](../implementacion_grafo_rol.md)
