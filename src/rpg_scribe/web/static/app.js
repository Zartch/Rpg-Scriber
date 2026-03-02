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

  // ── State ─────────────────────────────────────────────────────

  var viewingHistorical = false;  // true when viewing a past session
  var activeSessionId = null;     // current live session id
  var activeCampaignId = null;    // current campaign id
  var currentCampaign = null;     // full campaign data object
  var lastStatusTimestamp = {};   // for latency tracking
  var previousQuestionCount = 0;
  var questionsBadge = null;      // may not exist in DOM

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
    transcriptionFeed.scrollTop = transcriptionFeed.scrollHeight;
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
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
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
        } else {
          campaignBar.classList.add("hidden");
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
      systemText += (systemText ? " · " : "") + campaign.language.toUpperCase();
    }
    campaignSystemEl.textContent = systemText ? "(" + systemText + ")" : "";

    // Hide edit for generic campaigns
    if (campaign.is_generic) {
      campaignEditBtn.classList.add("hidden");
      campaignNameEl.textContent = campaign.name + " (generic)";
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
      // Pulse animation when new questions arrive
      if (count > previousQuestionCount) {
        questionsBadge.classList.remove("pulse");
        // Force reflow to restart animation
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
    // First get the active status to know session id
    fetch("/api/status")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        activeSessionId = data.active_session_id;
      })
      .catch(function () {});

    // Then fetch sessions — use campaign-specific or all
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

      // Icons for summary / transcription availability
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

  function loadHistoricalSession(sessionId) {
    viewingHistorical = true;
    backToLiveBtn.classList.remove("hidden");

    // Fetch transcriptions and summary for the historical session
    Promise.all([
      fetch("/api/sessions/" + sessionId + "/transcriptions").then(function (r) { return r.json(); }),
      fetch("/api/sessions/" + sessionId + "/summary").then(function (r) { return r.json(); })
    ])
      .then(function (results) {
        var transData = results[0];
        var summData = results[1];

        // Clear and render transcriptions
        transcriptionFeed.innerHTML = "";
        var transcriptions = transData.transcriptions || [];
        if (transcriptions.length === 0) {
          transcriptionFeed.innerHTML = '<p class="placeholder">No transcriptions for this session.</p>';
        } else {
          transcriptions.forEach(function (t) { addTranscription(t); });
        }

        // Render summary
        sessionSummaryEl.textContent = summData.session_summary || "(no summary)";
        campaignSummaryEl.textContent = summData.campaign_summary || "(no campaign summary)";
      })
      .catch(function () {
        transcriptionFeed.innerHTML = '<p class="placeholder">Failed to load session data.</p>';
      });
  }

  function switchToLive() {
    viewingHistorical = false;
    backToLiveBtn.classList.add("hidden");

    // Remove selected highlighting
    var items = sessionListEl.querySelectorAll(".session-item");
    for (var i = 0; i < items.length; i++) {
      items[i].classList.remove("selected");
    }

    // Restore live view — clear and let WebSocket repopulate
    transcriptionFeed.innerHTML = "";
    sessionSummaryEl.innerHTML = '<p class="placeholder">Waiting for summary updates&hellip;</p>';
    campaignSummaryEl.innerHTML = '<p class="placeholder">No campaign summary yet.</p>';
  }

  backToLiveBtn.addEventListener("click", switchToLive);

  // ── Init ──────────────────────────────────────────────────────

  connectWS();
  fetchCampaignInfo();
  pollQuestions();
  setInterval(pollQuestions, 5000);

  // Delay session list fetch slightly so campaign info is available
  setTimeout(function () {
    fetchSessionList();
    // Refresh session list periodically
    setInterval(fetchSessionList, 30000);
  }, 500);
})();
