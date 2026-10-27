# RulesBot (consulta de reglas con RAG) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un bot activado por voz ("bot reglas, …") que busca en los manuales RAG configurados, sigue una referencia de página, redacta la respuesta con Claude citando la fuente, la habla por TTS y la escribe como embed en un canal de texto de Discord.

**Architecture:** Pieza pura de recuperación (`RuleRetriever`) sobre la API async de `rag_lib`; pieza pura de redacción (`RuleAnswerer`) sobre `AsyncAnthropic`; un `RulesBot` que las orquesta. El framework de bots gana inyección de dependencias (`BotServices` + `setup()`) y un retorno estructurado (`BotResponse`). El `TriggerWatcher` normaliza el retorno y publica un `BotTextResponseEvent` que un `DiscordBotResponsePublisher` convierte en embed. Toda la config nueva vive en `[campaign.rag]` del TOML de campaña; los secretos siguen viviendo solo en `AppConfig`/env e inyectándose.

**Herencia de configuración (resumen):**
- **Secretos / rutas globales** → `AppConfig` (env): `anthropic_api_key` ← `ANTHROPIC_API_KEY`, `rag_db_path` (default `data/rag.db`), modelo de Claude ← `summarizer.model` (el bot reutiliza el modelo del summarizer). Se inyectan vía `BotServices`; el bot nunca lee env.
- **Ajustes por campaña** → `[campaign.rag]` del TOML: `manuals`, `rules_channel_id`, `keyword`, `top_k` → `RagCampaignConfig` → `CampaignContext.rag` → `BotServices.rag`.
- **Defaults del bot** → atributos de clase de `RulesBot` (`keyword = "bot reglas"`), overridable por `[campaign.rag].keyword`.

**Canal de la respuesta escrita (decidido con el usuario):** la respuesta hablada va al canal de voz (TTS). La respuesta escrita (embed con cita) va, **por orden de preferencia**: (1) al `rules_channel_id` de `[campaign.rag]` si está configurado; (2) en su defecto, al **chat integrado del canal de voz donde se invocó al bot** (en discord.py 2.x un `VoiceChannel` es *messageable*); (3) si ninguno está disponible, no se escribe (solo voz). Es un canal independiente del de resúmenes (`DISCORD_SUMMARY_CHANNEL_ID`). El `TriggerWatcher` resuelve el id del canal de voz desde el cliente de voz y lo adjunta al evento.

**Tech Stack:** Python 3.10 (async), `rag_lib` (SQLite/aiosqlite + FTS5), `anthropic` (AsyncAnthropic), discord.py, pytest + pytest-asyncio (`asyncio_mode="auto"`).

**Convención de commits del usuario:** un **único commit final** (Task 7). No hay commits intermedios; entre tareas solo se corren los tests indicados como checkpoint.

**Diseño de referencia:** `docs/superpowers/specs/2026-05-29-rules-bot-rag-design.md`.

**Desviaciones deliberadas respecto al diseño** (ambas mejoran cohesión, sin cambiar el comportamiento):
1. `RuleRetriever` vive en `src/rpg_scribe/bots/rules/retriever.py` (el diseño sugería `integrations/rag_retrieval.py`). Mantener todo el bot bajo `bots/rules/` agrupa lo que cambia junto.
2. `Citation` y `BotTextResponseEvent` se definen en la **Fase 2** (`core/events.py`), no en la Fase 4. Así el `TriggerWatcher` se modifica una sola vez y la Fase 4 solo añade el subscriber de Discord.

---

## File Map

| Archivo | Acción | Responsabilidad |
|---|---|---|
| `src/rag_lib/store.py` | Modify | `ChunkRepo.list_by_page()` — chunks que cubren una página |
| `src/rag_lib/__init__.py` | Modify | API pública `list_chunks_by_page()` |
| `src/rpg_scribe/core/events.py` | Modify | `Citation`, `BotTextResponseEvent` (frozen) |
| `src/rpg_scribe/core/models.py` | Modify | `RagCampaignConfig` + campo `rag` en `CampaignContext` |
| `src/rpg_scribe/config.py` | Modify | Parseo de `[campaign.rag]` en `load_campaign_toml` |
| `src/rpg_scribe/bots/base.py` | Modify | `BotResponse`, `BotServices`, hook `setup()` no-op |
| `src/rpg_scribe/bots/watcher.py` | Modify | Normalizar retorno + publicar `BotTextResponseEvent` |
| `src/rpg_scribe/bots/rules/__init__.py` | Create | Exporta `RulesBot` (necesario para `discover_bots`) |
| `src/rpg_scribe/bots/rules/retriever.py` | Create | `RuleRetriever` (híbrido + follow de página) |
| `src/rpg_scribe/bots/rules/answerer.py` | Create | `RuleAnswerer` (prompt + citas deterministas) |
| `src/rpg_scribe/bots/rules/bot.py` | Create | `RulesBot` (orquesta retriever → answerer) |
| `src/rpg_scribe/discord_bot/bot_response_publisher.py` | Create | `DiscordBotResponsePublisher` (embed de la cita) |
| `src/rpg_scribe/main.py` | Modify | Cablear `BotServices`/`setup()` y el publisher |
| `tests/rag_lib/test_store.py` | Modify | Tests de `list_by_page` / `list_chunks_by_page` |
| `tests/test_bots.py` | Modify | Tests de `setup()` no-op y `BotResponse` |
| `tests/test_trigger_watcher.py` | Modify | Test de normalización + publish del evento |
| `tests/test_config.py` | Modify | Test de parseo `[campaign.rag]` |
| `tests/bots/test_rule_retriever.py` | Create | Tests del retriever (fake embedder + DB temporal) |
| `tests/bots/test_rule_answerer.py` | Create | Tests del answerer (mock Anthropic) |
| `tests/bots/test_rules_bot.py` | Create | Tests del bot (retriever/answerer mockeados) |
| `tests/test_bot_response_publisher.py` | Create | Test del publisher (canal configurado + fallback a voz) |
| `docs/rules-bot.md` | Create | Doc de dominio: bot de reglas + framework de bots |
| `CLAUDE.md` | Modify | Índice "Documentación de Dominio" + nota del framework de bots |
| `README.md` | Modify | Característica + ejemplo `[campaign.rag]` + tabla de componentes |

---

## Task 1: `rag_lib.list_chunks_by_page` (Fase 1 — independiente)

Trae todos los chunks de un manual que **cubren** una página dada, considerando rangos (`page` … `page_end`). Base del follow de página del retriever.

**Files:**
- Modify: `src/rag_lib/store.py` (añadir método en `ChunkRepo`, tras `get_many_by_ids`, ~línea 164)
- Modify: `src/rag_lib/__init__.py` (añadir función pública tras `list_chunks`, ~línea 147)
- Test: `tests/rag_lib/test_store.py`

- [ ] **Step 1: Escribir los tests que fallan**

Abre `tests/rag_lib/test_store.py` y añade al final del archivo:

```python
# ---------------------------------------------------------------------------
# list_by_page / list_chunks_by_page — chunks que cubren una página
# ---------------------------------------------------------------------------

import rag_lib  # noqa: E402  (al principio del archivo si no estaba ya)


async def _page_db(tmp_path):
    """Manual con 4 chunks: pág 1, rango 2-4, pág 5, y un segundo manual en pág 3."""
    db = Database(str(tmp_path / "pages.db"))
    await db.connect()
    m1 = await db.manuals.insert(
        name="Manual A", source_path="a.pdf", source_hash="sha_pa",
        page_count=5, file_size=10, parser="pdfplumber",
    )
    m2 = await db.manuals.insert(
        name="Manual B", source_path="b.pdf", source_hash="sha_pb",
        page_count=5, file_size=10, parser="pdfplumber",
    )
    await db.chunks.insert_many(m1, [
        {"seq": 0, "chunk_type": "prose", "page": 1, "page_end": None,
         "section_path": None, "text": "uno", "text_hash": "p1", "token_count": 1},
        {"seq": 1, "chunk_type": "prose", "page": 2, "page_end": 4,
         "section_path": None, "text": "dos-cuatro", "text_hash": "p2", "token_count": 1},
        {"seq": 2, "chunk_type": "prose", "page": 5, "page_end": None,
         "section_path": None, "text": "cinco", "text_hash": "p3", "token_count": 1},
    ])
    await db.chunks.insert_many(m2, [
        {"seq": 0, "chunk_type": "prose", "page": 3, "page_end": None,
         "section_path": None, "text": "otro manual", "text_hash": "p4", "token_count": 1},
    ])
    return db, m1, m2


async def test_list_by_page_single_page_chunk(tmp_path):
    db, m1, _ = await _page_db(tmp_path)
    try:
        rows = await db.chunks.list_by_page(m1, 1)
        assert [r["text"] for r in rows] == ["uno"]
    finally:
        await db.close()


async def test_list_by_page_within_range(tmp_path):
    """Página 3 cae dentro del rango 2-4 → devuelve el chunk de rango."""
    db, m1, _ = await _page_db(tmp_path)
    try:
        rows = await db.chunks.list_by_page(m1, 3)
        assert [r["text"] for r in rows] == ["dos-cuatro"]
    finally:
        await db.close()


async def test_list_by_page_scopes_to_manual(tmp_path):
    """La página 3 del Manual B no contamina los resultados del Manual A."""
    db, m1, m2 = await _page_db(tmp_path)
    try:
        rows_a = await db.chunks.list_by_page(m1, 3)
        rows_b = await db.chunks.list_by_page(m2, 3)
        assert [r["text"] for r in rows_a] == ["dos-cuatro"]
        assert [r["text"] for r in rows_b] == ["otro manual"]
    finally:
        await db.close()


async def test_public_list_chunks_by_page_returns_chunks(tmp_path):
    db, m1, _ = await _page_db(tmp_path)
    db_path = str(tmp_path / "pages.db")
    await db.close()
    chunks = await rag_lib.list_chunks_by_page(m1, 3, db_path)
    assert len(chunks) == 1
    assert chunks[0].text == "dos-cuatro"
    assert chunks[0].page == 2
    assert chunks[0].page_end == 4
```

