/* RPG Scribe — frontend WebSocket client and DOM updates */

(function () {
  "use strict";

  // ── Elements ──────────────────────────────────────────────────

  var connectionBadge = document.getElementById("connection-badge");
  var transcriptionFeed = document.getElementById("transcription-feed");
  var sessionSummaryEl = document.getElementById("session-summary");
  var campaignSummaryEl = document.getElementById("campaign-summary");
  var questionsList = document.getElementById("questions-list");
  var componentStatusEl = document.getElementById("component-status");
  var sessionListEl = document.getElementById("session-list");
  var backToLiveBtn = document.getElementById("back-to-live");
  var openTranscriptBtn = document.getElementById("open-transcript-btn");

  // Campaign bar elements
  var campaignBar = document.getElementById("campaign-bar");
  var campaignDisplay = document.getElementById("campaign-display");
  var campaignNameEl = document.getElementById("campaign-name");
  var campaignSystemEl = document.getElementById("campaign-system");
  var campaignEditBtn = document.getElementById("campaign-edit-btn");
  var campaignEditForm = document.getElementById("campaign-edit-form");
  var campaignEditCancel = document.getElementById("campaign-edit-cancel");
  var editNameInput = document.getElementById("edit-campaign-name");
  var editSystemInput = document.getElementById("edit-campaign-system");
  var editDescInput = document.getElementById("edit-campaign-desc");
  var editInstructionsInput = document.getElementById("edit-campaign-instructions");

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

  // Finalize button
  var finalizeBtn = document.getElementById("finalize-btn");

  // ── State ─────────────────────────────────────────────────────

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

  // ── WebSocket ─────────────────────────────────────────────────

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
      if (viewingHistorical) return; // ignore live updates when viewing history
      var msg;
      try { msg = JSON.parse(evt.data); } catch (_) { return; }
      handleMessage(msg);
    };
  }

  // ── Message handlers ──────────────────────────────────────────

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

  // ── Campaign info ───────────────────────────────────────────────

  function fetchCampaignInfo() {
    fetch("/api/campaigns")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.campaign) {
          currentCampaign = data.campaign;
          activeCampaignId = data.campaign.id;
          renderCampaignBar(data.campaign);
          renderPlayers(data.campaign.players || []);
          renderNpcs(data.campaign.npcs || []);
        } else {
          // No campaign loaded — show "Resume mode"
          campaignBar.classList.remove("hidden");
          campaignNameEl.textContent = "No campaign \u2014 Resume mode";
          campaignSystemEl.textContent = "";
          campaignEditBtn.classList.add("hidden");
          playersSection.classList.add("hidden");
          npcsSection.classList.add("hidden");
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

    // Hide edit for generic campaigns
    if (campaign.is_generic) {
      campaignEditBtn.classList.add("hidden");
      campaignNameEl.textContent = "No campaign \u2014 Resume mode";
      campaignSystemEl.textContent = "";
      playersSection.classList.add("hidden");
      npcsSection.classList.add("hidden");
    } else {
      campaignEditBtn.classList.remove("hidden");
    }
  }

  function openCampaignEdit() {
    if (!currentCampaign) return;
    editNameInput.value = currentCampaign.name || "";
    editSystemInput.value = currentCampaign.game_system || "";
    editDescInput.value = currentCampaign.description || "";
    editInstructionsInput.value = currentCampaign.custom_instructions || "";

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
    if (!currentCampaign || !activeCampaignId) return;

    var body = {
      name: editNameInput.value.trim(),
      game_system: editSystemInput.value.trim(),
      description: editDescInput.value.trim(),
      custom_instructions: editInstructionsInput.value.trim(),
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

  // ── Players & NPCs ──────────────────────────────────────────────

  function renderPlayers(players) {
    if (!players || players.length === 0) {
      playersSection.classList.add("hidden");
      return;
    }
    playersSection.classList.remove("hidden");
    playersCount.textContent = "(" + players.length + ")";
    playersList.innerHTML = "";

    players.forEach(function (p) {
      var card = document.createElement("div");
      card.className = "entity-card";
      card.innerHTML =
        '<div class="entity-display">' +
          '<div class="entity-info">' +
            '<strong class="entity-name">' + escapeHtml(p.character_name) + '</strong>' +
            '<span class="entity-meta">' + escapeHtml(p.discord_name) + '</span>' +
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

      npcsList.appendChild(card);
    });
  }

  // Collapse toggles
  playersHeader.addEventListener("click", function () {
    playersBody.classList.toggle("collapsed");
    playersHeader.querySelector(".collapse-arrow").classList.toggle("rotated");
  });
  npcsHeader.addEventListener("click", function () {
    npcsBody.classList.toggle("collapsed");
    npcsHeader.querySelector(".collapse-arrow").classList.toggle("rotated");
  });

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

  // ── Questions polling ─────────────────────────────────────────

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

  // ── Session history ───────────────────────────────────────────

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

        if (!viewingHistorical && activeSessionId && loadedLiveSessionId !== activeSessionId) {
          loadLiveSessionSnapshot(activeSessionId);
        }
      })
      .catch(function () {});

    var sessionsUrl;
    if (activeCampaignId) {
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
        metaLine += '</div>';
      }

      var indicators = '';
      if (s.has_summary) {
        indicators += '<span class="session-indicator" title="Has summary">S</span>';
      }

      item.innerHTML =
        '<div class="session-header">' +
        '<span class="session-id">' + escapeHtml(s.id.substring(0, 8)) + '</span>' +
        '<div class="session-header-right">' +
        indicators +
        '<span class="session-badge ' + (isActive ? 'live' : s.status) + '">' +
        escapeHtml(label) + '</span>' +
        '</div>' +
        '</div>' +
        metaLine +
        (preview ? '<div class="session-preview">' + escapeHtml(preview) + '</div>' : '');

      if (!isActive) {
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
      })
      .catch(function () {});
  }

  function loadHistoricalSession(sessionId) {
    viewingHistorical = true;
    currentHistoricalSessionId = sessionId;
    backToLiveBtn.classList.remove("hidden");

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
    viewingHistorical = false;
    currentHistoricalSessionId = null;
    loadedLiveSessionId = null;
    backToLiveBtn.classList.add("hidden");

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
    if (viewingHistorical && currentHistoricalSessionId) {
      return currentHistoricalSessionId;
    }
    if (activeSessionId) {
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

  // ── Finalize session ───────────────────────────────────────────

  function updateFinalizeButton() {
    if (finalizeBtn) {
      if (activeSessionId && !viewingHistorical) {
        finalizeBtn.classList.remove("hidden");
      } else {
        finalizeBtn.classList.add("hidden");
      }
    }
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

  // ── Init ──────────────────────────────────────────────────────

  connectWS();
  fetchCampaignInfo();
  pollQuestions();
  setInterval(pollQuestions, 5000);

  setTimeout(function () {
    fetchSessionList();
    setInterval(fetchSessionList, 30000);
  }, 500);
})();






