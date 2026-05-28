# Previous-Session Chronology Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When generating a session chronology, inject the previous session's stored chronology as context so the LLM omits recap events and flags discrepancies.

**Architecture:** Three-layer change: (1) new DB query method to fetch the previous session's chronology, (2) updated prompt template with previous-session block and new instructions, (3) summarizer passes the fetched chronology into `_build_chronology_system_prompt`. Post-hoc chronology regeneration (`generate_chronology_from_transcriptions`) bypasses the DB lookup via `include_previous=False`.

**Tech Stack:** Python 3.10, aiosqlite, Anthropic SDK, pytest-asyncio

---

### Task 1: DB — `get_previous_session_chronology`

**Files:**
- Modify: `src/rpg_scribe/core/database/repositories/session_repo.py`
- Test: `tests/test_database.py` (add `TestGetPreviousSessionChronology` class)

- [ ] **Step 1: Write the failing tests**

Add at the bottom of `tests/test_database.py`:

```python
class TestGetPreviousSessionChronology:
    async def test_returns_chronology_of_most_recent_completed_session(
        self, db: Database
    ) -> None:
        await db.campaigns.upsert_campaign(campaign_id="c1", name="Test")
        await db.sessions.create_session("s1", "c1")
        await db.sessions.end_session("s1", summary="S1", chronology="Cronología sesión 1.")
        await db.sessions.create_session("s2", "c1")
        await db.sessions.end_session("s2", summary="S2", chronology="Cronología sesión 2.")
        await db.sessions.create_session("s3", "c1")  # active, this is the "current"

        result = await db.sessions.get_previous_session_chronology("c1", "s3")
        assert result == "Cronología sesión 2."

    async def test_excludes_current_session(self, db: Database) -> None:
        await db.campaigns.upsert_campaign(campaign_id="c1", name="Test")
        await db.sessions.create_session("s1", "c1")
        await db.sessions.end_session("s1", summary="S1", chronology="Cronología sesión 1.")

        result = await db.sessions.get_previous_session_chronology("c1", "s1")
        assert result == ""

    async def test_returns_empty_when_no_previous_session(self, db: Database) -> None:
        await db.campaigns.upsert_campaign(campaign_id="c1", name="Test")
        await db.sessions.create_session("s1", "c1")

        result = await db.sessions.get_previous_session_chronology("c1", "s1")
        assert result == ""

    async def test_returns_empty_when_previous_has_no_chronology(
        self, db: Database
    ) -> None:
        await db.campaigns.upsert_campaign(campaign_id="c1", name="Test")
        await db.sessions.create_session("s1", "c1")
        await db.sessions.end_session("s1", summary="S1")  # no chronology arg
        await db.sessions.create_session("s2", "c1")

        result = await db.sessions.get_previous_session_chronology("c1", "s2")
        assert result == ""

    async def test_ignores_active_sessions(self, db: Database) -> None:
        await db.campaigns.upsert_campaign(campaign_id="c1", name="Test")
        await db.sessions.create_session("s1", "c1")
        await db.sessions.end_session("s1", summary="S1", chronology="Antigua.")
        await db.sessions.create_session("s2", "c1")  # active, not ended
        await db.sessions.create_session("s3", "c1")

        result = await db.sessions.get_previous_session_chronology("c1", "s3")
        assert result == "Antigua."
```

- [ ] **Step 2: Run tests to confirm they fail**

```
pytest tests/test_database.py::TestGetPreviousSessionChronology -v
```

Expected: `AttributeError: 'SessionRepository' object has no attribute 'get_previous_session_chronology'`

- [ ] **Step 3: Implement the method**

Add at the end of `SessionRepository` in `src/rpg_scribe/core/database/repositories/session_repo.py`:

```python
async def get_previous_session_chronology(
    self, campaign_id: str, current_session_id: str
) -> str:
    """Return the chronology of the most recent completed session for *campaign_id*,
    excluding *current_session_id*.

    Returns "" if no qualifying session exists or its chronology is empty.
    """
    cursor = await self.conn.execute(
        """
        SELECT session_chronology FROM sessions
        WHERE campaign_id = ?
          AND id != ?
          AND status = 'completed'
          AND (merged_into IS NULL OR merged_into = '')
          AND ended_at IS NOT NULL
        ORDER BY ended_at DESC
        LIMIT 1
        """,
        (campaign_id, current_session_id),
    )
    row = await cursor.fetchone()
    if row is None:
        return ""
    return row["session_chronology"] or ""
```

- [ ] **Step 4: Run tests to confirm they pass**

```
pytest tests/test_database.py::TestGetPreviousSessionChronology -v
```

Expected: 5 tests PASS

- [ ] **Step 5: Run full suite to check for regressions**

```
pytest tests/test_database.py -v
```

Expected: all pass

- [ ] **Step 6: Commit**

```
git add src/rpg_scribe/core/database/repositories/session_repo.py tests/test_database.py
git commit -m "feat: add get_previous_session_chronology to SessionRepository"
```

---

### Task 2: Prompt — update `CHRONOLOGY_SYSTEM_PROMPT`

