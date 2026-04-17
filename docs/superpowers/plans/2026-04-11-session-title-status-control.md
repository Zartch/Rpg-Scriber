# Session Title & Status Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a live-view banner to System Status that lets users manually change a stuck session's status and edit/auto-generate a human-readable session title.

**Architecture:** Add `title` column via existing `_ensure_column` migration pattern; add `update_session_title` / `update_session_status` to `SessionRepository`; add `generate_title_from_summary` to `ClaudeSummarizer`; add 3 new REST endpoints + extend `/api/status`; add banner HTML/CSS and JS logic in the live view; show title in the session list.

**Tech Stack:** Python 3.10, aiosqlite, FastAPI, Anthropic SDK (already wired), vanilla ES-module JS.

---

## File Map

| File | Change |
|------|--------|
| `src/rpg_scribe/core/database/connection.py` | Add `_ensure_column("sessions", "title", ...)` call |
| `src/rpg_scribe/core/database/repositories/session_repo.py` | Add `update_session_title`, `update_session_status` |
| `src/rpg_scribe/summarizers/claude_summarizer.py` | Add `generate_title_from_summary` |
| `src/rpg_scribe/web/routers/status.py` | Extend `GET /api/status` → include `active_session_title` |
| `src/rpg_scribe/web/routers/sessions.py` | Add 3 endpoints, update `_format_session_list` |
| `src/rpg_scribe/web/static/index.html` | Add `#session-banner` inside `#status-panel` |
| `src/rpg_scribe/web/static/css/layout.css` | Add `.session-banner` styles |
| `src/rpg_scribe/web/static/js/main.js` | Banner show/hide, title edit, status change, auto-generate |
| `src/rpg_scribe/web/static/js/sessions.js` | Show `title` in session list items |
| `tests/test_database.py` | Tests for new repo methods |
| `tests/test_web.py` | Tests for new endpoints |

---

## Task 1: DB migration — add `title` column

**Files:**
- Modify: `src/rpg_scribe/core/database/connection.py:40-57`
- Test: `tests/test_database.py`

- [ ] **Step 1: Write the failing test**

Add to `class TestDatabaseSessions` in `tests/test_database.py`:

```python
async def test_session_has_title_column(self, db: Database) -> None:
    await db.campaigns.upsert_campaign(campaign_id="c1", name="Test")
    await db.sessions.create_session("s1", "c1")
    session = await db.sessions.get_session("s1")
    assert session is not None
    assert "title" in session
    assert session["title"] == ""
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_database.py::TestDatabaseSessions::test_session_has_title_column -v
```

Expected: FAIL — `KeyError: 'title'`

- [ ] **Step 3: Add the migration call**

In `src/rpg_scribe/core/database/connection.py`, inside `_run_schema_migrations`, add after the last `_ensure_column("sessions", ...)` line (line ~46):

```python
await self._ensure_column("sessions", "title", "TEXT NOT NULL DEFAULT ''")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_database.py::TestDatabaseSessions::test_session_has_title_column -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/rpg_scribe/core/database/connection.py tests/test_database.py
git commit -m "feat: add title column to sessions table"
```

---

## Task 2: Repository — `update_session_title` and `update_session_status`

**Files:**
- Modify: `src/rpg_scribe/core/database/repositories/session_repo.py`
- Test: `tests/test_database.py`

- [ ] **Step 1: Write the failing tests**

Add to `class TestDatabaseSessions` in `tests/test_database.py`:

```python
async def test_update_session_title(self, db: Database) -> None:
    await db.campaigns.upsert_campaign(campaign_id="c1", name="Test")
    await db.sessions.create_session("s1", "c1")
    result = await db.sessions.update_session_title("s1", "El dragón rojo")
    assert result is True
    session = await db.sessions.get_session("s1")
    assert session is not None
    assert session["title"] == "El dragón rojo"

async def test_update_session_title_not_found(self, db: Database) -> None:
    result = await db.sessions.update_session_title("nonexistent", "titulo")
    assert result is False

async def test_update_session_status_to_completed(self, db: Database) -> None:
    await db.campaigns.upsert_campaign(campaign_id="c1", name="Test")
    await db.sessions.create_session("s1", "c1")
    result = await db.sessions.update_session_status("s1", "completed")
    assert result is True
    session = await db.sessions.get_session("s1")
    assert session is not None
    assert session["status"] == "completed"

async def test_update_session_status_invalid_raises(self, db: Database) -> None:
    await db.campaigns.upsert_campaign(campaign_id="c1", name="Test")
    await db.sessions.create_session("s1", "c1")
    with pytest.raises(ValueError, match="status must be"):
        await db.sessions.update_session_status("s1", "paused")

async def test_update_session_status_not_found(self, db: Database) -> None:
    result = await db.sessions.update_session_status("nonexistent", "completed")
    assert result is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_database.py::TestDatabaseSessions::test_update_session_title tests/test_database.py::TestDatabaseSessions::test_update_session_title_not_found tests/test_database.py::TestDatabaseSessions::test_update_session_status_to_completed tests/test_database.py::TestDatabaseSessions::test_update_session_status_invalid_raises tests/test_database.py::TestDatabaseSessions::test_update_session_status_not_found -v
```

Expected: FAIL — `AttributeError: 'SessionRepository' object has no attribute 'update_session_title'`

- [ ] **Step 3: Implement the methods**

At the end of `SessionRepository` in `src/rpg_scribe/core/database/repositories/session_repo.py`, add:

```python
async def update_session_title(self, session_id: str, title: str) -> bool:
    """Update the session title. Returns True if a row was updated."""
    cursor = await self.conn.execute(
        "UPDATE sessions SET title = ? WHERE id = ?",
        (title, session_id),
    )
    await self.conn.commit()
    return cursor.rowcount > 0

async def update_session_status(self, session_id: str, status: str) -> bool:
    """Force-set session status. Returns True if a row was updated.

    Only 'active' and 'completed' are valid values.
    Raises ValueError for invalid status.
    """
    if status not in ("active", "completed"):
        raise ValueError(
            f"status must be 'active' or 'completed', got {status!r}"
        )
    cursor = await self.conn.execute(
        "UPDATE sessions SET status = ? WHERE id = ?",
        (status, session_id),
    )
    await self.conn.commit()
    return cursor.rowcount > 0
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_database.py::TestDatabaseSessions::test_update_session_title tests/test_database.py::TestDatabaseSessions::test_update_session_title_not_found tests/test_database.py::TestDatabaseSessions::test_update_session_status_to_completed tests/test_database.py::TestDatabaseSessions::test_update_session_status_invalid_raises tests/test_database.py::TestDatabaseSessions::test_update_session_status_not_found -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/rpg_scribe/core/database/repositories/session_repo.py tests/test_database.py
git commit -m "feat: add update_session_title and update_session_status to SessionRepository"
```

---

## Task 3: Summarizer — `generate_title_from_summary`

**Files:**
- Modify: `src/rpg_scribe/summarizers/claude_summarizer.py`

No unit test for this method — it calls a live LLM. Verification is done via the API endpoint in Task 5. The method is trivially thin (delegates to `_call_api`), so the test coverage comes from the endpoint test that mocks the summarizer.

- [ ] **Step 1: Add the method**

In `src/rpg_scribe/summarizers/claude_summarizer.py`, add after `_call_api` (after line ~347):