(Si `from rag_lib.store import Database` no está ya importado al principio de `test_store.py`, añádelo.)

- [ ] **Step 2: Verificar que fallan**

```
pytest tests/rag_lib/test_store.py -k "list_by_page or list_chunks_by_page" -v
```
Esperado: `AttributeError: 'ChunkRepo' object has no attribute 'list_by_page'` / `module 'rag_lib' has no attribute 'list_chunks_by_page'`.

- [ ] **Step 3: Implementar `ChunkRepo.list_by_page`**

En `src/rag_lib/store.py`, dentro de `class ChunkRepo`, justo después de `get_many_by_ids` (antes de `update`), añade:

```python
    async def list_by_page(self, manual_id: int, page: int) -> list[dict[str, Any]]:
        """Return chunks of *manual_id* that cover *page*, ordered by seq.

        A chunk covers the page when ``page <= page <= COALESCE(page_end, page)``
        (single-page chunks have page_end NULL → COALESCE collapses to page).
        """
        cur = await self._db.conn.execute(
            """SELECT * FROM rag_chunks
               WHERE manual_id = ?
                 AND page <= ?
                 AND COALESCE(page_end, page) >= ?
               ORDER BY seq""",
            (manual_id, page, page),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
```

- [ ] **Step 4: Implementar `rag_lib.list_chunks_by_page`**

En `src/rag_lib/__init__.py`, justo después de la función `list_chunks` (~línea 147), añade:

```python
async def list_chunks_by_page(
    manual_id: int, page: int, db_path: str | Path
) -> list[Chunk]:
    """Return all chunks of *manual_id* that cover *page* (incl. page ranges)."""
    db = Database(db_path)
    await db.connect()
    try:
        rows = await db.chunks.list_by_page(manual_id, page)
        return [_row_to_chunk(r) for r in rows]
    finally:
        await db.close()
```

- [ ] **Step 5: Verificar que pasan**

```
pytest tests/rag_lib/test_store.py -k "list_by_page or list_chunks_by_page" -v
```
Esperado: 4 PASSED.

- [ ] **Step 6: CHECKPOINT — suite de `rag_lib` sin regresiones**

```
pytest tests/rag_lib/ -q
```
Esperado: todos pasan (sin nuevos fallos respecto a la línea base).

---

## Task 2: Framework de bots — `BotResponse`, `BotServices`, `setup()`, eventos y normalización (Fase 2)

Añade inyección de dependencias y retorno estructurado **sin romper `EchoBot`**. Define los tipos de cita y el evento de texto aquí para tocar el watcher una sola vez.

**Files:**
- Modify: `src/rpg_scribe/core/events.py` (añadir `Citation`, `BotTextResponseEvent`)
- Modify: `src/rpg_scribe/bots/base.py` (añadir `BotResponse`, `BotServices`, `setup()`)
- Modify: `src/rpg_scribe/bots/watcher.py` (normalizar retorno + publicar evento)
- Test: `tests/test_bots.py`, `tests/test_trigger_watcher.py`

- [ ] **Step 1: Escribir los tests que fallan (tipos + normalización)**

En `tests/test_bots.py`, añade al final:

```python
import pytest

from rpg_scribe.bots.base import BotResponse, BotServices
from rpg_scribe.bots.echo_bot import EchoBot


def test_bot_response_defaults():
    r = BotResponse(spoken="hola")
    assert r.spoken == "hola"
    assert r.written is None
    assert r.citations is None


async def test_echo_bot_setup_is_noop():
    """El hook setup() por defecto no hace nada y no rompe bots existentes."""
    services = BotServices(
        rag_db_path="x.db",
        anthropic_api_key="",
        summarizer_model="m",
        campaign=None,
        event_bus=None,
        rag=None,
    )
    assert await EchoBot().setup(services) is None
```

En `tests/test_trigger_watcher.py`, añade al final:

```python
from rpg_scribe.bots.base import BotResponse
from rpg_scribe.bots.watcher import _normalize_response


def test_normalize_str_wraps_in_bot_response():
    r = _normalize_response("hola")
    assert isinstance(r, BotResponse)
    assert r.spoken == "hola"
    assert r.written is None


def test_normalize_bot_response_passthrough():
    original = BotResponse(spoken="s", written="w")
    assert _normalize_response(original) is original
```

- [ ] **Step 2: Verificar que fallan**

```
pytest tests/test_bots.py -k "bot_response or setup_is_noop" tests/test_trigger_watcher.py -k normalize -v
```
Esperado: `ImportError` (símbolos aún no existen).

- [ ] **Step 3: Añadir `Citation` y `BotTextResponseEvent` en `core/events.py`**

Al final de `src/rpg_scribe/core/events.py` añade:

```python
@dataclass(frozen=True)
class Citation:
    """Una referencia a manual + página usada en una respuesta de bot."""

    manual: str
    page: int
    section_path: str | None = None


@dataclass(frozen=True)
class BotTextResponseEvent:
    """Emitido por TriggerWatcher cuando un bot devuelve una respuesta escrita.

    Lo consume DiscordBotResponsePublisher para postear un embed. ``citations``
    puede ir vacío. ``voice_channel_id`` es el canal de voz donde se invocó al
    bot (resuelto por el watcher); el publisher lo usa como fallback cuando no
    hay un canal de texto dedicado configurado.
    """

    session_id: str
    bot_keyword: str
    speaker_name: str
    question: str
    answer_md: str
    citations: tuple[Citation, ...] = ()
    voice_channel_id: int | None = None
```

- [ ] **Step 4: Añadir `BotResponse`, `BotServices` y `setup()` en `bots/base.py`**

En `src/rpg_scribe/bots/base.py`, debajo de los imports existentes (después de `from typing import ClassVar`), reemplaza esa línea de import por:

```python
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from rpg_scribe.core.event_bus import EventBus
    from rpg_scribe.core.events import Citation
    from rpg_scribe.core.models import CampaignContext, RagCampaignConfig
```

Justo encima de `class BaseBot(ABC):` añade:

```python
@dataclass(frozen=True)
class BotResponse:
    """Retorno estructurado de ``BaseBot.handle``.

    ``spoken`` es lo que se sintetiza por TTS; ``written`` (si no es None) se
    publica como ``BotTextResponseEvent`` para el canal de texto.
    """

    spoken: str
    written: str | None = None
    citations: "list[Citation] | None" = None


@dataclass
class BotServices:
    """Dependencias que el framework inyecta a cada bot vía ``setup()``.

    Construido una sola vez en main.py reusando AppConfig. Los secretos
    (anthropic_api_key) viven solo aquí; el bot nunca lee env.
    """

    rag_db_path: str
    anthropic_api_key: str
    summarizer_model: str
    campaign: "CampaignContext | None"
    event_bus: "EventBus | None"
    rag: "RagCampaignConfig | None"
```

Dentro de `class BaseBot`, justo antes del `@abstractmethod async def handle`, añade el hook por defecto y amplía el tipo de retorno de `handle`:

