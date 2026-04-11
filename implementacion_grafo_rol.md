# Documento de implementación para Codex

## Objetivo

Evolucionar el modelo actual de relaciones del sistema de extracción de entidades y relaciones a un modelo canónico más rico, orientado a transcripciones de partidas de rol, con especial atención a:

- contexto narrativo
- temporalidad
- incertidumbre
- procedencia de la información
- posibilidad de construir vistas derivadas ponderadas para análisis y visualización

El dominio inicial es una partida ambientada en **Cyberpunk 2077**, pero el diseño debe ser suficientemente genérico para reutilizarse en otros mundos o campañas.

---

## Situación actual

Actualmente, una relación entre entidades se modela de forma simplificada como:

- `source`
- `target`
- `relationship_type` como texto libre

Problemas del modelo actual:

1. El tipo de relación en texto libre genera mucha variabilidad y poca consistencia.
2. No diferencia entre relación explícita, inferida o curada manualmente.
3. No captura bien contexto narrativo, tiempo, sesión, escena o evidencia.
4. No permite derivar con facilidad un grafo agregado ponderado sin perder trazabilidad.
5. No distingue adecuadamente entre hechos, rumores, sospechas, objetivos o estados emocionales.

---

## Objetivo funcional

Pasar a un modelo con dos capas:

### 1. Capa canónica
Fuente de verdad semántica.

Debe preservar:

- tipo de entidad
- tipo de relación normalizado
- evidencia de origen
- contexto narrativo
- confianza
- perspectiva
- temporalidad
- origen de la relación

### 2. Capa derivada ponderada
Vista simplificada para:

- exploración visual
- ranking de relevancia
- detección de clusters
- centralidad
- navegación entre entidades
- cambio de modo en la UI

Esta capa se construye a partir de la canónica y **no sustituye** al modelo fuente.

---

## Principios de diseño

1. **No perder semántica pronto**. La agregación debe ocurrir después de extraer y normalizar.
2. **Separar extracción de interpretación**. Lo extraído no es lo mismo que lo inferido.
3. **Mantener trazabilidad**. Toda relación relevante debe apuntar a una o varias evidencias.
4. **Normalizar tipos de relación**. Evitar texto libre como base del sistema.
5. **Permitir extensión por dominio**. Cyberpunk 2077 hoy, otros mundos mañana.
6. **Aceptar incertidumbre**. En una partida hay rumores, puntos de vista y hechos parciales.
7. **Preparar la representación para cambio de vista**. Grafo semántico, grafo agregado y vista temporal.

---

## Modelo conceptual propuesto

## Entidades

Se recomienda que las entidades tengan al menos:

- `id`
- `entity_type`
- `canonical_name`
- `aliases[]`
- `description`
- `world`
- `campaign_id`
- `status`
- `metadata`

### Tipos de entidad sugeridos

- `player_character`
- `npc`
- `faction`
- `location`
- `item`
- `vehicle`
- `organization`
- `event`
- `objective`
- `theme`
- `technology`
- `corporation`
- `gang`
- `scene`
- `session`

Notas:

- `corporation` y `gang` pueden ser subtipos de `organization` si se prefiere un modelo más compacto.
- `theme` sirve para etiquetas narrativas o conceptuales: traición, deuda, paranoia, supervivencia, honor, etc.
- `event` debe usarse para sucesos relevantes y persistentes en el grafo.

---

## Relaciones canónicas

La relación deja de ser solo un texto libre y pasa a tener estructura.

### Estructura base sugerida

```json
{
  "id": "rel_123",
  "source_entity_id": "ent_a",
  "target_entity_id": "ent_b",
  "relation_type": "ally_of",
  "relation_family": "social",
  "strength": 0.72,
  "confidence": 0.81,
  "polarity": "positive",
  "certainty": "explicit",
  "perspective_entity_id": "ent_observer_optional",
  "origin": "extracted",
  "source_summary_id": "sum_12",
  "source_session_id": "sess_04",
  "source_scene_id": "scene_03",
  "evidence_snippets": ["..."] ,
  "first_seen_at": "session_03",
  "last_seen_at": "session_04",
  "is_active": true,
  "metadata": {}
}
```