**Files:**
- Modify: `src/rpg_scribe/summarizers/prompts.py`

- [ ] **Step 1: Replace `CHRONOLOGY_SYSTEM_PROMPT` in `prompts.py`**

Replace the entire `CHRONOLOGY_SYSTEM_PROMPT` constant (lines 157–204) with:

```python
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

{previous_session_block}\
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
8. Si la transcripción contiene un repaso verbal de la sesión anterior \
(el Master o los jugadores recuerdan lo que pasó), NO incluyas esos eventos \
como parte de la nueva sesión. Son referencias al pasado, no eventos nuevos.
9. Si el Master corrige o contradice algo de la cronología anterior, incluye \
al principio del texto una sección "## Discrepancias con la sesión anterior" \
listando cada corrección detectada, antes de comenzar la cronología nueva.
"""
```

- [ ] **Step 2: Confirm the prompt change compiles (no syntax errors)**

```
python -c "from rpg_scribe.summarizers.prompts import CHRONOLOGY_SYSTEM_PROMPT; print('ok')"
```

Expected: `ok`. Note: existing chronology tests will fail with `KeyError: 'previous_session_block'` until Task 3 updates `_build_chronology_system_prompt` — this is expected.

- [ ] **Step 3: Commit (prompt only, tests will pass after Task 3)**

```
git add src/rpg_scribe/summarizers/prompts.py
git commit -m "feat: add previous_session_block and recap/discrepancy instructions to CHRONOLOGY_SYSTEM_PROMPT"
```

---

### Task 3: Summarizer — wire previous chronology into `generate_chronology`

**Files:**
- Modify: `src/rpg_scribe/summarizers/claude_summarizer.py`
- Test: `tests/test_summarizer.py` (add `TestChronologyPreviousSession` class)

- [ ] **Step 1: Write the failing tests**

Add at the bottom of `tests/test_summarizer.py` (after the last class):

```python
class TestChronologyPreviousSession:
    """generate_chronology injects previous session chronology when available."""

    @pytest.fixture
    def bus(self):
        return EventBus()

    @pytest.fixture
    def config(self):
        return _make_config()

    @pytest.fixture
    def campaign(self):
        return _make_campaign()

    @pytest.fixture
    def mock_client(self):
        client = MagicMock()
        client.messages = MagicMock()
        client.messages.create = AsyncMock(
            return_value=_mock_anthropic_response("Cronología de la nueva sesión.")
        )
        return client

    @pytest.mark.asyncio
    async def test_build_chronology_system_prompt_includes_previous_block(
        self, bus, config, campaign, mock_client
    ):
        """When previous_session_chronology is non-empty the block appears in the prompt."""
        summarizer = ClaudeSummarizer(bus, config, campaign, client=mock_client)
        prompt = summarizer._build_chronology_system_prompt(
            previous_session_chronology="Escena 1: Los héroes entraron al castillo."
        )
        assert "CRONOLOGÍA DE LA SESIÓN ANTERIOR:" in prompt
        assert "Escena 1: Los héroes entraron al castillo." in prompt

    @pytest.mark.asyncio
    async def test_build_chronology_system_prompt_empty_when_no_previous(
        self, bus, config, campaign, mock_client
    ):
        """When previous_session_chronology is empty no previous block is added."""
        summarizer = ClaudeSummarizer(bus, config, campaign, client=mock_client)
        prompt = summarizer._build_chronology_system_prompt()
        assert "CRONOLOGÍA DE LA SESIÓN ANTERIOR:" not in prompt

    @pytest.mark.asyncio
    async def test_generate_chronology_fetches_and_injects_previous(
        self, bus, config, campaign, mock_client
    ):
        """generate_chronology queries DB for the previous chronology and includes it."""
        db = AsyncMock(spec=Database)
        db.sessions = MagicMock()
        db.sessions.get_previous_session_chronology = AsyncMock(
            return_value="Escena previa: el grupo llegó a la ciudad."
        )

        summarizer = ClaudeSummarizer(
            bus, config, campaign, client=mock_client, database=db
        )
        await summarizer.start("session-42")

        entries = [TranscriptionEntry("u1", "Aelar", "Buscamos al mercader.", time.time())]
        await summarizer.generate_chronology(entries)

        db.sessions.get_previous_session_chronology.assert_awaited_once_with(
            "test-campaign", "session-42"
        )
        system_used = mock_client.messages.create.call_args.kwargs["system"]
        assert "Escena previa: el grupo llegó a la ciudad." in system_used

    @pytest.mark.asyncio
    async def test_generate_chronology_include_previous_false_skips_db(
        self, bus, config, campaign, mock_client
    ):
        """With include_previous=False the DB is not queried."""
        db = AsyncMock(spec=Database)
        db.sessions = MagicMock()
        db.sessions.get_previous_session_chronology = AsyncMock(return_value="Algo.")

        summarizer = ClaudeSummarizer(
            bus, config, campaign, client=mock_client, database=db
        )
        await summarizer.start("session-1")

        entries = [TranscriptionEntry("u1", "Aelar", "Texto.", time.time())]
        await summarizer.generate_chronology(entries, include_previous=False)

        db.sessions.get_previous_session_chronology.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_generate_chronology_generic_campaign_skips_db(
        self, bus, config, mock_client
    ):
        """Generic campaign (no campaign_id) does not query the DB."""
        generic_campaign = CampaignContext.create_generic(language="es")
        db = AsyncMock(spec=Database)
        db.sessions = MagicMock()
        db.sessions.get_previous_session_chronology = AsyncMock(return_value="Algo.")

        summarizer = ClaudeSummarizer(
            bus, config, generic_campaign, client=mock_client, database=db
        )
        await summarizer.start("session-1")

        entries = [TranscriptionEntry("u1", "Alice", "Texto.", time.time())]
        await summarizer.generate_chronology(entries)

        db.sessions.get_previous_session_chronology.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_generate_chronology_from_transcriptions_skips_db(
        self, bus, config, campaign, mock_client
    ):
        """generate_chronology_from_transcriptions uses include_previous=False."""
        db = AsyncMock(spec=Database)
        db.sessions = MagicMock()
        db.sessions.get_previous_session_chronology = AsyncMock(return_value="Algo.")

        summarizer = ClaudeSummarizer(
            bus, config, campaign, client=mock_client, database=db
        )
        await summarizer.start("session-1")

        rows = [{"speaker_id": "u1", "speaker_name": "Aelar", "text": "Texto.", "timestamp": time.time(), "is_ingame": True}]
        await summarizer.generate_chronology_from_transcriptions(rows)

        db.sessions.get_previous_session_chronology.assert_not_awaited()
```

