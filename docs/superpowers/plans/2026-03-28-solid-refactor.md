# SOLID Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split monolithic files into modules <800 lines with clean separation: Routers → Services → Repositories (backend) and ES modules by feature (frontend).

**Architecture:** Three-layer backend (HTTP routers, business services, data repositories) with dependency injection via constructor. Vanilla JS frontend split into ES modules using `state.js` as shared store. No new dependencies introduced.

**Tech Stack:** Python 3.10+, FastAPI APIRouter, aiosqlite, ES modules (browser-native), CSS with multiple files.

**Spec:** `docs/superpowers/specs/2026-03-28-solid-refactor-design.md`

---

## Phase dependencies

```
Phase 1 (Database)  ──→ Phase 2 (Services) ──→ Phase 4 (Routers)
                                             ──→ Phase 5 (main.py)
Phase 3 (Summarizer) — independent, parallelizable with Phase 1-2
Phase 6 (Frontend JS) — independent of all backend phases
Phase 7 (Frontend CSS) — independent, parallelizable with Phase 6
```

---

## Phase 1: Core Database Split

### Task 1.1: Create database/connection.py

**Files:**
- Create: `src/rpg_scribe/core/database/__init__.py`
- Create: `src/rpg_scribe/core/database/connection.py`
- Create: `src/rpg_scribe/core/database/schema.py`

- [ ] **Step 1: Create the database package directory**

```bash
mkdir -p src/rpg_scribe/core/database/repositories
```

- [ ] **Step 2: Create schema.py with the DDL extracted from database.py**

Extract `SCHEMA_SQL` (lines 55-188 of `core/database.py`) into `core/database/schema.py`:

```python
"""Database schema definitions and migrations."""
from __future__ import annotations

SCHEMA_SQL = """
... (copy lines 55-188 from database.py — the full CREATE TABLE block)
"""
```

- [ ] **Step 3: Create connection.py with the Database class infrastructure methods**

Extract the following methods from `core/database.py` into `core/database/connection.py`:
- `__init__` (line 194)
- `connect` (line 198) — change to import `SCHEMA_SQL` from `schema.py`
- `_run_schema_migrations` (line 207)
- `_ensure_column` (line 215)
- `close` (line 222)
- `conn` property (line 230)

Also include the imports and the static helper `_merge_text_fields` (line 875) since repositories will need it.

```python
"""Async SQLite connection wrapper."""
from __future__ import annotations

import logging
from pathlib import Path

import aiosqlite

from rpg_scribe.core.database.schema import SCHEMA_SQL

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: str | Path = "rpg_scribe.db") -> None:
        self._db_path = str(db_path)
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        ... # (copy from database.py line 198-205, using SCHEMA_SQL import)

    async def _run_schema_migrations(self) -> None:
        ... # (copy from database.py line 207-213)

    async def _ensure_column(self, table: str, column: str, col_type: str = "TEXT DEFAULT ''") -> None:
        ... # (copy from database.py line 215-220)

    async def close(self) -> None:
        ... # (copy from database.py line 222-228)

    @property
    def conn(self) -> aiosqlite.Connection:
        ... # (copy from database.py line 230-234)

    @staticmethod
    def _merge_text_fields(old: str, new: str, separator: str = "\n\n") -> str:
        ... # (copy from database.py line 875-885)
```

- [ ] **Step 4: Create `__init__.py` that re-exports Database for backward compatibility**

```python
"""Database package — re-exports Database for backward compatibility."""
from rpg_scribe.core.database.connection import Database

__all__ = ["Database"]
```

- [ ] **Step 5: Run tests to verify imports still work**

```bash
pytest tests/test_database.py -v --tb=short -x
```

Expected: Tests may fail because Database no longer has the CRUD methods. That's expected — we'll add repositories next. The key check is that the import `from rpg_scribe.core.database import Database` resolves.

```bash
python -c "from rpg_scribe.core.database import Database; print('OK')"
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add src/rpg_scribe/core/database/
git commit -m "refactor(database): extract connection, schema into database package"
```

---

### Task 1.2: Create campaign_repo.py

**Files:**
- Create: `src/rpg_scribe/core/database/repositories/__init__.py`
- Create: `src/rpg_scribe/core/database/repositories/campaign_repo.py`

- [ ] **Step 1: Create repositories/__init__.py**

```python
"""Database repositories."""
from __future__ import annotations
```

- [ ] **Step 2: Create campaign_repo.py**

Extract these methods from `core/database.py` (the old monolith, keep it as reference):
- `upsert_campaign` (line 237)
- `get_campaign` (line 281)
- `list_campaigns` (line 294)
- `update_campaign_summary` (line 308)
- `save_campaign_summary` (line 318)
- `list_campaign_summaries` (line 341)
- `get_campaign_summary_by_id` (line 350)
- `get_latest_campaign_summary` (line 360)

```python
"""Campaign data access."""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from rpg_scribe.core.database.connection import Database

logger = logging.getLogger(__name__)


class CampaignRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    @property
    def conn(self):
        return self._db.conn

    async def upsert(self, ...) -> int:
        ... # (adapt from database.py line 237, using self.conn instead of self._conn)

    async def get(self, campaign_id: int) -> dict | None:
        ... # (adapt from line 281)

    async def list_all(self) -> list[dict]:
        ... # (adapt from line 294)

    async def update_summary_text(self, campaign_id: int, summary: str) -> None:
        ... # (adapt from line 308)

    async def save_summary(self, ...) -> int:
        ... # (adapt from line 318)

    async def list_summaries(self, campaign_id: int) -> list[dict]:
        ... # (adapt from line 341)

    async def get_summary_by_id(self, summary_id: int) -> dict | None:
        ... # (adapt from line 350)

    async def get_latest_summary(self, campaign_id: int) -> dict | None:
        ... # (adapt from line 360)
```

**Key adaptation pattern:** Every method that used `self._conn` now uses `self.conn` which delegates to `self._db.conn`.

- [ ] **Step 3: Verify import works**

```bash
python -c "from rpg_scribe.core.database.repositories.campaign_repo import CampaignRepository; print('OK')"
```

- [ ] **Step 4: Commit**

```bash
git add src/rpg_scribe/core/database/repositories/
git commit -m "refactor(database): extract CampaignRepository"
```

---

### Task 1.3: Create session_repo.py

**Files:**
- Create: `src/rpg_scribe/core/database/repositories/session_repo.py`

- [ ] **Step 1: Create session_repo.py**

Extract these methods from `core/database.py`:
- `create_session` (line 374)
- `end_session` (line 382)
- `get_session` (line 392)
- `list_sessions` (line 400)
- `list_all_sessions` (line 410)
- `list_uncategorized_sessions` (line 419)
- `merge_sessions` (line 1335)
- `update_session_summary` (line 1780)
- `update_session_chronology` (line 1789)

```python
"""Session data access."""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from rpg_scribe.core.database.connection import Database

logger = logging.getLogger(__name__)


class SessionRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    @property
    def conn(self):
        return self._db.conn

    async def create(self, campaign_id: int, session_name: str = "") -> int:
        ... # (adapt from line 374)

    async def end(self, session_id: int) -> None:
        ... # (adapt from line 382)

    async def get(self, session_id: int) -> dict | None:
        ... # (adapt from line 392)

    async def list_by_campaign(self, campaign_id: int) -> list[dict]:
        ... # (adapt from line 400)

    async def list_all(self) -> list[dict]:
        ... # (adapt from line 410)

    async def list_uncategorized(self) -> list[dict]:
        ... # (adapt from line 419)

    async def merge(self, source_id: int, target_id: int) -> None:
        ... # (adapt from line 1335)

    async def update_summary(self, session_id: int, summary: str) -> None:
        ... # (adapt from line 1780)

    async def update_chronology(self, session_id: int, chronology: str) -> None:
        ... # (adapt from line 1789)
```

- [ ] **Step 2: Commit**

```bash
git add src/rpg_scribe/core/database/repositories/session_repo.py
git commit -m "refactor(database): extract SessionRepository"
```

---

### Task 1.4: Create transcription_repo.py

**Files:**
- Create: `src/rpg_scribe/core/database/repositories/transcription_repo.py`

- [ ] **Step 1: Create transcription_repo.py**