```python
async def generate_title_from_summary(self, summary: str) -> str:
    """Generate a short session title (≤60 chars) from an existing summary.

    Returns a generic fallback if the summary is empty or the LLM call fails.
    """
    import datetime

    if not summary or not summary.strip():
        today = datetime.date.today().strftime("%Y-%m-%d")
        return f"Sesión {today}"

    system = (
        "Eres un asistente que genera títulos cortos y descriptivos para sesiones de rol. "
        "El título debe tener máximo 60 caracteres. "
        "Responde ÚNICAMENTE con el título, sin comillas ni explicaciones."
    )
    user = f"Resumen de la sesión:\n\n{summary[:2000]}"
    try:
        title = await self._call_api(system, user, purpose="generate_title")
        title = title.strip().strip('"').strip("'")
        return title[:60] if title else f"Sesión {datetime.date.today():%Y-%m-%d}"
    except Exception:
        import datetime as _dt
        return f"Sesión {_dt.date.today():%Y-%m-%d}"
```

- [ ] **Step 2: Commit**

```bash
git add src/rpg_scribe/summarizers/claude_summarizer.py
git commit -m "feat: add generate_title_from_summary to ClaudeSummarizer"
```

---

## Task 4: Status endpoint — expose `active_session_title`

**Files:**
- Modify: `src/rpg_scribe/web/routers/status.py`
- Test: `tests/test_web.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_web.py`, add a new test class or extend existing status tests:

```python
class TestStatusEndpoint:
    async def test_status_includes_active_session_title_none(self, client) -> None:
        resp = await client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "active_session_title" in data
        assert data["active_session_title"] is None

    async def test_status_includes_active_session_title_from_db(
        self, client, app
    ) -> None:
        from rpg_scribe.web import routes as _routes
        from unittest.mock import AsyncMock

        state = _routes.router.state
        state.active_session_id = "sess-abc"

        db_mock = AsyncMock()
        db_mock.sessions.get_session = AsyncMock(
            return_value={"id": "sess-abc", "title": "El dragón rojo", "status": "active"}
        )
        _routes.router.database = db_mock

        try:
            resp = await client.get("/api/status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["active_session_title"] == "El dragón rojo"
        finally:
            state.active_session_id = None
            _routes.router.database = None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_web.py::TestStatusEndpoint -v
```

Expected: FAIL — `KeyError: 'active_session_title'`

- [ ] **Step 3: Implement**

In `src/rpg_scribe/web/routers/status.py`, replace the `get_status` function body:

```python
@router.get("/api/status")
async def get_status() -> dict[str, Any]:
    """Return current component statuses."""
    state = _get_state()
    config = _get_config()
    db = _get_database()

    active_session_title: str | None = None
    if state.active_session_id and db is not None:
        try:
            session = await db.sessions.get_session(state.active_session_id)
            if session:
                active_session_title = session.get("title") or ""
        except Exception:
            pass

    return {
        "components": state.component_status,
        "active_session_id": state.active_session_id,
        "active_session_title": active_session_title,
        "websocket_clients": _get_manager().active_count,
        "web_limits": {
            "transcriptions_buffer_max_items": state.max_transcriptions,
            "live_feed_max_items": getattr(config, "web_feed_max_items", 1000),
        },
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_web.py::TestStatusEndpoint -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/rpg_scribe/web/routers/status.py tests/test_web.py
git commit -m "feat: expose active_session_title in /api/status"
```

---

## Task 5: Session router — 3 new endpoints + title in session list

**Files:**
- Modify: `src/rpg_scribe/web/routers/sessions.py`
- Test: `tests/test_web.py`

- [ ] **Step 1: Update `_format_session_list` to include `title`**

In `src/rpg_scribe/web/routers/sessions.py`, in `_format_session_list` (around line 149), add `"title"` to the dict:

```python
result.append(
    {
        "id": s["id"],
        "campaign_id": s.get("campaign_id", ""),
        "title": s.get("title", "") or "",
        "started_at": started,
        "ended_at": ended,
        "duration_minutes": duration_minutes,
        "status": s.get("status", ""),
        "summary_preview": preview,
        "has_summary": bool(summary),
    }
)
```

- [ ] **Step 2: Write the failing tests for the new endpoints**

Add to `tests/test_web.py`:

```python
class TestSessionTitleStatusEndpoints:
    async def test_patch_title_no_db_returns_503(self, client) -> None:
        resp = await client.patch(
            "/api/sessions/s1/title", json={"title": "nuevo titulo"}
        )
        assert resp.status_code == 503

    async def test_patch_status_no_db_returns_503(self, client) -> None:
        resp = await client.patch(
            "/api/sessions/s1/status", json={"status": "completed"}
        )
        assert resp.status_code == 503

    async def test_patch_title_not_found_returns_404(self, client, app) -> None:
        from rpg_scribe.web import routes as _routes
        from unittest.mock import AsyncMock

        db_mock = AsyncMock()
        db_mock.sessions.update_session_title = AsyncMock(return_value=False)
        _routes.router.database = db_mock

        try:
            resp = await client.patch(
                "/api/sessions/missing/title", json={"title": "test"}
            )
            assert resp.status_code == 404
        finally:
            _routes.router.database = None

    async def test_patch_title_success(self, client, app) -> None:
        from rpg_scribe.web import routes as _routes
        from unittest.mock import AsyncMock

        db_mock = AsyncMock()
        db_mock.sessions.update_session_title = AsyncMock(return_value=True)
        _routes.router.database = db_mock

        try:
            resp = await client.patch(
                "/api/sessions/s1/title", json={"title": "El dragón rojo"}
            )
            assert resp.status_code == 200
            assert resp.json() == {"ok": True}
        finally:
            _routes.router.database = None

    async def test_patch_status_invalid_value_returns_422(self, client, app) -> None:
        from rpg_scribe.web import routes as _routes
        from unittest.mock import AsyncMock

        db_mock = AsyncMock()
        db_mock.sessions.update_session_status = AsyncMock(
            side_effect=ValueError("status must be 'active' or 'completed'")
        )
        _routes.router.database = db_mock

        try:
            resp = await client.patch(
                "/api/sessions/s1/status", json={"status": "paused"}
            )
            assert resp.status_code == 422
        finally:
            _routes.router.database = None

    async def test_patch_status_success(self, client, app) -> None:
        from rpg_scribe.web import routes as _routes
        from unittest.mock import AsyncMock

        db_mock = AsyncMock()
        db_mock.sessions.update_session_status = AsyncMock(return_value=True)
        _routes.router.database = db_mock

        try:
            resp = await client.patch(
                "/api/sessions/s1/status", json={"status": "completed"}
            )
            assert resp.status_code == 200
            assert resp.json() == {"ok": True}
        finally:
            _routes.router.database = None

    async def test_post_generate_title_no_db_returns_503(self, client) -> None:
        resp = await client.post("/api/sessions/s1/generate-title")
        assert resp.status_code == 503

    async def test_post_generate_title_not_found_returns_404(self, client, app) -> None:
        from rpg_scribe.web import routes as _routes
        from unittest.mock import AsyncMock

        db_mock = AsyncMock()
        db_mock.sessions.get_session = AsyncMock(return_value=None)
        _routes.router.database = db_mock

        try:
            resp = await client.post("/api/sessions/missing/generate-title")
            assert resp.status_code == 404
        finally:
            _routes.router.database = None
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest tests/test_web.py::TestSessionTitleStatusEndpoints -v
```