```python
    async def setup(self, services: "BotServices") -> None:
        """Inyección de dependencias. Default: no-op (bots simples la ignoran)."""
        return None

    @abstractmethod
    async def handle(
        self,
        command: str,
        *,
        session_id: str,
        speaker_id: str,
        speaker_name: str,
    ) -> "str | BotResponse":
        """Process ``command`` and return text (str) or a structured BotResponse."""
```

(Borra la firma anterior de `handle` que devolvía `-> str`; el resto del docstring de clase puede quedarse.)

- [ ] **Step 5: Normalizar el retorno y publicar el evento en `watcher.py`**

En `src/rpg_scribe/bots/watcher.py`, amplía los imports de `core.events`:

```python
from rpg_scribe.core.events import (
    BotTextResponseEvent,
    TranscriptionEvent,
    TriggerActivatedEvent,
)
```

y añade el import de los tipos de bot debajo:

```python
from rpg_scribe.bots.base import BaseBot, BotResponse
```

Justo después de `logger = logging.getLogger(__name__)` añade el helper puro:

```python
def _normalize_response(raw: "str | BotResponse") -> BotResponse:
    """Acepta el retorno legado (str) o el nuevo BotResponse y normaliza a BotResponse."""
    if isinstance(raw, BotResponse):
        return raw
    return BotResponse(spoken=raw)
```

En `_finalize`, localiza el bloque (líneas ~168-184):

```python
        try:
            response = await asyncio.wait_for(
                cap.bot.handle(
                    command,
                    session_id=ev.session_id,
                    speaker_id=ev.speaker_id,
                    speaker_name=ev.speaker_name,
                ),
                timeout=30.0,
            )
        except Exception as exc:
            logger.exception("Bot %s.handle failed: %s", cap.bot.keyword, exc)
            response = "Lo siento, ha habido un problema."

        if not response or not response.strip():
            return

        voice = cap.bot.voice or self._default_voice
        try:
            paths = await synthesize_to_wav_paths(
                response,
                voice,
```

y reemplázalo por:

```python
        try:
            raw = await asyncio.wait_for(
                cap.bot.handle(
                    command,
                    session_id=ev.session_id,
                    speaker_id=ev.speaker_id,
                    speaker_name=ev.speaker_name,
                ),
                timeout=30.0,
            )
        except Exception as exc:
            logger.exception("Bot %s.handle failed: %s", cap.bot.keyword, exc)
            raw = "Lo siento, ha habido un problema."

        response = _normalize_response(raw)

        # Publish the written answer (if any). Adjuntamos el canal de voz actual
        # para que el publisher pueda hacer fallback a su chat integrado.
        if response.written:
            vc = self._player.get_voice_client()
            voice_channel_id = (
                vc.channel.id if vc is not None and vc.channel is not None else None
            )
            await self._bus.publish(
                BotTextResponseEvent(
                    session_id=ev.session_id,
                    bot_keyword=cap.bot.keyword,
                    speaker_name=ev.speaker_name,
                    question=command,
                    answer_md=response.written,
                    citations=tuple(response.citations or ()),
                    voice_channel_id=voice_channel_id,
                )
            )

        spoken = response.spoken
        if not spoken or not spoken.strip():
            return

        voice = cap.bot.voice or self._default_voice
        try:
            paths = await synthesize_to_wav_paths(
                spoken,
                voice,
```

(El resto del bloque de síntesis/playback —los kwargs `provider=`, `cache=`, etc.— queda intacto.)

- [ ] **Step 6: Verificar que pasan**

```
pytest tests/test_bots.py -k "bot_response or setup_is_noop" tests/test_trigger_watcher.py -k normalize -v
```
Esperado: 4 PASSED.

- [ ] **Step 7: CHECKPOINT — el framework de bots no regresiona**

```
pytest tests/test_bots.py tests/test_trigger_watcher.py -q
```
Esperado: todos pasan (EchoBot sigue funcionando).

---

## Task 3: `RuleRetriever` — recuperación híbrida + follow de página (Fase 3, requiere Task 1)

Pieza pura, sin Discord. Fusiona búsqueda semántica + FTS5 y sigue **un** salto de página.

**Files:**
- Create: `src/rpg_scribe/bots/rules/__init__.py`
- Create: `src/rpg_scribe/bots/rules/retriever.py`
- Test: `tests/bots/test_rule_retriever.py`

- [ ] **Step 1: Crear el paquete `bots/rules`**

Crea `src/rpg_scribe/bots/rules/__init__.py` con (de momento vacío de re-exports; el bot se añade en Task 6):

```python
"""Paquete del bot de reglas (RAG)."""
from __future__ import annotations
```

- [ ] **Step 2: Escribir los tests que fallan**

Crea `tests/bots/test_rule_retriever.py`:

```python
"""Tests de RuleRetriever: fusión híbrida y follow de página (1 salto)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from rag_lib.store import Database
from rpg_scribe.bots.rules.retriever import RuleRetriever
from tests.rag_lib.conftest import FakeEmbedder


async def _retriever_db(tmp_path: Path):
    """Manual con: pág 1 (menciona 'ver pág. 2'), pág 1 (otra), pág 2 (destino)."""
    db_path = str(tmp_path / "retr.db")
    db = Database(db_path)
    await db.connect()
    manual_id = await db.manuals.insert(
        name="Manual A", source_path="a.pdf", source_hash="sha_r",
        page_count=2, file_size=10, parser="pdfplumber",
    )
    chunks = [
        {"seq": 0, "chunk_type": "prose", "page": 1, "page_end": None,
         "section_path": "Hackeo",
         "text": "Para el hackeo de sistemas ver pág. 2 donde se detalla el proceso.",
         "text_hash": "r1", "token_count": 12},
        {"seq": 1, "chunk_type": "prose", "page": 1, "page_end": None,
         "section_path": "Combate",
         "text": "El combate cuerpo a cuerpo no tiene relación con esto.",
         "text_hash": "r2", "token_count": 10},
        {"seq": 2, "chunk_type": "prose", "page": 2, "page_end": None,
         "section_path": "Hackeo / Detalle",
         "text": "El hackeo requiere superar la tirada de Interface contra la dificultad.",
         "text_hash": "r3", "token_count": 11},
    ]
    ids = await db.chunks.insert_many(manual_id, chunks)
    emb = FakeEmbedder()
    vecs = await emb.embed([c["text"] for c in chunks])
    await db.embeddings.upsert_many([
        {"chunk_id": cid, "vector_bytes": np.array(v, dtype=np.float32).tobytes(),
         "dim": emb.dim, "model": emb.model}
        for cid, v in zip(ids, vecs)
    ])
    await db.close()
    return db_path, manual_id, ids


async def test_retrieve_returns_chunks(tmp_path):
    db_path, manual_id, _ = await _retriever_db(tmp_path)
    retriever = RuleRetriever(
        db_path, [manual_id], top_k=8, embedder=FakeEmbedder()
    )
    results = await retriever.retrieve("hackeo")
    assert results, "debe devolver al menos un chunk"
    assert all(c.manual_id == manual_id for c in results)


async def test_retrieve_follows_page_reference(tmp_path):
    """El chunk que dice 'ver pág. 2' arrastra el chunk de la página 2."""
    db_path, manual_id, ids = await _retriever_db(tmp_path)
    retriever = RuleRetriever(
        db_path, [manual_id], top_k=8, embedder=FakeEmbedder()
    )
    results = await retriever.retrieve("hackeo")
    pages = {c.page for c in results}
    assert 2 in pages, "el follow de página debe traer la página 2"
    # Sin duplicados por chunk_id
    result_ids = [c.id for c in results]
    assert len(result_ids) == len(set(result_ids))


async def test_retrieve_empty_when_no_manuals(tmp_path):
    db_path, _, _ = await _retriever_db(tmp_path)
    retriever = RuleRetriever(db_path, [], top_k=8, embedder=FakeEmbedder())
    assert await retriever.retrieve("hackeo") == []
```

Asegúrate de que existe `tests/bots/__init__.py` (créalo vacío si no está):

```python
```

- [ ] **Step 3: Verificar que fallan**

```
pytest tests/bots/test_rule_retriever.py -v
```
Esperado: `ModuleNotFoundError: rpg_scribe.bots.rules.retriever`.

- [ ] **Step 4: Implementar `RuleRetriever`**

Crea `src/rpg_scribe/bots/rules/retriever.py`:

```python
"""RuleRetriever: recuperación híbrida (semántica + FTS5) con follow de página."""
from __future__ import annotations

import asyncio
import re

import rag_lib
from rag_lib.embedding.base import Embedder
from rag_lib.types import Chunk, SearchResult

# "pág. 45", "pagina 45", "p. 45" (case-insensitive)
_PAGE_RE = re.compile(r"(?:pág(?:ina)?\.?|p\.)\s*(\d+)", re.IGNORECASE)


class RuleRetriever:
    """Recupera chunks relevantes para una pregunta de reglas.

    Combina búsqueda semántica y FTS5 (fusión por chunk_id con scores
    normalizados) y aplica un único salto de follow de página: si un chunk
    top referencia "ver pág. N", trae los chunks de esa página del mismo
    manual.
    """

    def __init__(
        self,
        db_path: str,
        manual_ids: list[int],
        *,
        top_k: int = 8,
        sem_weight: float = 0.5,
        embedder: Embedder | None = None,
    ) -> None:
        self._db_path = db_path
        self._manual_ids = manual_ids
        self._top_k = top_k
        self._sem_weight = sem_weight
        self._embedder = embedder

    async def retrieve(self, question: str) -> list[Chunk]:
        if not self._manual_ids or not question.strip():
            return []

        sem, fts = await asyncio.gather(
            rag_lib.search(
                question, self._db_path,
                manual_ids=self._manual_ids, k=self._top_k,
                embedder=self._embedder,
            ),
            rag_lib.search_fts(
                question, self._db_path,
                manual_ids=self._manual_ids, k=self._top_k,
            ),
        )
        merged = self._merge(sem, fts)
        return await self._follow_pages(merged)

    def _merge(
        self, sem: list[SearchResult], fts: list[SearchResult]
    ) -> list[Chunk]:
        """Fusiona por chunk_id sumando scores normalizados ponderados."""
        scores: dict[int, float] = {}
        chunks: dict[int, Chunk] = {}

        def add(results: list[SearchResult], weight: float) -> None:
            if not results:
                return
            top = max(r.score for r in results) or 1.0
            for r in results:
                norm = (r.score / top) * weight
                scores[r.chunk_id] = scores.get(r.chunk_id, 0.0) + norm
                chunks[r.chunk_id] = r.chunk

        add(sem, self._sem_weight)
        add(fts, 1.0 - self._sem_weight)

        ranked = sorted(scores, key=lambda cid: scores[cid], reverse=True)
        return [chunks[cid] for cid in ranked[: self._top_k]]

    async def _follow_pages(self, chunks: list[Chunk]) -> list[Chunk]:
        """Un salto: por cada (manual_id, página) referida, añade sus chunks."""
        seen_ids = {c.id for c in chunks}
        refs: set[tuple[int, int]] = set()
        for c in chunks:
            for m in _PAGE_RE.finditer(c.text):
                refs.add((c.manual_id, int(m.group(1))))

        out = list(chunks)
        for manual_id, page in refs:
            extra = await rag_lib.list_chunks_by_page(manual_id, page, self._db_path)
            for ch in extra:
                if ch.id not in seen_ids:
                    seen_ids.add(ch.id)
                    out.append(ch)
        return out
```

- [ ] **Step 5: Verificar que pasan**

```
pytest tests/bots/test_rule_retriever.py -v
```
Esperado: 3 PASSED.

---

## Task 4: `DiscordBotResponsePublisher` (Fase 4, requiere Task 2)

Subscriber que convierte `BotTextResponseEvent` en un embed. Elige el canal por orden: `channel_id` configurado (rules channel) → `event.voice_channel_id` (chat del canal de voz) → ninguno (no postea). Replica el patrón de `DiscordSummaryPublisher`.

**Files:**
- Create: `src/rpg_scribe/discord_bot/bot_response_publisher.py`
- Test: `tests/test_bot_response_publisher.py`

- [ ] **Step 1: Escribir los tests que fallan**

Crea `tests/test_bot_response_publisher.py`:

```python
"""Tests de DiscordBotResponsePublisher (canal configurado + fallback a voz)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from rpg_scribe.core.event_bus import EventBus
from rpg_scribe.core.events import BotTextResponseEvent, Citation
from rpg_scribe.discord_bot.bot_response_publisher import DiscordBotResponsePublisher


def _event(voice_channel_id: int | None = None) -> BotTextResponseEvent:
    return BotTextResponseEvent(
        session_id="s1",
        bot_keyword="bot reglas",
        speaker_name="Alice",
        question="¿Cómo funciona el hackeo?",
        answer_md="El hackeo requiere una tirada de Interface.\n\n**Fuentes:**\n- *Manual A*, p. 2",
        citations=(Citation(manual="Manual A", page=2, section_path="Hackeo"),),
        voice_channel_id=voice_channel_id,
    )


async def test_publishes_to_configured_channel():
    channel = MagicMock(spec=discord.TextChannel)
    channel.send = AsyncMock(return_value=MagicMock())
    bot = MagicMock()
    bot.get_channel.return_value = channel

    bus = EventBus()
    DiscordBotResponsePublisher(bot=bot, event_bus=bus, channel_id=123)

    await bus.publish(_event(voice_channel_id=456))

    bot.get_channel.assert_called_once_with(123)  # prioriza el canal configurado
    channel.send.assert_awaited_once()
    embed = channel.send.call_args.kwargs["embed"]
    assert "hackeo" in embed.description.lower()


async def test_fallback_to_voice_channel_when_no_configured_channel():
    voice_chan = MagicMock(spec=discord.VoiceChannel)
    voice_chan.send = AsyncMock(return_value=MagicMock())
    bot = MagicMock()
    bot.get_channel.return_value = voice_chan

    bus = EventBus()
    DiscordBotResponsePublisher(bot=bot, event_bus=bus, channel_id=None)

    await bus.publish(_event(voice_channel_id=456))

    bot.get_channel.assert_called_once_with(456)  # usa el canal de voz
    voice_chan.send.assert_awaited_once()


async def test_no_target_does_not_post():
    bot = MagicMock()
    bus = EventBus()
    DiscordBotResponsePublisher(bot=bot, event_bus=bus, channel_id=None)

    await bus.publish(_event(voice_channel_id=None))

    bot.get_channel.assert_not_called()


async def test_unfetchable_channel_does_not_raise():
    bot = MagicMock()
    bot.get_channel.return_value = None
    bot.fetch_channel = AsyncMock(side_effect=RuntimeError("no channel"))

    bus = EventBus()
    DiscordBotResponsePublisher(bot=bot, event_bus=bus, channel_id=999)

    # No debe propagar la excepción al bus.
    await bus.publish(_event())
```

- [ ] **Step 2: Verificar que fallan**

```
pytest tests/test_bot_response_publisher.py -v
```
Esperado: `ModuleNotFoundError: ...bot_response_publisher`.

- [ ] **Step 3: Implementar el publisher**

Crea `src/rpg_scribe/discord_bot/bot_response_publisher.py`:

```python
"""Discord embed publisher para respuestas de bots (BotTextResponseEvent).

Elige el canal destino por orden de preferencia:
  1. ``channel_id`` configurado ([campaign.rag].rules_channel_id).
  2. ``event.voice_channel_id`` — el chat integrado del canal de voz donde se
     invocó al bot (un VoiceChannel es messageable en discord.py 2.x).
  3. Ninguno → no postea (solo quedó la respuesta hablada).
"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

from rpg_scribe.core.event_bus import EventBus
from rpg_scribe.core.events import BotTextResponseEvent

logger = logging.getLogger(__name__)

_EMBED_DESC_LIMIT = 4096
_EMBED_FIELD_LIMIT = 1024

# Canales a los que sabemos enviar (todos messageable en discord.py 2.x).
_SENDABLE = (discord.TextChannel, discord.VoiceChannel, discord.Thread)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


class DiscordBotResponsePublisher:
    """Postea cada respuesta escrita de un bot como embed en un canal de texto."""

    def __init__(
        self,
        bot: commands.Bot,
        event_bus: EventBus,
        channel_id: int | None,
    ) -> None:
        self._bot = bot
        self._event_bus = event_bus
        self._channel_id = channel_id
        self._event_bus.subscribe(BotTextResponseEvent, self._on_response)

    async def _on_response(self, event: BotTextResponseEvent) -> None:
        target_id = self._channel_id or event.voice_channel_id
        if target_id is None:
            logger.info(
                "Respuesta de bot no publicada: sin canal de reglas ni de voz"
            )
            return

        channel = self._bot.get_channel(target_id)
        if channel is None:
            try:
                channel = await self._bot.fetch_channel(target_id)
            except Exception as exc:
                logger.error("No se pudo obtener el canal %d: %s", target_id, exc)
                return

        if not isinstance(channel, _SENDABLE):
            logger.error("El canal %d no admite mensajes de texto", target_id)
            return

        embed = self._build_embed(event)
        try:
            await channel.send(embed=embed)
        except Exception as exc:
            logger.error("Fallo al publicar el embed de respuesta: %s", exc)

    def _build_embed(self, event: BotTextResponseEvent) -> discord.Embed:
        embed = discord.Embed(
            title=f"📖 {event.question}",
            description=_truncate(event.answer_md, _EMBED_DESC_LIMIT),
            colour=discord.Colour.teal(),
            timestamp=discord.utils.utcnow(),
        )
        if event.citations:
            sources = "\n".join(
                f"*{c.manual}*, p. {c.page}"
                + (f" — {c.section_path}" if c.section_path else "")
                for c in event.citations
            )
            embed.add_field(
                name="Fuentes",
                value=_truncate(sources, _EMBED_FIELD_LIMIT),
                inline=False,
            )
        embed.set_footer(text=f"{event.bot_keyword} · preguntó {event.speaker_name}")
        return embed

    async def stop(self) -> None:
        self._event_bus.unsubscribe(BotTextResponseEvent, self._on_response)
```