### Nuevos campos recomendados

- `relation_type`: valor normalizado de catálogo, nunca texto libre arbitrario en persistencia principal.
- `relation_family`: agrupación amplia para explotar filtros y visualización.
- `strength`: intensidad estimada de la relación.
- `confidence`: confianza de extracción o validación.
- `polarity`: positiva, negativa, neutra, mixta.
- `certainty`: explícita, inferida, rumor, sospecha, memoria, plan, etc.
- `perspective_entity_id`: quién sostiene esa visión si aplica.
- `origin`: `extracted`, `inferred`, `curated`.
- `source_summary_id`: resumen o bloque de contexto del que nace.
- `source_session_id`: sesión asociada.
- `source_scene_id`: escena asociada si existe.
- `evidence_snippets`: fragmentos de texto o referencias de evidencia.
- `first_seen_at` / `last_seen_at`: útiles para evolución narrativa.
- `is_active`: algunas relaciones expiran o cambian.
- `metadata`: campo flexible para extensiones.

---

## Catálogo de familias de relación

Se propone una clasificación de alto nivel.

- `identity`
- `social`
- `hierarchy`
- `conflict`
- `affiliation`
- `location`
- `ownership`
- `objective`
- `knowledge`
- `event_participation`
- `transaction`
- `emotional`
- `narrative`
- `temporal`

Estas familias ayudan a:

- agrupar y filtrar
- colorear el grafo
- simplificar prompts de extracción
- crear vistas agregadas

---

## Catálogo inicial de tipos de relación normalizados

El sistema debe usar una lista cerrada inicial, extensible en el futuro.

### Identity

- `is`
- `alias_of`
- `same_as`
- `disguised_as`

### Social

- `knows`
- `ally_of`
- `friend_of`
- `close_to`
- `protects`
- `mentors`
- `depends_on`
- `owes`
- `trusts`
- `distrusts`
- `fears`
- `admires`
- `loves`
- `hates`

### Hierarchy

- `commands`
- `reports_to`
- `works_for`
- `controls`
- `serves`

### Conflict

- `conflicts_with`
- `hunts`
- `betrayed`
- `threatens`
- `attacked`
- `pursues`
- `competes_with`

### Affiliation

- `member_of`
- `belongs_to`
- `aligned_with`
- `loyal_to`
- `associated_with`

### Location

- `located_in`
- `lives_in`
- `operates_in`
- `last_seen_in`
- `travels_to`
- `hides_in`

### Ownership / resources

- `owns`
- `uses`
- `seeks`
- `stole`
- `lost`
- `delivered`
- `has_access_to`

### Objective

- `wants`
- `needs`
- `investigates`
- `searches_for`
- `must_protect`
- `must_destroy`
- `must_reach`
- `is_target_of`

### Knowledge

- `knows_about`
- `suspects`
- `rumors_about`
- `revealed_to`
- `hides_information_from`
- `informed_about`

### Event participation

- `participated_in`
- `caused`
- `triggered`
- `survived`
- `witnessed`
- `was_present_at`
- `died_in`

### Transaction

- `paid`
- `bought_from`
- `sold_to`
- `hired`
- `rewarded`
- `blackmailed`
- `extorted`

### Narrative / thematic

- `connected_to_theme`
- `symbolizes`
- `mirrors`
- `foreshadows`

Notas:

- No es obligatorio usar todos desde el primer día.
- Se recomienda empezar por un subconjunto estable y ampliar después.
- Mantener siempre una tabla o enumeración centralizada.

---

## Etiquetas o tags complementarios

Además del `relation_type`, puede existir una colección de etiquetas auxiliares.

Ejemplos de tags para relaciones:

- `betrayal`
- `debt`
- `romance`
- `paranoia`
- `violence`
- `corporate`
- `street`
- `survival`
- `political`
- `family`
- `crime`
- `cyberware`
- `mission_related`
- `flashback`
- `secret`

Ejemplos de tags para entidades:

- `fixer`
- `mercenary`
- `netrunner`
- `corporate`
- `gang_member`
- `nomad`
- `police`
- `militech`
- `arasaka`
- `dangerous`
- `injured`
- `missing`
- `dead`
- `unknown_identity`

