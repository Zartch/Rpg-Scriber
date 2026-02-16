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

  // ── State ─────────────────────────────────────────────────────

  var viewingHistorical = false;  // true when viewing a past session
  var activeSessionId = null;     // current live session id
  var activeCampaignId = null;    // current campaign id

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
    var d = new Date(ts);
    return d.toLocaleDateString() + " " + d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
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

  // ── Questions polling ─────────────────────────────────────────

  function pollQuestions() {
    fetch("/api/questions")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var questions = data.questions || [];
        renderQuestions(questions);
        updateQuestionsBadge(questions.length);
      })
      .catch(function () {});
  }

  function updateQuestionsBadge(count) {
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
    // First get the active status to know campaign and session ids
    fetch("/api/status")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        activeSessionId = data.active_session_id;
      })
      .catch(function () {});

    fetch("/api/campaigns")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.campaign && data.campaign.id) {
          activeCampaignId = data.campaign.id;
          return fetch("/api/campaigns/" + data.campaign.id + "/sessions");
        }
        return null;
      })
      .then(function (r) { return r ? r.json() : null; })
      .then(function (data) {
        if (data) renderSessionList(data.sessions || []);
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

      item.innerHTML =
        '<div class="session-header">' +
        '<span class="session-id">' + escapeHtml(s.id.substring(0, 8)) + '</span>' +
        '<span class="session-badge ' + (isActive ? 'live' : s.status) + '">' +
        escapeHtml(label) + '</span>' +
        '</div>' +
        (dateStr ? '<div class="session-date">' + escapeHtml(dateStr) + '</div>' : '') +
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
  pollQuestions();
  setInterval(pollQuestions, 5000);
  fetchSessionList();
  // Refresh session list periodically
  setInterval(fetchSessionList, 30000);
})();