- [ ] **Step 4: Verificar que pasan**

```
pytest tests/test_bot_response_publisher.py -v
```
Esperado: 4 PASSED.

> Nota: confirma que `EventBus` tiene `subscribe`/`publish`/`unsubscribe` (ya usados por `DiscordSummaryPublisher`). El publisher traga sus propias excepciones en `_on_response`, así que `test_unfetchable_channel_does_not_raise` pasa con independencia de cómo `publish` propague errores de los handlers.

---

## Task 5: `RuleAnswerer` — redacción con Claude + citas deterministas (Fase 5, requiere Tasks 2 y 3)

**Files:**
- Create: `src/rpg_scribe/bots/rules/answerer.py`
- Test: `tests/bots/test_rule_answerer.py`

- [ ] **Step 1: Escribir los tests que fallan**

Crea `tests/bots/test_rule_answerer.py`:

```python
"""Tests de RuleAnswerer: prompt, citas deterministas, fallback."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from rag_lib.types import Chunk
from rpg_scribe.bots.base import BotResponse
from rpg_scribe.bots.rules.answerer import RuleAnswerer


def _chunk(cid, manual_id, page, section, text) -> Chunk:
    return Chunk(
        id=cid, manual_id=manual_id, seq=cid, chunk_type="prose",
        page=page, page_end=None, section_path=section,
        text=text, text_hash=f"h{cid}", token_count=10,
    )


def _mock_anthropic_response(text: str):
    block = MagicMock()
    block.text = text
    resp = MagicMock()
    resp.content = [block]
    return resp


def _answerer(client=None) -> RuleAnswerer:
    return RuleAnswerer(
        api_key="sk-test",
        model="claude-sonnet-4-20250514",
        manual_names={1: "Cyberpunk RED"},
        language="es",
        client=client,
    )


CHUNKS = [
    _chunk(1, 1, 45, "Netrunning", "El hackeo requiere una tirada de Interface."),
    _chunk(2, 1, 45, "Netrunning", "La dificultad la fija el GM."),
    _chunk(3, 1, 46, "Netrunning / NET", "Cada NET architecture tiene niveles."),
]


def test_build_prompt_includes_chunk_text_and_page():
    answerer = _answerer()
    system, user = answerer._build_prompt("¿Cómo se hackea?", CHUNKS)
    assert "es" in system
    assert "El hackeo requiere una tirada de Interface." in user
    assert "pág. 45" in user
    assert "Cyberpunk RED" in user


def test_build_citations_dedupes_by_manual_and_page():
    answerer = _answerer()
    cits = answerer._build_citations(CHUNKS)
    # (1,45) y (1,46) → 2 citas; el segundo chunk (1,45) se deduplica.
    assert len(cits) == 2
    assert cits[0].manual == "Cyberpunk RED"
    assert {c.page for c in cits} == {45, 46}


async def test_answer_returns_bot_response_with_sources():
    client = MagicMock()
    client.messages.create = AsyncMock(
        return_value=_mock_anthropic_response("Se hackea con una tirada de Interface.")
    )
    answerer = _answerer(client=client)
    resp = await answerer.answer("¿Cómo se hackea?", CHUNKS)

    assert isinstance(resp, BotResponse)
    assert resp.spoken == "Se hackea con una tirada de Interface."
    assert "**Fuentes:**" in resp.written
    assert "Cyberpunk RED" in resp.written
    assert len(resp.citations) == 2


async def test_answer_falls_back_when_llm_fails():
    client = MagicMock()
    client.messages.create = AsyncMock(side_effect=RuntimeError("API down"))
    answerer = _answerer(client=client)
    resp = await answerer.answer("¿Cómo se hackea?", CHUNKS)

    # Degradación: usa el chunk top en bruto + cita determinista.
    assert "El hackeo requiere una tirada de Interface." in resp.spoken
    assert resp.citations  # citas siguen presentes
```

- [ ] **Step 2: Verificar que fallan**

```
pytest tests/bots/test_rule_answerer.py -v
```
Esperado: `ModuleNotFoundError: ...rules.answerer`.

- [ ] **Step 3: Implementar `RuleAnswerer`**

Crea `src/rpg_scribe/bots/rules/answerer.py`:

```python
"""RuleAnswerer: redacta la respuesta con Claude y construye citas deterministas."""
from __future__ import annotations

import logging

from rag_lib.types import Chunk
from rpg_scribe.bots.base import BotResponse
from rpg_scribe.core.events import Citation

logger = logging.getLogger(__name__)

_MAX_TOKENS = 1024


class RuleAnswerer:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        manual_names: dict[int, str],
        language: str = "es",
        client=None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._manual_names = manual_names
        self._language = language
        self._client = client

    def _get_client(self):
        if self._client is None:
            from anthropic import AsyncAnthropic

            self._client = AsyncAnthropic(api_key=self._api_key)
        return self._client

    def _manual_name(self, manual_id: int) -> str:
        return self._manual_names.get(manual_id, f"manual {manual_id}")

    def _build_citations(self, chunks: list[Chunk]) -> list[Citation]:
        seen: set[tuple[int, int]] = set()
        out: list[Citation] = []
        for c in chunks:
            key = (c.manual_id, c.page)
            if key in seen:
                continue
            seen.add(key)
            out.append(
                Citation(
                    manual=self._manual_name(c.manual_id),
                    page=c.page,
                    section_path=c.section_path,
                )
            )
        return out

    def _build_prompt(self, question: str, chunks: list[Chunk]) -> tuple[str, str]:
        system = (
            "Eres un asistente experto en reglas de juegos de rol. Responde "
            "ÚNICAMENTE con la información presente en los fragmentos de manual "
            "proporcionados. Si la respuesta no aparece en los fragmentos, dilo "
            "explícitamente. Cita el manual y la página de forma inline. Sé "
            f"conciso. Responde en este idioma (código ISO): {self._language}."
        )
        blocks = []
        for c in chunks:
            sec = c.section_path or "—"
            blocks.append(
                f"[{self._manual_name(c.manual_id)} · pág. {c.page} · {sec}]\n{c.text}"
            )
        user = (
            f"Pregunta: {question}\n\n"
            "Fragmentos de los manuales:\n\n" + "\n\n---\n\n".join(blocks)
        )
        return system, user

    def _format_sources(self, citations: list[Citation]) -> str:
        lines = ["**Fuentes:**"]
        for c in citations:
            sec = f" — {c.section_path}" if c.section_path else ""
            lines.append(f"- *{c.manual}*, p. {c.page}{sec}")
        return "\n".join(lines)

    def _fallback_text(self, chunks: list[Chunk]) -> str:
        top = chunks[0]
        return (
            f"Según *{self._manual_name(top.manual_id)}*, pág. {top.page}:\n{top.text}"
        )

    async def answer(self, question: str, chunks: list[Chunk]) -> BotResponse:
        citations = self._build_citations(chunks)
        system, user = self._build_prompt(question, chunks)
        try:
            client = self._get_client()
            resp = await client.messages.create(
                model=self._model,
                max_tokens=_MAX_TOKENS,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            text = resp.content[0].text.strip()
        except Exception as exc:
            logger.exception("RuleAnswerer LLM failed, using fallback: %s", exc)
            text = self._fallback_text(chunks)

        written = f"{text}\n\n{self._format_sources(citations)}"
        return BotResponse(spoken=text, written=written, citations=citations)
```

- [ ] **Step 4: Verificar que pasan**