- [ ] **Step 2: Run tests to confirm they fail**

```
pytest tests/test_summarizer.py::TestChronologyPreviousSession -v
```

Expected: failures on `_build_chronology_system_prompt` (missing `previous_session_block` kwarg) and `generate_chronology` (no `include_previous` param, no DB lookup).

- [ ] **Step 3: Update `_build_chronology_system_prompt`**

In `src/rpg_scribe/summarizers/claude_summarizer.py`, replace the `_build_chronology_system_prompt` method:

```python
def _build_chronology_system_prompt(
    self, previous_session_chronology: str = ""
) -> str:
    """Build the system prompt for chronological timeline generation."""
    c = self.campaign
    previous_session_block = (
        f"CRONOLOGÍA DE LA SESIÓN ANTERIOR:\n{previous_session_chronology}\n\n"
        if previous_session_chronology
        else ""
    )

    if c.is_generic:
        return CHRONOLOGY_SYSTEM_PROMPT.format(
            game_system="(genérico)",
            name="(sin campaña)",
            description="Resumen genérico de conversación",
            players_block="(desconocidos)",
            locations_block="(ninguna conocida)",
            npcs_block="(ninguno conocido)",
            relationships_block="(ninguna registrada)",
            previous_session_block=previous_session_block,
        )

    return CHRONOLOGY_SYSTEM_PROMPT.format(
        game_system=c.game_system,
        name=c.name,
        description=c.description,
        players_block=self._build_players_block(),
        locations_block=self._build_locations_block(),
        npcs_block=self._build_npcs_block(),
        relationships_block=self._build_relationships_block(),
        previous_session_block=previous_session_block,
    )
```

- [ ] **Step 4: Update `generate_chronology` signature and add DB lookup**

Replace the `generate_chronology` method signature and opening block (the part before the first API call) in `claude_summarizer.py`. The method currently starts:

```python
async def generate_chronology(
    self,
    entries: list[TranscriptionEntry],
) -> str:
    if not entries:
        return ""

    system = self._build_chronology_system_prompt()
```

Replace with:

```python
async def generate_chronology(
    self,
    entries: list[TranscriptionEntry],
    *,
    include_previous: bool = True,
) -> str:
    if not entries:
        return ""

    previous_chronology = ""
    if (
        include_previous
        and self._database is not None
        and not self.campaign.is_generic
        and self._session_id
    ):
        previous_chronology = (
            await self._database.sessions.get_previous_session_chronology(
                self.campaign.campaign_id, self._session_id
            )
        )

    system = self._build_chronology_system_prompt(previous_chronology)
```

- [ ] **Step 5: Update `generate_chronology_from_transcriptions` to pass `include_previous=False`**

Find the last line of `generate_chronology_from_transcriptions`:

```python
        return await self.generate_chronology(entries=entries)
```

Replace with:

```python
        return await self.generate_chronology(entries=entries, include_previous=False)
```

- [ ] **Step 6: Run new tests**

```
pytest tests/test_summarizer.py::TestChronologyPreviousSession -v
```

Expected: 6 tests PASS

- [ ] **Step 7: Run full summarizer suite to check for regressions**

```
pytest tests/test_summarizer.py -v
```

Expected: all pass (pre-existing failures excluded per CLAUDE.md)

- [ ] **Step 8: Run full test suite**

```
pytest -x
```

Expected: all pass

- [ ] **Step 9: Commit**

```
git add src/rpg_scribe/summarizers/claude_summarizer.py tests/test_summarizer.py
git commit -m "feat: inject previous session chronology context into generate_chronology"
```
