var payloadEl = document.getElementById("campaign-export-data");
var payload = payloadEl ? JSON.parse(payloadEl.textContent || "{}") : {};
var campaign = payload.campaign || {};
var sessions = payload.sessions || [];
var sessionPayloads = payload.session_payloads || {};

var state = {
  graphFilters: { players: true, npcs: true, locations: true, entities: true },
  activeSessionId: "",
  graphRenderer: null,
};

function normalizeEntityKey(key) {
  var raw = String(key || "").trim();
  if (!raw) return "";
  if (raw.indexOf("location:") === 0) return "loc:" + raw.slice("location:".length);
  if (raw.indexOf("entity:") === 0) return "ent:" + raw.slice("entity:".length);
  return raw;
}

function entityTypeFromKey(key) {
  key = normalizeEntityKey(key);
  if (!key) return "unknown";
  if (key.indexOf("player:") === 0) return "player";
  if (key.indexOf("npc:") === 0) return "npc";
  if (key.indexOf("loc:") === 0) return "location";
  if (key.indexOf("ent:") === 0) return "entity";
  return "unknown";
}

function buildRelationshipEntities(currentCampaign) {
  var entities = [];

  (currentCampaign.players || []).forEach(function (player) {
    entities.push({
      key: "player:" + (player.discord_id || ""),
      label:
        "Player: "
        + (player.character_name || player.discord_name || player.discord_id || "?"),
      kind: "player",
      description: player.character_description || "",
      entityType: "player",
    });
  });

  (currentCampaign.npcs || []).forEach(function (npc) {
    entities.push({
      key: "npc:" + (npc.name || ""),
      label: "NPC: " + (npc.name || "?"),
      kind: "npc",
      description: npc.description || "",
      entityType: "npc",
    });
  });

  (currentCampaign.locations || []).forEach(function (loc) {
    var name = locationName(loc);
    if (!name) return;
    entities.push({
      key: "loc:" + name,
      label: "Location: " + name,
      kind: "location",
      description: locationDescription(loc),
      entityType: "location",
    });
  });

  (currentCampaign.entities || []).forEach(function (item) {
    if (!item || !item.name) return;
    entities.push({
      key: "ent:" + item.name,
      label: "Entity (" + entityType(item) + "): " + item.name,
      kind: "entity",
      description: entityDescription(item),
      entityType: entityType(item),
    });
  });

  return entities.filter(function (item) {
    return !!item.key && !item.key.endsWith(":");
  });
}

function entityDetailsFromKey(currentCampaign, key) {
  var normalized = normalizeEntityKey(key);
  var entities = buildRelationshipEntities(currentCampaign);
  for (var i = 0; i < entities.length; i++) {
    if (normalizeEntityKey(entities[i].key) === normalized) return entities[i];
  }
  var kind = entityTypeFromKey(normalized);
  return { key: normalized, label: normalized, kind: kind, description: "", entityType: kind };
}

function relationTypeKey(rel) {
  return rel.type_key || rel.relation_type_key || rel.type_label || rel.relation_type_label || "unknown";
}

function relationTypeLabel(rel) {
  return rel.type_label || rel.relation_type_label || rel.type_key || rel.relation_type_key || "unknown";
}

function relationCategory(rel) {
  return rel.type_category || rel.relation_type_category || rel.category || "general";
}

function graphGroupIncluded(kind) {
  if (kind === "player") return !!state.graphFilters.players;
  if (kind === "npc") return !!state.graphFilters.npcs;
  if (kind === "location") return !!state.graphFilters.locations;
  if (kind === "entity") return !!state.graphFilters.entities;
  return true;
}