```
pytest tests/bots/test_rule_answerer.py -v
```
Esperado: 5 PASSED.

---

## Task 6: `RulesBot` + config `[campaign.rag]` + cableado en `main.py` (Fase 6, requiere Tasks 3, 4, 5)

**Files:**
- Modify: `src/rpg_scribe/core/models.py` (`RagCampaignConfig` + campo `rag`)
- Modify: `src/rpg_scribe/config.py` (parseo de `[campaign.rag]`)
- Create: `src/rpg_scribe/bots/rules/bot.py`
- Modify: `src/rpg_scribe/bots/rules/__init__.py` (re-export para discovery)
- Modify: `src/rpg_scribe/main.py` (BotServices + setup() + publisher)
- Test: `tests/test_config.py`, `tests/bots/test_rules_bot.py`

- [ ] **Step 1: Test que falla — parseo de `[campaign.rag]`**

En `tests/test_config.py`, añade (mira los imports del archivo: usa `load_campaign_toml` o el helper de tmp TOML ya presente; aquí escribimos un TOML temporal):

```python
def test_campaign_rag_section_parsed(tmp_path):
    from rpg_scribe.config import load_campaign_toml

    toml = tmp_path / "camp.toml"
    toml.write_text(
        """
[campaign]
id = "cp"
name = "Cyberpunk"
game_system = "Cyberpunk RED"
language = "es"

[campaign.rag]
manuals = ["Cyberpunk RED — Core"]
rules_channel_id = "123456789012345678"
keyword = "bot reglas"
top_k = 6
""",
        encoding="utf-8",
    )
    ctx = load_campaign_toml(toml)
    assert ctx.rag is not None
    assert ctx.rag.manuals == ["Cyberpunk RED — Core"]
    assert ctx.rag.rules_channel_id == "123456789012345678"
    assert ctx.rag.keyword == "bot reglas"
    assert ctx.rag.top_k == 6


def test_campaign_without_rag_section_is_none(tmp_path):
    from rpg_scribe.config import load_campaign_toml

    toml = tmp_path / "camp2.toml"
    toml.write_text(
        '[campaign]\nid = "x"\nname = "X"\ngame_system = "Y"\nlanguage = "es"\n',
        encoding="utf-8",
    )
    ctx = load_campaign_toml(toml)
    assert ctx.rag is None
```

- [ ] **Step 2: Test que falla — `RulesBot`**

Crea `tests/bots/test_rules_bot.py`:

```python
"""Tests de RulesBot: orquestación retriever → answerer, y casos de borde."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from rag_lib.types import Chunk
from rpg_scribe.bots.base import BotResponse
from rpg_scribe.bots.rules.bot import RulesBot


def _chunk() -> Chunk:
    return Chunk(
        id=1, manual_id=1, seq=0, chunk_type="prose", page=45,
        page_end=None, section_path="Netrunning",
        text="El hackeo requiere una tirada de Interface.",
        text_hash="h", token_count=10,
    )


def _wired_bot() -> RulesBot:
    """Bot con retriever/answerer mockeados (simula un setup() exitoso)."""
    bot = RulesBot()
    bot._enabled = True
    bot._retriever = MagicMock()
    bot._answerer = MagicMock()
    return bot


async def test_handle_disabled_returns_notice():
    bot = RulesBot()  # sin setup → deshabilitado
    out = await bot.handle("¿cómo se hackea?", session_id="s", speaker_id="u", speaker_name="A")
    assert "no" in out.lower()  # mensaje de no-configurado


async def test_handle_no_results_returns_not_found():
    bot = _wired_bot()
    bot._retriever.retrieve = AsyncMock(return_value=[])
    out = await bot.handle("¿cómo se hackea?", session_id="s", speaker_id="u", speaker_name="A")
    assert isinstance(out, BotResponse)
    assert "no encontré" in out.spoken.lower()


async def test_handle_orchestrates_retriever_and_answerer():
    bot = _wired_bot()
    bot._retriever.retrieve = AsyncMock(return_value=[_chunk()])
    expected = BotResponse(spoken="respuesta", written="respuesta\n\n**Fuentes:**\n- *X*, p. 45")
    bot._answerer.answer = AsyncMock(return_value=expected)

    out = await bot.handle("¿cómo se hackea?", session_id="s", speaker_id="u", speaker_name="A")

    assert out is expected
    bot._retriever.retrieve.assert_awaited_once_with("¿cómo se hackea?")
    bot._answerer.answer.assert_awaited_once()
```

- [ ] **Step 3: Verificar que fallan**

```
pytest tests/test_config.py -k campaign_rag tests/test_config.py -k without_rag tests/bots/test_rules_bot.py -v
```
Esperado: `ModuleNotFoundError` / `AttributeError: ... 'rag'`.

- [ ] **Step 4: Añadir `RagCampaignConfig` y el campo `rag` en `models.py`**

En `src/rpg_scribe/core/models.py`, justo antes de `class CampaignContext:` (línea ~94) añade:

```python
@dataclass
class RagCampaignConfig:
    """Ajustes RAG por campaña (sección [campaign.rag] del TOML)."""

    manuals: list[str] = field(default_factory=list)
    rules_channel_id: str = ""
    keyword: str | None = None
    top_k: int = 8
```

Dentro de `CampaignContext`, junto al resto de campos opcionales (p. ej. tras `custom_instructions: str = ""` y antes de `is_generic`), añade:

```python
    rag: "RagCampaignConfig | None" = None
```

- [ ] **Step 5: Parsear `[campaign.rag]` en `config.py`**

En `src/rpg_scribe/config.py`:

1. Amplía el import de `models` para incluir `RagCampaignConfig`:

```python
from rpg_scribe.core.models import (
    CharacterRelationshipInfo,
    CampaignContext,
    EntityInfo,
    ListenerConfig,
    LocationInfo,
    NPCInfo,
    PlayerInfo,
    RagCampaignConfig,
    RelationshipTypeInfo,
    SummarizerConfig,
    TranscriberConfig,
    TTSConfig,
)
```

2. En `load_campaign_toml`, justo antes del `return CampaignContext(...)` (línea ~228), añade:

```python
    # RAG (sección opcional [campaign.rag])
    rag_data = campaign_data.get("rag")
    rag_config: RagCampaignConfig | None = None
    if isinstance(rag_data, dict):
        keyword = rag_data.get("keyword")
        rag_config = RagCampaignConfig(
            manuals=[str(m) for m in rag_data.get("manuals", [])],
            rules_channel_id=str(rag_data.get("rules_channel_id", "")),
            keyword=str(keyword) if keyword else None,
            top_k=int(rag_data.get("top_k", 8)),
        )
```

3. En el `return CampaignContext(...)`, añade el argumento al final (antes del cierre del paréntesis, tras `custom_instructions=...`):

```python
        custom_instructions=custom_text.strip(),
        rag=rag_config,
    )
```

- [ ] **Step 6: Implementar `RulesBot`**

Crea `src/rpg_scribe/bots/rules/bot.py`:

```python
"""RulesBot: bot de reglas activado por voz que consulta los manuales RAG."""
from __future__ import annotations

import logging
from typing import ClassVar

import rag_lib
from rpg_scribe.bots.base import BaseBot, BotResponse, BotServices
from rpg_scribe.bots.rules.answerer import RuleAnswerer
from rpg_scribe.bots.rules.retriever import RuleRetriever

logger = logging.getLogger(__name__)

_NOT_CONFIGURED = "El bot de reglas no está configurado para esta campaña."
_NOT_FOUND = "No encontré esa regla en los manuales."


class RulesBot(BaseBot):
    keyword: ClassVar[str] = "bot reglas"
    name: ClassVar[str] = "Bot de Reglas"

    def __init__(self) -> None:
        self._enabled = False
        self._retriever: RuleRetriever | None = None
        self._answerer: RuleAnswerer | None = None

    async def setup(self, services: BotServices) -> None:
        rag = services.rag
        if rag is None or not rag.manuals:
            logger.info("RulesBot: sin [campaign.rag] o sin manuales → deshabilitado")
            return

        # Permite override de keyword desde el TOML antes de que el watcher
        # construya su tabla de keywords.
        if rag.keyword:
            self.keyword = rag.keyword

        try:
            manuals = await rag_lib.list_manuals(services.rag_db_path)
        except Exception as exc:
            logger.error("RulesBot: no se pudo abrir rag.db (%s) → deshabilitado", exc)
            return

        name_to_id = {m.name: m.id for m in manuals}
        manual_ids = [name_to_id[n] for n in rag.manuals if n in name_to_id]
        missing = [n for n in rag.manuals if n not in name_to_id]
        if missing:
            logger.warning("RulesBot: manuales no encontrados en rag.db: %s", missing)
        if not manual_ids:
            logger.info("RulesBot: ningún manual configurado existe → deshabilitado")
            return

        manual_names = {mid: name for name, mid in name_to_id.items()}
        language = services.campaign.language if services.campaign else "es"

        self._retriever = RuleRetriever(
            services.rag_db_path, manual_ids, top_k=rag.top_k
        )
        self._answerer = RuleAnswerer(
            api_key=services.anthropic_api_key,
            model=services.summarizer_model,
            manual_names=manual_names,
            language=language,
        )
        self._enabled = True
        logger.info(
            "RulesBot habilitado: keyword=%r, manuales=%s", self.keyword, manual_ids
        )

    async def handle(
        self,
        command: str,
        *,
        session_id: str,
        speaker_id: str,
        speaker_name: str,
    ) -> str | BotResponse:
        if not self._enabled or self._retriever is None or self._answerer is None:
            return _NOT_CONFIGURED

        chunks = await self._retriever.retrieve(command)
        if not chunks:
            return BotResponse(spoken=_NOT_FOUND)

        return await self._answerer.answer(command, chunks)
```