Estas etiquetas no deben sustituir el `relation_type`, sino enriquecer el análisis.

---

## Diferencia entre tipo de relación y etiquetas

### `relation_type`
Es la semántica principal, normalizada y estable.

Ejemplo:
- `betrayed`
- `member_of`
- `wants`

### `tags[]`
Son calificadores o señales secundarias.

Ejemplo:
- `secret`
- `corporate`
- `high_risk`
- `mission_related`

Regla general:

- si una semántica cambia la naturaleza de la relación, debe ser `relation_type`
- si solo añade matiz, debe ir como `tag`

---

## Estados de certeza recomendados

Dado que el dominio es narrativo, se recomienda normalizar también la naturaleza epistemológica de la relación.

Valores sugeridos para `certainty`:

- `explicit`
- `inferred`
- `rumor`
- `suspected`
- `claimed`
- `remembered`
- `planned`
- `uncertain`

Ejemplos:

- Un NPC dice “creo que trabaja para Arasaka” → `works_for` + `certainty = suspected`
- El resumen deduce “parecen aliados” → `ally_of` + `certainty = inferred`
- Se ve claramente en escena → `certainty = explicit`

---

## Origen de la relación

Campo `origin`:

- `extracted`: extraída directamente del texto o resumen
- `inferred`: deducida por el modelo
- `curated`: añadida o corregida manualmente por usuarios
- `imported`: cargada desde una fuente externa estructurada

Esto es obligatorio para poder confiar de forma distinta en cada capa del sistema.

---

## Temporalidad

Las relaciones en una campaña cambian. Por eso hay que modelar el tiempo.

Campos mínimos recomendados:

- `first_seen_at`
- `last_seen_at`
- `source_session_id`
- `source_scene_id`
- `is_active`

Opcionalmente:

- `valid_from`
- `valid_to`
- `timeline_order`

Ejemplo:

Un personaje puede tener:

- `ally_of` en la sesión 2
- `betrayed` en la sesión 5
- `conflicts_with` en la sesión 6

No deben pisarse sin más. Debe conservarse evolución o al menos histórico.

---

## Uso de eventos como entidades de primer nivel

Se recomienda promover eventos importantes a entidades.

Ejemplo:

En lugar de solo:

- A `betrayed` B

conviene poder guardar también:

- A `participated_in` Evento_X
- B `participated_in` Evento_X
- Evento_X `caused` ruptura_de_confianza

Ventajas:

- mejores resúmenes
- trazabilidad narrativa
- reconstrucción de arcos
- visualización temporal más rica

Promover a `event` cuando:

- el suceso tiene consecuencias duraderas
- afecta a varias entidades
- reaparece en sesiones posteriores
- sirve como pivote narrativo

---

## Capa derivada ponderada

Esta capa se genera a partir de la canónica.

### Objetivo

Construir una arista agregada entre dos entidades principales para responder cosas como:

- qué tan conectadas están
- por qué lo están
- en cuántas sesiones aparecen juntas
- qué tipo de vínculo domina

### Estructura sugerida

```json
{
  "source_entity_id": "ent_a",
  "target_entity_id": "ent_b",
  "aggregated_weight": 0.84,
  "relation_count": 9,
  "distinct_relation_types": 4,
  "top_relation_types": ["ally_of", "owes", "investigates"],
  "top_tags": ["mission_related", "debt"],
  "session_span": 3,
  "evidence_count": 12
}
```

### Posible fórmula inicial de peso

Versión simple:

`aggregated_weight = suma(rel.strength * rel.confidence * factor_relation_type * factor_recency)`

Añadidos opcionales:

- bonus por diversidad de tipos de relación
- bonus por persistencia en varias sesiones
- penalización por evidencia débil
- penalización por relaciones de tipo rumor o sospecha

### Recomendación

No usar solo “número de etiquetas compartidas” como criterio principal.

Mejor combinar:

- frecuencia
- confianza
- recencia
- importancia narrativa
- tipo de relación

---

## Cambios concretos a implementar en el modelo actual

Partimos del modelo actual:

- `source`
- `target`
- `relationship_type` texto libre

### Objetivo de migración

Pasar a algo conceptualmente equivalente a:

- `source_entity_id`
- `target_entity_id`
- `relation_type`
- `relation_family`
- `tags[]`
- `confidence`
- `strength`
- `certainty`
- `origin`
- `source_summary_id`
- `source_session_id`
- `source_scene_id`
- `evidence_snippets[]`
- `first_seen_at`
- `last_seen_at`
- `is_active`
- `metadata`

### Compatibilidad hacia atrás

Durante una fase transicional:

- mantener `relationship_type_raw`
- calcular `relation_type` normalizado a partir de ese valor
- registrar casos no mapeados para revisión manual

Ejemplo:

- `relationship_type_raw = "trabaja para"`
- `relation_type = "works_for"`
- `relation_family = "hierarchy"`

---

## Estrategia de normalización del tipo libre actual

Crear una capa de normalización con reglas y fallback.

### Paso 1: catálogo de equivalencias

Ejemplos:

- `trabaja para` → `works_for`
- `es aliado de` → `ally_of`
- `odia a` → `hates`
- `pertenece a` → `member_of`
- `busca` → `searches_for`
- `quiere` → `wants`

### Paso 2: resolución con LLM si no hay match claro

El modelo recibe:

- el tipo libre original
- entidades implicadas
- contexto textual
- lista cerrada de tipos posibles

Y debe escoger solo uno o marcar `unknown_relation_type`.

### Paso 3: cola de revisión manual

Todos los no mapeados o de baja confianza deben quedar trazados.

---

## Pipeline recomendado de extracción

## Entrada

Transcripción de sesión.

## Fases

### 1. Segmentación
Dividir en escenas, bloques narrativos o ventanas manejables.

### 2. Summaries y contexto
Generar:

- resumen narrativo
- resumen factual
- contexto de sesión
- eventos clave
- cambios de estado relevantes

### 3. Extracción de entidades
Usar catálogo de tipos conocido y alias.

### 4. Extracción de relaciones
En esta fase el modelo debe trabajar con:

- el catálogo de entidades existentes
- los tipos de entidad disponibles
- el catálogo cerrado de `relation_type`
- familias de relación
- ejemplos positivos y negativos

### 5. Normalización
Resolver aliases, duplicados, tipos y relaciones.

### 6. Enriquecimiento
Añadir:

- tags
- confidence
- certainty
- origin
- evidencia
- temporalidad

### 7. Persistencia canónica
Guardar el grafo rico.

### 8. Generación derivada
Construir el grafo agregado ponderado.

---

## Instrucciones para Codex sobre la capa de extracción

Cuando se modifique la extracción de relaciones, el modelo debe recibir explícitamente los modelos y catálogos existentes.

### Recomendación de prompt técnico para extracción

El extractor no debe inventar estructuras arbitrarias. Debe trabajar con los modelos definidos por el sistema.

Debe conocer:

- el esquema de entidades existente
- el esquema de relaciones existente
- los campos obligatorios
- la lista cerrada de `relation_type`
- la lista de `entity_type`
- las etiquetas comunes sugeridas

### Regla crítica

No usar texto libre como valor final de `relation_type`.

Si no encuentra un match razonable:

- usar `unknown_relation_type` o equivalente temporal
- rellenar `relationship_type_raw`
- bajar `confidence`
- dejar trazabilidad para revisión

### Sugerencia de comportamiento del extractor

1. Identifica entidades candidatas.
2. Reutiliza entidades ya existentes si hay match semántico o alias.
3. Extrae relaciones solo si hay evidencia suficiente.
4. Selecciona `relation_type` desde una lista cerrada.
5. Añade `tags[]` si aportan matiz.
6. Indica `certainty` y `origin` correctamente.
7. Devuelve fragmentos de evidencia cuando sea posible.
8. No colapse varias relaciones distintas en una sola si representan semánticas distintas.

---

## Sugerencia de tipos y etiquetas a inyectar al modelo

### Tipos de entidad base

- `player_character`
- `npc`
- `faction`
- `location`
- `item`
- `vehicle`
- `organization`
- `event`
- `objective`
- `theme`
- `technology`
- `corporation`
- `gang`
- `scene`
- `session`

### Tipos de relación base