function buildRelationshipGraphData(relationships, currentCampaign) {
  var items = relationships || [];
  var entityMap = {};
  var visibleEntities = buildRelationshipEntities(currentCampaign || {}).filter(function (entity) {
    return graphGroupIncluded(entity.kind);
  });

  visibleEntities.forEach(function (entity) {
    entityMap[normalizeEntityKey(entity.key)] = entity;
  });

  var filteredItems = items.filter(function (rel) {
    var source = entityDetailsFromKey(currentCampaign || {}, rel.source_key || "");
    var target = entityDetailsFromKey(currentCampaign || {}, rel.target_key || "");
    return graphGroupIncluded(source.kind) && graphGroupIncluded(target.kind);
  });

  var nodeKeys = visibleEntities
    .map(function (entity) { return normalizeEntityKey(entity.key); })
    .filter(function (key, idx, arr) { return !!key && arr.indexOf(key) === idx; });

  filteredItems.forEach(function (rel) {
    var sourceKey = normalizeEntityKey(rel.source_key || "");
    var targetKey = normalizeEntityKey(rel.target_key || "");
    if (sourceKey && nodeKeys.indexOf(sourceKey) < 0) nodeKeys.push(sourceKey);
    if (targetKey && nodeKeys.indexOf(targetKey) < 0) nodeKeys.push(targetKey);
  });

  var nodes = nodeKeys.map(function (key) {
    var details = entityMap[key] || entityDetailsFromKey(currentCampaign || {}, key);
    var rawLabel = (details.label || details.key || key)
      .replace("Player: ", "")
      .replace("NPC: ", "")
      .replace("Location: ", "")
      .replace(/^Entity \([^)]+\): /, "");
    return {
      id: key,
      label: rawLabel,
      shortLabel: rawLabel.length > 18 ? rawLabel.slice(0, 16) + ".." : rawLabel,
      kind: details.kind || "unknown",
      description: details.description || "",
      entityType: details.entityType || details.kind || "unknown",
    };
  });

  var links = filteredItems.map(function (rel, idx) {
    return {
      id: [normalizeEntityKey(rel.source_key || ""), normalizeEntityKey(rel.target_key || ""), relationTypeKey(rel), idx].join("|"),
      source: normalizeEntityKey(rel.source_key || ""),
      target: normalizeEntityKey(rel.target_key || ""),
      typeKey: relationTypeKey(rel),
      typeLabel: relationTypeLabel(rel),
      category: relationCategory(rel),
    };
  }).filter(function (link) {
    return !!(link.source && link.target);
  });

  return { nodes: nodes, links: links };
}

function renderSimpleList(containerId, items, renderItem, emptyText) {
  var container = document.getElementById(containerId);
  if (!container) return;
  if (!items.length) {
    container.innerHTML = '<p class="placeholder">' + escapeHtml(emptyText) + "</p>";
    return;
  }
  container.innerHTML = items.map(renderItem).join("");
}

function getMasterDisplayName(currentCampaign) {
  var players = currentCampaign.players || [];
  var dmId = currentCampaign.dm_speaker_id || "";
  if (!dmId) return "";
  for (var i = 0; i < players.length; i++) {
    if (players[i].discord_id === dmId) {
      return "Master: " + (players[i].discord_name || players[i].character_name || dmId);
    }
  }
  return "Master: " + dmId;
}

function renderCampaignHeader() {
  var nameEl = document.getElementById("campaign-name");
  var systemEl = document.getElementById("campaign-system");
  var masterEl = document.getElementById("campaign-master");
  var exportDateEl = document.getElementById("campaign-export-date");

  if (nameEl) nameEl.textContent = campaign.name || campaign.id || "Unnamed Campaign";

  var metaParts = [];
  if (campaign.game_system) metaParts.push(campaign.game_system);
  if (campaign.language) metaParts.push(String(campaign.language).toUpperCase());
  if (systemEl) systemEl.textContent = metaParts.length ? "(" + metaParts.join(" · ") + ")" : "";
  if (masterEl) masterEl.textContent = getMasterDisplayName(campaign);
  if (exportDateEl) exportDateEl.textContent = payload.export_date ? "Export: " + payload.export_date : "";
}

