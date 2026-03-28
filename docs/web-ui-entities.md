# Web UI — Entity Panels

High-level overview of how the entity management panels work in the RPG Scribe Web UI.

## Architecture

All entity types (Players, NPCs, Locations, Entities, Relationships) live inside a **single collapsible section** called "Campaign Details" (`#campaign-details-section`). The section is:

- **Hidden** when no campaign is loaded or in generic/resume mode
- **Collapsed by default** when visible — clicking the header expands it
- **Tabbed internally** — five tabs switch between entity types

### HTML Structure

```
#campaign-details-section (collapsible panel)
  ├── #campaign-details-header (click to expand/collapse)
  ├── #campaign-details-body
  │   ├── .campaign-details-tabs (tab buttons)
  │   ├── #players-tab.detail-tab-content
  │   ├── #npcs-tab.detail-tab-content
  │   ├── #locations-tab.detail-tab-content
  │   ├── #entities-tab.detail-tab-content
  │   └── #relationships-tab.detail-tab-content
```

The Word Replacements section (`#replacements-section`) remains as a separate collapsible panel outside the tabs.

## CRUD Flow

All entity CRUD follows the same pattern:

1. **Display mode** — Entity card shows name + description + "Edit" button
2. **Edit mode** — Click "Edit" toggles a hidden `<form>` with inputs
3. **Save** — Form submit sends `fetch()` to REST API (PUT/POST)
4. **Refresh** — On success, `fetchCampaignInfo()` re-renders all panels from API data
5. **WebSocket** — In live mode, `entities_updated` events also trigger re-renders

### Entity-specific patterns

| Entity | Create | Edit | Merge | API base |
|--------|--------|------|-------|----------|
| Players | N/A (from TOML/Discord) | PUT `/api/campaigns/{id}/players/{pid}` | No | `routes.py` |
| NPCs | POST `.../npcs` | PUT `.../npcs/{nid}` | POST `.../npcs/merge` | `routes.py` |
| Locations | POST `.../locations` | PUT `.../locations/{lid}` | POST `.../locations/merge` | `routes.py` |
| Entities | POST `.../entities` | PUT `.../entities/{eid}` | POST `.../entities/merge` | `routes.py` |
| Relationships | POST `.../relationships` | PUT `.../relationships` | N/A | `routes.py` |

## Edit Mode vs Browse Mode

Both **live** and **browse** modes allow full entity editing. The distinction:

- **Live mode**: WebSocket connected, real-time updates from transcription/summarization
- **Browse mode**: No active session, navigate campaigns from the database

Editing requires only a valid `activeCampaignId`. The backend validates the campaign exists (in memory or DB via `_validate_campaign()`), and lazily loads the campaign into memory if needed.

## Merge Functionality

NPCs, Locations, and Entities support merging:

1. Click "Edit" on an entity to see the merge controls
2. **Merge into** — search dropdown to pick a target entity
3. Click "Merge" — POST to merge endpoint
4. Source entity becomes a child of the target, visible in "Merged children" editor
5. Merged children can be renamed, re-parented, or unmerged

### Session Merge

Sessions can also be merged from the session sidebar:

1. Click "Merge" button to enter merge mode
2. Select 2 sessions (highlighted in yellow)
3. Confirm — transcriptions and summaries are combined into the earlier session

## Tab System

The tab switching reuses the `.summary-tab` CSS pattern (also used for session summary tabs). Tabs are initialized via `initCampaignDetailsTabs()` which binds click handlers to `[data-detail-tab]` buttons, toggling `.detail-tab-content.active` visibility.

### Key JavaScript functions

| Function | Purpose |
|----------|---------|
| `fetchCampaignInfo()` | Load campaign data from API, render all entity tabs |
| `renderPlayers(players)` | Populate players tab |
| `renderNpcs(npcs)` | Populate NPCs tab with edit/merge forms |
| `renderLocations(locations)` | Populate locations tab |
| `renderEntities(entities)` | Populate entities tab |
| `renderRelationships(rels, campaign)` | Populate relationships tab + graph |
| `selectBrowseCampaign(id)` | Load a campaign in browse mode |

## Files

- **HTML**: `src/rpg_scribe/web/static/index.html` — panel structure
- **JavaScript**: `src/rpg_scribe/web/static/app.js` — all rendering, event handling, tab logic
- **CSS**: `src/rpg_scribe/web/static/style.css` — entity card styles, tab styles
- **Backend**: `src/rpg_scribe/web/routes.py` — REST API endpoints
- **Database**: `src/rpg_scribe/core/database.py` — async SQLite CRUD
