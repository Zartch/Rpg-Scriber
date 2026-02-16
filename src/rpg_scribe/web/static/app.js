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
  var questionsBadge = document.getElementById("questions-badge");

  // ── State ─────────────────────────────────────────────────────

  var previousQuestionCount = 0;
  // Track last status timestamp per component for latency display
  var lastStatusTimestamp = {};

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

  // ── Init ──────────────────────────────────────────────────────

  connectWS();
  pollQuestions();
  setInterval(pollQuestions, 5000);
})();