function renderCampaignStats() {
  [
    ["stat-players", (campaign.players || []).length],
    ["stat-npcs", (campaign.npcs || []).length],
    ["stat-locations", (campaign.locations || []).length],
    ["stat-entities", (campaign.entities || []).length],
    ["stat-relationships", (campaign.relationships || []).length],
  ].forEach(function (entry) {
    var el = document.getElementById(entry[0]);
    if (el) el.textContent = String(entry[1]);
  });
}

function renderCampaignDetails() {
  renderSimpleList("players-list", campaign.players || [], function (player) {
    return '<div class="entity-card"><div class="entity-display"><div class="entity-info"><strong class="entity-name">'
      + escapeHtml(player.character_name || player.discord_name || player.discord_id || "?")
      + '</strong><span class="entity-meta">' + escapeHtml(player.discord_name || player.discord_id || "") + '</span></div><div class="entity-desc">'
      + escapeHtml(player.character_description || "") + "</div></div></div>";
  }, "No players loaded.");

  renderSimpleList("npcs-list", campaign.npcs || [], function (npc) {
    return '<div class="entity-card"><div class="entity-display"><div class="entity-info"><strong class="entity-name">'
      + escapeHtml(npc.name || "?") + '</strong></div><div class="entity-desc">'
      + escapeHtml(npc.description || "") + "</div></div></div>";
  }, "No NPCs loaded.");

  renderSimpleList("locations-list", campaign.locations || [], function (loc) {
    return '<div class="entity-card"><div class="entity-display"><div class="entity-info"><strong class="entity-name">'
      + escapeHtml(locationName(loc) || "?") + '</strong></div><div class="entity-desc">'
      + escapeHtml(locationDescription(loc) || "") + "</div></div></div>";
  }, "No locations loaded.");

  renderSimpleList("entities-list", campaign.entities || [], function (item) {
    return '<div class="entity-card"><div class="entity-display"><div class="entity-info"><strong class="entity-name">'
      + escapeHtml(item.name || "?") + '</strong><span class="entity-meta">'
      + escapeHtml(entityType(item) || "group") + '</span></div><div class="entity-desc">'
      + escapeHtml(entityDescription(item) || "") + "</div></div></div>";
  }, "No entities loaded.");

  renderSimpleList("relationships-list", campaign.relationships || [], function (rel) {
    var source = entityDetailsFromKey(campaign, rel.source_key || "");
    var target = entityDetailsFromKey(campaign, rel.target_key || "");
    var notes = rel.notes ? '<div class="related-rel-notes">' + escapeHtml(rel.notes) + "</div>" : "";
    return '<div class="entity-card"><div class="entity-display"><div class="entity-info"><strong class="entity-name">'
      + escapeHtml(source.label || rel.source_key || "?") + ' -> ' + escapeHtml(target.label || rel.target_key || "?")
      + '</strong><span class="entity-meta">' + escapeHtml(relationTypeLabel(rel)) + " [" + escapeHtml(relationCategory(rel)) + "]</span></div></div>"
      + notes + "</div>";
  }, "No relationships loaded.");
}

function renderSessionList() {
  var listEl = document.getElementById("session-list");
  var countEl = document.getElementById("sessions-count");
  if (countEl) countEl.textContent = String(sessions.length);
  if (!listEl) return;
  if (!sessions.length) {
    listEl.innerHTML = '<p class="placeholder">No sessions in this campaign.</p>';
    return;
  }

  listEl.innerHTML = "";
  sessions.forEach(function (session) {
    var item = document.createElement("button");
    item.type = "button";
    item.className = "session-item export-session-item";
    item.dataset.sessionId = session.id;
    var dateLabel = session.started_at ? formatDate(session.started_at) : "";
    var duration = session.duration_minutes ? formatDuration(session.duration_minutes) : "";
    item.innerHTML = '<div class="session-header"><span class="session-id">'
      + escapeHtml((session.id || "").slice(0, 8)) + '</span><span class="session-badge '
      + escapeHtml(session.status || "") + '">' + escapeHtml(session.status || "") + "</span></div>"
      + '<div class="session-title">' + escapeHtml(session.title || "Untitled session") + "</div>"
      + (dateLabel ? ('<div class="session-date">' + escapeHtml(dateLabel) + (duration ? ' <span class="session-duration">(' + escapeHtml(duration) + ")</span>" : "") + "</div>") : "")
      + (session.summary_preview ? ('<div class="session-preview">' + escapeHtml(session.summary_preview) + "</div>") : "");
    item.addEventListener("click", function () {
      selectSession(session.id);
    });
    listEl.appendChild(item);
  });
}