- [ ] **Step 7: Re-exportar `RulesBot` para `discover_bots`**

Reemplaza el contenido de `src/rpg_scribe/bots/rules/__init__.py` por:

```python
"""Paquete del bot de reglas (RAG)."""
from __future__ import annotations

# Import necesario para que discover_bots() (que importa el subpaquete) registre
# la subclase RulesBot.
from rpg_scribe.bots.rules.bot import RulesBot

__all__ = ["RulesBot"]
```

- [ ] **Step 8: Verificar tests de config y bot**

```
pytest tests/test_config.py -k "campaign_rag or without_rag" tests/bots/test_rules_bot.py -v
```
Esperado: todos PASSED.

- [ ] **Step 9: Cablear `BotServices`/`setup()` en `main.py`**

En `src/rpg_scribe/main.py`, dentro de `_start_trigger_watcher`, localiza:

```python
        try:
            bots = discover_bots()
        except Exception as exc:
            logger.error("Bot discovery failed: %s — skipping trigger watcher", exc)
            return
        if not bots:
            logger.info("No bots registered — trigger watcher not started")
            return
```

Inmediatamente **después** de ese bloque (antes de construir el provider TTS), añade:

```python
        # Inyección de dependencias en los bots (una vez, antes del watcher).
        from rpg_scribe.bots.base import BotServices

        campaign = self.config.campaign
        services = BotServices(
            rag_db_path=self.config.rag_db_path,
            anthropic_api_key=self.config.anthropic_api_key,
            summarizer_model=self.config.summarizer.model,
            campaign=campaign,
            event_bus=self.event_bus,
            rag=campaign.rag if campaign else None,
        )
        for bot in bots:
            try:
                await bot.setup(services)
            except Exception as exc:
                logger.error("Bot %s setup failed: %s", bot.keyword, exc)
```

(El `TriggerWatcher(...)` se construye después con `bots=bots`; como `setup()` puede haber cambiado `self.keyword`, el dict de keywords se construye con el valor ya resuelto.)

- [ ] **Step 10: Cablear `DiscordBotResponsePublisher` en `main.py`**

En `_start_discord_bot`, localiza el bloque del summary publisher:

```python
        from rpg_scribe.discord_bot.bot import create_bot
        from rpg_scribe.discord_bot.publisher import DiscordSummaryPublisher
        from rpg_scribe.discord_bot.tts_player import DiscordTTSPlayer
```

Añade el import del nuevo publisher:

```python
        from rpg_scribe.discord_bot.bot_response_publisher import (
            DiscordBotResponsePublisher,
        )
```

Y tras el bloque que crea `self._discord_publisher` (el `if self.config.discord_summary_channel_id:`), añade:

```python
        # Bot de reglas: publica las respuestas escritas. Si [campaign.rag] existe
        # se cablea el publisher aunque no haya rules_channel_id, porque entonces
        # hace fallback al chat del canal de voz (lo resuelve el watcher en el
        # evento). channel_id=None activa ese fallback.
        campaign = self.config.campaign
        rag_cfg = campaign.rag if campaign else None
        if rag_cfg:
            channel_id = (
                int(rag_cfg.rules_channel_id) if rag_cfg.rules_channel_id else None
            )
            self._bot_response_publisher = DiscordBotResponsePublisher(
                bot=bot,
                event_bus=self.event_bus,
                channel_id=channel_id,
            )
```

(Declara `self._bot_response_publisher = None` en `__init__` de la clase junto a `self._discord_publisher`, si esa inicialización existe ahí; si no, esta asignación condicional basta.)

- [ ] **Step 11: CHECKPOINT — discovery, main y config sin regresiones**

```
pytest tests/test_bots.py tests/test_main.py tests/test_config.py tests/test_trigger_watcher.py -q
```
Esperado: todos pasan (verifica que `discover_bots()` ahora incluye `bot reglas` sin errores de keyword duplicada).

---

## Task 7: Documentación — `docs/rules-bot.md`, índice en `CLAUDE.md`, README (requiere Task 6)

Documenta la feature ya implementada. No hay tests; el "test" es coherencia con el código de las Tasks 1-6.

**Files:**
- Create: `docs/rules-bot.md`
- Modify: `CLAUDE.md` (lista "Documentación de Dominio")
- Modify: `README.md` (característica + ejemplo TOML + tabla de componentes)

- [ ] **Step 1: Crear `docs/rules-bot.md`**

Crea `docs/rules-bot.md` con este contenido:

````markdown
# Bot de Reglas (RAG)

Bot activado por voz que responde preguntas de reglas consultando los manuales
ingeridos en `rag_lib`, citando siempre la fuente. Habla la respuesta por el
canal de voz (TTS) y la escribe como embed en un canal de texto.

## Flujo

```
Voz: "bot reglas, ¿cómo funciona el hackeo?"
  → TriggerWatcher capta la pregunta tras la keyword (multi-chunk)
  → RulesBot.handle():
        1. RuleRetriever: búsqueda híbrida (semántica + FTS5) en los manuales
           configurados + follow de página (1 salto: "ver pág. N")
        2. RuleAnswerer: Claude redacta citando manual + página; citas
           deterministas construidas a partir de los chunks usados
        3. devuelve BotResponse(spoken, written, citations)
  → TriggerWatcher habla `spoken` por TTS
  → publica BotTextResponseEvent (con el canal de voz adjunto)
  → DiscordBotResponsePublisher postea el embed con la cita
```

## Framework de bots (base)

Los bots activados por voz viven en `src/rpg_scribe/bots/` y los descubre
`discover_bots()` al arrancar (cualquier submódulo del paquete se auto-importa;
los subpaquetes deben re-exportar su clase en `__init__.py`).

- `BaseBot` (ABC): declara `keyword` (única, lowercase) y opcionalmente `name`,
  `voice`, `close_word`, `timeout_s`.
- `setup(services: BotServices)`: hook opcional de **inyección de dependencias**
  (default no-op). El framework lo llama una vez tras el discovery y antes de
  arrancar el `TriggerWatcher`. Aquí el bot recibe rutas/secretos/config sin
  leer env directamente.
- `handle(command, *, session_id, speaker_id, speaker_name) -> str | BotResponse`:
  procesa el comando. Devolver `str` equivale a `BotResponse(spoken=str)`.
- `BotResponse(spoken, written=None, citations=None)`: lo que se habla
  (`spoken`) y lo que se escribe en texto (`written`, markdown).
- `TriggerWatcher`: detecta la keyword en `TranscriptionEvent`, captura el
  comando, llama a `handle`, sintetiza `spoken` por TTS y, si hay `written`,
  publica `BotTextResponseEvent`.

`EchoBot` es la referencia mínima (devuelve un `str`).

## Configuración

La config se reparte en tres fuentes (estrategia anti-duplicación):

| Qué | Dónde | Cómo llega al bot |
|---|---|---|
| `anthropic_api_key` | env `ANTHROPIC_API_KEY` → `AppConfig` | `BotServices.anthropic_api_key` |
| `rag_db_path` | `AppConfig.rag_db_path` (default `data/rag.db`) | `BotServices.rag_db_path` |
| modelo de Claude | `summarizer.model` (reutilizado) | `BotServices.summarizer_model` |
| manuales, canal, keyword, top_k | `[campaign.rag]` del TOML de campaña | `BotServices.rag` (`RagCampaignConfig`) |
| keyword por defecto | atributo de clase `RulesBot.keyword` | overridable por `[campaign.rag].keyword` |