Extract these methods from `core/database.py`:
- `save_transcription` (line 431)
- `get_transcriptions` (line 459)
- `update_transcription_text` (line 1662)
- `delete_transcription` (line 1673)
- `update_transcription_is_ingame` (line 1682)
- `save_transcription_edit` (line 1693)
- `get_transcription_edits` (line 1710)
- `save_word_replacement` (line 1723)
- `get_word_replacements` (line 1736)
- `delete_word_replacement` (line 1745)
- `apply_word_replacements` (line 1753)

```python
"""Transcription and word replacement data access."""
from __future__ import annotations

import difflib
import json
import logging
import re
import time
import unicodedata
from typing import Any

from rpg_scribe.core.database.connection import Database

logger = logging.getLogger(__name__)


class TranscriptionRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    @property
    def conn(self):
        return self._db.conn

    async def save(self, ...) -> int:
        ... # (adapt from line 431)

    async def get_by_session(self, session_id: int, limit: int | None = None) -> list[dict]:
        ... # (adapt from line 459)

    async def update_text(self, transcription_id: int, text: str) -> None:
        ... # (adapt from line 1662)

    async def delete(self, transcription_id: int) -> None:
        ... # (adapt from line 1673)

    async def update_is_ingame(self, transcription_id: int, is_ingame: bool) -> None:
        ... # (adapt from line 1682)

    async def save_edit(self, ...) -> int:
        ... # (adapt from line 1693)

    async def get_edits(self, transcription_id: int) -> list[dict]:
        ... # (adapt from line 1710)

    async def save_word_replacement(self, campaign_id: int, original: str, replacement: str) -> int:
        ... # (adapt from line 1723)

    async def get_word_replacements(self, campaign_id: int) -> list[dict]:
        ... # (adapt from line 1736)

    async def delete_word_replacement(self, replacement_id: int) -> None:
        ... # (adapt from line 1745)

    async def apply_word_replacements(self, campaign_id: int) -> int:
        ... # (adapt from line 1753)
```

- [ ] **Step 2: Commit**

```bash
git add src/rpg_scribe/core/database/repositories/transcription_repo.py
git commit -m "refactor(database): extract TranscriptionRepository"
```

---

### Task 1.5: Create entity_repo.py

**Files:**
- Create: `src/rpg_scribe/core/database/repositories/entity_repo.py`

- [ ] **Step 1: Create entity_repo.py**

This is the largest repository. Extract ALL entity-related methods from `core/database.py`:

**Players:** `save_player` (1101), `get_players` (1128), `player_exists` (1136), `update_player` (1144)

**NPCs:** `save_npc` (469), `get_npcs` (487), `get_merged_npcs_map` (497), `npc_exists` (516), `update_npc` (528), `update_merged_npc` (542), `merge_npcs` (962)

**Locations:** `save_location` (596), `get_locations` (614), `get_merged_locations_map` (624), `location_exists` (643), `update_location` (655), `update_merged_location` (671), `merge_locations` (1007)

**Entities:** `save_entity` (728), `get_entities` (755), `get_merged_entities_map` (765), `entity_exists` (784), `update_entity` (793), `update_merged_entity` (809), `merge_entities` (1053)

**Relationships:** `get_relationship_types` (1160), `resolve_relationship_type` (1176), `merge_relationship_types` (1247), `_upsert_relationship_row` (887), `_rewrite_relationship_entity_keys` (919), `save_character_relationship` (1441), `_recompute_relationship_type_usage` (1526), `delete_character_relationship` (1542), `relationship_exists` (1557), `get_character_relationships` (1572), `rename_relationship_entity_key` (1586)

**Questions:** `save_question` (1614), `answer_question` (1623), `get_pending_questions` (1631), `get_answered_unprocessed_questions` (1639), `mark_questions_processed` (1649)

Also needs `_merge_text_fields` from `connection.py`.

```python
"""Entity data access: players, NPCs, locations, entities, relationships, questions."""
from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
from typing import Any

from rpg_scribe.core.database.connection import Database

logger = logging.getLogger(__name__)


class EntityRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    @property
    def conn(self):
        return self._db.conn

    # --- Players ---
    async def save_player(self, ...) -> int: ...
    async def get_players(self, campaign_id: int) -> list[dict]: ...
    async def player_exists(self, ...) -> bool: ...
    async def update_player(self, ...) -> None: ...

    # --- NPCs ---
    async def save_npc(self, ...) -> int: ...
    async def get_npcs(self, campaign_id: int) -> list[dict]: ...
    async def get_merged_npcs_map(self, campaign_id: int) -> dict: ...
    async def npc_exists(self, ...) -> bool: ...
    async def update_npc(self, ...) -> None: ...
    async def update_merged_npc(self, ...) -> None: ...
    async def merge_npcs(self, ...) -> None: ...

    # --- Locations ---
    async def save_location(self, ...) -> int: ...
    # ... (same pattern)

    # --- Campaign Entities ---
    async def save_entity(self, ...) -> int: ...
    # ... (same pattern)

    # --- Relationships ---
    async def get_relationship_types(self, campaign_id: int) -> list[dict]: ...
    async def resolve_relationship_type(self, ...) -> int: ...
    async def save_character_relationship(self, ...) -> int: ...
    async def get_character_relationships(self, campaign_id: int) -> list[dict]: ...
    async def delete_character_relationship(self, ...) -> None: ...
    async def relationship_exists(self, ...) -> bool: ...
    async def rename_relationship_entity_key(self, ...) -> int: ...
    async def merge_relationship_types(self, ...) -> None: ...

    # --- Questions ---
    async def save_question(self, ...) -> int: ...
    async def answer_question(self, ...) -> None: ...
    async def get_pending_questions(self, campaign_id: int) -> list[dict]: ...
    async def get_answered_unprocessed_questions(self, campaign_id: int) -> list[dict]: ...
    async def mark_questions_processed(self, ...) -> None: ...

    # --- Private helpers ---
    async def _upsert_relationship_row(self, ...) -> int: ...
    async def _rewrite_relationship_entity_keys(self, ...) -> None: ...
    async def _recompute_relationship_type_usage(self, ...) -> None: ...
```

- [ ] **Step 2: Commit**

```bash
git add src/rpg_scribe/core/database/repositories/entity_repo.py
git commit -m "refactor(database): extract EntityRepository"
```

---

### Task 1.6: Wire Database to delegate to repositories + backward compatibility

**Files:**
- Modify: `src/rpg_scribe/core/database/connection.py`
- Modify: `src/rpg_scribe/core/database/__init__.py`

- [ ] **Step 1: Add repository instances to Database class**

In `connection.py`, after `connect()` initializes the connection, create repository instances:

```python
from rpg_scribe.core.database.repositories.campaign_repo import CampaignRepository
from rpg_scribe.core.database.repositories.session_repo import SessionRepository
from rpg_scribe.core.database.repositories.transcription_repo import TranscriptionRepository
from rpg_scribe.core.database.repositories.entity_repo import EntityRepository

class Database:
    def __init__(self, db_path: str | Path = "rpg_scribe.db") -> None:
        self._db_path = str(db_path)
        self._conn: aiosqlite.Connection | None = None
        self.campaigns = CampaignRepository(self)
        self.sessions = SessionRepository(self)
        self.transcriptions = TranscriptionRepository(self)
        self.entities = EntityRepository(self)
```

- [ ] **Step 2: Add delegation methods on Database for backward compatibility**

To avoid breaking all existing callers at once, add thin delegation methods on `Database` that forward to the appropriate repository. These are temporary — they will be removed as callers migrate to use repos directly.

```python
    # --- Backward-compat delegations (remove as callers migrate) ---
    async def upsert_campaign(self, *a, **kw):
        return await self.campaigns.upsert(*a, **kw)
    async def get_campaign(self, *a, **kw):
        return await self.campaigns.get(*a, **kw)
    # ... (one line per old method, delegating to the correct repo)
```

Generate one delegation method for every public method that was in the old `database.py`. This is tedious but safe — it means nothing breaks during migration.

- [ ] **Step 3: Update __init__.py to also export repositories**