function renderSummaryContent(containerId, text, emptyText) {
  var container = document.getElementById(containerId);
  if (!container) return;
  if (!String(text || "").trim()) {
    container.innerHTML = '<p class="placeholder">' + escapeHtml(emptyText) + "</p>";
    return;
  }
  container.innerHTML = '<div class="editable-paragraph">' + escapeHtml(text) + "</div>";
}

function renderTranscriptRows(rows) {
  if (!rows.length) {
    return '<p class="placeholder">No transcriptions exported for this session.</p>';
  }
  return '<div class="transcript-table-wrap"><table><thead><tr><th>Timestamp</th><th>Speaker</th><th>Kind</th><th>Text</th><th>Confidence</th></tr></thead><tbody>'
    + rows.map(function (row) {
      return "<tr>"
        + '<td class="mono">' + escapeHtml(row.timestamp_label || "") + "</td>"
        + '<td><span class="speaker">' + escapeHtml(row.speaker_name || "Unknown") + "</span></td>"
        + '<td class="mono">' + escapeHtml(row.kind_label || "") + "</td>"
        + "<td>" + escapeHtml(row.text || "") + "</td>"
        + '<td class="mono">' + escapeHtml(String(row.confidence == null ? "" : row.confidence)) + "</td>"
        + "</tr>";
    }).join("") + "</tbody></table></div>";
}

function setSummaryPanel(name) {
  var panels = {
    narrative: document.getElementById("session-panel-narrative"),
    chronology: document.getElementById("session-panel-chronology"),
    transcript: document.getElementById("session-panel-transcript"),
    campaign: document.getElementById("session-panel-campaign"),
  };
  document.querySelectorAll("[data-session-tab]").forEach(function (tab) {
    tab.classList.toggle("active", tab.getAttribute("data-session-tab") === name);
  });
  Object.keys(panels).forEach(function (key) {
    if (!panels[key]) return;
    panels[key].classList.toggle("hidden", key !== name);
    panels[key].classList.toggle("active", key === name);
  });
}

function selectSession(sessionId) {
  state.activeSessionId = sessionId;
  var session = sessionPayloads[sessionId];
  document.querySelectorAll(".export-session-item").forEach(function (item) {
    item.classList.toggle("selected", item.dataset.sessionId === sessionId);
  });
  if (!session) return;

  var titleEl = document.getElementById("session-title");
  var metaEl = document.getElementById("session-meta");
  var linksEl = document.getElementById("session-download-links");
  var transcriptEl = document.getElementById("session-transcript");

  if (titleEl) titleEl.textContent = session.title || session.id || "Untitled session";
  if (metaEl) {
    var metaParts = [];
    if (session.started_at) metaParts.push(formatDate(session.started_at));
    if (session.duration_minutes) metaParts.push(formatDuration(session.duration_minutes));
    if (session.status) metaParts.push(session.status);
    metaEl.textContent = metaParts.join(" · ");
  }
  if (linksEl) {
    linksEl.innerHTML = '<a href="' + escapeHtml(session.files.transcript_csv) + '">CSV</a>'
      + '<a href="' + escapeHtml(session.files.summary_md) + '">Summary</a>'
      + '<a href="' + escapeHtml(session.files.chronology_md) + '">Chronology</a>';
  }

  renderSummaryContent("session-summary", session.session_summary || "", "No session summary exported.");
  renderSummaryContent("session-chronology", session.session_chronology || "", "No chronology exported.");
  renderSummaryContent("campaign-summary", campaign.campaign_summary || "", "No campaign summary exported.");
  if (transcriptEl) transcriptEl.innerHTML = renderTranscriptRows(session.transcriptions || []);
}

