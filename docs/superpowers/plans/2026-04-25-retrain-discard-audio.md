# Retrain & Discard Audio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Añadir botón ✎ en el feed de transcripciones para corrección inline que copia el audio al folder de reentrenamiento, y mejorar el botón × para mover el audio a discard antes de eliminar.

**Architecture:** Nuevo router `audio.py` con dos endpoints POST (`/retrain`, `/discard`) que hacen operaciones de filesystem puras. El endpoint `DELETE /api/transcriptions/{id}` existente se amplía para llamar a la lógica de discard antes de borrar. El frontend gestiona la edición inline con un `<textarea>` y llama a los nuevos endpoints.

**Tech Stack:** Python 3.10, FastAPI, aiosqlite, Vanilla JS (ES modules), pytest + httpx AsyncClient

---

## File Map

| Acción | Archivo |
|---|---|
| Modify | `src/rpg_scribe/core/database/repositories/transcription_repo.py` |
| Create | `src/rpg_scribe/web/routers/audio.py` |
| Modify | `src/rpg_scribe/web/app.py` |
| Modify | `src/rpg_scribe/web/routers/transcriptions.py` |
| Modify | `src/rpg_scribe/web/static/js/transcription.js` |
| Modify | `tests/test_database.py` |
| Create | `tests/test_audio_router.py` |
| Modify | `tests/test_web.py` |

---

## Task 1: Add `get_transcription_by_id` to TranscriptionRepository

El endpoint DELETE necesita obtener `session_id`, `timestamp` y `speaker_name` antes de borrar la fila, para construir el filename del audio.

**Files:**
- Modify: `src/rpg_scribe/core/database/repositories/transcription_repo.py`
- Test: `tests/test_database.py`

- [ ] **Step 1: Write the failing test**

Añadir al final de `tests/test_database.py`, dentro de la clase `TestDatabaseTranscriptions` existente (o crear la clase si no existe):

```python
class TestDatabaseTranscriptions:
    async def test_get_transcription_by_id_returns_row(self, db) -> None:
        row_id = await db.transcriptions.save_transcription(
            session_id="s1",
            speaker_id="spk1",
            speaker_name="Ana",
            text="Hola",
            timestamp=1700000000.0,
            confidence=0.9,
        )
        result = await db.transcriptions.get_transcription_by_id(row_id)
        assert result is not None
        assert result["speaker_name"] == "Ana"
        assert result["session_id"] == "s1"
        assert result["timestamp"] == 1700000000.0

    async def test_get_transcription_by_id_returns_none_if_missing(self, db) -> None:
        result = await db.transcriptions.get_transcription_by_id(99999)
        assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_database.py::TestDatabaseTranscriptions -v
```

Expected: `AttributeError: 'TranscriptionRepository' object has no attribute 'get_transcription_by_id'`

- [ ] **Step 3: Implement the method**

En `src/rpg_scribe/core/database/repositories/transcription_repo.py`, añadir después de `delete_transcription`:

```python
async def get_transcription_by_id(self, transcription_id: int) -> dict[str, Any] | None:
    """Get a single transcription by ID. Returns None if not found."""
    cursor = await self.conn.execute(
        "SELECT * FROM transcriptions WHERE id = ?",
        (transcription_id,),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_database.py::TestDatabaseTranscriptions -v
```

Expected: ambos tests en PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rpg_scribe/core/database/repositories/transcription_repo.py tests/test_database.py
git commit -m "feat: add get_transcription_by_id to TranscriptionRepository"
```

---

## Task 2: Create `audio.py` router with retrain + discard endpoints

Router puro de filesystem: no accede a la DB ni al estado de la app.

**Files:**
- Create: `src/rpg_scribe/web/routers/audio.py`
- Create: `tests/test_audio_router.py`

- [ ] **Step 1: Write the failing tests**

Crear `tests/test_audio_router.py`:

```python
"""Tests for the audio retrain/discard endpoints."""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import rpg_scribe.web.routers.audio as audio_module
from rpg_scribe.web.routers.audio import router