- `knows`
- `ally_of`
- `friend_of`
- `protects`
- `trusts`
- `distrusts`
- `fears`
- `works_for`
- `commands`
- `reports_to`
- `member_of`
- `belongs_to`
- `conflicts_with`
- `betrayed`
- `threatens`
- `located_in`
- `operates_in`
- `owns`
- `uses`
- `wants`
- `needs`
- `investigates`
- `searches_for`
- `is_target_of`
- `knows_about`
- `suspects`
- `rumors_about`
- `participated_in`
- `caused`
- `triggered`
- `hired`
- `paid`
- `blackmailed`
- `connected_to_theme`

### Tags sugeridos iniciales

- `mission_related`
- `secret`
- `debt`
- `betrayal`
- `family`
- `romance`
- `violence`
- `crime`
- `corporate`
- `street`
- `cyberware`
- `survival`
- `political`
- `high_risk`
- `temporary`
- `flashback`

---

## Recomendaciones de implementación técnica

### 1. Añadir catálogo centralizado

Crear una definición central para:

- `entity_type`
- `relation_type`
- `relation_family`
- `certainty`
- `origin`

Puede ser:

- enum
- tabla en base de datos
- constantes tipadas en código

Lo importante es que sea única y reutilizable.

### 2. Mantener campo raw mientras dure la transición

Añadir:

- `relationship_type_raw`
- `normalization_status`
- `normalization_notes`

### 3. Añadir capacidad de múltiples evidencias

Una relación puede estar respaldada por varios resúmenes o escenas.

### 4. Preparar endpoints o servicios para vistas distintas

- vista canónica
- vista agregada
- vista temporal
- vista centrada en entidad

### 5. No mezclar capa canónica con capa derivada en persistencia principal

La agregada debe vivir aparte o marcarse claramente como derivada.

---

## Fases recomendadas de implementación

### Fase 1
- introducir catálogos
- añadir nuevos campos a relaciones
- mantener compatibilidad con el modelo actual

### Fase 2
- implementar normalización del texto libre actual
- registrar no mapeados

### Fase 3
- adaptar prompts y capa de extracción para usar lista cerrada
- inyectar modelos existentes al extractor

### Fase 4
- construir grafo agregado ponderado
- añadir modo de visualización alternable en frontend

### Fase 5
- introducir relaciones temporales e históricas más avanzadas
- refinar pesos y relevancia narrativa

---

## Criterios de aceptación

1. Ya no se persisten nuevas relaciones con `relation_type` totalmente libre.
2. Toda relación nueva tiene `relation_type` normalizado.
3. Se conserva el valor original en `relationship_type_raw` cuando aplique.
4. Toda relación nueva puede indicar `origin` y `confidence`.
5. La extracción conoce el catálogo de tipos soportados.
6. Se puede generar una vista agregada entre entidades.
7. El frontend puede cambiar al menos entre modo canónico y modo ponderado.
8. Los casos ambiguos quedan trazados para revisión.

---

## Riesgos y decisiones a vigilar

### Riesgos

- exceso de tipos de relación demasiado pronto
- prompts demasiado abiertos
- pérdida de trazabilidad durante la migración
- mezcla entre hecho e inferencia
- peso agregado mal calibrado

### Decisiones importantes

- si `corporation` y `gang` serán subtipos o tipos independientes
- si `scene` será entidad real o solo metadato
- si `event` se crea siempre o solo para eventos importantes
- si las etiquetas serán libres o también normalizadas

---

## Instrucción final para Codex

Implementar la evolución del modelo de relaciones desde un esquema basado en texto libre a un esquema canónico normalizado, preservando compatibilidad transitoria, trazabilidad de origen y capacidad de derivar un grafo agregado ponderado.

Al modificar la capa de extracción, proporcionar explícitamente al modelo:

- los modelos existentes del sistema
- los tipos de entidad soportados
- la lista cerrada de tipos de relación
- las etiquetas más comunes sugeridas
- las reglas para distinguir tipo principal frente a tag
- los campos de confianza, certeza, origen y evidencia

La extracción debe producir datos consistentes con el modelo canónico y evitar inventar tipos o estructuras fuera del catálogo salvo en modo controlado de fallback.