function initCampaignDetailsTabs() {
  document.querySelectorAll("[data-detail-tab]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var name = btn.getAttribute("data-detail-tab");
      document.querySelectorAll("[data-detail-tab]").forEach(function (other) {
        other.classList.toggle("active", other === btn);
      });
      document.querySelectorAll(".detail-tab-content").forEach(function (panel) {
        panel.classList.toggle("active", panel.id === name + "-tab");
      });
      if (state.graphRenderer) {
        state.graphRenderer.setVisible(name === "graph");
        if (name === "graph") {
          state.graphRenderer.resize();
          state.graphRenderer.render(buildRelationshipGraphData(campaign.relationships || [], campaign));
        }
      }
    });
  });
}

function initSessionTabs() {
  document.querySelectorAll("[data-session-tab]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      setSummaryPanel(btn.getAttribute("data-session-tab"));
    });
  });
}

function initCollapse() {
  var header = document.getElementById("campaign-details-header");
  var body = document.getElementById("campaign-details-body");
  var arrow = header ? header.querySelector(".collapse-arrow") : null;
  if (!header || !body || !arrow) return;
  header.addEventListener("click", function () {
    body.classList.toggle("collapsed");
    arrow.classList.toggle("rotated");
  });
}

function initGraph() {
  var root = document.getElementById("relationship-graph-panel");
  var canvas = document.getElementById("relationship-graph-canvas");
  if (!root || !canvas) return;

  state.graphRenderer = createRelationshipGraph3D({
    root: root,
    canvas: canvas,
    emptyState: document.getElementById("relationship-graph-empty"),
    tooltip: document.getElementById("relationship-node-tooltip"),
    legend: document.getElementById("relationship-legend"),
    searchInput: document.getElementById("relationship-graph-search"),
    communitySelect: document.getElementById("relationship-graph-community"),
    neighborhoodSelect: document.getElementById("relationship-graph-neighborhood"),
    metricSelect: document.getElementById("relationship-graph-metric"),
    isolateCheckbox: document.getElementById("relationship-graph-isolate-component"),
    stats: document.getElementById("relationship-graph-stats"),
    details: document.getElementById("relationship-graph-details"),
    pathSourceSelect: document.getElementById("relationship-graph-path-source"),
    pathTargetSelect: document.getElementById("relationship-graph-path-target"),
    pathOutput: document.getElementById("relationship-graph-path-output"),
    topList: document.getElementById("relationship-graph-top"),
    fitAllButton: document.getElementById("relationship-graph-fit-all"),
  });
  state.graphRenderer.setVisible(false);
  state.graphRenderer.render(buildRelationshipGraphData(campaign.relationships || [], campaign));

  [
    ["graph-filter-players", "players"],
    ["graph-filter-npcs", "npcs"],
    ["graph-filter-locations", "locations"],
    ["graph-filter-entities", "entities"],
  ].forEach(function (entry) {
    var el = document.getElementById(entry[0]);
    if (!el) return;
    el.addEventListener("change", function () {
      state.graphFilters[entry[1]] = !!el.checked;
      if (state.graphRenderer) {
        state.graphRenderer.render(buildRelationshipGraphData(campaign.relationships || [], campaign));
      }
    });
  });
}

function init() {
  renderCampaignHeader();
  renderCampaignStats();
  renderCampaignDetails();
  renderSessionList();
  initCampaignDetailsTabs();
  initSessionTabs();
  initCollapse();
  initGraph();
  setSummaryPanel("narrative");
  if (sessions.length) selectSession(sessions[0].id);
}

init();
