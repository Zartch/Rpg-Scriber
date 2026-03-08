/* RPG Scribe - frontend WebSocket client and DOM updates */

(function () {
  "use strict";

  // Elements

  var connectionBadge = document.getElementById("connection-badge");
  var transcriptionFeed = document.getElementById("transcription-feed");
  var sessionSummaryEl = document.getElementById("session-summary");
  var campaignSummaryEl = document.getElementById("campaign-summary");
  var questionsList = document.getElementById("questions-list");
  var componentStatusEl = document.getElementById("component-status");
  var sessionListEl = document.getElementById("session-list");
  var backToLiveBtn = document.getElementById("back-to-live");
  var openTranscriptBtn = document.getElementById("open-transcript-btn");
  var modeLiveBtn = document.getElementById("mode-live-btn");
  var modeBrowseBtn = document.getElementById("mode-browse-btn");
  var browseCampaignsPanel = document.getElementById("browse-campaigns-panel");
  var browseCampaignListEl = document.getElementById("browse-campaign-list");
  var sessionsTitleEl = document.getElementById("sessions-title");
  var statusPanel = document.getElementById("status-panel");
  var questionsPanel = document.getElementById("questions-panel");
  var sessionLogLinkEl = document.getElementById("session-log-link");

  // Campaign bar elements
  var campaignBar = document.getElementById("campaign-bar");
  var campaignDisplay = document.getElementById("campaign-display");
  var campaignNameEl = document.getElementById("campaign-name");
  var campaignSystemEl = document.getElementById("campaign-system");
  var campaignMasterEl = document.getElementById("campaign-master");
  var campaignEditBtn = document.getElementById("campaign-edit-btn");
  var campaignEditForm = document.getElementById("campaign-edit-form");
  var campaignEditCancel = document.getElementById("campaign-edit-cancel");
  var editNameInput = document.getElementById("edit-campaign-name");
  var editSystemInput = document.getElementById("edit-campaign-system");
  var editDescInput = document.getElementById("edit-campaign-desc");
  var editInstructionsInput = document.getElementById("edit-campaign-instructions");
  var editMasterSelect = document.getElementById("edit-campaign-master");

  // Player/NPC elements
  var playersSection = document.getElementById("players-section");
  var playersHeader = document.getElementById("players-header");
  var playersBody = document.getElementById("players-body");
  var playersList = document.getElementById("players-list");
  var playersCount = document.getElementById("players-count");
  var npcsSection = document.getElementById("npcs-section");
  var npcsHeader = document.getElementById("npcs-header");
  var npcsBody = document.getElementById("npcs-body");
  var npcsList = document.getElementById("npcs-list");
  var npcsCount = document.getElementById("npcs-count");
  var addNpcBtn = document.getElementById("add-npc-btn");
  var addNpcForm = document.getElementById("add-npc-form");
  var addNpcCancel = document.getElementById("add-npc-cancel");
  var locationsSection = document.getElementById("locations-section");
  var locationsHeader = document.getElementById("locations-header");
  var locationsBody = document.getElementById("locations-body");
  var locationsList = document.getElementById("locations-list");
  var locationsCount = document.getElementById("locations-count");
  var addLocationBtn = document.getElementById("add-location-btn");
  var addLocationForm = document.getElementById("add-location-form");
  var addLocationCancel = document.getElementById("add-location-cancel");
  var entitiesSection = document.getElementById("entities-section");
  var entitiesHeader = document.getElementById("entities-header");
  var entitiesBody = document.getElementById("entities-body");
  var entitiesList = document.getElementById("entities-list");
  var entitiesCount = document.getElementById("entities-count");
  var addEntityBtn = document.getElementById("add-entity-btn");
  var addEntityForm = document.getElementById("add-entity-form");
  var addEntityCancel = document.getElementById("add-entity-cancel");
  var relationshipsSection = document.getElementById("relationships-section");
  var relationshipsHeader = document.getElementById("relationships-header");
  var relationshipsBody = document.getElementById("relationships-body");
  var relationshipsList = document.getElementById("relationships-list");
  var relationshipsCount = document.getElementById("relationships-count");
  var addRelationshipBtn = document.getElementById("add-relationship-btn");
  var addRelationshipForm = document.getElementById("add-relationship-form");
  var addRelationshipCancel = document.getElementById("add-relationship-cancel");
  var relSourceSelect = document.getElementById("new-rel-source");
  var relTargetSelect = document.getElementById("new-rel-target");
  var relSourceSearch = document.getElementById("new-rel-source-search");
  var relTargetSearch = document.getElementById("new-rel-target-search");
  var relSourceKind = document.getElementById("new-rel-source-kind");
  var relTargetKind = document.getElementById("new-rel-target-kind");
  var relTypeInput = document.getElementById("new-rel-type");
  var relCategoryInput = document.getElementById("new-rel-category");
  var relNotesInput = document.getElementById("new-rel-notes");
  var toggleRelationshipGraphBtn = document.getElementById("toggle-relationship-graph-btn");
  var relationshipGraphPanel = document.getElementById("relationship-graph-panel");
  var relationshipGraphSvg = document.getElementById("relationship-graph-svg");
  var relationshipLegend = document.getElementById("relationship-legend");
  var graphFilterPlayers = document.getElementById("graph-filter-players");
  var graphFilterNpcs = document.getElementById("graph-filter-npcs");
  var graphFilterLocations = document.getElementById("graph-filter-locations");
  var graphFilterEntities = document.getElementById("graph-filter-entities");
  var relationshipNodeTooltip = document.getElementById("relationship-node-tooltip");

  // Summary control buttons
  var refreshSummaryBtn = document.getElementById("refresh-summary-btn");
  var finalizeBtn = document.getElementById("finalize-btn");

  // State

  var viewingHistorical = false;  // true when viewing a past session
  var activeSessionId = null;     // current live session id
  var activeCampaignId = null;    // current campaign id
  var currentCampaign = null;     // full campaign data object
  var lastStatusTimestamp = {};   // for latency tracking
  var previousQuestionCount = 0;
  var questionsBadge = null;      // may not exist in DOM
  var maxFeedItems = 1000;        // max rows kept in DOM for live feed
  var loadedLiveSessionId = null; // latest session snapshot loaded into feed
  var currentHistoricalSessionId = null;
  var appMode = "live";         // live | browse
  var browseCampaignId = null;
  var UNCATEGORIZED_BROWSE_ID = "__uncategorized__";
  var browseCampaignsCache = [];
  var relationshipGraphVisible = false;
  var relationshipNodePositions = {};
  var relationshipGraphFilters = { players: true, npcs: true, locations: true, entities: true };
  var pinnedNodeTooltipKey = null;
  var lastRelationshipItems = [];
  var lastRelationshipCampaign = null;
  var relationshipEditOriginal = null;

  // WebSocket

  var ws = null;
  var reconnectDelay = 1000;
  var MAX_RECONNECT = 16000;

  function connectWS() {
    var proto = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(proto + "//" + location.host + "/ws/live");

    ws.onopen = function () {
      reconnectDelay = 1000;
      connectionBadge.textContent = "Connected";
      connectionBadge.className = "badge badge-connected";
    };

    ws.onclose = function () {
      connectionBadge.textContent = "Disconnected";
      connectionBadge.className = "badge badge-idle";
      setTimeout(connectWS, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT);
    };

    ws.onerror = function () {
      ws.close();
    };

    ws.onmessage = function (evt) {
      if (appMode !== "live" || viewingHistorical) return; // ignore live updates outside live mode
      var msg;
      try { msg = JSON.parse(evt.data); } catch (_) { return; }
      handleMessage(msg);
    };
  }

  // Message handlers

  function handleMessage(msg) {
    switch (msg.type) {
      case "transcription":
        addTranscription(msg.data);
        break;
      case "summary":
        updateSummary(msg.data);
        break;
      case "status":
        updateStatus(msg.data);
        break;
    }
  }

  function formatTime(ts) {
    if (!ts) return "";
    var d = new Date(ts * 1000);
    return d.toLocaleTimeString();
  }

  function formatDate(ts) {
    if (!ts) return "";
    var d = new Date(ts * 1000);
    return d.toLocaleDateString() + " " + d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function formatDuration(minutes) {
    if (!minutes && minutes !== 0) return "";
    if (minutes < 60) return Math.round(minutes) + " min";
    var h = Math.floor(minutes / 60);
    var m = Math.round(minutes % 60);
    return h + "h " + (m > 0 ? m + "m" : "");
  }

  function addTranscription(data) {
    // Remove placeholder
    var ph = transcriptionFeed.querySelector(".placeholder");
    if (ph) ph.remove();

    var entry = document.createElement("div");
    entry.className = "feed-entry" + (data.is_partial ? " partial" : "");
    entry.innerHTML =
      '<span class="speaker">' + escapeHtml(data.speaker_name) + ":</span>" +
      escapeHtml(data.text) +
      '<span class="ts">' + formatTime(data.timestamp) + "</span>";
    transcriptionFeed.appendChild(entry);
    if (!viewingHistorical) {
      trimTranscriptionFeed();
    }
    transcriptionFeed.scrollTop = transcriptionFeed.scrollHeight;
  }

  function trimTranscriptionFeed() {
    var entries = transcriptionFeed.querySelectorAll(".feed-entry");
    var overflow = entries.length - maxFeedItems;
    for (var i = 0; i < overflow; i++) {
      entries[i].remove();
    }
  }
  function updateSummary(data) {
    if (data.session_summary) {
      sessionSummaryEl.textContent = data.session_summary;
    }
    if (data.campaign_summary) {
      campaignSummaryEl.textContent = data.campaign_summary;
    }
  }

  function updateStatus(data) {
    var card = componentStatusEl.querySelector(
      '[data-component="' + data.component + '"]'
    );
    if (!card) return;
    var dot = card.querySelector(".status-dot");
    var msgEl = card.querySelector(".status-msg");
    var latencyEl = card.querySelector(".status-latency");

    dot.className = "status-dot " + data.status;
    msgEl.textContent = data.message || data.status;

    // Calculate and display latency between status updates
    if (latencyEl && data.timestamp) {
      var prev = lastStatusTimestamp[data.component];
      lastStatusTimestamp[data.component] = data.timestamp;

      if (prev && data.status === "running") {
        var delta = data.timestamp - prev;
        if (delta > 0 && delta < 300) {
          latencyEl.textContent = formatLatency(delta);
          latencyEl.className = "status-latency " + latencyClass(delta);
        }
      } else if (data.status === "idle") {
        latencyEl.textContent = "";
        latencyEl.className = "status-latency";
      }
    }
  }

  function formatLatency(seconds) {
    if (seconds < 1) return Math.round(seconds * 1000) + "ms";
    return seconds.toFixed(1) + "s";
  }

  function latencyClass(seconds) {
    if (seconds < 2) return "latency-good";
    if (seconds < 10) return "latency-ok";
    return "latency-slow";
  }

  function escapeHtml(str) {
    var div = document.createElement("div");
    div.appendChild(document.createTextNode(str || ""));
    return div.innerHTML;
  }

  function escapeAttr(str) {
    return (str || "").replace(/&/g, "&amp;").replace(/"/g, "&quot;")
      .replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function locationName(loc) {
    if (!loc) return "";
    if (typeof loc === "string") return loc.trim();
    if (typeof loc === "object") return String(loc.name || "").trim();
    return String(loc).trim();
  }

  function locationDescription(loc) {
    if (loc && typeof loc === "object") return String(loc.description || "").trim();
    return "";
  }

  function entityType(entity) {
    if (entity && typeof entity === "object") return String(entity.entity_type || "group").trim() || "group";
    return "group";
  }

  function entityDescription(entity) {
    if (entity && typeof entity === "object") return String(entity.description || "").trim();
    return "";
  }

  // Campaign info

  function fetchCampaignInfo() {
    fetch("/api/campaigns")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.campaign) {
          currentCampaign = data.campaign;
          activeCampaignId = data.campaign.id;
          renderCampaignBar(data.campaign);
          if (data.campaign.is_generic) {
            playersSection.classList.add("hidden");
            npcsSection.classList.add("hidden");
            if (locationsSection) locationsSection.classList.add("hidden");
            if (entitiesSection) entitiesSection.classList.add("hidden");
            if (relationshipsSection) relationshipsSection.classList.add("hidden");
          } else {
            renderPlayers(data.campaign.players || []);
            renderNpcs(data.campaign.npcs || []);
            renderLocations(data.campaign.locations || []);
            renderEntities(data.campaign.entities || []);
            renderRelationships(data.campaign.relationships || [], data.campaign);
          }
          // Show "View all" link and "Generate" button for campaign summaries
          var summariesLink = document.getElementById("campaign-summaries-link");
          var generateBtn = document.getElementById("btn-generate-campaign-summary");
          if (summariesLink && data.campaign.id) {
            summariesLink.href = "/campaign-summaries.html?campaign=" + encodeURIComponent(data.campaign.id);
            summariesLink.classList.remove("hidden");
          }
          if (generateBtn && data.campaign.id) {
            generateBtn.classList.remove("hidden");
            generateBtn.dataset.campaignId = data.campaign.id;
          }
        } else {
          // No campaign loaded - show "Resume mode"
          campaignBar.classList.remove("hidden");
          campaignNameEl.textContent = "No campaign \u2014 Resume mode";
          campaignSystemEl.textContent = "";
          campaignMasterEl.textContent = "";
          campaignEditBtn.classList.add("hidden");
          playersSection.classList.add("hidden");
          npcsSection.classList.add("hidden");
          if (locationsSection) locationsSection.classList.add("hidden");
          if (entitiesSection) entitiesSection.classList.add("hidden");
          if (relationshipsSection) relationshipsSection.classList.add("hidden");
          currentCampaign = null;
          activeCampaignId = null;
        }
      })
      .catch(function () {});
  }

  function renderCampaignBar(campaign) {
    campaignBar.classList.remove("hidden");
    campaignNameEl.textContent = campaign.name || "Unnamed Campaign";

    var systemText = "";
    if (campaign.game_system) systemText += campaign.game_system;
    if (campaign.language) {
      systemText += (systemText ? " \u00b7 " : "") + campaign.language.toUpperCase();
    }
    campaignSystemEl.textContent = systemText ? "(" + systemText + ")" : "";
    campaignMasterEl.textContent = getMasterDisplayName(campaign);

    // Hide edit for generic campaigns
    if (campaign.is_generic) {
      campaignEditBtn.classList.add("hidden");
      campaignNameEl.textContent = "No campaign \u2014 Resume mode";
      campaignSystemEl.textContent = "";
      campaignMasterEl.textContent = "";
      playersSection.classList.add("hidden");
      npcsSection.classList.add("hidden");
      if (locationsSection) locationsSection.classList.add("hidden");
      if (entitiesSection) entitiesSection.classList.add("hidden");
      if (relationshipsSection) relationshipsSection.classList.add("hidden");
    } else {
      campaignEditBtn.classList.remove("hidden");
    }
  }

  function getMasterDisplayName(campaign) {
    var players = campaign.players || [];
    var dmId = campaign.dm_speaker_id || "";
    if (!dmId) return "";
    for (var i = 0; i < players.length; i++) {
      if (players[i].discord_id === dmId) {
        return "Master: " + (players[i].discord_name || players[i].character_name || dmId);
      }
    }
    return "Master: " + dmId;
  }

  function populateMasterSelect(players, selectedDmId) {
    editMasterSelect.innerHTML = "";
    var noneOpt = document.createElement("option");
    noneOpt.value = "";
    noneOpt.textContent = "(No master selected)";
    editMasterSelect.appendChild(noneOpt);

    players.forEach(function (p) {
      var opt = document.createElement("option");
      opt.value = p.discord_id || "";
      opt.textContent = (p.discord_name || "?") + " -> " + (p.character_name || "?");
      editMasterSelect.appendChild(opt);
    });

    editMasterSelect.value = selectedDmId || "";
    editMasterSelect.disabled = !players || players.length === 0;
  }

  function openCampaignEdit() {
    if (appMode !== "live") return;
    if (!currentCampaign) return;
    editNameInput.value = currentCampaign.name || "";
    editSystemInput.value = currentCampaign.game_system || "";
    editDescInput.value = currentCampaign.description || "";
    editInstructionsInput.value = currentCampaign.custom_instructions || "";
    populateMasterSelect(currentCampaign.players || [], currentCampaign.dm_speaker_id || "");

    campaignDisplay.classList.add("hidden");
    campaignEditForm.classList.remove("hidden");
    editNameInput.focus();
  }

  function closeCampaignEdit() {
    campaignEditForm.classList.add("hidden");
    campaignDisplay.classList.remove("hidden");
  }

  function saveCampaignEdit(e) {
    e.preventDefault();
    if (appMode !== "live") return;
    if (!currentCampaign || !activeCampaignId) return;

    var body = {
      name: editNameInput.value.trim(),
      game_system: editSystemInput.value.trim(),
      description: editDescInput.value.trim(),
      custom_instructions: editInstructionsInput.value.trim(),
      dm_speaker_id: editMasterSelect.value,
    };

    var saveBtn = campaignEditForm.querySelector(".btn-save");
    saveBtn.disabled = true;
    saveBtn.textContent = "Saving...";

    fetch("/api/campaigns/" + activeCampaignId, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.ok && data.campaign) {
          currentCampaign = data.campaign;
          renderCampaignBar(data.campaign);
          closeCampaignEdit();
        } else {
          alert("Error: " + (data.error || "Unknown error"));
        }
      })
      .catch(function () {
        alert("Failed to save campaign changes.");
      })
      .finally(function () {
        saveBtn.disabled = false;
        saveBtn.textContent = "Save";
      });
  }

  campaignEditBtn.addEventListener("click", openCampaignEdit);
  campaignEditCancel.addEventListener("click", closeCampaignEdit);
  campaignEditForm.addEventListener("submit", saveCampaignEdit);

  // Players and NPCs

  function renderPlayers(players) {
    if (!players || players.length === 0) {
      playersSection.classList.add("hidden");
      return;
    }
    playersSection.classList.remove("hidden");
    playersCount.textContent = "(" + players.length + ")";
    playersList.innerHTML = "";

    players.forEach(function (p) {
      var isMaster = !!(currentCampaign && currentCampaign.dm_speaker_id && p.discord_id === currentCampaign.dm_speaker_id);
      var masterSuffix = isMaster ? " - Master" : "";
      var card = document.createElement("div");
      card.className = "entity-card";
      card.innerHTML =
        '<div class="entity-display">' +
          '<div class="entity-info">' +
            '<strong class="entity-name">' + escapeHtml(p.character_name) + '</strong>' +
            '<span class="entity-meta">' + escapeHtml((p.discord_name || "") + masterSuffix) + '</span>' +
          '</div>' +
          '<span class="entity-desc">' + escapeHtml(p.character_description) + '</span>' +
          '<button class="btn-small btn-edit-entity" title="Edit">Edit</button>' +
        '</div>' +
        '<form class="entity-edit-form hidden">' +
          '<div class="edit-row"><label>Discord</label>' +
            '<input type="text" class="edit-discord-name" value="' + escapeAttr(p.discord_name) + '" /></div>' +
          '<div class="edit-row"><label>Character</label>' +
            '<input type="text" class="edit-char-name" value="' + escapeAttr(p.character_name) + '" required /></div>' +
          '<div class="edit-row"><label>Description</label>' +
            '<textarea class="edit-char-desc" rows="2">' + escapeHtml(p.character_description) + '</textarea></div>' +
          '<div class="edit-actions">' +
            '<button type="submit" class="btn-small btn-save">Save</button>' +
            '<button type="button" class="btn-small btn-cancel entity-edit-cancel">Cancel</button>' +
          '</div>' +
        '</form>';

      // Toggle edit
      var displayEl = card.querySelector(".entity-display");
      var formEl = card.querySelector(".entity-edit-form");
      card.querySelector(".btn-edit-entity").addEventListener("click", function () {
        displayEl.classList.add("hidden");
        formEl.classList.remove("hidden");
      });
      card.querySelector(".entity-edit-cancel").addEventListener("click", function () {
        formEl.classList.add("hidden");
        displayEl.classList.remove("hidden");
      });

      // Save player
      formEl.addEventListener("submit", function (e) {
        e.preventDefault();
        var reqBody = {
          discord_id: p.discord_id,
          discord_name: formEl.querySelector(".edit-discord-name").value.trim(),
          character_name: formEl.querySelector(".edit-char-name").value.trim(),
          character_description: formEl.querySelector(".edit-char-desc").value.trim(),
        };
        var saveBtn = formEl.querySelector(".btn-save");
        saveBtn.disabled = true;
        saveBtn.textContent = "Saving...";

        if (appMode !== "live") return;
        fetch("/api/campaigns/" + activeCampaignId + "/players/" + p.id, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(reqBody),
        })
          .then(function (r) { return r.json(); })
          .then(function (data) {
            if (data.ok) {
              fetchCampaignInfo();
            } else {
              alert("Error: " + (data.error || "Unknown error"));
            }
          })
          .catch(function () { alert("Failed to save player."); })
          .finally(function () {
            saveBtn.disabled = false;
            saveBtn.textContent = "Save";
          });
      });

      if (appMode !== "live") {
        var editBtn = card.querySelector(".btn-edit-entity");
        if (editBtn) editBtn.classList.add("hidden");
      }
      playersList.appendChild(card);
    });
  }

  function renderNpcs(npcs) {
    if (!npcs || npcs.length === 0) {
      npcsSection.classList.remove("hidden");
      npcsCount.textContent = "(0)";
      npcsList.innerHTML = '<p class="placeholder">No NPCs yet.</p>';
      return;
    }
    npcsSection.classList.remove("hidden");
    npcsCount.textContent = "(" + npcs.length + ")";
    npcsList.innerHTML = "";

    npcs.forEach(function (n) {
      var card = document.createElement("div");
      card.className = "entity-card";
      card.innerHTML =
        '<div class="entity-display">' +
          '<div class="entity-info">' +
            '<strong class="entity-name">' + escapeHtml(n.name) + '</strong>' +
          '</div>' +
          '<span class="entity-desc">' + escapeHtml(n.description) + '</span>' +
          '<button class="btn-small btn-edit-entity" title="Edit">Edit</button>' +
        '</div>' +
        '<form class="entity-edit-form hidden">' +
          '<div class="edit-row"><label>Name</label>' +
            '<input type="text" class="edit-npc-name" value="' + escapeAttr(n.name) + '" required /></div>' +
          '<div class="edit-row"><label>Description</label>' +
            '<textarea class="edit-npc-desc" rows="2">' + escapeHtml(n.description) + '</textarea></div>' +
          '<div class="edit-actions">' +
            '<button type="submit" class="btn-small btn-save">Save</button>' +
            '<button type="button" class="btn-small btn-cancel entity-edit-cancel">Cancel</button>' +
          '</div>' +
        '</form>';

      var displayEl = card.querySelector(".entity-display");
      var formEl = card.querySelector(".entity-edit-form");
      card.querySelector(".btn-edit-entity").addEventListener("click", function () {
        displayEl.classList.add("hidden");
        formEl.classList.remove("hidden");
      });
      card.querySelector(".entity-edit-cancel").addEventListener("click", function () {
        formEl.classList.add("hidden");
        displayEl.classList.remove("hidden");
      });

      // Save NPC
      formEl.addEventListener("submit", function (e) {
        e.preventDefault();
        var reqBody = {
          old_name: n.name,
          name: formEl.querySelector(".edit-npc-name").value.trim(),
          description: formEl.querySelector(".edit-npc-desc").value.trim(),
        };
        var saveBtn = formEl.querySelector(".btn-save");
        saveBtn.disabled = true;
        saveBtn.textContent = "Saving...";

        if (appMode !== "live") return;
        fetch("/api/campaigns/" + activeCampaignId + "/npcs/" + n.id, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(reqBody),
        })
          .then(function (r) { return r.json(); })
          .then(function (data) {
            if (data.ok) { fetchCampaignInfo(); }
            else { alert("Error: " + (data.error || "Unknown error")); }
          })
          .catch(function () { alert("Failed to save NPC."); })
          .finally(function () {
            saveBtn.disabled = false;
            saveBtn.textContent = "Save";
          });
      });

      if (appMode !== "live") {
        var editBtnNpc = card.querySelector(".btn-edit-entity");
        if (editBtnNpc) editBtnNpc.classList.add("hidden");
      }
      npcsList.appendChild(card);
    });
  }



  function renderLocations(locations) {
    if (!locationsSection) return;

    var items = (locations || []).map(function (loc) {
      return {
        name: locationName(loc),
        description: locationDescription(loc),
      };
    }).filter(function (loc) { return !!loc.name; });

    locationsSection.classList.remove("hidden");
    locationsCount.textContent = "(" + items.length + ")";

    if (!items.length) {
      locationsList.innerHTML = '<p class="placeholder">No locations yet.</p>';
      return;
    }

    locationsList.innerHTML = "";
    items.forEach(function (loc) {
      var name = loc.name;
      var description = loc.description;
      var card = document.createElement("div");
      card.className = "entity-card";
      card.innerHTML =
        '<div class="entity-display">' +
          '<div class="entity-info">' +
            '<strong class="entity-name">' + escapeHtml(name) + '</strong>' +
          '</div>' +
          '<span class="entity-desc">' + escapeHtml(description || "") + '</span>' +
          '<button class="btn-small btn-edit-entity" title="Edit">Edit</button>' +
        '</div>' +
        '<form class="entity-edit-form hidden">' +
          '<div class="edit-row"><label>Name</label>' +
            '<input type="text" class="edit-location-name" value="' + escapeAttr(name) + '" required /></div>' +
          '<div class="edit-row"><label>Description</label>' +
            '<textarea class="edit-location-desc" rows="2">' + escapeHtml(description || "") + '</textarea></div>' +
          '<div class="edit-actions">' +
            '<button type="submit" class="btn-small btn-save">Save</button>' +
            '<button type="button" class="btn-small btn-cancel entity-edit-cancel">Cancel</button>' +
          '</div>' +
        '</form>';

      var displayEl = card.querySelector(".entity-display");
      var formEl = card.querySelector(".entity-edit-form");
      card.querySelector(".btn-edit-entity").addEventListener("click", function () {
        displayEl.classList.add("hidden");
        formEl.classList.remove("hidden");
      });
      card.querySelector(".entity-edit-cancel").addEventListener("click", function () {
        formEl.classList.add("hidden");
        displayEl.classList.remove("hidden");
      });

      formEl.addEventListener("submit", function (e) {
        e.preventDefault();
        if (appMode !== "live" || !activeCampaignId) return;

        var reqBody = {
          old_name: name,
          name: formEl.querySelector(".edit-location-name").value.trim(),
          description: ((formEl.querySelector(".edit-location-desc") || {}).value || "").trim(),
        };
        if (!reqBody.name) return;
        var saveBtn = formEl.querySelector(".btn-save");
        saveBtn.disabled = true;
        saveBtn.textContent = "Saving...";

        fetch("/api/campaigns/" + activeCampaignId + "/locations", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(reqBody),
        })
          .then(function (r) { return r.json(); })
          .then(function (data) {
            if (data.ok) { fetchCampaignInfo(); }
            else { alert("Error: " + (data.error || "Unknown error")); }
          })
          .catch(function () { alert("Failed to save location."); })
          .finally(function () {
            saveBtn.disabled = false;
            saveBtn.textContent = "Save";
          });
      });

      if (appMode !== "live") {
        var editBtnLoc = card.querySelector(".btn-edit-entity");
        if (editBtnLoc) editBtnLoc.classList.add("hidden");
      }

      locationsList.appendChild(card);
    });
  }

  function renderEntities(entities) {
    if (!entitiesSection) return;

    var items = (entities || []).filter(function (ent) {
      return !!(ent && ent.name);
    });

    entitiesSection.classList.remove("hidden");
    entitiesCount.textContent = "(" + items.length + ")";

    if (!items.length) {
      entitiesList.innerHTML = '<p class="placeholder">No entities yet.</p>';
      return;
    }

    entitiesList.innerHTML = "";
    items.forEach(function (ent) {
      var card = document.createElement("div");
      card.className = "entity-card";
      card.innerHTML =
        '<div class="entity-display">' +
          '<div class="entity-info">' +
            '<strong class="entity-name">' + escapeHtml(ent.name) + '</strong>' +
            '<span class="entity-meta">' + escapeHtml(entityType(ent)) + '</span>' +
          '</div>' +
          '<span class="entity-desc">' + escapeHtml(entityDescription(ent)) + '</span>' +
          '<button class="btn-small btn-edit-entity" title="Edit">Edit</button>' +
        '</div>' +
        '<form class="entity-edit-form hidden">' +
          '<div class="edit-row"><label>Name</label>' +
            '<input type="text" class="edit-entity-name" value="' + escapeAttr(ent.name) + '" required /></div>' +
          '<div class="edit-row"><label>Type</label>' +
            '<input type="text" class="edit-entity-type" value="' + escapeAttr(entityType(ent)) + '" /></div>' +
          '<div class="edit-row"><label>Description</label>' +
            '<textarea class="edit-entity-desc" rows="2">' + escapeHtml(entityDescription(ent)) + '</textarea></div>' +
          '<div class="edit-actions">' +
            '<button type="submit" class="btn-small btn-save">Save</button>' +
            '<button type="button" class="btn-small btn-cancel">Cancel</button>' +
          '</div>' +
        '</form>';

      var editBtn = card.querySelector(".btn-edit-entity");
      var form = card.querySelector(".entity-edit-form");
      var cancelBtn = card.querySelector(".btn-cancel");

      if (editBtn && form) {
        editBtn.addEventListener("click", function () {
          if (appMode !== "live") return;
          form.classList.remove("hidden");
          editBtn.classList.add("hidden");
          var input = form.querySelector(".edit-entity-name");
          if (input) input.focus();
        });
      }

      if (cancelBtn && form && editBtn) {
        cancelBtn.addEventListener("click", function () {
          form.classList.add("hidden");
          editBtn.classList.remove("hidden");
        });
      }

      if (form) {
        form.addEventListener("submit", function (e) {
          e.preventDefault();
          if (appMode !== "live") return;

          var reqBody = {
            old_name: ent.name || "",
            name: ((form.querySelector(".edit-entity-name") || {}).value || "").trim(),
            entity_type: ((form.querySelector(".edit-entity-type") || {}).value || "").trim(),
            description: ((form.querySelector(".edit-entity-desc") || {}).value || "").trim(),
          };
          if (!reqBody.name) return;
          if (!reqBody.entity_type) reqBody.entity_type = "group";

          var saveBtn = form.querySelector(".btn-save");
          saveBtn.disabled = true;
          saveBtn.textContent = "Saving...";

          fetch("/api/campaigns/" + activeCampaignId + "/entities/" + ent.id, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(reqBody),
          })
            .then(function (r) { return r.json(); })
            .then(function (data) {
              if (data.ok) { fetchCampaignInfo(); }
              else { alert("Error: " + (data.error || "Unknown error")); }
            })
            .catch(function () { alert("Failed to update entity."); })
            .finally(function () {
              saveBtn.disabled = false;
              saveBtn.textContent = "Save";
            });
        });
      }

      if (appMode !== "live") {
        if (editBtn) editBtn.classList.add("hidden");
      }

      entitiesList.appendChild(card);
    });
  }

  function normalizeEntityKey(key) {
    var raw = (key || "").trim();
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
    if (key.indexOf("loc:") === 0 || key.indexOf("location:") === 0) return "location";
    if (key.indexOf("ent:") === 0 || key.indexOf("entity:") === 0) return "entity";
    return "unknown";
  }

  function buildRelationshipEntities(campaign) {
    var allEntities = [];
    var players = campaign.players || [];
    var npcs = campaign.npcs || [];
    var locations = campaign.locations || [];
    var campaignEntities = campaign.entities || [];

    players.forEach(function (p) {
      allEntities.push({
        key: "player:" + (p.discord_id || ""),
        label: "Player: " + (p.character_name || p.discord_name || p.discord_id || "?"),
        kind: "player",
        description: p.character_description || "",
      });
    });

    npcs.forEach(function (n) {
      allEntities.push({
        key: "npc:" + (n.name || ""),
        label: "NPC: " + (n.name || "?"),
        kind: "npc",
        description: n.description || "",
      });
    });

    locations.forEach(function (loc) {
      var name = locationName(loc);
      if (!name) return;
      allEntities.push({
        key: "loc:" + name,
        label: "Location: " + name,
        kind: "location",
        description: locationDescription(loc),
      });
    });

    campaignEntities.forEach(function (ent) {
      if (!ent || !ent.name) return;
      allEntities.push({
        key: "ent:" + ent.name,
        label: "Entity (" + entityType(ent) + "): " + ent.name,
        kind: "entity",
        description: entityDescription(ent),
      });
    });

    return allEntities.filter(function (e) { return !!e.key && !e.key.endsWith(":"); });
  }

  function entityDetailsFromKey(campaign, key) {
    var normalized = normalizeEntityKey(key);
    var entities = buildRelationshipEntities(campaign);
    for (var i = 0; i < entities.length; i++) {
      if (normalizeEntityKey(entities[i].key) === normalized) return entities[i];
    }
    var kind = entityTypeFromKey(normalized);
    return { key: normalized, label: normalized, kind: kind, description: "" };
  }

  function entityLabelFromKey(campaign, key) {
    return entityDetailsFromKey(campaign, key).label;
  }

  function relationTypeKey(rel) {
    return rel.type_key || rel.relation_type_key || rel.type_label || rel.relation_type_label || "unknown";
  }

  function relationTypeLabel(rel) {
    return rel.type_label || rel.relation_type_label || rel.type_key || rel.relation_type_key || "unknown";
  }

  function relationPaletteColor(index) {
    var palette = [
      "#ff6b6b", "#22c55e", "#3b82f6", "#eab308", "#f97316",
      "#14b8a6", "#a855f7", "#ec4899", "#84cc16", "#06b6d4"
    ];
    return palette[index % palette.length];
  }

  function graphPointFromMouse(evt) {
    var rect = relationshipGraphSvg.getBoundingClientRect();
    var x = ((evt.clientX - rect.left) / rect.width) * 900;
    var y = ((evt.clientY - rect.top) / rect.height) * 520;
    return { x: x, y: y };
  }

  function refreshRelationshipGraphPositions() {
    if (!window.__relGraphModel) return;
    var model = window.__relGraphModel;
    Object.keys(model.nodes).forEach(function (key) {
      var nodeEl = model.nodes[key];
      var pos = relationshipNodePositions[key];
      if (!nodeEl || !pos) return;
      nodeEl.setAttribute("transform", "translate(" + pos.x + " " + pos.y + ")");
    });

    model.edges.forEach(function (edge) {
      var source = relationshipNodePositions[edge.source];
      var target = relationshipNodePositions[edge.target];
      if (!source || !target) return;
      edge.line.setAttribute("x1", source.x);
      edge.line.setAttribute("y1", source.y);
      edge.line.setAttribute("x2", target.x);
      edge.line.setAttribute("y2", target.y);
      edge.label.setAttribute("x", ((source.x + target.x) / 2));
      edge.label.setAttribute("y", ((source.y + target.y) / 2) - 6);
    });
  }

  function graphGroupIncluded(kind) {
    if (kind === "player") return !!relationshipGraphFilters.players;
    if (kind === "npc") return !!relationshipGraphFilters.npcs;
    if (kind === "location") return !!relationshipGraphFilters.locations;
    if (kind === "entity") return !!relationshipGraphFilters.entities;
    return true;
  }

  function nodeFillColor(kind) {
    if (kind === "player") return "#1f3b5a";
    if (kind === "npc") return "#3f3f46";
    if (kind === "location") return "#2d4f3a";
    if (kind === "entity") return "#5b3a1f";
    return "#374151";
  }

  function showNodeTooltip(details, relationshipCount) {
    if (!relationshipNodeTooltip) return;
    relationshipNodeTooltip.classList.remove("hidden");
    relationshipNodeTooltip.innerHTML =
      '<strong>' + escapeHtml(details.label || details.key) + '</strong><br/>' +
      'Type: ' + escapeHtml(details.kind || "unknown") + '<br/>' +
      'Relations: ' + relationshipCount +
      (details.description ? '<br/>' + escapeHtml(details.description) : "");
  }

  function hideNodeTooltip(force) {
    if (!relationshipNodeTooltip) return;
    if (!force && pinnedNodeTooltipKey) return;
    relationshipNodeTooltip.classList.add("hidden");
    relationshipNodeTooltip.innerHTML = "";
  }

  function renderRelationshipGraph(relationships, campaign) {
    if (!relationshipGraphSvg || !relationshipLegend || !relationshipGraphPanel) return;
    relationshipGraphSvg.innerHTML = "";
    relationshipLegend.innerHTML = "";
    hideNodeTooltip(true);

    if (!relationshipGraphVisible) return;
    var items = relationships || [];

    var entityMap = {};
    var visibleEntities = buildRelationshipEntities(campaign || {}).filter(function (entity) {
      return graphGroupIncluded(entity.kind);
    });

    visibleEntities.forEach(function (entity) {
      entityMap[normalizeEntityKey(entity.key)] = entity;
    });

    var filteredItems = items.filter(function (rel) {
      var source = entityDetailsFromKey(campaign || {}, rel.source_key || "");
      var target = entityDetailsFromKey(campaign || {}, rel.target_key || "");
      return graphGroupIncluded(source.kind) && graphGroupIncluded(target.kind);
    });

    if (!visibleEntities.length) {
      relationshipGraphSvg.innerHTML = '<text x="450" y="260" fill="#8b8fa3" text-anchor="middle">No visible entities with current filters</text>';
      return;
    }

    var nodeKeys = visibleEntities
      .map(function (e) { return normalizeEntityKey(e.key); })
      .filter(function (k, idx, arr) { return !!k && arr.indexOf(k) === idx; });
    var typeOrder = [];
    var typeColors = {};
    var typeLabels = {};
    var relCountByNode = {};

    filteredItems.forEach(function (rel) {
      var source = normalizeEntityKey(rel.source_key || "");
      var target = normalizeEntityKey(rel.target_key || "");
      if (source && nodeKeys.indexOf(source) < 0) nodeKeys.push(source);
      if (target && nodeKeys.indexOf(target) < 0) nodeKeys.push(target);
      if (source) relCountByNode[source] = (relCountByNode[source] || 0) + 1;
      if (target) relCountByNode[target] = (relCountByNode[target] || 0) + 1;
      var tKey = relationTypeKey(rel);
      if (typeOrder.indexOf(tKey) < 0) typeOrder.push(tKey);
      if (!typeLabels[tKey]) typeLabels[tKey] = relationTypeLabel(rel);
    });

    typeOrder.forEach(function (tKey, idx) {
      typeColors[tKey] = relationPaletteColor(idx);
    });

    var centerX = 450;
    var centerY = 260;
    var radius = Math.max(90, Math.min(210, 70 + nodeKeys.length * 14));
    nodeKeys.forEach(function (key, idx) {
      if (!relationshipNodePositions[key]) {
        var angle = (Math.PI * 2 * idx) / Math.max(1, nodeKeys.length);
        relationshipNodePositions[key] = {
          x: centerX + Math.cos(angle) * radius,
          y: centerY + Math.sin(angle) * radius,
        };
      }
    });

    var edgeLayer = document.createElementNS("http://www.w3.org/2000/svg", "g");
    var nodeLayer = document.createElementNS("http://www.w3.org/2000/svg", "g");
    relationshipGraphSvg.appendChild(edgeLayer);
    relationshipGraphSvg.appendChild(nodeLayer);

    var nodeEls = {};
    var edgeEls = [];
    window.__relGraphDragKey = null;

    filteredItems.forEach(function (rel) {
      var sourceKey = normalizeEntityKey(rel.source_key || "");
      var targetKey = normalizeEntityKey(rel.target_key || "");
      if (!sourceKey || !targetKey) return;
      var line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      var tKey = relationTypeKey(rel);
      line.setAttribute("stroke", typeColors[tKey] || "#888");
      line.setAttribute("stroke-width", "2");
      line.setAttribute("opacity", "0.9");
      edgeLayer.appendChild(line);

      var label = document.createElementNS("http://www.w3.org/2000/svg", "text");
      label.setAttribute("class", "relationship-edge-label");
      label.textContent = relationTypeLabel(rel);
      edgeLayer.appendChild(label);

      edgeEls.push({ line: line, label: label, source: sourceKey, target: targetKey });
    });

    nodeKeys.forEach(function (key) {
      var details = entityMap[key] || entityDetailsFromKey(campaign || {}, key);
      var group = document.createElementNS("http://www.w3.org/2000/svg", "g");
      var shape;
      if (details.kind === "player") {
        shape = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        shape.setAttribute("r", "22");
      } else if (details.kind === "npc") {
        shape = document.createElementNS("http://www.w3.org/2000/svg", "rect");
        shape.setAttribute("x", "-20");
        shape.setAttribute("y", "-20");
        shape.setAttribute("width", "40");
        shape.setAttribute("height", "40");
        shape.setAttribute("rx", "2");
      } else {
        shape = document.createElementNS("http://www.w3.org/2000/svg", "rect");
        shape.setAttribute("x", "-30");
        shape.setAttribute("y", "-16");
        shape.setAttribute("width", "60");
        shape.setAttribute("height", "32");
        shape.setAttribute("rx", "4");
      }
      shape.setAttribute("fill", nodeFillColor(details.kind));
      shape.setAttribute("class", "relationship-node-shape");

      var text = document.createElementNS("http://www.w3.org/2000/svg", "text");
      text.setAttribute("class", "relationship-node-label");
      var rawLabel = (details.label || details.key || key).replace("Player: ", "").replace("NPC: ", "").replace("Location: ", "");
      text.textContent = rawLabel.length > 14 ? rawLabel.slice(0, 12) + ".." : rawLabel;
      text.setAttribute("y", "4");

      group.appendChild(shape);
      group.appendChild(text);
      nodeLayer.appendChild(group);
      nodeEls[key] = group;

      shape.addEventListener("mousedown", function () {
        window.__relGraphDragKey = key;
        shape.classList.add("dragging");
      });
      shape.addEventListener("mouseenter", function () {
        showNodeTooltip(details, relCountByNode[key] || 0);
      });
      shape.addEventListener("mouseleave", function () {
        hideNodeTooltip(false);
      });
      shape.addEventListener("click", function () {
        if (pinnedNodeTooltipKey === key) {
          pinnedNodeTooltipKey = null;
          hideNodeTooltip(true);
        } else {
          pinnedNodeTooltipKey = key;
          showNodeTooltip(details, relCountByNode[key] || 0);
        }
      });
    });

    window.__relGraphModel = { nodes: nodeEls, edges: edgeEls };
    refreshRelationshipGraphPositions();

    relationshipGraphSvg.onmousemove = function (evt) {
      var dragKey = window.__relGraphDragKey;
      if (!dragKey) return;
      var point = graphPointFromMouse(evt);
      relationshipNodePositions[dragKey] = {
        x: Math.max(24, Math.min(876, point.x)),
        y: Math.max(24, Math.min(496, point.y)),
      };
      refreshRelationshipGraphPositions();
    };

    relationshipGraphSvg.onmouseup = function () {
      var dragKey = window.__relGraphDragKey;
      if (dragKey && nodeEls[dragKey]) {
        var dragShape = nodeEls[dragKey].querySelector(".relationship-node-shape");
        if (dragShape) dragShape.classList.remove("dragging");
      }
      window.__relGraphDragKey = null;
    };

    relationshipGraphSvg.onmouseleave = relationshipGraphSvg.onmouseup;

    if (!typeOrder.length) {
      var emptyLegend = document.createElement("span");
      emptyLegend.className = "relationship-legend-empty";
      emptyLegend.textContent = "No relationships to draw for current filters.";
      relationshipLegend.appendChild(emptyLegend);
    } else {
      typeOrder.forEach(function (tKey) {
        var item = document.createElement("span");
        item.className = "relationship-legend-item";
        item.innerHTML =
          '<span class="relationship-legend-swatch" style="background:' + escapeAttr(typeColors[tKey] || "#888") + '"></span>' +
          '<span>' + escapeHtml(typeLabels[tKey] || tKey) + '</span>';
        relationshipLegend.appendChild(item);
      });
    }
  }
  function setRelationshipGraphVisible(visible) {
    relationshipGraphVisible = !!visible;
    if (!relationshipGraphVisible) { pinnedNodeTooltipKey = null; hideNodeTooltip(true); }
    if (!relationshipGraphPanel || !toggleRelationshipGraphBtn) return;
    relationshipGraphPanel.classList.toggle("hidden", !relationshipGraphVisible);
    toggleRelationshipGraphBtn.textContent = relationshipGraphVisible ? "Hide Graph" : "Graph";
  }

  function populateRelationshipSelects(campaign) {
    if (!relSourceSelect || !relTargetSelect) return;
    var entities = buildRelationshipEntities(campaign);
    setRelationshipEntityOptions(relSourceSelect, entities);
    setRelationshipEntityOptions(relTargetSelect, entities);
    applyRelationshipEntityFilters(relSourceSelect, relSourceSearch, relSourceKind);
    applyRelationshipEntityFilters(relTargetSelect, relTargetSearch, relTargetKind);

    relSourceSelect.disabled = entities.length < 2;
    relTargetSelect.disabled = entities.length < 2;
    if (relSourceSearch) relSourceSearch.disabled = entities.length < 2;
    if (relTargetSearch) relTargetSearch.disabled = entities.length < 2;
    if (relSourceKind) relSourceKind.disabled = entities.length < 2;
    if (relTargetKind) relTargetKind.disabled = entities.length < 2;
  }

  function setRelationshipEntityOptions(selectEl, entities) {
    if (!selectEl) return;
    var previous = selectEl.value;
    selectEl.__allEntityOptions = (entities || []).map(function (e) {
      return { value: e.key, label: e.label, kind: e.kind || "unknown" };
    });

    selectEl.innerHTML = "";
    selectEl.__allEntityOptions.forEach(function (item) {
      var opt = document.createElement("option");
      opt.value = item.value;
      opt.textContent = item.label;
      selectEl.appendChild(opt);
    });

    if (previous && selectEl.querySelector('option[value="' + cssEscapeValue(previous) + '"]')) {
      selectEl.value = previous;
    }
  }

  function filterRelationshipEntityOptions(selectEl, query, kindFilter) {
    if (!selectEl) return;
    var allItems = selectEl.__allEntityOptions || [];
    var previous = selectEl.value;
    var q = (query || "").trim().toLowerCase();
    var kind = (kindFilter || "all").trim().toLowerCase();
    var filtered = !q ? allItems : allItems.filter(function (item) {
      return item.label.toLowerCase().indexOf(q) >= 0 || item.value.toLowerCase().indexOf(q) >= 0;
    });
    if (kind && kind !== "all") {
      filtered = filtered.filter(function (item) {
        return (item.kind || "").toLowerCase() === kind;
      });
    }

    selectEl.innerHTML = "";
    filtered.forEach(function (item) {
      var opt = document.createElement("option");
      opt.value = item.value;
      opt.textContent = item.label;
      selectEl.appendChild(opt);
    });

    if (!filtered.length) {
      var emptyOpt = document.createElement("option");
      emptyOpt.value = "";
      emptyOpt.textContent = "No matches";
      selectEl.appendChild(emptyOpt);
      selectEl.value = "";
      return;
    }

    if (previous && filtered.some(function (item) { return item.value === previous; })) {
      selectEl.value = previous;
    } else {
      selectEl.selectedIndex = 0;
    }
  }

  function cssEscapeValue(value) {
    if (window.CSS && typeof window.CSS.escape === "function") {
      return window.CSS.escape(value);
    }
    return String(value).replace(/["\\]/g, "\\$&");
  }
  function renderRelationships(relationships, campaign) {
    if (!relationshipsSection) return;
    relationshipsSection.classList.remove("hidden");

    var items = relationships || [];
    lastRelationshipItems = items.slice();
    lastRelationshipCampaign = campaign || {};
    relationshipsCount.textContent = "(" + items.length + ")";

    populateRelationshipSelects(campaign || {});
    renderRelationshipGraph(items, campaign || {});

    if (!items.length) {
      relationshipsList.innerHTML = '<p class="placeholder">No relationships yet.</p>';
      return;
    }

    relationshipsList.innerHTML = "";
    items.forEach(function (rel) {
      var source = entityLabelFromKey(campaign, rel.source_key || "");
      var target = entityLabelFromKey(campaign, rel.target_key || "");
      var typeLabel = rel.type_label || rel.relation_type_label || rel.type_key || rel.relation_type_key || "(unknown)";
      var category = rel.type_category || "general";

      var card = document.createElement("div");
      card.className = "entity-card";
      card.innerHTML =
        '<div class="entity-display">' +
          '<div class="entity-info">' +
            '<strong class="entity-name">' + escapeHtml(source) + ' -> ' + escapeHtml(target) + '</strong>' +
            '<span class="entity-meta">' + escapeHtml(typeLabel) + ' [' + escapeHtml(category) + ']</span>' +
          '</div>' +
          '<span class="entity-desc">' + escapeHtml(rel.notes || "") + '</span>' +
          '<button class="btn-small btn-edit-entity" title="Edit">Edit</button>' +
        '</div>';
      var editBtn = card.querySelector(".btn-edit-entity");
      if (editBtn) {
        editBtn.addEventListener("click", function () {
          if (appMode !== "live") return;
          relationshipEditOriginal = {
            source_key: rel.source_key || "",
            target_key: rel.target_key || "",
            type_key: rel.type_key || rel.relation_type_key || "",
          };
          if (relSourceSearch) relSourceSearch.value = "";
          if (relTargetSearch) relTargetSearch.value = "";
          if (relSourceKind) relSourceKind.value = "all";
          if (relTargetKind) relTargetKind.value = "all";
          applyRelationshipEntityFilters(relSourceSelect, relSourceSearch, relSourceKind);
          applyRelationshipEntityFilters(relTargetSelect, relTargetSearch, relTargetKind);
          if (relSourceSelect) relSourceSelect.value = normalizeEntityKey(rel.source_key || "");
          if (relTargetSelect) relTargetSelect.value = normalizeEntityKey(rel.target_key || "");
          if (relTypeInput) relTypeInput.value = typeLabel;
          if (relCategoryInput) relCategoryInput.value = category;
          if (relNotesInput) relNotesInput.value = rel.notes || "";
          if (addRelationshipBtn) addRelationshipBtn.classList.add("hidden");
          if (addRelationshipForm) addRelationshipForm.classList.remove("hidden");
          if (relTypeInput) relTypeInput.focus();
        });
      }
      if (appMode !== "live" && editBtn) editBtn.classList.add("hidden");
      relationshipsList.appendChild(card);
    });
  }

  if (toggleRelationshipGraphBtn) {
    toggleRelationshipGraphBtn.addEventListener("click", function () {
      setRelationshipGraphVisible(!relationshipGraphVisible);
      renderRelationshipGraph(lastRelationshipItems, lastRelationshipCampaign || {});
    });
  }

  function onGraphFiltersChanged() {
    relationshipGraphFilters.players = !graphFilterPlayers || !!graphFilterPlayers.checked;
    relationshipGraphFilters.npcs = !graphFilterNpcs || !!graphFilterNpcs.checked;
    relationshipGraphFilters.locations = !graphFilterLocations || !!graphFilterLocations.checked;
    relationshipGraphFilters.entities = !graphFilterEntities || !!graphFilterEntities.checked;
    renderRelationshipGraph(lastRelationshipItems, lastRelationshipCampaign || {});
  }

  function applyRelationshipEntityFilters(selectEl, searchEl, kindEl) {
    var query = searchEl ? searchEl.value : "";
    var kind = kindEl ? kindEl.value : "all";
    filterRelationshipEntityOptions(selectEl, query, kind);
  }

  if (graphFilterPlayers) graphFilterPlayers.addEventListener("change", onGraphFiltersChanged);
  if (graphFilterNpcs) graphFilterNpcs.addEventListener("change", onGraphFiltersChanged);
  if (graphFilterLocations) graphFilterLocations.addEventListener("change", onGraphFiltersChanged);
  if (graphFilterEntities) graphFilterEntities.addEventListener("change", onGraphFiltersChanged);
  if (relSourceSearch) {
    relSourceSearch.addEventListener("input", function () {
      applyRelationshipEntityFilters(relSourceSelect, relSourceSearch, relSourceKind);
    });
  }
  if (relTargetSearch) {
    relTargetSearch.addEventListener("input", function () {
      applyRelationshipEntityFilters(relTargetSelect, relTargetSearch, relTargetKind);
    });
  }
  if (relSourceKind) {
    relSourceKind.addEventListener("change", function () {
      applyRelationshipEntityFilters(relSourceSelect, relSourceSearch, relSourceKind);
    });
  }
  if (relTargetKind) {
    relTargetKind.addEventListener("change", function () {
      applyRelationshipEntityFilters(relTargetSelect, relTargetSearch, relTargetKind);
    });
  }

  onGraphFiltersChanged();

  setRelationshipGraphVisible(false);

  // Collapse toggles
  playersHeader.addEventListener("click", function () {
    playersBody.classList.toggle("collapsed");
    playersHeader.querySelector(".collapse-arrow").classList.toggle("rotated");
  });
  npcsHeader.addEventListener("click", function () {
    npcsBody.classList.toggle("collapsed");
    npcsHeader.querySelector(".collapse-arrow").classList.toggle("rotated");
  });
  if (locationsHeader) {
    locationsHeader.addEventListener("click", function () {
      locationsBody.classList.toggle("collapsed");
      locationsHeader.querySelector(".collapse-arrow").classList.toggle("rotated");
    });
  }
  if (entitiesHeader) {
    entitiesHeader.addEventListener("click", function () {
      entitiesBody.classList.toggle("collapsed");
      entitiesHeader.querySelector(".collapse-arrow").classList.toggle("rotated");
    });
  }
  if (relationshipsHeader) {
    relationshipsHeader.addEventListener("click", function () {
      relationshipsBody.classList.toggle("collapsed");
      relationshipsHeader.querySelector(".collapse-arrow").classList.toggle("rotated");
    });
  }

  // Add Location form
  if (addLocationBtn) {
    addLocationBtn.addEventListener("click", function () {
      addLocationBtn.classList.add("hidden");
      addLocationForm.classList.remove("hidden");
      var input = document.getElementById("new-location-name");
      if (input) input.focus();
    });
  }
  if (addLocationCancel) {
    addLocationCancel.addEventListener("click", function () {
      addLocationForm.classList.add("hidden");
      addLocationBtn.classList.remove("hidden");
    });
  }
  if (addLocationForm) {
    addLocationForm.addEventListener("submit", function (e) {
      e.preventDefault();
      if (!activeCampaignId || appMode !== "live") return;

      var nameInput = document.getElementById("new-location-name");
      var descInput = document.getElementById("new-location-desc");
      var reqBody = {
        name: nameInput ? nameInput.value.trim() : "",
        description: descInput ? descInput.value.trim() : "",
      };
      if (!reqBody.name) return;

      var saveBtn = addLocationForm.querySelector(".btn-save");
      saveBtn.disabled = true;
      saveBtn.textContent = "Saving...";

      fetch("/api/campaigns/" + activeCampaignId + "/locations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(reqBody),
      })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data.ok) {
            if (nameInput) nameInput.value = "";
            if (descInput) descInput.value = "";
            addLocationForm.classList.add("hidden");
            addLocationBtn.classList.remove("hidden");
            fetchCampaignInfo();
          } else {
            alert("Error: " + (data.error || "Unknown error"));
          }
        })
        .catch(function () { alert("Failed to add location."); })
        .finally(function () {
          saveBtn.disabled = false;
          saveBtn.textContent = "Save";
      });
    });
  }

  // Add Entity form
  if (addEntityBtn) {
    addEntityBtn.addEventListener("click", function () {
      addEntityBtn.classList.add("hidden");
      addEntityForm.classList.remove("hidden");
      var input = document.getElementById("new-entity-name");
      if (input) input.focus();
    });
  }
  if (addEntityCancel) {
    addEntityCancel.addEventListener("click", function () {
      addEntityForm.classList.add("hidden");
      addEntityBtn.classList.remove("hidden");
    });
  }
  if (addEntityForm) {
    addEntityForm.addEventListener("submit", function (e) {
      e.preventDefault();
      if (!activeCampaignId || appMode !== "live") return;

      var nameInput = document.getElementById("new-entity-name");
      var typeInput = document.getElementById("new-entity-type");
      var descInput = document.getElementById("new-entity-desc");
      var reqBody = {
        name: nameInput ? nameInput.value.trim() : "",
        entity_type: typeInput ? typeInput.value.trim() : "group",
        description: descInput ? descInput.value.trim() : "",
      };
      if (!reqBody.name) return;
      if (!reqBody.entity_type) reqBody.entity_type = "group";

      var saveBtn = addEntityForm.querySelector(".btn-save");
      saveBtn.disabled = true;
      saveBtn.textContent = "Saving...";

      fetch("/api/campaigns/" + activeCampaignId + "/entities", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(reqBody),
      })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data.ok) {
            if (nameInput) nameInput.value = "";
            if (typeInput) typeInput.value = "group";
            if (descInput) descInput.value = "";
            addEntityForm.classList.add("hidden");
            addEntityBtn.classList.remove("hidden");
            fetchCampaignInfo();
          } else {
            alert("Error: " + (data.error || "Unknown error"));
          }
        })
        .catch(function () { alert("Failed to add entity."); })
        .finally(function () {
          saveBtn.disabled = false;
          saveBtn.textContent = "Save";
        });
    });
  }
  // Add NPC form
  addNpcBtn.addEventListener("click", function () {
    addNpcBtn.classList.add("hidden");
    addNpcForm.classList.remove("hidden");
    document.getElementById("new-npc-name").focus();
  });
  addNpcCancel.addEventListener("click", function () {
    addNpcForm.classList.add("hidden");
    addNpcBtn.classList.remove("hidden");
  });
  addNpcForm.addEventListener("submit", function (e) {
    e.preventDefault();
    var reqBody = {
      name: document.getElementById("new-npc-name").value.trim(),
      description: document.getElementById("new-npc-desc").value.trim(),
    };
    if (!reqBody.name) return;
    var saveBtn = addNpcForm.querySelector(".btn-save");
    saveBtn.disabled = true;
    saveBtn.textContent = "Saving...";

    if (appMode !== "live") return;
    fetch("/api/campaigns/" + activeCampaignId + "/npcs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(reqBody),
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.ok) {
          document.getElementById("new-npc-name").value = "";
          document.getElementById("new-npc-desc").value = "";
          addNpcForm.classList.add("hidden");
          addNpcBtn.classList.remove("hidden");
          fetchCampaignInfo();
        } else {
          alert("Error: " + (data.error || "Unknown error"));
        }
      })
      .catch(function () { alert("Failed to add NPC."); })
      .finally(function () {
        saveBtn.disabled = false;
        saveBtn.textContent = "Save";
      });
  });

  // Questions polling


  // Add Relationship form
  if (addRelationshipBtn) {
    addRelationshipBtn.addEventListener("click", function () {
      relationshipEditOriginal = null;
      addRelationshipBtn.classList.add("hidden");
      addRelationshipForm.classList.remove("hidden");
      if (relTypeInput) relTypeInput.focus();
    });
  }
  if (addRelationshipCancel) {
    addRelationshipCancel.addEventListener("click", function () {
      addRelationshipForm.classList.add("hidden");
      addRelationshipBtn.classList.remove("hidden");
      relationshipEditOriginal = null;
      if (relSourceSearch) relSourceSearch.value = "";
      if (relTargetSearch) relTargetSearch.value = "";
      if (relSourceKind) relSourceKind.value = "all";
      if (relTargetKind) relTargetKind.value = "all";
      applyRelationshipEntityFilters(relSourceSelect, relSourceSearch, relSourceKind);
      applyRelationshipEntityFilters(relTargetSelect, relTargetSearch, relTargetKind);
    });
  }
  if (addRelationshipForm) {
    addRelationshipForm.addEventListener("submit", function (e) {
      e.preventDefault();
      if (!activeCampaignId) return;

      var reqBody = {
        source_key: (relSourceSelect && relSourceSelect.value) || "",
        target_key: (relTargetSelect && relTargetSelect.value) || "",
        relation_type: (relTypeInput && relTypeInput.value.trim()) || "",
        category: (relCategoryInput && relCategoryInput.value.trim()) || "general",
        notes: (relNotesInput && relNotesInput.value.trim()) || "",
      };

      if (!reqBody.source_key || !reqBody.target_key || !reqBody.relation_type) return;

      var saveBtn = addRelationshipForm.querySelector(".btn-save");
      saveBtn.disabled = true;
      saveBtn.textContent = "Saving...";

      var isEditing = !!relationshipEditOriginal;
      var url = "/api/campaigns/" + activeCampaignId + "/relationships";
      if (isEditing) {
        reqBody.old_source_key = relationshipEditOriginal.source_key;
        reqBody.old_target_key = relationshipEditOriginal.target_key;
        reqBody.old_type_key = relationshipEditOriginal.type_key;
      }

      if (appMode !== "live") return;
      fetch(url, {
        method: isEditing ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(reqBody),
      })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data.ok) {
            if (relTypeInput) relTypeInput.value = "";
            if (relNotesInput) relNotesInput.value = "";
            if (relCategoryInput) relCategoryInput.value = "general";
            addRelationshipForm.classList.add("hidden");
            addRelationshipBtn.classList.remove("hidden");
            relationshipEditOriginal = null;
            fetchCampaignInfo();
          } else {
            alert("Error: " + (data.error || "Unknown error"));
          }
        })
        .catch(function () { alert("Failed to save relationship."); })
        .finally(function () {
          saveBtn.disabled = false;
          saveBtn.textContent = "Save";
        });
    });
  }

  function pollQuestions() {
    fetch("/api/questions")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var questions = data.questions || [];
        renderQuestions(questions);
        if (questionsBadge) {
          updateQuestionsBadge(questions.length);
        }
      })
      .catch(function () {});
  }

  function updateQuestionsBadge(count) {
    if (!questionsBadge) return;
    if (count > 0) {
      questionsBadge.textContent = count;
      questionsBadge.classList.remove("hidden");
      if (count > previousQuestionCount) {
        questionsBadge.classList.remove("pulse");
        void questionsBadge.offsetWidth;
        questionsBadge.classList.add("pulse");
      }
    } else {
      questionsBadge.classList.add("hidden");
    }
    previousQuestionCount = count;
  }

  function renderQuestions(questions) {
    if (questions.length === 0) {
      questionsList.innerHTML = '<p class="placeholder">No pending questions.</p>';
      return;
    }
    questionsList.innerHTML = "";
    questions.forEach(function (q) {
      var card = document.createElement("div");
      card.className = "question-card";
      card.innerHTML =
        '<div class="q-icon">?</div>' +
        '<div class="q-content">' +
        "<p>" + escapeHtml(q.question) + "</p>" +
        '<form data-qid="' + q.id + '">' +
        '<input type="text" placeholder="Your answer..." required />' +
        '<button type="submit">Answer</button>' +
        "</form>" +
        '<div class="q-feedback hidden"></div>' +
        "</div>";
      card.querySelector("form").addEventListener("submit", function (e) {
        e.preventDefault();
        var form = this;
        var input = form.querySelector("input");
        var btn = form.querySelector("button");
        var feedback = card.querySelector(".q-feedback");

        btn.disabled = true;
        btn.textContent = "Sending...";

        submitAnswer(q.id, input.value, function (ok) {
          if (ok) {
            feedback.textContent = "Answer saved!";
            feedback.className = "q-feedback success";
            form.classList.add("hidden");
            setTimeout(function () { pollQuestions(); }, 1200);
          } else {
            feedback.textContent = "Failed to save. Try again.";
            feedback.className = "q-feedback error";
            btn.disabled = false;
            btn.textContent = "Answer";
          }
        });
      });
      questionsList.appendChild(card);
    });
  }

  function submitAnswer(qid, answer, callback) {
    fetch("/api/questions/" + qid + "/answer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answer: answer }),
    })
      .then(function (r) { return r.json(); })
      .then(function (data) { callback(data.ok); })
      .catch(function () { callback(false); });
  }


  function setMode(mode) {
    appMode = mode === "browse" ? "browse" : "live";
    if (modeLiveBtn) modeLiveBtn.classList.toggle("active", appMode === "live");
    if (modeBrowseBtn) modeBrowseBtn.classList.toggle("active", appMode === "browse");

    if (browseCampaignsPanel) {
      if (appMode === "browse") browseCampaignsPanel.classList.remove("hidden");
      else browseCampaignsPanel.classList.add("hidden");
    }

    if (statusPanel) statusPanel.classList.toggle("hidden", appMode !== "live");
    if (questionsPanel) questionsPanel.classList.toggle("hidden", appMode !== "live");
    if (sessionsTitleEl) sessionsTitleEl.textContent = appMode === "browse" ? "Campaign Sessions" : "Sessions";

    if (appMode === "browse") {
      viewingHistorical = true;
      loadedLiveSessionId = null;
      backToLiveBtn.classList.add("hidden");
      currentHistoricalSessionId = null;
      if (sessionLogLinkEl) { sessionLogLinkEl.classList.add("hidden"); sessionLogLinkEl.innerHTML = ""; }
      transcriptionFeed.innerHTML = '<p class="placeholder">Select a session to view transcriptions.</p>';
      sessionSummaryEl.innerHTML = '<p class="placeholder">Select a session to view summary.</p>';
      campaignSummaryEl.innerHTML = '<p class="placeholder">Select a session to view campaign summary.</p>';
      if (campaignEditBtn) campaignEditBtn.classList.add("hidden");
      if (addNpcBtn) addNpcBtn.classList.add("hidden");
      if (addLocationBtn) addLocationBtn.classList.add("hidden");
      if (addEntityBtn) addEntityBtn.classList.add("hidden");
      if (addRelationshipBtn) addRelationshipBtn.classList.add("hidden");
      if (addNpcForm) addNpcForm.classList.add("hidden");
      if (addLocationForm) addLocationForm.classList.add("hidden");
      if (addEntityForm) addEntityForm.classList.add("hidden");
      if (addRelationshipForm) addRelationshipForm.classList.add("hidden");
      fetchBrowseCampaigns();
    } else {
      viewingHistorical = false;
      currentHistoricalSessionId = null;
      browseCampaignId = null;
      if (sessionLogLinkEl) sessionLogLinkEl.classList.add("hidden");
      fetchCampaignInfo();
      if (addNpcBtn) addNpcBtn.classList.remove("hidden");
      if (addLocationBtn) addLocationBtn.classList.remove("hidden");
      if (addEntityBtn) addEntityBtn.classList.remove("hidden");
      if (addRelationshipBtn) addRelationshipBtn.classList.remove("hidden");
      fetchSessionList();
      pollQuestions();
    }

    updateFinalizeButton();
  }

  function fetchBrowseCampaigns() {
    fetch("/api/browse/campaigns")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var campaigns = [{
          id: UNCATEGORIZED_BROWSE_ID,
          name: "Sin campana",
          game_system: "",
          is_active: false
        }].concat(data.campaigns || []);
        browseCampaignsCache = campaigns.slice();
        renderBrowseCampaignList(campaigns);

        var preferred = browseCampaignId || data.active_campaign_id || UNCATEGORIZED_BROWSE_ID;
        if (preferred) {
          selectBrowseCampaign(preferred);
        } else {
          sessionListEl.innerHTML = '<p class="placeholder">No sessions yet.</p>';
        }
      })
      .catch(function () {
        if (browseCampaignListEl) browseCampaignListEl.innerHTML = '<p class="placeholder">Failed to load campaigns.</p>';
      });
  }

  function renderBrowseCampaignList(campaigns) {
    if (!browseCampaignListEl) return;
    if (!campaigns.length) {
      browseCampaignListEl.innerHTML = '<p class="placeholder">No campaigns in database.</p>';
      return;
    }

    browseCampaignListEl.innerHTML = "";
    campaigns.forEach(function (campaign) {
      var item = document.createElement("div");
      item.className = "campaign-item" + (campaign.id === browseCampaignId ? " active" : "");
      item.dataset.campaignId = campaign.id;

      var meta = [];
      if (campaign.game_system) meta.push(campaign.game_system);
      if (campaign.is_active) meta.push("active");
      item.innerHTML =
        '<div class="campaign-item-name">' + escapeHtml(campaign.name || campaign.id) + "</div>" +
        '<div class="campaign-item-meta">' + escapeHtml(meta.join(" | ")) + "</div>";

      item.addEventListener("click", function () {
        selectBrowseCampaign(campaign.id);
      });
      browseCampaignListEl.appendChild(item);
    });
  }

  function selectBrowseCampaign(campaignId) {
    browseCampaignId = campaignId;

    if (campaignId === UNCATEGORIZED_BROWSE_ID) {
      currentCampaign = null;
      activeCampaignId = null;
      campaignBar.classList.remove("hidden");
      campaignNameEl.textContent = "Sin campana";
      campaignSystemEl.textContent = "";
      campaignMasterEl.textContent = "";
      if (campaignEditBtn) campaignEditBtn.classList.add("hidden");
      playersSection.classList.add("hidden");
      npcsSection.classList.add("hidden");
      if (locationsSection) locationsSection.classList.add("hidden");
      if (entitiesSection) entitiesSection.classList.add("hidden");
      if (relationshipsSection) relationshipsSection.classList.add("hidden");
      renderBrowseCampaignList(browseCampaignsCache);
      fetchSessionList();
      return;
    }

    fetch("/api/browse/campaigns/" + encodeURIComponent(campaignId))
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var campaign = data.campaign;
        if (!campaign) {
          return;
        }
        currentCampaign = campaign;
        activeCampaignId = campaign.id;
        renderCampaignBar(campaign);
        campaignEditBtn.classList.add("hidden");
        renderPlayers(campaign.players || []);
        renderNpcs(campaign.npcs || []);
        renderLocations(campaign.locations || []);
        renderEntities(campaign.entities || []);
        renderRelationships(campaign.relationships || [], campaign);
        addNpcBtn.classList.add("hidden");
        if (addLocationBtn) addLocationBtn.classList.add("hidden");
        if (addEntityBtn) addEntityBtn.classList.add("hidden");
        addRelationshipBtn.classList.add("hidden");
        addNpcForm.classList.add("hidden");
        if (addLocationForm) addLocationForm.classList.add("hidden");
        if (addEntityForm) addEntityForm.classList.add("hidden");
        addRelationshipForm.classList.add("hidden");
        renderBrowseCampaignList(browseCampaignsCache);
        fetchSessionList();
      })
      .catch(function () {});
  }

  function renderSessionLogLink(sessionId) {
    if (!sessionLogLinkEl || !sessionId) return;
    fetch("/api/sessions/" + encodeURIComponent(sessionId) + "/logs")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data.exists || !data.explorer_url) {
          sessionLogLinkEl.classList.add("hidden");
          sessionLogLinkEl.innerHTML = "";
          return;
        }
        sessionLogLinkEl.classList.remove("hidden");
        sessionLogLinkEl.innerHTML = '<a href="' + escapeAttr(data.explorer_url) + '" target="_blank" rel="noopener">Open session logs</a>';
      })
      .catch(function () {
        sessionLogLinkEl.classList.add("hidden");
      });
  }

  // Session history

  function fetchSessionList() {
    fetch("/api/status")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        activeSessionId = data.active_session_id;
        var limits = data.web_limits || {};
        if (typeof limits.live_feed_max_items === "number" && limits.live_feed_max_items > 0) {
          maxFeedItems = limits.live_feed_max_items;
        }
        updateFinalizeButton();

        if (appMode === "live" && !viewingHistorical && activeSessionId && loadedLiveSessionId !== activeSessionId) {
          loadLiveSessionSnapshot(activeSessionId);
        }
      })
      .catch(function () {});

    var sessionsUrl;
    if (appMode === "browse") {
      if (browseCampaignId === UNCATEGORIZED_BROWSE_ID) {
        sessionsUrl = "/api/browse/sessions/uncategorized";
      } else if (browseCampaignId) {
        sessionsUrl = "/api/campaigns/" + browseCampaignId + "/sessions";
      } else {
        sessionsUrl = "/api/sessions";
      }
    } else if (activeCampaignId) {
      sessionsUrl = "/api/campaigns/" + activeCampaignId + "/sessions";
    } else {
      sessionsUrl = "/api/sessions";
    }

    fetch(sessionsUrl)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        renderSessionList(data.sessions || []);
      })
      .catch(function () {});
  }

  function renderSessionList(sessions) {
    if (sessions.length === 0) {
      sessionListEl.innerHTML = '<p class="placeholder">No sessions yet.</p>';
      return;
    }
    sessionListEl.innerHTML = "";
    sessions.forEach(function (s) {
      var item = document.createElement("div");
      var isActive = s.id === activeSessionId;
      item.className = "session-item" + (isActive ? " active" : "") +
        (s.status === "completed" ? " completed" : "");
      item.dataset.sessionId = s.id;

      var label = isActive ? "LIVE" : (s.status || "");
      var dateStr = s.started_at ? formatDate(s.started_at) : "";
      var preview = s.summary_preview || "";
      var duration = s.duration_minutes ? formatDuration(s.duration_minutes) : "";

      var metaLine = "";
      if (dateStr || duration) {
        metaLine += '<div class="session-date">';
        metaLine += escapeHtml(dateStr);
        if (duration) {
          metaLine += ' <span class="session-duration">(' + escapeHtml(duration) + ')</span>';
        }
        metaLine += "</div>";
      }

      var indicators = "";
      if (s.has_summary) {
        indicators += '<span class="session-indicator" title="Has summary">S</span>';
      }

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

      if (appMode === "browse") {
        item.addEventListener("click", function () {
          loadHistoricalSession(s.id);
          highlightSession(s.id);
        });
      } else if (!isActive) {
        item.addEventListener("click", function () {
          loadHistoricalSession(s.id);
          highlightSession(s.id);
        });
      } else {
        item.addEventListener("click", function () {
          switchToLive();
        });
      }

      sessionListEl.appendChild(item);
    });
  }

  function highlightSession(sessionId) {
    var items = sessionListEl.querySelectorAll(".session-item");
    for (var i = 0; i < items.length; i++) {
      items[i].classList.remove("selected");
      if (items[i].dataset.sessionId === sessionId) {
        items[i].classList.add("selected");
      }
    }
  }

  function loadLiveSessionSnapshot(sessionId) {
    Promise.all([
      fetch("/api/sessions/" + sessionId + "/transcriptions").then(function (r) { return r.json(); }),
      fetch("/api/sessions/" + sessionId + "/summary").then(function (r) { return r.json(); })
    ])
      .then(function (results) {
        var transData = results[0];
        var summData = results[1];

        transcriptionFeed.innerHTML = "";
        var transcriptions = transData.transcriptions || [];
        if (transcriptions.length === 0) {
          transcriptionFeed.innerHTML = '<p class="placeholder">No transcriptions yet.</p>';
        } else {
          transcriptions.forEach(function (t) { addTranscription(t); });
        }

        sessionSummaryEl.textContent = summData.session_summary || "";
        campaignSummaryEl.textContent = summData.campaign_summary || "";
        loadedLiveSessionId = sessionId;
        renderSessionLogLink(sessionId);
      })
      .catch(function () {});
  }

  function loadHistoricalSession(sessionId) {
    viewingHistorical = true;
    currentHistoricalSessionId = sessionId;
    if (appMode === "live") backToLiveBtn.classList.remove("hidden");
    renderSessionLogLink(sessionId);

    Promise.all([
      fetch("/api/sessions/" + sessionId + "/transcriptions").then(function (r) { return r.json(); }),
      fetch("/api/sessions/" + sessionId + "/summary").then(function (r) { return r.json(); })
    ])
      .then(function (results) {
        var transData = results[0];
        var summData = results[1];

        transcriptionFeed.innerHTML = "";
        var transcriptions = transData.transcriptions || [];
        if (transcriptions.length === 0) {
          transcriptionFeed.innerHTML = '<p class="placeholder">No transcriptions for this session.</p>';
        } else {
          transcriptions.forEach(function (t) { addTranscription(t); });
        }

        sessionSummaryEl.textContent = summData.session_summary || "(no summary)";
        campaignSummaryEl.textContent = summData.campaign_summary || "(no campaign summary)";
      })
      .catch(function () {
        transcriptionFeed.innerHTML = '<p class="placeholder">Failed to load session data.</p>';
      });
  }

  function switchToLive() {
    if (appMode !== "live") return;
    viewingHistorical = false;
    currentHistoricalSessionId = null;
    loadedLiveSessionId = null;
    backToLiveBtn.classList.add("hidden");

    if (sessionLogLinkEl) {
      sessionLogLinkEl.classList.add("hidden");
      sessionLogLinkEl.innerHTML = "";
    }

    var items = sessionListEl.querySelectorAll(".session-item");
    for (var i = 0; i < items.length; i++) {
      items[i].classList.remove("selected");
    }

    transcriptionFeed.innerHTML = "";
    sessionSummaryEl.innerHTML = '<p class="placeholder">Waiting for summary updates&hellip;</p>';
    campaignSummaryEl.innerHTML = '<p class="placeholder">No campaign summary yet.</p>';
    if (activeSessionId) {
      loadLiveSessionSnapshot(activeSessionId);
    }
  }

  backToLiveBtn.addEventListener("click", switchToLive);

  function getSessionIdForTranscriptView() {
    if (currentHistoricalSessionId) {
      return currentHistoricalSessionId;
    }
    if (appMode === "live" && activeSessionId) {
      return activeSessionId;
    }
    return null;
  }

  if (openTranscriptBtn) {
    openTranscriptBtn.addEventListener("click", function () {
      var sessionId = getSessionIdForTranscriptView();
      if (!sessionId) {
        alert("No active or selected session.");
        return;
      }
      var url = "/transcript.html?session_id=" + encodeURIComponent(sessionId);
      window.open(url, "_blank");
    });
  }

  // Finalize session

  function updateFinalizeButton() {
    var show = !!(appMode === "live" && activeSessionId && !viewingHistorical);

    if (finalizeBtn) {
      if (show) {
        finalizeBtn.classList.remove("hidden");
      } else {
        finalizeBtn.classList.add("hidden");
      }
    }

    if (refreshSummaryBtn) {
      if (show) {
        refreshSummaryBtn.classList.remove("hidden");
      } else {
        refreshSummaryBtn.classList.add("hidden");
      }
    }
  }

  if (refreshSummaryBtn) {
    refreshSummaryBtn.addEventListener("click", function () {
      if (!activeSessionId) return;

      refreshSummaryBtn.disabled = true;
      refreshSummaryBtn.textContent = "Updating...";

      fetch("/api/sessions/" + activeSessionId + "/refresh-summary", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (!data.ok) {
            alert("Error: " + (data.error || "Failed to update summary"));
          }
        })
        .catch(function () {
          alert("Failed to update summary.");
        })
        .finally(function () {
          refreshSummaryBtn.disabled = false;
          refreshSummaryBtn.textContent = "Update Summary";
        });
    });
  }

  if (finalizeBtn) {
    finalizeBtn.addEventListener("click", function () {
      if (!activeSessionId) return;
      if (!confirm("Finalize the current session? This will generate the final summary and end the session.")) {
        return;
      }
      finalizeBtn.disabled = true;
      finalizeBtn.textContent = "Finalizing...";

      fetch("/api/sessions/" + activeSessionId + "/finalize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data.ok) {
            activeSessionId = null;
            updateFinalizeButton();
            setTimeout(fetchSessionList, 2000);
          } else {
            alert("Error: " + (data.error || "Failed to finalize"));
          }
        })
        .catch(function () {
          alert("Failed to finalize session.");
        })
        .finally(function () {
          finalizeBtn.disabled = false;
          finalizeBtn.textContent = "Finalize Session";
        });
    });
  }

  // Init

  if (modeLiveBtn) {
    modeLiveBtn.addEventListener("click", function () {
      setMode("live");
    });
  }

  if (modeBrowseBtn) {
    modeBrowseBtn.addEventListener("click", function () {
      setMode("browse");
    });
  }

  // Generate Campaign Summary button
  var generateCampaignSummaryBtn = document.getElementById("btn-generate-campaign-summary");
  if (generateCampaignSummaryBtn) {
    generateCampaignSummaryBtn.addEventListener("click", function () {
      var campaignId = generateCampaignSummaryBtn.dataset.campaignId;
      if (!campaignId) return;
      var originalText = generateCampaignSummaryBtn.textContent;
      generateCampaignSummaryBtn.disabled = true;
      generateCampaignSummaryBtn.textContent = "Generatingâ€¦";
      fetch("/api/campaigns/" + encodeURIComponent(campaignId) + "/campaign-summaries/generate", {
        method: "POST",
      })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data.status === "ok") {
            if (data.campaign_summary && campaignSummaryEl) {
              campaignSummaryEl.innerHTML = "<p>" + escapeHtml(data.campaign_summary) + "</p>";
            }
            var msg = "Campaign summary generated from " + data.session_count + " session(s).";
            if (data.sessions_processed > 0) {
              msg += " Also generated " + data.sessions_processed + " missing session summary(s).";
            }
            alert(msg);
          } else {
            alert("Error: " + (data.detail || "Unknown error"));
          }
        })
        .catch(function () { alert("Failed to generate campaign summary."); })
        .finally(function () {
          generateCampaignSummaryBtn.disabled = false;
          generateCampaignSummaryBtn.textContent = originalText;
        });
    });
  }

  connectWS();
  fetchCampaignInfo();
  pollQuestions();
  setInterval(function () {
    if (appMode === "live") pollQuestions();
  }, 5000);

  setTimeout(function () {
    fetchSessionList();
    setInterval(fetchSessionList, 30000);
  }, 500);

  setMode("live");
})();