```python
"""Database package."""
from rpg_scribe.core.database.connection import Database
from rpg_scribe.core.database.repositories.campaign_repo import CampaignRepository
from rpg_scribe.core.database.repositories.session_repo import SessionRepository
from rpg_scribe.core.database.repositories.transcription_repo import TranscriptionRepository
from rpg_scribe.core.database.repositories.entity_repo import EntityRepository

__all__ = [
    "Database",
    "CampaignRepository",
    "SessionRepository",
    "TranscriptionRepository",
    "EntityRepository",
]
```

- [ ] **Step 4: Delete the old monolithic database.py**

```bash
rm src/rpg_scribe/core/database.py
```

Note: This file was at `src/rpg_scribe/core/database.py`. Now `core/database/` is a package at the same import path. The `__init__.py` re-exports `Database`, so `from rpg_scribe.core.database import Database` still works.

- [ ] **Step 5: Run full test suite**

```bash
pytest tests/ -v --tb=short -x
```

Expected: All ~307 tests pass (same as before). If any fail, fix import issues — the delegation layer should catch everything.

- [ ] **Step 6: Commit**

```bash
git add -A src/rpg_scribe/core/database/ && git rm src/rpg_scribe/core/database.py 2>/dev/null; true
git add tests/
git commit -m "refactor(database): wire repos with backward-compat delegation, delete monolith"
```

---

## Phase 2: Services Layer

### Task 2.1: Create transcription_service.py

**Files:**
- Create: `src/rpg_scribe/services/__init__.py`
- Create: `src/rpg_scribe/services/transcription_service.py`
- Create: `src/rpg_scribe/services/file_writer.py`

- [ ] **Step 1: Create the services package**

```bash
mkdir -p src/rpg_scribe/services
```

```python
# src/rpg_scribe/services/__init__.py
"""Business logic services."""
from __future__ import annotations
```

- [ ] **Step 2: Create file_writer.py**

Move `TranscriptionFileWriter` from `main.py` (lines 38-85) verbatim:

```python
"""Writes transcriptions to rotating text files."""
from __future__ import annotations

import datetime
import logging
from pathlib import Path

from rpg_scribe.core.events import TranscriptionEvent

logger = logging.getLogger(__name__)

_MAX_TRANSCRIPTION_FILE_MB = 5


class TranscriptionFileWriter:
    ... # (copy lines 38-85 from main.py verbatim)
```

- [ ] **Step 3: Create transcription_service.py**

Extract `_persist_transcription` and `_apply_word_replacements` logic from `main.py` (lines 191-237):

```python
"""Transcription business logic."""
from __future__ import annotations

import logging
import re
from typing import Any

from rpg_scribe.core.database.repositories.transcription_repo import TranscriptionRepository
from rpg_scribe.core.event_bus import EventBus
from rpg_scribe.core.events import TranscriptionEvent

logger = logging.getLogger(__name__)


class TranscriptionService:
    def __init__(
        self,
        transcription_repo: TranscriptionRepository,
        event_bus: EventBus,
    ) -> None:
        self._repo = transcription_repo
        self._event_bus = event_bus
        self._word_replacements: list[tuple[re.Pattern, str]] = []

    async def reload_replacements(self, campaign_id: int) -> None:
        """Load word replacements from DB into memory."""
        rows = await self._repo.get_word_replacements(campaign_id)
        self._word_replacements = [
            (re.compile(re.escape(r["original"]), re.IGNORECASE), r["replacement"])
            for r in rows
        ]

    def apply_replacements(self, text: str) -> str:
        """Apply word replacements to text."""
        for pattern, replacement in self._word_replacements:
            text = pattern.sub(replacement, text)
        return text

    async def persist(self, event: TranscriptionEvent, campaign_id: int, session_id: int) -> dict:
        """Persist transcription to DB, apply word replacements, return data dict."""
        text = self.apply_replacements(event.text) if self._word_replacements else event.text

        transcription_id = await self._repo.save(
            session_id=session_id,
            speaker_id=event.speaker_id,
            speaker_name=event.speaker_name,
            text=text,
            original_text=event.text if text != event.text else None,
            timestamp=event.timestamp,
            is_ingame=event.is_ingame,
        )

        return {
            "id": transcription_id,
            "speaker_id": event.speaker_id,
            "speaker_name": event.speaker_name,
            "text": text,
            "original_text": event.text if text != event.text else None,
            "timestamp": event.timestamp,
            "is_ingame": event.is_ingame,
        }
```

- [ ] **Step 4: Verify import**

```bash
python -c "from rpg_scribe.services.transcription_service import TranscriptionService; print('OK')"
```

- [ ] **Step 5: Commit**

```bash
git add src/rpg_scribe/services/
git commit -m "refactor(services): add TranscriptionService and FileWriter"
```

---

### Task 2.2: Create audio_diagnostics.py, campaign_service.py, session_service.py

**Files:**
- Create: `src/rpg_scribe/services/audio_diagnostics.py`
- Create: `src/rpg_scribe/services/campaign_service.py`
- Create: `src/rpg_scribe/services/session_service.py`

- [ ] **Step 1: Create audio_diagnostics.py**

Move `AudioDiagnosticSaver` from `main.py` (lines 88-131) verbatim:

```python
"""Save audio chunks as WAV files for manual inspection."""
from __future__ import annotations

import logging
from pathlib import Path

from rpg_scribe.core.events import AudioChunkEvent

logger = logging.getLogger(__name__)


class AudioDiagnosticSaver:
    ... # (copy lines 88-131 from main.py verbatim)
```

- [ ] **Step 2: Create campaign_service.py**

Extract `_load_campaign_context_from_db` (routes.py lines 178-264) and `_validate_campaign` (lines 114-155):

```python
"""Campaign business logic."""
from __future__ import annotations

import logging
from typing import Any

from rpg_scribe.core.database.connection import Database
from rpg_scribe.core.database.repositories.campaign_repo import CampaignRepository
from rpg_scribe.core.database.repositories.entity_repo import EntityRepository
from rpg_scribe.core.models import (
    CampaignContext,
    CharacterRelationshipInfo,
    EntityInfo,
    LocationInfo,
    NPCInfo,
    PlayerInfo,
    RelationshipTypeInfo,
)

logger = logging.getLogger(__name__)


class CampaignService:
    def __init__(
        self,
        campaign_repo: CampaignRepository,
        entity_repo: EntityRepository,
    ) -> None:
        self._campaigns = campaign_repo
        self._entities = entity_repo

    async def load_full_context(self, campaign_id: int) -> CampaignContext | None:
        """Hydrate a full CampaignContext from the database."""
        ... # (adapt from routes.py _load_campaign_context_from_db, lines 178-264)

    async def validate_and_load(self, campaign_id: int, state) -> dict | None:
        """Ensure campaign is loaded in state, fetch from DB if needed."""
        ... # (adapt from routes.py _validate_campaign, lines 114-155)
```

- [ ] **Step 3: Create session_service.py**

```python
"""Session lifecycle business logic."""
from __future__ import annotations

import logging
from typing import Any

from rpg_scribe.core.database.repositories.session_repo import SessionRepository
from rpg_scribe.core.database.repositories.transcription_repo import TranscriptionRepository
from rpg_scribe.core.event_bus import EventBus

logger = logging.getLogger(__name__)


class SessionService:
    def __init__(
        self,
        session_repo: SessionRepository,
        transcription_repo: TranscriptionRepository,
        event_bus: EventBus,
    ) -> None:
        self._sessions = session_repo
        self._transcriptions = transcription_repo
        self._event_bus = event_bus

    async def merge(self, source_id: int, target_id: int) -> dict:
        """Merge source session into target."""
        await self._sessions.merge(source_id, target_id)
        return {"ok": True, "target_id": target_id}

    async def finalize(self, session_id: int) -> None:
        """Mark session as ended."""
        await self._sessions.end(session_id)
```

- [ ] **Step 4: Commit**

```bash
git add src/rpg_scribe/services/
git commit -m "refactor(services): add AudioDiagnostics, CampaignService, SessionService"
```

---

### Task 2.3: Create entity_service.py and tts_service.py

**Files:**
- Create: `src/rpg_scribe/services/entity_service.py`
- Create: `src/rpg_scribe/services/tts_service.py`

- [ ] **Step 1: Create entity_service.py**

Extract normalization helpers from `routes.py` (lines 348-453):

