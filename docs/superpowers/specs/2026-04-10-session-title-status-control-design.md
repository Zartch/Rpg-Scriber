# Session Title & Status Control — Design Spec

**Date:** 2026-04-10  
**Branch:** refactor_solid

---

## Problem

Sessions can get stuck in `active` status (e.g. Discord bot crashes, network drop, unexpected shutdown). The merge endpoint rejects active sessions, so stuck sessions block all merge operations. There's also no human-readable name for sessions — they're identified only by a 12-char hex ID.

## Goal

1. Allow manually changing a session's status from the live view's System Status panel.
2. Allow naming sessions with a freetext title (editable inline).
3. Allow auto-generating the title from the session summary on demand.
4. Show the title in the sessions history list.

---

## Architecture

### 1. Database — migration

Add `title TEXT NOT NULL DEFAULT ''` column to the `sessions` table via the existing migration pattern in `connection.py` (`ALTER TABLE sessions ADD COLUMN ...` wrapped in a try/except for already-exists).

**File:** `src/rpg_scribe/core/database/connection.py`

### 2. Repository — new methods

Add two methods to `SessionRepository`:

```python
async def update_session_title(self, session_id: str, title: str) -> None
async def update_session_status(self, session_id: str, status: str) -> None
```

`update_session_status` validates that `status` is one of `{"active", "completed"}` before writing.

**File:** `src/rpg_scribe/core/database/repositories/session_repo.py`

### 3. Service — generate_title

Add `generate_title(session_id: str) -> str` to `SessionService`. It reads the session summary from the DB, calls the LLM (same Claude client used for `generate_session_summary`), and returns a short title (≤60 chars). It also persists the title via `update_session_title`.

**File:** `src/rpg_scribe/services/session_service.py`

### 4. API — three new endpoints

Following the existing pattern (`PUT /summary`, `PUT /chronology`, `POST /generate-summary`):

| Method | Path | Body | Action |
|--------|------|------|--------|
| `PATCH` | `/api/sessions/{id}/title` | `{"title": str}` | Save freetext title |
| `PATCH` | `/api/sessions/{id}/status` | `{"status": str}` | Force-set status (`active`\|`completed`) |
| `POST` | `/api/sessions/{id}/generate-title` | — | LLM-generate and save title, return `{"title": str}` |

**File:** `src/rpg_scribe/web/routers/sessions.py`

Return `{"ok": true}` on success, 404 if session not found, 422 if invalid status value.

### 5. Frontend — live view banner

**`index.html`** — Inside `#status-panel`, below the `.status-grid`, add a `<div id="session-banner">` (hidden by default):

```html
<div id="session-banner" class="session-banner hidden">
  <span class="session-banner-live">LIVE</span>
  <span id="session-banner-id" class="session-banner-id"></span>
  <input id="session-banner-title" type="text" placeholder="Sin título..." />
  <button id="session-banner-autotitle">✨ Auto</button>
  <select id="session-banner-status">
    <option value="active">active</option>
    <option value="completed">completed</option>
  </select>
  <button id="session-banner-apply">Aplicar</button>
</div>
```

**`status.py`** — Extend `GET /api/status` to also return `active_session_title: str | None` by querying the DB when `active_session_id` is set. This avoids adding a new single-session GET endpoint.

**`main.js`** — New logic:
- On page load, call `GET /api/status` (returns `active_session_id` + `active_session_title`). If a session is active, show the banner and populate ID and title.
- On WebSocket `session_start`/`session_end` events, show/hide the banner accordingly.
- Title input: on `blur` or Enter, call `PATCH /api/sessions/{id}/title`.
- Auto button: call `POST /api/sessions/{id}/generate-title`, then populate the input with the returned title and show a brief loading state.
- Apply button: call `PATCH /api/sessions/{id}/status` with the dropdown value, then refresh the session list.

**`css/layout.css`** — Add `.session-banner` styles matching the mockup: dark blue-tinted background, monospace ID, compact input/select/button row.

### 6. Frontend — sessions list

**`sessions.js`** — `renderSessionList` already reads `s.status`. Extend it to also show `s.title` (falling back to `"Sin título"` in muted italic when empty).

The title is returned by the existing `GET /api/sessions` and `GET /api/campaigns/{id}/sessions` endpoints — just add `title` to the rows returned by `list_sessions` in the repository (it will come from the DB column automatically via `SELECT *`).

---

## Data Flow

```
User edits title input → blur/Enter
  → PATCH /api/sessions/{id}/title
  → session_repo.update_session_title()

User clicks ✨ Auto
  → POST /api/sessions/{id}/generate-title
  → session_service.generate_title()
    → reads summary from DB
    → LLM call (short title prompt)
    → session_repo.update_session_title()
  → response: {"title": "..."}
  → populate input

User changes status dropdown → Aplicar
  → PATCH /api/sessions/{id}/status
  → session_repo.update_session_status()
  → frontend refreshes session list
```

---

## Error Handling

- Invalid status value → 422 with message `"status must be 'active' or 'completed'"`
- Session not found → 404
- LLM call failure in `generate-title` → 500, input stays unchanged
- Empty summary when generating title → return a generic fallback: `"Sesión {date}"`

---

## Verification

1. **Manual:** Start the app, open the live view. Confirm the banner is hidden when no session is active. Start a session via Discord bot. Confirm banner appears with the session ID and `active` status.
2. **Title edit:** Type a title in the input, press Enter. Reload the page — confirm the title persists. Check the sessions list shows the title.
3. **Auto-generate:** With a session that has a summary, click ✨ Auto. Confirm a title appears.
4. **Status change:** Set dropdown to `completed`, click Aplicar. Confirm the banner reflects the change and the merge endpoint no longer rejects the session.
5. **Tests:** `pytest -k session` — confirm existing session tests still pass. Add unit tests for `update_session_status` (invalid value raises), `update_session_title`, and the three new router endpoints.
