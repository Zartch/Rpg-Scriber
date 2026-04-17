"""Prompt constants for the Claude summarizer."""

from __future__ import annotations

import re

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
1. Escribe en tercera persona, estilo narrativo. Los personajes \
jugadores (PJs) son los PROTAGONISTAS de la historia — el relato \
debe centrarse en sus acciones, decisiones y experiencias.
2. Distingue entre lo que dicen los personajes (in-game) y las \
conversaciones de los jugadores (meta-rol). El meta-rol NO va \
en el resumen narrativo, pero puedes anotarlo como [META] si \
es relevante (decisiones de grupo, dudas de reglas, etc.).
3. El DM ({dm_name}) habla como múltiples PNJs y también como narrador \
de escena. Cuando habla el DM, su texto puede ser ambientación, \
resultados de tiradas, consecuencias de acciones, eventos del mundo \
o interpretación de distintos PNJs. No lo atribuyas automáticamente \
a un único PNJ sin evidencia contextual. Las líneas del DM marcadas \
con [MASTER] en la transcripción indican que es el director narrando.
4. Mantén el resumen coherente y fluido. Reescribe secciones \
anteriores si nueva información las clarifica.
5. Si algo no está claro, márcalo con [PREGUNTA: ...].
"""

SESSION_UPDATE_USER = """\
TRANSCRIPCIÓN RECIENTE:
{recent_transcriptions}
{chronology_block}\
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
{chronology_block}\
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

CHRONOLOGY_SYSTEM_PROMPT = """\
Eres un guionista de sesiones de rol. Tu trabajo es escribir una cronología \
detallada de la sesión: un relato escena a escena, en orden estricto, que \
pudiera servir como boceto de guión de película.

CONTEXTO:
- Sistema: {game_system}
- Campaña: {name} — {description}

JUGADORES:
{players_block}

LOCALIZACIONES CONOCIDAS:
{locations_block}

PNJS CONOCIDOS:
{npcs_block}

RELACIONES CONOCIDAS:
{relationships_block}

INSTRUCCIONES:
1. Escribe en orden cronológico estricto, cubriendo TODAS las localizaciones \
visitadas y escenas principales.
2. Adapta el tono al setting de la campaña. Ejemplos: para ciberpunk usa un \
estilo noir y directo con jerga urbana; para fantasía medieval usa tono de \
crónica épica; para horror cósmico usa un tono inquietante y atmosférico. \
Sé creativo con el tono pero mantén la claridad.
3. ESCENAS PARALELAS: Cuando el MASTER dice "mientras tanto", "por otro lado", \
"en otro lugar" o cambia bruscamente de grupo de personajes/localización, \
significa que hay escenas que ocurren simultáneamente en distintos lugares. \
Preséntalo como cortes de escena paralelos (ej. "Mientras tanto, en [lugar]...") \
y deja claro que ambas líneas temporales suceden a la vez. En la transcripción, \
las líneas marcadas con [CAMBIO DE ESCENA] indican estos momentos.
4. Para cada escena, incluye: los eventos principales, diálogos significativos \
entre PJs y PNJs (parafraseados o con citas breves), interacciones relevantes \
entre personajes, y conflictos o tensiones que surjan. Escribe como si \
describieras las escenas de una película: quién dice qué, qué reacciones \
provoca, qué tensión hay en el ambiente.
5. Formato: párrafos cortos separados por escena/localización, con \
marcadores temporales si aplican.
6. Las líneas marcadas con [META] son conversaciones fuera de personaje. \
Si alguna aporta contexto útil para entender la escena (ej. una aclaración \
de reglas que afecta a lo que ocurre), puedes incorporar ese contexto en la \
narración. Pero NUNCA cites una línea [META] como diálogo de un personaje \
ni la incluyas como acción in-game.
7. Escribe con fluidez narrativa, no como una lista de puntos.
"""