@pytest.fixture
def audio_app():
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
async def client(audio_app):
    transport = ASGITransport(app=audio_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestRetrainEndpoint:
    async def test_copies_wav_and_creates_json(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(audio_module, "_audio_base", lambda: tmp_path)
        src = tmp_path / "sess1" / "1234.56_Ana.wav"
        src.parent.mkdir(parents=True)
        src.write_bytes(b"RIFF")

        resp = await client.post(
            "/api/audio/sess1/1234.56_Ana.wav/retrain",
            json={
                "original": "hola mundo",
                "corrected": "hola mundo!",
                "speaker": "Ana",
                "timestamp": 1234.56,
            },
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        assert (tmp_path / "retrain" / "sess1" / "1234.56_Ana.wav").read_bytes() == b"RIFF"
        meta = json.loads(
            (tmp_path / "retrain" / "sess1" / "1234.56_Ana.json").read_text(encoding="utf-8")
        )
        assert meta["original"] == "hola mundo"
        assert meta["corrected"] == "hola mundo!"
        assert meta["speaker"] == "Ana"
        assert meta["timestamp"] == 1234.56

    async def test_source_wav_remains_after_retrain(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(audio_module, "_audio_base", lambda: tmp_path)
        src = tmp_path / "sess1" / "1234.56_Ana.wav"
        src.parent.mkdir(parents=True)
        src.write_bytes(b"RIFF")

        await client.post(
            "/api/audio/sess1/1234.56_Ana.wav/retrain",
            json={"original": "x", "corrected": "y", "speaker": "Ana", "timestamp": 1234.56},
        )
        assert src.exists()  # copy, not move

    async def test_returns_404_if_wav_missing(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(audio_module, "_audio_base", lambda: tmp_path)
        resp = await client.post(
            "/api/audio/sess1/missing.wav/retrain",
            json={"original": "", "corrected": "", "speaker": "", "timestamp": 0},
        )
        assert resp.status_code == 404


class TestDiscardEndpoint:
    async def test_moves_wav_to_discard(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(audio_module, "_audio_base", lambda: tmp_path)
        src = tmp_path / "sess1" / "1234.56_Ana.wav"
        src.parent.mkdir(parents=True)
        src.write_bytes(b"RIFF")

        resp = await client.post("/api/audio/sess1/1234.56_Ana.wav/discard")
        assert resp.status_code == 200
        assert not src.exists()
        assert (tmp_path / "discard" / "sess1" / "1234.56_Ana.wav").read_bytes() == b"RIFF"

    async def test_idempotent_if_wav_missing(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(audio_module, "_audio_base", lambda: tmp_path)
        resp = await client.post("/api/audio/sess1/nonexistent.wav/discard")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_audio_router.py -v
```

Expected: `ModuleNotFoundError` o `ImportError` porque el módulo no existe.

- [ ] **Step 3: Implement the router**

Crear `src/rpg_scribe/web/routers/audio.py`:

```python
"""Audio chunk retrain/discard endpoints."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


def _audio_base() -> Path:
    return Path.cwd() / "data" / "audio"


async def _move_audio_to_discard(session_id: str, filename: str) -> None:
    """Move audio file to discard folder. Silently skips if file not found."""
    base = _audio_base()
    src = base / session_id / filename
    if not src.exists():
        return
    dest_dir = base / "discard" / session_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), dest_dir / filename)


@router.post("/api/audio/{session_id}/{filename}/retrain")
async def mark_retrain(
    session_id: str, filename: str, body: dict[str, Any]
) -> dict[str, Any]:
    base = _audio_base()
    src = base / session_id / filename
    if not src.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")

    dest_dir = base / "retrain" / session_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest_dir / filename)

    stem = Path(filename).stem
    (dest_dir / f"{stem}.json").write_text(
        json.dumps(
            {
                "original": body.get("original", ""),
                "corrected": body.get("corrected", ""),
                "speaker": body.get("speaker", ""),
                "timestamp": body.get("timestamp", 0),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return {"ok": True}


@router.post("/api/audio/{session_id}/{filename}/discard")
async def mark_discard(session_id: str, filename: str) -> dict[str, Any]:
    await _move_audio_to_discard(session_id, filename)
    return {"ok": True}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_audio_router.py -v
```

Expected: todos en PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rpg_scribe/web/routers/audio.py tests/test_audio_router.py
git commit -m "feat: add audio retrain/discard endpoints"
```

---

## Task 3: Register audio router + enhance DELETE endpoint

**Files:**
- Modify: `src/rpg_scribe/web/app.py`
- Modify: `src/rpg_scribe/web/routers/transcriptions.py`
- Test: `tests/test_web.py`

- [ ] **Step 1: Write the failing test for enhanced DELETE**

Añadir al final de `tests/test_web.py`, en la clase existente de transcripciones (o al final del archivo como clase nueva):

```python
class TestDeleteTranscriptionDiscard:
    async def test_delete_moves_audio_to_discard(
        self, event_bus: EventBus, tmp_path, monkeypatch
    ) -> None:
        import rpg_scribe.web.routers.audio as audio_module
        monkeypatch.setattr(audio_module, "_audio_base", lambda: tmp_path)

        # Create a fake wav file
        wav = tmp_path / "sess-del" / "1700000000.0_Ana.wav"
        wav.parent.mkdir(parents=True)
        wav.write_bytes(b"RIFF")

        db = AsyncMock()
        db.transcriptions.get_transcription_by_id = AsyncMock(return_value={
            "id": 1,
            "session_id": "sess-del",
            "speaker_id": "spk1",
            "speaker_name": "Ana",
            "text": "Hola",
            "timestamp": 1700000000.0,
            "confidence": 0.9,
            "is_ingame": True,
        })
        db.transcriptions.delete_transcription = AsyncMock(return_value=True)

        app = create_app(event_bus, database=db)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.delete("/api/transcriptions/1")

        assert resp.status_code == 200
        assert not wav.exists()
        assert (tmp_path / "discard" / "sess-del" / "1700000000.0_Ana.wav").exists()

    async def test_delete_succeeds_even_if_wav_missing(
        self, event_bus: EventBus, tmp_path, monkeypatch
    ) -> None:
        import rpg_scribe.web.routers.audio as audio_module
        monkeypatch.setattr(audio_module, "_audio_base", lambda: tmp_path)

        db = AsyncMock()
        db.transcriptions.get_transcription_by_id = AsyncMock(return_value={
            "id": 2,
            "session_id": "sess-del",
            "speaker_id": "spk1",
            "speaker_name": "Ana",
            "text": "Hola",
            "timestamp": 1700000001.0,
            "confidence": 0.9,
            "is_ingame": True,
        })
        db.transcriptions.delete_transcription = AsyncMock(return_value=True)

        app = create_app(event_bus, database=db)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.delete("/api/transcriptions/2")

        assert resp.status_code == 200  # no error even though wav doesn't exist
```

- [ ] **Step 2: Run the new tests to verify they fail**

```bash
pytest tests/test_web.py::TestDeleteTranscriptionDiscard -v
```

Expected: FAIL — el DELETE actual no llama a `get_transcription_by_id` ni mueve el audio.

- [ ] **Step 3: Register audio router in `app.py`**

En `src/rpg_scribe/web/app.py`, localizar el bloque de imports de routers (línea ~176) y añadir:

```python
    from rpg_scribe.web.routers import (
        campaigns as campaigns_router,
        sessions as sessions_router,
        entities as entities_router,
        transcriptions as transcriptions_router,
        tts as tts_router,
        status as status_router,
        audio as audio_router,          # ← añadir
    )
    app.include_router(campaigns_router.router)
    app.include_router(sessions_router.router)
    app.include_router(entities_router.router)
    app.include_router(transcriptions_router.router)
    app.include_router(tts_router.router)
    app.include_router(status_router.router)
    app.include_router(audio_router.router)   # ← añadir
```

- [ ] **Step 4: Enhance `delete_transcription` in `transcriptions.py`**

Añadir el import al inicio del archivo, junto a los otros imports de la stdlib:

```python
import re
```

Reemplazar la función `delete_transcription` completa (líneas 114-129):

```python
@router.delete("/api/transcriptions/{transcription_id}")
async def delete_transcription(transcription_id: int) -> dict[str, Any]:
    """Delete a transcription by ID, moving its audio to the discard folder."""
    db = _get_database()
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")

    row = await db.transcriptions.get_transcription_by_id(transcription_id)

    ok = await db.transcriptions.delete_transcription(transcription_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Transcription not found")

    if row:
        from rpg_scribe.web.routers.audio import _move_audio_to_discard
        speaker_san = re.sub(r"\W", "_", row.get("speaker_name") or "")[:30]
        filename = f"{row['timestamp']}_{speaker_san}.wav"
        await _move_audio_to_discard(row["session_id"], filename)

    state = _get_state()
    state.transcriptions = [
        t for t in state.transcriptions if t.get("id") != transcription_id
    ]
    return {"ok": True, "id": transcription_id}
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
pytest tests/test_web.py::TestDeleteTranscriptionDiscard -v
```

Expected: ambos en PASS.

- [ ] **Step 6: Run the full suite to check regressions**

```bash
pytest tests/test_web.py tests/test_audio_router.py tests/test_database.py -v
```

Expected: sin fallos nuevos (sólo los pre-existentes conocidos).

- [ ] **Step 7: Commit**

```bash
git add src/rpg_scribe/web/app.py src/rpg_scribe/web/routers/transcriptions.py tests/test_web.py
git commit -m "feat: register audio router and move audio to discard on delete"
```

---

## Task 4: Frontend — botón ✎ con edición inline (retrain)

Sin tests automatizados — verificar manualmente en el browser.

**Files:**
- Modify: `src/rpg_scribe/web/static/js/transcription.js`

- [ ] **Step 1: Añadir botón ✎ al HTML de cada entrada**

En `addTranscription`, localizar la línea que construye `entry.innerHTML` (línea ~34). Añadir el botón `btn-retrain` entre el play y el timestamp:

```javascript
  entry.innerHTML =
    '<span class="entry-actions">' +
      '<button class="btn-meta" title="Marcar como META">M</button>' +
      '<button class="btn-delete" title="Eliminar">\u00d7</button>' +
    '</span>' +
    '<span class="meta-badge">[META]</span>' +
    '<span class="speaker">' + escapeHtml(data.speaker_name) + ":</span>" +
    '<span class="transcription-text">' + wordHtml + "</span>" +
    '<button class="btn-play" title="Reproducir audio" data-audio-url="' + escapeHtml(audioUrl) + '">\u25B6</button>' +
    '<button class="btn-retrain" title="Corregir transcripci\u00f3n">\u270E</button>' +
    '<span class="ts">' + formatTime(data.timestamp) + "</span>";
```

- [ ] **Step 2: Añadir listener para btn-retrain en `initTranscriptionListeners`**

Añadir al final de `initTranscriptionListeners`, antes del cierre de la función (antes de `}`):

```javascript
  // ── Retrain inline edit ──────────────────────────────────────
  transcriptionFeed.addEventListener("click", function (e) {
    var btn = e.target.closest(".btn-retrain");
    if (!btn) return;
    var entry = btn.closest(".feed-entry");
    if (!entry) return;
    if (entry.querySelector(".retrain-textarea")) return; // already editing

    var textSpan = entry.querySelector(".transcription-text");
    var originalText = textSpan ? textSpan.textContent : "";

    var textarea = document.createElement("textarea");
    textarea.className = "retrain-textarea";
    textarea.value = originalText;
    textarea.rows = 2;

    var saveBtn = document.createElement("button");
    saveBtn.className = "btn-retrain-save";
    saveBtn.title = "Guardar corrección";
    saveBtn.textContent = "✓";

    var cancelBtn = document.createElement("button");
    cancelBtn.className = "btn-retrain-cancel";
    cancelBtn.title = "Cancelar";
    cancelBtn.textContent = "✗";

    if (textSpan) textSpan.replaceWith(textarea);
    btn.replaceWith(saveBtn);
    saveBtn.insertAdjacentElement("afterend", cancelBtn);
    textarea.focus();
    textarea.select();

    function doCancel() {
      var restoredSpan = document.createElement("span");
      restoredSpan.className = "transcription-text";
      restoredSpan.textContent = originalText;
      textarea.replaceWith(restoredSpan);
      saveBtn.replaceWith(btn);
      cancelBtn.remove();
    }

    function doSave() {
      var newText = textarea.value.trim();
      if (!newText || newText === originalText) { doCancel(); return; }

      var restoredSpan = document.createElement("span");
      restoredSpan.className = "transcription-text";
      restoredSpan.textContent = newText;
      textarea.replaceWith(restoredSpan);
      saveBtn.replaceWith(btn);
      cancelBtn.remove();

      var playBtn = entry.querySelector(".btn-play");
      var audioUrl = playBtn ? playBtn.dataset.audioUrl : "";
      var filename = audioUrl ? audioUrl.split("/").pop() : "";
      var sessionId = entry.dataset.sessionId;
      var speakerEl = entry.querySelector(".speaker");
      var speaker = speakerEl ? speakerEl.textContent.replace(/:$/, "").trim() : "";

      resolveTranscriptionId(entry).then(function (id) {
        var promises = [];
        if (id) {
          promises.push(fetch("/api/transcriptions/" + id, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text: newText }),
          }));
        }
        if (filename && sessionId) {
          promises.push(fetch(
            "/api/audio/" + encodeURIComponent(sessionId) +
              "/" + encodeURIComponent(filename) + "/retrain",
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                original: originalText,
                corrected: newText,
                speaker: speaker,
                timestamp: parseFloat(entry.dataset.timestamp) || 0,
              }),
            }
          ));
        }
        return Promise.all(promises);
      });
    }

    saveBtn.addEventListener("click", doSave);
    cancelBtn.addEventListener("click", doCancel);
    textarea.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); doSave(); }
      if (e.key === "Escape") { e.preventDefault(); doCancel(); }
    });
  });
```

- [ ] **Step 3: Verificar en el browser**

1. Iniciar el servidor: `rpg-scribe` o `python -m rpg_scribe`
2. Abrir el Live Transcription feed
3. Verificar que aparece `✎` al final de cada entrada (junto al ▶)
4. Click en `✎` → debe aparecer un textarea con el texto y los botones `✓` `✗`
5. Editar el texto y pulsar `✓` → el texto se actualiza en la entrada, aparece en `data/audio/retrain/{session_id}/`
6. Click en `✎` de nuevo → cancelar con `✗` → el texto vuelve al original
7. Pulsar Escape también debe cancelar; Enter (sin Shift) debe guardar

- [ ] **Step 4: Commit**

```bash
git add src/rpg_scribe/web/static/js/transcription.js
git commit -m "feat: add retrain inline edit button to transcription feed"
```

---

## Task 5: Frontend — botón × mueve audio a discard antes de eliminar

**Files:**
- Modify: `src/rpg_scribe/web/static/js/transcription.js`

- [ ] **Step 1: Modificar el listener `btn-delete`**

Localizar el listener `btn-delete` en `initTranscriptionListeners` (línea ~116). Reemplazar el bloque completo:

```javascript
  // ── Delete transcription ──────────────────────────────────────
  transcriptionFeed.addEventListener("click", function (e) {
    var btn = e.target.closest(".btn-delete");
    if (!btn) return;
    var entry = btn.closest(".feed-entry");
    if (!entry) return;
    if (!confirm("¿Eliminar esta transcripción?")) return;

    import("./utils.js").then(function (utils) {
      utils.withLoading(btn, function () {
        var playBtn = entry.querySelector(".btn-play");
        var audioUrl = playBtn ? playBtn.dataset.audioUrl : "";
        var filename = audioUrl ? audioUrl.split("/").pop() : "";
        var sessionId = entry.dataset.sessionId;

        var discardPromise = (filename && sessionId)
          ? fetch(
              "/api/audio/" + encodeURIComponent(sessionId) +
                "/" + encodeURIComponent(filename) + "/discard",
              { method: "POST" }
            ).catch(function () {})
          : Promise.resolve();

        return discardPromise.then(function () {
          return resolveTranscriptionId(entry).then(function (id) {
            if (!id) return Promise.reject(new Error("No transcription ID"));
            return fetch("/api/transcriptions/" + id, { method: "DELETE" })
              .then(function (r) {
                if (r.ok) entry.remove();
                else return Promise.reject(new Error("Delete failed"));
              });
          });
        });
      }, { loadingText: "Eliminando..." });
    });
  });
```

- [ ] **Step 2: Verificar en el browser**

1. Tener una sesión activa con entradas en el feed y archivos `.wav` en `data/audio/{session_id}/`
2. Click en `×` de una entrada → confirmar
3. La entrada desaparece del feed
4. Verificar que el `.wav` se ha movido a `data/audio/discard/{session_id}/` y ya no está en la carpeta original
5. Click en `×` de una entrada sin archivo de audio → debe eliminar sin error

- [ ] **Step 3: Commit**

```bash
git add src/rpg_scribe/web/static/js/transcription.js
git commit -m "feat: move audio to discard folder when deleting transcription"
```

---

## Verificación final

```bash
pytest tests/test_database.py tests/test_audio_router.py tests/test_web.py -v
```

Expected: todos los tests nuevos en PASS, sin regresiones nuevas respecto a los fallos pre-existentes conocidos.