Expected: FAIL — 404 for all (routes don't exist yet)

- [ ] **Step 4: Add the three new endpoints**

In `src/rpg_scribe/web/routers/sessions.py`, add after the `update_session_chronology` endpoint (after line ~254):

```python
@router.patch("/api/sessions/{session_id}/title")
async def update_session_title(
    session_id: str, body: dict[str, str]
) -> dict[str, Any]:
    """Set or update the human-readable title of a session."""
    db = _get_database()
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")
    title = body.get("title", "")
    ok = await db.sessions.update_session_title(session_id, title)
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": True}


@router.patch("/api/sessions/{session_id}/status")
async def update_session_status(
    session_id: str, body: dict[str, str]
) -> dict[str, Any]:
    """Force-set the status of a session (active or completed).

    Useful for unsticking sessions left active after a crash.
    """
    db = _get_database()
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")
    status = body.get("status", "")
    try:
        ok = await db.sessions.update_session_status(session_id, status)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": True}


@router.post("/api/sessions/{session_id}/generate-title")
async def generate_session_title(session_id: str) -> dict[str, Any]:
    """Auto-generate and save a session title using the LLM (on demand)."""
    db = _get_database()
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")

    session = await db.sessions.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    summary = str(session.get("session_summary") or "")
    config = _get_config()

    from rpg_scribe.core.models import CampaignContext, SummarizerConfig
    from rpg_scribe.summarizers.claude_summarizer import ClaudeSummarizer
    from rpg_scribe.web.routers.campaigns import _load_campaign_context_from_db

    campaign = None
    campaign_id = session.get("campaign_id")
    if campaign_id:
        campaign = await _load_campaign_context_from_db(db, campaign_id)
    if campaign is None:
        campaign = CampaignContext.create_generic()

    summarizer_config = (
        config.summarizer
        if config is not None and getattr(config, "summarizer", None)
        else SummarizerConfig()
    )

    summarizer = ClaudeSummarizer(
        _get_event_bus(),
        summarizer_config,
        campaign,
        database=db,
    )

    title = await summarizer.generate_title_from_summary(summary)
    await db.sessions.update_session_title(session_id, title)
    return {"ok": True, "title": title}
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_web.py::TestSessionTitleStatusEndpoints -v
```

Expected: all PASS

- [ ] **Step 6: Run full test suite to check for regressions**

```bash
pytest tests/test_database.py tests/test_web.py -v
```

Expected: all pass (except the 4 pre-existing known failures listed in CLAUDE.md)

- [ ] **Step 7: Commit**

```bash
git add src/rpg_scribe/web/routers/sessions.py tests/test_web.py
git commit -m "feat: add PATCH title/status and POST generate-title endpoints"
```

---

## Task 6: Frontend HTML & CSS — session banner

**Files:**
- Modify: `src/rpg_scribe/web/static/index.html`
- Modify: `src/rpg_scribe/web/static/css/layout.css`

- [ ] **Step 1: Add the banner HTML to `index.html`**

Find `</section>` that closes `#status-panel` (the section containing `id="component-status"`). Add the banner **inside** the section, after the `.status-grid` div:

```html
<div id="session-banner" class="session-banner hidden">
  <span class="session-banner-live">LIVE</span>
  <span id="session-banner-id" class="session-banner-id"></span>
  <input id="session-banner-title" class="session-banner-title" type="text" placeholder="Sin título..." maxlength="60" />
  <button id="session-banner-autotitle" class="session-banner-autotitle" title="Autogenerar título">✨ Auto</button>
  <select id="session-banner-status" class="session-banner-status">
    <option value="active">active</option>
    <option value="completed">completed</option>
  </select>
  <button id="session-banner-apply" class="session-banner-apply">Aplicar</button>
</div>
```

- [ ] **Step 2: Add CSS to `layout.css`**

At the end of `src/rpg_scribe/web/static/css/layout.css`, append:

```css
/* ── Session banner (live view) ─────────────────────────────────── */
.session-banner {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
  margin-top: 0.6rem;
  padding: 0.5rem 0.75rem;
  background: #111827;
  border: 1px solid #1e3a5f;
  border-radius: 0.375rem;
  font-size: 0.8rem;
}
.session-banner.hidden { display: none; }
.session-banner-live {
  background: var(--green);
  color: #000;
  font-size: 0.6rem;
  font-weight: 700;
  padding: 0.1rem 0.4rem;
  border-radius: 9999px;
  text-transform: uppercase;
  flex-shrink: 0;
}
.session-banner-id {
  color: var(--text-muted);
  font-family: monospace;
  font-size: 0.7rem;
  flex-shrink: 0;
}
.session-banner-title {
  flex: 1;
  min-width: 130px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 0.25rem;
  color: var(--text);
  padding: 0.25rem 0.5rem;
  font-size: 0.75rem;
}
.session-banner-autotitle {
  background: #064e3b;
  border: 1px solid #065f46;
  color: #34d399;
  padding: 0.2rem 0.45rem;
  border-radius: 0.25rem;
  font-size: 0.7rem;
  cursor: pointer;
  white-space: nowrap;
  flex-shrink: 0;
}
.session-banner-autotitle:disabled { opacity: 0.5; cursor: not-allowed; }
.session-banner-status {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 0.25rem;
  color: var(--text);
  padding: 0.25rem 0.5rem;
  font-size: 0.75rem;
  flex-shrink: 0;
}
.session-banner-apply {
  background: #1d4ed8;
  border: none;
  color: #fff;
  padding: 0.25rem 0.5rem;
  border-radius: 0.25rem;
  font-size: 0.75rem;
  cursor: pointer;
  flex-shrink: 0;
}
.session-banner-apply:hover { background: #1e40af; }
```

- [ ] **Step 3: Verify visually**

Start the app (`rpg-scribe`) and open http://localhost:8000. The banner should be hidden (no session active). No JS errors in the browser console.

- [ ] **Step 4: Commit**

```bash
git add src/rpg_scribe/web/static/index.html src/rpg_scribe/web/static/css/layout.css
git commit -m "feat: add session banner HTML and CSS to System Status panel"
```

---

## Task 7: Frontend JS — banner logic in `main.js`

**Files:**
- Modify: `src/rpg_scribe/web/static/js/main.js`

- [ ] **Step 1: Add banner wiring at the end of `main.js`**

Append the following block after the `setMode("live")` call at the bottom of `src/rpg_scribe/web/static/js/main.js`:

```javascript
// ── Session banner ────────────────────────────────────────────────

(function initSessionBanner() {
  var bannerEl = document.getElementById("session-banner");
  var bannerIdEl = document.getElementById("session-banner-id");
  var titleInput = document.getElementById("session-banner-title");
  var autoTitleBtn = document.getElementById("session-banner-autotitle");
  var statusSelect = document.getElementById("session-banner-status");
  var applyBtn = document.getElementById("session-banner-apply");

  if (!bannerEl) return;

  function showBanner(sessionId, title, currentStatus) {
    bannerIdEl.textContent = sessionId;
    titleInput.value = title || "";
    statusSelect.value = currentStatus || "active";
    bannerEl.classList.remove("hidden");
    state.activeSessionId = sessionId;
  }

  function hideBanner() {
    bannerEl.classList.add("hidden");
  }

  // Fetch current status on page load to set banner initial state
  fetch("/api/status")
    .then(function (r) { return r.json(); })
    .then(function (data) {
      if (data.active_session_id) {
        showBanner(
          data.active_session_id,
          data.active_session_title || "",
          "active"
        );
      }
    })
    .catch(function () {});

  // Save title on blur or Enter
  function saveTitle() {
    var sessionId = bannerIdEl.textContent;
    if (!sessionId) return;
    fetch("/api/sessions/" + encodeURIComponent(sessionId) + "/title", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: titleInput.value }),
    }).catch(function () {});
  }

  titleInput.addEventListener("blur", saveTitle);
  titleInput.addEventListener("keydown", function (e) {
    if (e.key === "Enter") { saveTitle(); titleInput.blur(); }
  });

  // Auto-generate title
  autoTitleBtn.addEventListener("click", function () {
    var sessionId = bannerIdEl.textContent;
    if (!sessionId) return;
    autoTitleBtn.disabled = true;
    autoTitleBtn.textContent = "...";
    fetch("/api/sessions/" + encodeURIComponent(sessionId) + "/generate-title", {
      method: "POST",
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.title) { titleInput.value = data.title; }
      })
      .catch(function () {})
      .finally(function () {
        autoTitleBtn.disabled = false;
        autoTitleBtn.textContent = "✨ Auto";
      });
  });

  // Apply status change
  applyBtn.addEventListener("click", function () {
    var sessionId = bannerIdEl.textContent;
    if (!sessionId) return;
    applyBtn.disabled = true;
    fetch("/api/sessions/" + encodeURIComponent(sessionId) + "/status", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: statusSelect.value }),
    })
      .then(function (r) {
        if (!r.ok) { return r.json().then(function (d) { alert("Error: " + (d.detail || r.status)); }); }
        // Refresh the session list to reflect the status change
        fetchSessionList();
      })
      .catch(function () { alert("Error al aplicar el estado."); })
      .finally(function () { applyBtn.disabled = false; });
  });

})();
```

- [ ] **Step 2: Verify manually**

Start the app. In the live view:
1. With no active session: banner is hidden, no JS errors.
2. Start a session via Discord bot or start command. Verify the banner appears on next page load (fetches from `/api/status`).
3. Type a title and press Enter. Reload — verify title persists.
4. Click ✨ Auto (with a session that has a summary). Verify a title appears.
5. Change the status dropdown to `completed` and click Aplicar. Verify the session list updates.

- [ ] **Step 3: Commit**

```bash
git add src/rpg_scribe/web/static/js/main.js
git commit -m "feat: wire session banner in live view (title edit, status change, auto-generate)"
```

---

## Task 8: Sessions list — show title

**Files:**
- Modify: `src/rpg_scribe/web/static/js/sessions.js`

- [ ] **Step 1: Update `renderSessionList` to show the title**

In `src/rpg_scribe/web/static/js/sessions.js`, in the `renderSessionList` function (around line 334), replace the `item.innerHTML` assignment:

Current (the `session-header` block):
```javascript
item.innerHTML =
  '<div class="session-header">' +
  '<span class="session-id">' + escapeHtml(s.id.substring(0, 8)) + "</span>" +
  '<div class="session-header-right">' +
  indicators +
  '<span class="session-badge ' + (isActive ? 'live' : s.status) + '">' +
  escapeHtml(label) + '</span>' +
  '</div>' +
  '</div>' +
  metaLine +
  (preview ? '<div class="session-preview">' + escapeHtml(preview) + '</div>' : "");
```

Replace with:

```javascript
var titleLine = s.title
  ? '<div class="session-title">' + escapeHtml(s.title) + '</div>'
  : '<div class="session-title session-title-empty">Sin título</div>';

item.innerHTML =
  '<div class="session-header">' +
  '<span class="session-id">' + escapeHtml(s.id.substring(0, 8)) + "</span>" +
  '<div class="session-header-right">' +
  indicators +
  '<span class="session-badge ' + (isActive ? 'live' : s.status) + '">' +
  escapeHtml(label) + '</span>' +
  '</div>' +
  '</div>' +
  titleLine +
  metaLine +
  (preview ? '<div class="session-preview">' + escapeHtml(preview) + '</div>' : "");
```

- [ ] **Step 2: Add CSS for the title line**

In `src/rpg_scribe/web/static/css/layout.css`, append after the session banner styles added in Task 6:

```css
/* ── Session list title ──────────────────────────────────────────── */
.session-title {
  font-size: 0.8rem;
  color: var(--text);
  margin-top: 0.15rem;
}
.session-title-empty {
  color: var(--text-muted);
  font-style: italic;
}
```

- [ ] **Step 3: Verify manually**

Open the sessions list. Sessions with a title show it below the ID/badge row. Sessions without a title show "Sin título" in muted italic.

- [ ] **Step 4: Commit**

```bash
git add src/rpg_scribe/web/static/js/sessions.js src/rpg_scribe/web/static/css/layout.css
git commit -m "feat: show session title in sessions list"
```

---

## Final Verification

- [ ] Run the full test suite: `pytest` — only the 4 pre-existing failures listed in CLAUDE.md should fail.
- [ ] Run linter: `ruff check src/ tests/`
- [ ] End-to-end: start the app with a real session, confirm all 5 banner interactions work (see Task 7 Step 2).