CHRONOLOGY_USER = """\
A partir de la siguiente transcripción completa de la sesión, genera una \
cronología temporal detallada de lo que ocurrió, incluyendo las \
interacciones y diálogos más relevantes entre personajes.

TRANSCRIPCIÓN:
{transcriptions}

Genera ÚNICAMENTE la cronología detallada, sin explicaciones adicionales."""

CHRONOLOGY_UPDATE_USER = """\
Continúa la cronología de la sesión. A continuación tienes la última escena \
escrita (complétala si quedó a medias, o déjala y continúa si ya estaba \
cerrada) y una nueva sección de transcripción.

ÚLTIMA ESCENA ESCRITA:
{last_scene}

SIGUIENTE SECCIÓN DE TRANSCRIPCIÓN:
{transcriptions}

Genera la continuación empezando desde la última escena (reescríbela si \
necesita completarse) y las escenas nuevas. Sin explicaciones adicionales."""

EXTRACTION_USER = """\
A partir del siguiente resumen de sesión, extrae TODOS los elementos \
narrativos relevantes:

1. **PNJs nuevos**: cualquier personaje con nombre propio que NO sea un jugador
2. **Localizaciones nuevas**: lugares con nombre propio mencionados
3. **Entidades nuevas**: corporaciones, facciones, clanes, grupos, organizaciones, \
fuerzas militares/policiales, o cualquier entidad con nombre propio que no sea \
un personaje individual ni un lugar. IMPORTANTE: incluye TODA corporación, grupo \
u organización mencionada, aunque parezca secundaria o de contexto.
4. **Relaciones nuevas**: vínculos entre personajes, organizaciones y lugares

REGLA CRÍTICA: Si una entidad aparece en una relación (source o target), \
DEBE existir previamente en las listas de NPCs, localizaciones o entidades \
(ya conocidas o recién extraídas en esta respuesta). No crees relaciones \
que referencien entidades que no existen en ninguna lista.

{catalog_block}

TIPOS DE ENTIDAD VÁLIDOS para el campo entity_type:
- npc (personaje no jugador individual)
- faction (facción, clan, banda)
- organization (corporación, empresa, institución, fuerza policial/militar)
- location (lugar — solo si aparece como entidad en una relación)
- item (objeto relevante)
- event (suceso importante con consecuencias duraderas)
- objective (objetivo o misión)
- technology (tecnología, programa, implante)
- other (cualquier otro)

NIVELES DE CERTEZA para el campo certainty:
- explicit: afirmado claramente como hecho en la narración
- inferred: deducido del contexto, no dicho explícitamente
- suspected: un personaje lo cree pero no está confirmado
- rumor: información de segunda mano, no verificada
- claimed: alguien lo afirma, fiabilidad desconocida
- uncertain: evidencia insuficiente

JUGADORES (NO son PNJs, no los extraigas como NPCs):
{players_block}

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
"entities": [{{"name": "Nombre de la entidad", \
"entity_type": "npc|faction|organization|location|item|event|objective|technology|other", \
"description": "Breve descripción"}}], \
"relationships": [{{"source_key": "player:123|npc:Nombre|loc:Lugar|ent:Entidad", \
"target_key": "player:123|npc:Nombre|loc:Lugar|ent:Entidad", \
"relation_type": "works_for|member_of|ally_of|...", \
"certainty": "explicit|inferred|suspected|rumor|claimed|uncertain", \
"strength": 0.5, \
"tags": ["mission_related", "secret"], \
"evidence": "frase breve del resumen que sustenta esta relación", \
"notes": "contexto adicional opcional"}}]}}

Reglas para relation_type:
- Usa SIEMPRE una clave del catálogo proporcionado (ej: works_for, member_of).
- Si ningún tipo encaja bien, usa el más cercano y pon strength <= 0.3.
- Si el LLM retorna texto libre, ponlo en "notes" y elige el tipo más próximo.

Si no hay nuevos elementos, devuelve listas vacías.
"""