```python
"""Entity business logic and normalization."""
from __future__ import annotations

import logging
from typing import Any

from rpg_scribe.core.database.repositories.entity_repo import EntityRepository
from rpg_scribe.core.models import EntityInfo, LocationInfo, NPCInfo

logger = logging.getLogger(__name__)


class EntityService:
    def __init__(self, entity_repo: EntityRepository) -> None:
        self._repo = entity_repo

    @staticmethod
    def normalize_locations(values: list) -> list[dict[str, str]]:
        """Normalize a list of location values into {name, description} dicts."""
        ... # (adapt from routes.py _normalize_locations, lines 384-402)

    @staticmethod
    def normalize_entities(values: list) -> list[dict[str, str]]:
        """Normalize a list of entity values into {name, entity_type, description} dicts."""
        ... # (adapt from routes.py _normalize_entities, lines 434-453)

    @staticmethod
    def extract_location_name(value) -> str:
        ... # (adapt from routes.py line 364-372)

    @staticmethod
    def extract_location_description(value) -> str:
        ... # (adapt from routes.py line 375-381)

    async def load_merged_children_maps(self, campaign_id: int) -> dict:
        """Load merged children maps for npcs/locations/entities."""
        ... # (adapt from routes.py _load_merged_children_maps, lines 492-507)

    async def sync_relationships_to_config(self, config, campaign_id: int) -> None:
        """Refresh relationship thesaurus + relations from DB to config."""
        ... # (adapt from routes.py _sync_relationships_to_config, lines 459-489)
```

- [ ] **Step 2: Create tts_service.py**

```python
"""Text-to-Speech orchestration."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class TTSService:
    def __init__(self, provider=None, config=None) -> None:
        self._provider = provider
        self._config = config

    @staticmethod
    def split_chunks(text: str, limit: int = 3000) -> list[str]:
        """Split text into chunks respecting character limit."""
        ... # (adapt from routes.py _split_tts_chunks, lines 2809-2826)

    async def narrate(self, text: str, voice: str | None = None) -> list[dict]:
        """Generate TTS audio chunks for text."""
        chunks = self.split_chunks(text)
        results = []
        for chunk in chunks:
            if self._provider:
                result = await self._provider.synthesize(chunk, voice=voice)
                results.append(result)
        return results
```

- [ ] **Step 3: Commit**

```bash
git add src/rpg_scribe/services/
git commit -m "refactor(services): add EntityService and TTSService"
```

---

### Task 2.4: Move exporter.py to services/

**Files:**
- Move: `src/rpg_scribe/web/exporter.py` → `src/rpg_scribe/services/export_service.py`

- [ ] **Step 1: Move the file**

```bash
cp src/rpg_scribe/web/exporter.py src/rpg_scribe/services/export_service.py
```

- [ ] **Step 2: Update imports in export_service.py**

If the file imports from relative web paths, update them. Check and fix any `from rpg_scribe.web.exporter` references.

- [ ] **Step 3: Update all callers**

Search for `from rpg_scribe.web.exporter import` and update to `from rpg_scribe.services.export_service import`:

Files to update:
- `src/rpg_scribe/web/routes.py` (line ~32)

- [ ] **Step 4: Run tests**

```bash
pytest tests/ -v --tb=short -x
```

- [ ] **Step 5: Delete old file and commit**

```bash
rm src/rpg_scribe/web/exporter.py
git add src/rpg_scribe/services/export_service.py
git add -u
git commit -m "refactor(services): move exporter to services/export_service"
```

---

## Phase 3: Summarizer Split (parallelizable with Phases 1-2)

### Task 3.1: Extract prompts.py

**Files:**
- Create: `src/rpg_scribe/summarizers/prompts.py`
- Modify: `src/rpg_scribe/summarizers/claude_summarizer.py`

- [ ] **Step 1: Create prompts.py**

Extract all prompt constants from `claude_summarizer.py` (lines 29-299):

```python
"""System prompts and templates for Claude summarization."""
from __future__ import annotations

import re

# Regex for extracting questions from summaries
QUESTION_PATTERN = re.compile(...)  # (from line 29)

GENERIC_SYSTEM_PROMPT = """..."""      # (lines 35-44)
SESSION_SYSTEM_PROMPT = """..."""      # (lines 47-89)
SESSION_UPDATE_USER = """..."""        # (lines 92-99)
FINALIZE_USER = """..."""              # (lines 102-123)
CAMPAIGN_SUMMARY_SYSTEM = """..."""    # (lines 125-156)
CAMPAIGN_SUMMARY_USER = """..."""      # (lines 158-166)
CAMPAIGN_SUMMARY_COMPRESS_USER = """..."""  # (lines 168-177)
CHRONOLOGY_SYSTEM_PROMPT = """..."""   # (lines 179-226)
CHRONOLOGY_USER = """..."""            # (lines 228-236)
CHRONOLOGY_UPDATE_USER = """..."""     # (lines 238-250)
EXTRACTION_USER = """..."""            # (lines 252-299)
```

- [ ] **Step 2: Update claude_summarizer.py to import from prompts.py**

Replace all the prompt constant definitions (lines 29-299) with:

```python
from rpg_scribe.summarizers.prompts import (
    QUESTION_PATTERN,
    GENERIC_SYSTEM_PROMPT,
    SESSION_SYSTEM_PROMPT,
    SESSION_UPDATE_USER,
    FINALIZE_USER,
    CAMPAIGN_SUMMARY_SYSTEM,
    CAMPAIGN_SUMMARY_USER,
    CAMPAIGN_SUMMARY_COMPRESS_USER,
    CHRONOLOGY_SYSTEM_PROMPT,
    CHRONOLOGY_USER,
    CHRONOLOGY_UPDATE_USER,
    EXTRACTION_USER,
)
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/test_summarizer.py -v --tb=short -x
```

- [ ] **Step 4: Commit**

```bash
git add src/rpg_scribe/summarizers/prompts.py src/rpg_scribe/summarizers/claude_summarizer.py
git commit -m "refactor(summarizer): extract prompts to prompts.py"
```

---

### Task 3.2: Extract entity_extractor.py

**Files:**
- Create: `src/rpg_scribe/summarizers/entity_extractor.py`
- Modify: `src/rpg_scribe/summarizers/claude_summarizer.py`

- [ ] **Step 1: Create entity_extractor.py**

Extract from `claude_summarizer.py`:
- `_parse_extraction_response` (lines 1252-1284) — becomes static method
- `extract_entities_from_summary` (lines 1286-1524) — main method
- `_extract_entities` (lines 1526-1541) — background wrapper

```python
"""Entity extraction from session summaries using Claude."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from rpg_scribe.core.database.repositories.entity_repo import EntityRepository
from rpg_scribe.core.event_bus import EventBus
from rpg_scribe.core.events import EntitiesUpdatedEvent
from rpg_scribe.core.models import (
    CampaignContext,
    EntityInfo,
    LocationInfo,
    NPCInfo,
)
from rpg_scribe.summarizers.prompts import EXTRACTION_USER

logger = logging.getLogger(__name__)


class EntityExtractor:
    def __init__(
        self,
        client,
        model: str,
        campaign_context: CampaignContext,
        entity_repo: EntityRepository,
        event_bus: EventBus,
    ) -> None:
        self._client = client
        self._model = model
        self._campaign = campaign_context
        self._repo = entity_repo
        self._event_bus = event_bus

    @staticmethod
    def _parse_extraction_response(text: str) -> dict:
        ... # (copy from claude_summarizer.py lines 1252-1284)

    async def extract_from_summary(self, session_id: int, summary: str) -> dict:
        """Extract NPCs, locations, entities, relationships from summary text."""
        ... # (adapt from claude_summarizer.py lines 1286-1524)
        # Key change: use self._repo instead of self._db for all DB operations

    async def extract_and_publish(self, session_id: int, summary: str) -> None:
        """Background task: extract entities and publish event."""
        ... # (adapt from claude_summarizer.py lines 1526-1541)
```

- [ ] **Step 2: Update claude_summarizer.py to use EntityExtractor**

Remove the extraction methods (lines 1252-1541). Add EntityExtractor as a dependency:

```python
from rpg_scribe.summarizers.entity_extractor import EntityExtractor

class ClaudeSummarizer(BaseSummarizer):
    def __init__(self, ...):
        ... # existing init
        self._extractor: EntityExtractor | None = None

    def _ensure_extractor(self) -> EntityExtractor:
        if self._extractor is None:
            self._extractor = EntityExtractor(
                client=self._get_client(),
                model=self._model,
                campaign_context=self._campaign,
                entity_repo=self._db.entities if self._db else None,
                event_bus=self._event_bus,
            )
        return self._extractor
```