El bot **nunca lee env**: el framework construye `BotServices` reusando
`AppConfig` y se lo inyecta en `setup()`.

### Sección `[campaign.rag]`

```toml
[campaign.rag]
manuals = ["Cyberpunk RED — Core"]   # por nombre; se resuelven a ids en setup()
rules_channel_id = "123456789012345678"  # opcional (ver "Canal de respuesta")
keyword = "bot reglas"               # opcional; default del bot
top_k = 8                            # opcional
```

Si la sección no existe o no resuelve ningún manual de `rag.db`, el bot se
**auto-desactiva** en `setup()` (log) y no responde a la keyword.

## Canal de la respuesta escrita

La respuesta hablada va al canal de **voz** (TTS). La respuesta escrita (embed
con la cita) se publica por **orden de preferencia**:

1. `[campaign.rag].rules_channel_id` si está configurado (canal dedicado).
2. En su defecto, el **chat integrado del canal de voz** donde se invocó al bot
   (un `VoiceChannel` es *messageable* en discord.py 2.x). El `TriggerWatcher`
   resuelve ese id desde el cliente de voz y lo adjunta a `BotTextResponseEvent`.
3. Si ninguno está disponible, no se escribe (solo queda la respuesta hablada).

Es un canal **independiente** del de resúmenes (`DISCORD_SUMMARY_CHANNEL_ID`).

## Componentes

| Pieza | Archivo | Responsabilidad |
|---|---|---|
| `RuleRetriever` | `bots/rules/retriever.py` | Búsqueda híbrida + follow de página (puro, sin Discord) |
| `RuleAnswerer` | `bots/rules/answerer.py` | Prompt a Claude + citas deterministas + fallback |
| `RulesBot` | `bots/rules/bot.py` | Orquesta retriever → answerer; auto-desactivación |
| `BotTextResponseEvent` | `core/events.py` | Transporta la respuesta escrita + canal de voz |
| `DiscordBotResponsePublisher` | `discord_bot/bot_response_publisher.py` | Embed con la cita en el canal destino |
| `rag_lib.list_chunks_by_page` | `rag_lib/__init__.py` | Trae los chunks que cubren una página (follow) |

## Degradación y casos límite

- Sin manuales / sin resultados → "No encontré esa regla en los manuales."
- `rag.db` ausente o `[campaign.rag]` vacío → bot auto-desactivado en `setup()`.
- Fallo de Claude → fallback: chunk top en bruto + cita determinista.
- Página referida inexistente → se ignora (no rompe el follow).
- Límites de embed de Discord → truncado.

## Fuera de alcance (futuro)

- Trigger por comando de texto.
- Follow de página recursivo / multi-salto.
- Configuración de manuales/canal desde la Web UI.
````

- [ ] **Step 2: Añadir la doc al índice de `CLAUDE.md`**

En `CLAUDE.md`, en la lista "### Documentación de Dominio", añade al final (tras la línea del módulo RAG):

```markdown
- Bot de reglas (RAG) y framework de bots por voz: [`docs/rules-bot.md`](docs/rules-bot.md)
```

- [ ] **Step 3: Actualizar `README.md` — característica**

En `README.md`, en la lista de "## Características", añade un bullet (p. ej. tras el de "Integración Discord"):

```markdown
- **Bot de reglas por voz** — Pregunta "bot reglas, ¿…?" en el canal de voz: busca en los manuales (RAG), responde citando manual y página, lo habla por TTS y lo escribe como embed
```

- [ ] **Step 4: Actualizar `README.md` — ejemplo de campaña**

En `README.md`, en el bloque TOML de ejemplo de la sección "### 5. Configurar una campaña", añade al final del ejemplo (tras el bloque `[[campaign.npcs]]`):

```toml

# Opcional: bot de reglas por voz (consulta manuales ingeridos vía RAG)
[campaign.rag]
manuals = ["Cyberpunk RED — Core"]   # nombre del manual ya ingerido en rag.db
rules_channel_id = "123456789012345678"  # opcional; si falta, escribe en el chat del canal de voz
keyword = "bot reglas"               # opcional
top_k = 8                            # opcional
```

- [ ] **Step 5: Actualizar `README.md` — tabla de componentes**

En `README.md`, en la tabla "### Componentes principales", añade una fila al final:

```markdown
| **Bot de reglas** | Bot activado por voz que consulta manuales (RAG), responde citando la fuente y publica un embed |
```

- [ ] **Step 6: CHECKPOINT — coherencia**

Revisa que `docs/rules-bot.md` describe exactamente los nombres y rutas de las Tasks 1-6 (`RuleRetriever`, `RuleAnswerer`, `RulesBot`, `BotTextResponseEvent`, `DiscordBotResponsePublisher`, `rag_lib.list_chunks_by_page`, `[campaign.rag]`). No hay comando de test; es una revisión de lectura.

---

## Task 8: Verificación final + commit único

**Files:** ninguno nuevo.

- [ ] **Step 1: Suite completa**

```
pytest -q
```
Esperado: todos pasan salvo los fallos pre-existentes documentados en `CLAUDE.md` (`test_tts_config_from_toml`, `test_defaults_from_toml_override_dataclass_defaults` si `RPG_SCRIBE_HOST` está en env, `test_generate_toml_is_valid_toml` en 3.10, `test_half_open_failure_reopens`). Ningún fallo nuevo atribuible a esta feature.

- [ ] **Step 2: Lint**

```
ruff check src/ tests/
ruff format src/ tests/
```
Esperado: sin errores; formato aplicado.

- [ ] **Step 3: Commit único de toda la feature**

```bash
git add src/rag_lib/store.py src/rag_lib/__init__.py \
        src/rpg_scribe/core/events.py src/rpg_scribe/core/models.py \
        src/rpg_scribe/config.py src/rpg_scribe/bots/ \
        src/rpg_scribe/discord_bot/bot_response_publisher.py \
        src/rpg_scribe/main.py tests/ \
        docs/rules-bot.md CLAUDE.md README.md
git commit -m "feat(bots): RulesBot — consulta de reglas con RAG (voz + TTS + embed)"
```

(El mensaje de commit termina con la línea `Co-Authored-By` según las reglas del repo si se desea; el usuario pidió un único commit al final.)

---

## Self-Review (checklist del autor del plan)

**1. Cobertura del spec:**
- Inyección de dependencias (`BotServices` + `setup()`) → Task 2. ✔
- Retorno estructurado `BotResponse` + normalización en watcher → Task 2. ✔
- `RuleRetriever` (híbrido + follow 1 salto) → Task 3. ✔
- `rag_lib.list_chunks_by_page` → Task 1. ✔
- `RuleAnswerer` (prompt + citas deterministas + fallback) → Task 5. ✔
- `RulesBot` (setup resuelve manuales, auto-desactivación, orquesta) → Task 6. ✔
- `BotTextResponseEvent` + `DiscordBotResponsePublisher` + cableado → Tasks 2/4/6. ✔
- Canal de respuesta escrita con fallback al chat del canal de voz → Tasks 2 (evento + watcher), 4 (publisher), 6 (cableado). ✔
- `[campaign.rag]` en config (`RagCampaignConfig`) → Task 6. ✔
- Documentación (`docs/rules-bot.md` + índice CLAUDE.md + README) → Task 7. ✔
- Casos límite (sin manuales, sin resultados, fallo de Claude, página inexistente, truncado de embed, sin canal destino) → cubiertos en Tasks 3/4/5/6. ✔

**2. Placeholders:** ninguno — cada step de código incluye el código real.

**3. Consistencia de tipos:** `BotResponse(spoken, written, citations)`, `Citation(manual, page, section_path)`, `BotTextResponseEvent(session_id, bot_keyword, speaker_name, question, answer_md, citations, voice_channel_id)`, `DiscordBotResponsePublisher(bot, event_bus, channel_id: int | None)`, `RuleRetriever.retrieve(question) -> list[Chunk]`, `RuleAnswerer.answer(question, chunks) -> BotResponse`, `RagCampaignConfig(manuals, rules_channel_id, keyword, top_k)` — usados de forma idéntica en todas las tareas. ✔

**Riesgo conocido a validar en ejecución:** el comportamiento exacto de `EventBus.publish` ante una excepción de un handler (Task 4, `test_no_channel_does_not_raise`). El publisher ya traga la excepción internamente en `_on_response`, así que el test pasa con independencia de eso; si `EventBus` re-lanzara, sería un problema preexistente ajeno a esta feature.