Replace calls to `self.extract_entities_from_summary(...)` with `self._ensure_extractor().extract_from_summary(...)`.
Replace calls to `self._extract_entities(...)` with `self._ensure_extractor().extract_and_publish(...)`.

- [ ] **Step 3: Update __init__.py to re-export EntityExtractor**

```python
# src/rpg_scribe/summarizers/__init__.py
from rpg_scribe.summarizers.claude_summarizer import ClaudeSummarizer
from rpg_scribe.summarizers.entity_extractor import EntityExtractor

__all__ = ["ClaudeSummarizer", "EntityExtractor"]
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_summarizer.py -v --tb=short -x
```

- [ ] **Step 5: Commit**

```bash
git add src/rpg_scribe/summarizers/
git commit -m "refactor(summarizer): extract EntityExtractor"
```

---

## Phase 4: Web Routers (requires Phase 2)

### Task 4.1: Extract WebState to state.py

**Files:**
- Create: `src/rpg_scribe/web/state.py`
- Modify: `src/rpg_scribe/web/routes.py`
- Modify: `src/rpg_scribe/web/app.py`

- [ ] **Step 1: Create state.py**

Extract `WebState` class from `routes.py` (lines 36-92):

```python
"""In-memory state cache for the web layer."""
from __future__ import annotations

import time
from typing import Any


class WebState:
    ... # (copy lines 36-92 from routes.py verbatim)
```

- [ ] **Step 2: Update routes.py to import from state.py**

Replace the WebState class definition with:

```python
from rpg_scribe.web.state import WebState
```

- [ ] **Step 3: Update app.py import**

Change `from rpg_scribe.web.routes import WebState, router` to:

```python
from rpg_scribe.web.state import WebState
from rpg_scribe.web.routes import router
```

- [ ] **Step 4: Update test imports**

In `tests/test_web.py` and `tests/test_tts.py`, update `from rpg_scribe.web.routes import WebState` to `from rpg_scribe.web.state import WebState`.

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_web.py tests/test_tts.py -v --tb=short -x
```

- [ ] **Step 6: Commit**

```bash
git add src/rpg_scribe/web/state.py src/rpg_scribe/web/routes.py src/rpg_scribe/web/app.py tests/
git commit -m "refactor(web): extract WebState to state.py"
```

---

### Task 4.2: Create routers package and split routes.py

**Files:**
- Create: `src/rpg_scribe/web/routers/__init__.py`
- Create: `src/rpg_scribe/web/routers/campaigns.py`
- Create: `src/rpg_scribe/web/routers/sessions.py`
- Create: `src/rpg_scribe/web/routers/entities.py`
- Create: `src/rpg_scribe/web/routers/transcriptions.py`
- Create: `src/rpg_scribe/web/routers/tts.py`
- Create: `src/rpg_scribe/web/routers/status.py`
- Modify: `src/rpg_scribe/web/app.py`

This is the largest single task. Each router file follows this pattern:

```python
"""Campaign API endpoints."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

router = APIRouter()
logger = logging.getLogger(__name__)


# Helper to access shared dependencies (same pattern as current routes.py)
def _get_state():
    return router.state

def _get_database():
    return router.database

# ... (only the helpers this router needs)


@router.get("/campaigns")
async def get_campaigns():
    ... # (move from routes.py)
```

- [ ] **Step 1: Create routers directory**

```bash
mkdir -p src/rpg_scribe/web/routers
```

- [ ] **Step 2: Create routers/__init__.py**

```python
"""Web API routers."""
from __future__ import annotations
```

- [ ] **Step 3: Create status.py**

Move from `routes.py`:
- `favicon()` (line 510)
- `get_status()` (line 518)
- `websocket_live()` (line 2791)

- [ ] **Step 4: Create transcriptions.py**

Move from `routes.py`:
- `get_transcriptions()` (line 534)
- `get_full_transcriptions()` (line 562)
- `update_transcription()` (line 644)
- `delete_transcription()` (line 679)
- `toggle_transcription_meta()` (line 697)
- `get_word_replacements()` (line 723)
- `create_word_replacement()` (line 733)
- `delete_word_replacement()` (line 755)
- `apply_word_replacements()` (line 772)

- [ ] **Step 5: Create campaigns.py**

Move from `routes.py`:
- `get_campaigns()` (line 1016)
- `list_browse_campaigns()` (line 1117)
- `get_browse_campaign()` (line 1145)
- `update_campaign()` (line 1197)
- `update_campaign_summary_text()` (line 956)
- `generate_campaign_summary_on_demand()` (line 2235)
- `list_campaign_summaries()` (line 2347)
- `get_latest_campaign_summary()` (line 2378)
- `get_campaign_summary()` (line 2392)
- `get_questions()` (line 975)
- `answer_question()` (line 992)
- Helper: `_validate_campaign()`, `_load_campaign_context_from_db()`, `_flatten_campaign_row()`, `_persist_campaign_toml()`

- [ ] **Step 6: Create sessions.py**

Move from `routes.py`:
- `get_summary()` (line 580)
- `update_session_summary()` (line 785)
- `update_session_chronology()` (line 805)
- `generate_session_summary()` (line 825)
- `generate_session_chronology()` (line 898)
- `list_all_sessions()` (line 2408)
- `list_uncategorized_sessions()` (line 2422)
- `list_campaign_sessions()` (line 2436)
- `get_session_logs()` (line 2484)
- `get_session_log_file()` (line 2517)
- `get_session_logs_explorer()` (line 2531)
- `create_session_export()` (line 2568)
- `list_session_exports()` (line 2594)
- `download_session_export()` (line 2619)
- `finalize_session()` (line 2638)
- `extract_entities()` (line 2665)
- `refresh_summary()` (line 2750)
- `merge_sessions_endpoint()` (line 2771)
- Helpers: `_load_session_export_data()`, `_logs_root()`, `_session_logs_dir()`, `_exports_root()`, `_get_export_service()`, `_format_session_list()`

- [ ] **Step 7: Create entities.py**

Move from `routes.py`:
- All player/NPC/location/entity/relationship CRUD endpoints (lines 1287-2234)
- Helpers: `_normalize_locations()`, `_normalize_entities()`, `_extract_*()`, `_sync_relationships_to_config()`, `_load_merged_children_maps()`

- [ ] **Step 8: Create tts.py**

Move from `routes.py`:
- `tts_narrate()` (line 2828)
- `tts_voices()` (line 2886)
- Helper: `_split_tts_chunks()` (line 2809)

- [ ] **Step 9: Update app.py to mount sub-routers**

Replace the single router import with:

```python
from rpg_scribe.web.routers import campaigns, sessions, entities, transcriptions, tts, status

# In create_app(), replace the single router attachment with:
for sub_router in [campaigns, sessions, entities, transcriptions, tts, status]:
    sub_router.router.state = state
    sub_router.router.ws_manager = manager
    sub_router.router.database = database
    sub_router.router.config = config
    sub_router.router.event_bus = event_bus
    sub_router.router.application = application
    if tts_config:
        sub_router.router.tts_config = tts_config
        sub_router.router.tts_provider = tts_provider

app.include_router(status.router)
app.include_router(campaigns.router, prefix="/api")
app.include_router(sessions.router, prefix="/api")
app.include_router(entities.router, prefix="/api")
app.include_router(transcriptions.router, prefix="/api")
app.include_router(tts.router, prefix="/api")
```

**Important:** Check if endpoints in `routes.py` already include `/api` prefix or not. If they do, don't add `prefix="/api"` to `include_router`. Compare the current URL patterns and adjust accordingly.

- [ ] **Step 10: Delete old routes.py**

```bash
rm src/rpg_scribe/web/routes.py
```

- [ ] **Step 11: Update test imports**

In `tests/test_web.py` and `tests/test_tts.py`, update any `from rpg_scribe.web.routes import router` to import from the appropriate sub-router or use the app test client directly.

- [ ] **Step 12: Run full test suite**

```bash
pytest tests/ -v --tb=short -x
```

- [ ] **Step 13: Commit**

```bash
git add src/rpg_scribe/web/routers/ src/rpg_scribe/web/app.py
git add -u
git commit -m "refactor(web): split routes.py into domain routers"
```

---

## Phase 5: main.py Cleanup (requires Phase 2)

### Task 5.1: Wire main.py to use services

**Files:**
- Modify: `src/rpg_scribe/main.py`

- [ ] **Step 1: Remove TranscriptionFileWriter and AudioDiagnosticSaver classes**

Delete lines 38-131 from `main.py`. Replace with imports:

```python
from rpg_scribe.services.file_writer import TranscriptionFileWriter
from rpg_scribe.services.audio_diagnostics import AudioDiagnosticSaver
from rpg_scribe.services.transcription_service import TranscriptionService
```

- [ ] **Step 2: Refactor Application.__init__ to create service instances**

In `Application.__init__`, after creating the database, add:

```python
# After self._db is created:
self._transcription_service: TranscriptionService | None = None
```

In `Application.start`, after `await self._db.connect()`, add:

```python
self._transcription_service = TranscriptionService(
    transcription_repo=self._db.transcriptions,
    event_bus=self._event_bus,
)
if self._config.campaign:
    await self._transcription_service.reload_replacements(self._campaign_id)
```

- [ ] **Step 3: Replace _persist_transcription with service call**

Replace `self._persist_transcription(event)` calls with delegation to `self._transcription_service.persist(event, ...)`.

Replace `self._apply_word_replacements(text)` calls with `self._transcription_service.apply_replacements(text)`.

Remove the old `_persist_transcription` and `_apply_word_replacements` methods from Application.

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_main.py -v --tb=short -x
pytest tests/ -v --tb=short -x
```

- [ ] **Step 5: Commit**

```bash
git add src/rpg_scribe/main.py
git commit -m "refactor(main): wire services, remove extracted classes"
```

---

## Phase 6: Frontend JS (independent of backend phases)

### Task 6.1: Create state.js, api.js, utils.js

**Files:**
- Create: `src/rpg_scribe/web/static/js/state.js`
- Create: `src/rpg_scribe/web/static/js/api.js`
- Create: `src/rpg_scribe/web/static/js/utils.js`

- [ ] **Step 1: Create js directory**

```bash
mkdir -p src/rpg_scribe/web/static/js
mkdir -p src/rpg_scribe/web/static/js/relationships
```

- [ ] **Step 2: Create state.js**

Extract all state variables from `app.js` (lines 134-159 + 828-836):

```javascript
/**
 * Shared application state — singleton object imported by all modules.
 */
export const state = {
  // DOM won't be here — each module grabs its own DOM refs
  // Only shared mutable data
  viewingHistorical: false,
  activeSessionId: null,
  activeCampaignId: null,
  currentCampaign: null,
  lastStatusTimestamp: 0,
  previousQuestionCount: 0,
  maxFeedItems: 500,
  loadedLiveSessionId: null,
  currentHistoricalSessionId: null,
  appMode: "live",
  browseCampaignId: null,
  UNCATEGORIZED_BROWSE_ID: "__uncategorized__",
  sessionListLoaded: false,
  browseCampaignsCache: null,
  relationshipGraphVisible: false,
  relationshipGraphFilters: { players: true, npcs: true, locations: true, entities: true },
  relationshipGraph3d: null,
  lastRelationshipAllItems: null,
  lastRelationshipItems: null,
  lastRelationshipCampaign: null,
  relationshipEditOriginal: null,
  mergeMode: false,
  mergeSelected: [],
  // TTS state
  ttsEnabled: false,
  ttsAudio: null,
  ttsAllChunks: [],
  ttsCurrentIndex: 0,
  ttsTotalChunks: 0,
  ttsPaused: false,
  ttsActiveBtn: null,
  ttsControlsEl: null,
  _ttsGen: 0,
};
```

- [ ] **Step 3: Create api.js**

```javascript
/**
 * Centralized API fetch helpers.
 */

export async function apiGet(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`GET ${path}: ${res.status}`);
  return res.json();
}

export async function apiPost(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`POST ${path}: ${res.status}`);
  return res.json();
}

export async function apiPut(path, body) {
  const res = await fetch(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`PUT ${path}: ${res.status}`);
  return res.json();
}

export async function apiPatch(path, body) {
  const res = await fetch(path, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`PATCH ${path}: ${res.status}`);
  return res.json();
}

export async function apiDelete(path) {
  const res = await fetch(path, { method: "DELETE" });
  if (!res.ok) throw new Error(`DELETE ${path}: ${res.status}`);
  return res.json();
}

export async function apiPostRaw(path, body) {
  return fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
```

- [ ] **Step 4: Create utils.js**

Extract utility functions from `app.js` (lines 163-256, 309-328, 1138-1170):

```javascript
/**
 * Pure utility functions — no DOM dependencies, no state mutations.
 */

export function escapeHtml(str) {
  // (from app.js line 1138)
  if (!str) return "";
  return String(str).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}

export function escapeAttr(str) {
  // (from app.js line 1144)
  return escapeHtml(str).replace(/'/g, "&#39;");
}

export function formatTime(ts) { ... }      // (from line 309)
export function formatDate(ts) { ... }      // (from line 315)
export function formatDuration(minutes) { ... }  // (from line 321)
export function locationName(loc) { ... }   // (from line 1149)
export function locationDescription(loc) { ... } // (from line 1156)
export function entityType(entity) { ... }  // (from line 1161)
export function entityDescription(entity) { ... } // (from line 1166)
export function formatLatency(seconds) { ... }    // (from line 1127)
export function latencyClass(seconds) { ... }     // (from line 1132)

export function createSpinner() { ... }     // (from line 163)
export function withLoading(btn, asyncFn, options) { ... }  // (from line 170)
export function withPanelLoading(container, asyncFn) { ... } // (from line 190)
export function showSkeleton(container, lineCount) { ... }   // (from line 215)
export function hideSkeleton(container) { ... }              // (from line 229)
export function setRefreshing(container, active) { ... }     // (from line 243)
```

- [ ] **Step 5: Commit**

```bash
git add src/rpg_scribe/web/static/js/
git commit -m "refactor(frontend): create state.js, api.js, utils.js modules"
```

---

### Task 6.2: Create websocket.js

**Files:**
- Create: `src/rpg_scribe/web/static/js/websocket.js`

- [ ] **Step 1: Create websocket.js**

Extract `connectWS()` and `handleMessage()` from `app.js` (lines 257-308). Import handlers from other modules (these modules don't exist yet — use the imports as forward declarations; they'll be created in subsequent tasks).

```javascript
/**
 * WebSocket connection and message dispatch.
 */
import { state } from "./state.js";

// These will be populated by main.js after all modules load
const handlers = {};

export function registerHandler(type, fn) {
  handlers[type] = fn;
}

export function connectWS() {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${protocol}//${location.host}/ws/live`);

  ws.onopen = () => {
    document.getElementById("connection-badge").textContent = "Connected";
    document.getElementById("connection-badge").className = "badge connected";
  };

  ws.onclose = () => {
    document.getElementById("connection-badge").textContent = "Disconnected";
    document.getElementById("connection-badge").className = "badge";
    setTimeout(connectWS, 3000);
  };

  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    const handler = handlers[msg.type];
    if (handler) handler(msg);
  };

  state.ws = ws;
}
```

Note: The current `handleMessage()` has a switch statement. We replace it with a registry pattern so modules register their own handlers, avoiding circular imports.

- [ ] **Step 2: Commit**

```bash
git add src/rpg_scribe/web/static/js/websocket.js
git commit -m "refactor(frontend): create websocket.js module"
```

---

### Task 6.3: Create campaign.js, transcription.js, summary.js

**Files:**
- Create: `src/rpg_scribe/web/static/js/campaign.js`
- Create: `src/rpg_scribe/web/static/js/transcription.js`
- Create: `src/rpg_scribe/web/static/js/summary.js`

- [ ] **Step 1: Create campaign.js**

Extract from `app.js` (lines 1463-1658):
- `fetchCampaignInfo()`, `renderCampaignBar()`, `updateCampaignSummaryStats()`, `getMasterDisplayName()`, `populateMasterSelect()`, `openCampaignEdit()`, `closeCampaignEdit()`, `saveCampaignEdit()`

```javascript
/**
 * Campaign bar: display, edit, save campaign metadata.
 */
import { state } from "./state.js";
import { apiGet, apiPatch } from "./api.js";
import { escapeHtml } from "./utils.js";

// Forward references — set by main.js to break circular deps
let onCampaignLoaded = () => {};
export function setOnCampaignLoaded(fn) { onCampaignLoaded = fn; }

export async function fetchCampaignInfo() {
  ... // (adapt from app.js, call onCampaignLoaded(campaign) for entity rendering)
}

export function renderCampaignBar(campaign) { ... }
// ... rest of campaign functions
```

- [ ] **Step 2: Create transcription.js**

Extract from `app.js` (lines 329-631):
- `addTranscription()`, `trimTranscriptionFeed()`, `resolveTranscriptionId()`, `startWordEdit()`, `saveWordEdit()`, `addLogEntry()`, `clearLog()`

```javascript
/**
 * Transcription feed: display, edit, word replacements.
 */
import { state } from "./state.js";
import { apiPost, apiPut } from "./api.js";
import { escapeHtml, formatTime } from "./utils.js";

export function addTranscription(data) { ... }
export function trimTranscriptionFeed() { ... }
// ...
```

- [ ] **Step 3: Create summary.js**

Extract from `app.js` (lines 632-849):
- `addLogEntry()`, `clearLog()`, `handleGenerationProgress()`, `updateGenerateChronologyBtn()`, `updateSummary()`, `renderEditableSummary()`, `startParagraphEdit()`, `saveParagraphEdit()`

```javascript
/**
 * Summary tabs: narrative, chronology, campaign. Editable paragraphs.
 */
import { state } from "./state.js";
import { apiPut } from "./api.js";
import { escapeHtml } from "./utils.js";

export function updateSummary(data) { ... }
export function renderEditableSummary(container, text, type, targetId) { ... }
// ...
```

- [ ] **Step 4: Commit**

```bash
git add src/rpg_scribe/web/static/js/campaign.js src/rpg_scribe/web/static/js/transcription.js src/rpg_scribe/web/static/js/summary.js
git commit -m "refactor(frontend): create campaign, transcription, summary modules"
```

---

### Task 6.4: Create entities.js, sessions.js, tts.js

**Files:**
- Create: `src/rpg_scribe/web/static/js/entities.js`
- Create: `src/rpg_scribe/web/static/js/sessions.js`
- Create: `src/rpg_scribe/web/static/js/tts.js`

- [ ] **Step 1: Create entities.js**

Extract from `app.js`:
- `renderPlayers()` (line 1659), `renderNpcs()` (1742), `renderLocations()` (1905), `renderEntities()` (2077)
- All merge helpers (lines 1171-1462)
- Entity helper functions (lines 2262-2345)
- Word replacements functions (lines 3011-3296)

```javascript
/**
 * Entity management: players, NPCs, locations, entities, word replacements.
 */
import { state } from "./state.js";
import { apiGet, apiPost, apiPut, apiDelete } from "./api.js";
import { escapeHtml, escapeAttr, locationName, entityType, entityDescription } from "./utils.js";

export function renderPlayers(players) { ... }
export function renderNpcs(npcs) { ... }
export function renderLocations(locations) { ... }
export function renderEntities(entities) { ... }
export function fetchWordReplacements(campaignId) { ... }
// ... merge helpers
```

- [ ] **Step 2: Create sessions.js**

Extract from `app.js` (lines 3589-4142):
- `fetchSessionList()`, `renderSessionList()`, `highlightSession()`, `loadLiveSessionSnapshot()`, `loadHistoricalSession()`, `switchToLive()`, `getSessionIdForTranscriptView()`, `updateFinalizeButton()`
- Merge functions: `enterMergeMode()`, `exitMergeMode()`, `toggleMergeSelect()`, `updateMergeConfirmPanel()`, `executeMerge()`
- Browse/mode functions: `setMode()`, `fetchBrowseCampaigns()`, `renderBrowseCampaignList()`, `selectBrowseCampaign()`
- Questions/polling: `pollQuestions()`, `updateQuestionsBadge()`, `renderQuestions()`, `submitAnswer()`
- Export/log links: `renderSessionLogLink()`, `renderSessionExports()`

```javascript
/**
 * Session sidebar, browse mode, merge, questions, exports.
 */
import { state } from "./state.js";
import { apiGet, apiPost } from "./api.js";
import { escapeHtml, formatDate, formatDuration } from "./utils.js";

export function fetchSessionList() { ... }
export function setMode(mode) { ... }
// ...
```

- [ ] **Step 3: Create tts.js**

Extract from `app.js` (lines 828-1094):
- All TTS functions: `startNarration()`, `stopNarration()`, `_getNarrateText()`, `_createNarrateControls()`, `_updateControls()`, `_playChunk()`, `_onNarrationComplete()`, `_pauseResume()`, `_prevChunk()`, `_nextChunk()`, `_restartChunk()`

```javascript
/**
 * Text-to-Speech: narrate summaries with chunked playback.
 */
import { state } from "./state.js";
import { apiPostRaw } from "./api.js";

export async function startNarration(btn) { ... }
export function stopNarration() { ... }
// ...
```

- [ ] **Step 4: Commit**

```bash
git add src/rpg_scribe/web/static/js/entities.js src/rpg_scribe/web/static/js/sessions.js src/rpg_scribe/web/static/js/tts.js
git commit -m "refactor(frontend): create entities, sessions, tts modules"
```

---

### Task 6.5: Create relationships/ modules

**Files:**
- Create: `src/rpg_scribe/web/static/js/relationships/index.js`
- Create: `src/rpg_scribe/web/static/js/relationships/graph-2d.js`
- Move + refactor: `src/rpg_scribe/web/static/relationship-graph-3d.js` → `src/rpg_scribe/web/static/js/relationships/graph-3d.js`

- [ ] **Step 1: Create relationships/index.js**

This is the facade that the rest of the app imports. Extract from `app.js` (lines 2279-3010):
- `buildRelationshipEntities()`, `renderRelationshipCards()`, `renderRelationships()`, `renderRelationshipsFromCurrentState()`
- All filter/select helpers
- `setRelationshipGraphVisible()`, `onGraphFiltersChanged()`

```javascript
/**
 * Relationships: facade for CRUD, filters, graph rendering.
 */
import { state } from "../state.js";
import { apiGet, apiPost, apiPut, apiDelete } from "../api.js";
import { escapeHtml } from "../utils.js";

export function renderRelationships(relationships, campaign) { ... }
export function renderRelationshipsFromCurrentState() { ... }
export function onGraphFiltersChanged() { ... }
// ...
```

- [ ] **Step 2: Create graph-2d.js**

Extract the SVG graph rendering from `app.js` (if it exists as a separate 2D renderer — based on the analysis, the 2D graph may be inline in `renderRelationships`. If so, extract it here).

```javascript
/**
 * 2D SVG relationship graph renderer.
 */
export function createRelationshipGraph2D(options) { ... }
```

- [ ] **Step 3: Refactor graph-3d.js to ES module**

Convert `relationship-graph-3d.js` from IIFE to ES module:

```javascript
/**
 * 3D Canvas relationship graph renderer.
 */
import { escapeHtml } from "../utils.js";

// Remove IIFE wrapper, remove duplicated utilities
// Replace (function(global) { ... })(window) with exports

export function createRelationshipGraph3D(options) {
  ... // (same code, but using imported escapeHtml)
}
```

Remove duplicated functions: `clamp`, `escapeHtml`, `formatMetric` — import from `utils.js` or define locally only if they differ.

- [ ] **Step 4: Commit**

```bash
git add src/rpg_scribe/web/static/js/relationships/
git commit -m "refactor(frontend): create relationships/ module with 2D/3D graph"
```

---

### Task 6.6: Create main.js entry point and update index.html

**Files:**
- Create: `src/rpg_scribe/web/static/js/main.js`
- Modify: `src/rpg_scribe/web/static/index.html`

- [ ] **Step 1: Create main.js**

This is the entry point that wires everything together:

```javascript
/**
 * Entry point — initializes all modules.
 */
import { state } from "./state.js";
import { connectWS, registerHandler } from "./websocket.js";
import { fetchCampaignInfo, setOnCampaignLoaded } from "./campaign.js";
import { addTranscription } from "./transcription.js";
import { updateSummary, handleGenerationProgress } from "./summary.js";
import { renderPlayers, renderNpcs, renderLocations, renderEntities, fetchWordReplacements } from "./entities.js";
import { renderRelationships } from "./relationships/index.js";
import { fetchSessionList, pollQuestions, setMode } from "./sessions.js";
import { updateStatus } from "./utils.js"; // or wherever updateStatus lands

// Register WebSocket message handlers
registerHandler("transcription", addTranscription);
registerHandler("summary", (msg) => updateSummary(msg));
registerHandler("status", (msg) => updateStatus(msg));
registerHandler("generation_progress", handleGenerationProgress);
registerHandler("entities_updated", () => fetchCampaignInfo());

// Wire campaign load callback to render all entity sections
setOnCampaignLoaded((campaign) => {
  renderPlayers(campaign.players || []);
  renderNpcs(campaign.npcs || []);
  renderLocations(campaign.locations || []);
  renderEntities(campaign.entities || []);
  renderRelationships(campaign.relationships || [], campaign);
  if (campaign.id) fetchWordReplacements(campaign.id);
});

// Tab switching setup
const summaryTabs = document.querySelectorAll(".summary-tab");
summaryTabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    summaryTabs.forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    // ... tab switching logic
  });
});

// Initialize
connectWS();
fetchCampaignInfo();
pollQuestions();
setInterval(() => {
  if (state.appMode === "live") pollQuestions();
}, 5000);
setTimeout(() => {
  fetchSessionList();
  setInterval(fetchSessionList, 30000);
}, 500);
setMode("live");
```

- [ ] **Step 2: Update index.html**

Replace the script tags:

```html
<!-- Before -->
<script src="/relationship-graph-3d.js"></script>
<script src="/app.js"></script>

<!-- After -->
<script type="module" src="/js/main.js"></script>
```

- [ ] **Step 3: Delete old app.js (after verifying new modules work)**

Do NOT delete yet. First verify in browser:

1. Start the app: `rpg-scribe --campaign config/campaigns/example.toml`
2. Open browser to `http://localhost:8000`
3. Verify: campaign bar loads, WebSocket connects, entities render

Once verified:

```bash
rm src/rpg_scribe/web/static/app.js
rm src/rpg_scribe/web/static/relationship-graph-3d.js
```

- [ ] **Step 4: Commit**

```bash
git add src/rpg_scribe/web/static/js/main.js src/rpg_scribe/web/static/index.html
git add -u
git commit -m "refactor(frontend): create main.js entry point, switch to ES modules"
```

---

## Phase 7: Frontend CSS (parallelizable with Phase 6)

### Task 7.1: Split style.css into module files

**Files:**
- Create: `src/rpg_scribe/web/static/css/variables.css`
- Create: `src/rpg_scribe/web/static/css/base.css`
- Create: `src/rpg_scribe/web/static/css/layout.css`
- Create: `src/rpg_scribe/web/static/css/components.css`
- Create: `src/rpg_scribe/web/static/css/features/campaign.css`
- Create: `src/rpg_scribe/web/static/css/features/entities.css`
- Create: `src/rpg_scribe/web/static/css/features/relationships.css`
- Create: `src/rpg_scribe/web/static/css/features/feed.css`
- Create: `src/rpg_scribe/web/static/css/features/summary.css`
- Modify: `src/rpg_scribe/web/static/index.html`

- [ ] **Step 1: Create CSS directory structure**

```bash
mkdir -p src/rpg_scribe/web/static/css/features
```

- [ ] **Step 2: Create variables.css**

Extract CSS custom properties from `style.css` (lines 1-13):

```css
/* Design tokens */
:root {
  --bg: #0f172a;
  --accent: #7c3aed;
  /* ... all CSS variables */
}
```

- [ ] **Step 3: Create base.css**

Extract global styles (lines ~15-36): `*`, `body`, `h1-h6`, `a`, font stacks.

- [ ] **Step 4: Create layout.css**

Extract grid, sidebar, panels, responsive breakpoints (lines ~154-300 and ~1200+).

- [ ] **Step 5: Create components.css**

Extract reusable component styles (lines ~38-152 and ~300+): `.btn-small`, `.badge`, `input`, `textarea`, tabs, cards.

- [ ] **Step 6: Create features/campaign.css**

Extract campaign bar styles (lines ~47-82).

- [ ] **Step 7: Create features/entities.css**

Extract entity list/card styles (lines ~300-600).

- [ ] **Step 8: Create features/relationships.css**

Extract relationship graph styles (lines 895-1268 — the entire block).

- [ ] **Step 9: Create features/feed.css**

Extract transcription feed styles (lines ~800-894).

- [ ] **Step 10: Create features/summary.css**

Extract summary/editable paragraph styles (lines ~414-436 and related).

- [ ] **Step 11: Update index.html to use new CSS files**

Replace:
```html
<link rel="stylesheet" href="/style.css">
```

With:
```html
<link rel="stylesheet" href="/css/variables.css">
<link rel="stylesheet" href="/css/base.css">
<link rel="stylesheet" href="/css/layout.css">
<link rel="stylesheet" href="/css/components.css">
<link rel="stylesheet" href="/css/features/campaign.css">
<link rel="stylesheet" href="/css/features/entities.css">
<link rel="stylesheet" href="/css/features/relationships.css">
<link rel="stylesheet" href="/css/features/feed.css">
<link rel="stylesheet" href="/css/features/summary.css">
```

- [ ] **Step 12: Also update campaign-summaries.html if it references style.css**

Check and update the `<link>` tag in `campaign-summaries.html`.

- [ ] **Step 13: Delete old style.css and verify visually**

```bash
rm src/rpg_scribe/web/static/style.css
```

Open browser, verify all styles render correctly.

- [ ] **Step 14: Commit**

```bash
git add src/rpg_scribe/web/static/css/ src/rpg_scribe/web/static/index.html src/rpg_scribe/web/static/campaign-summaries.html
git add -u
git commit -m "refactor(frontend): split style.css into modular CSS files"
```

---

## Phase 8: Cleanup

### Task 8.1: Remove backward-compat delegation from Database

**Files:**
- Modify: `src/rpg_scribe/core/database/connection.py`

- [ ] **Step 1: Search for remaining direct Database method calls**

```bash
grep -rn "\.upsert_campaign\|\.get_campaign\|\.save_transcription\|\.get_transcriptions\|\.save_npc\|\.get_npcs" src/rpg_scribe/ --include="*.py" | grep -v "repo\|repository\|__pycache__"
```

For each caller still using the old `db.method()` style, update to use `db.campaigns.method()`, `db.sessions.method()`, etc.

- [ ] **Step 2: Remove delegation methods from Database class**

Once all callers are migrated, remove the backward-compat delegation methods from `connection.py`.

- [ ] **Step 3: Run full test suite**

```bash
pytest tests/ -v --tb=short
```

Expected: All tests pass.

- [ ] **Step 4: Run linter**

```bash
ruff check src/ tests/
ruff format src/ tests/
```

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: remove backward-compat delegation, all callers use repos directly"
```

---

### Task 8.2: Final verification

- [ ] **Step 1: Run full test suite**

```bash
pytest tests/ -v
```

Expected: Same ~307 tests pass, same 5 pre-existing failures.

- [ ] **Step 2: Run linter**

```bash
ruff check src/ tests/
```

- [ ] **Step 3: Manual smoke test**

Start the application and verify:
1. Web UI loads at `http://localhost:8000`
2. Campaign bar renders
3. Entity tabs work (players, NPCs, locations, entities, relationships)
4. Relationship graph renders (both 2D and 3D)
5. WebSocket connects (green badge)
6. Browse mode works
7. Session sidebar populates

- [ ] **Step 4: Verify no file exceeds 800 lines**

```bash
find src/rpg_scribe/ -name "*.py" -exec wc -l {} + | sort -rn | head -20
wc -l src/rpg_scribe/web/static/js/*.js src/rpg_scribe/web/static/js/relationships/*.js | sort -rn | head -20
wc -l src/rpg_scribe/web/static/css/*.css src/rpg_scribe/web/static/css/features/*.css | sort -rn | head -20
```

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "refactor: SOLID refactor complete — all files under 800 lines"
```
