/* RPG Scribe — frontend WebSocket client and DOM updates */

(function () {
  "use strict";

  // ── Elements ──────────────────────────────────────────────────

  const connectionBadge = document.getElementById("connection-badge");
  const transcriptionFeed = document.getElementById("transcription-feed");
  const sessionSummaryEl = document.getElementById("session-summary");
  const campaignSummaryEl = document.getElementById("campaign-summary");
  const questionsList = document.getElementById("questions-list");
  const componentStatusEl = document.getElementById("component-status");

  // ── WebSocket ─────────────────────────────────────────────────

  let ws = null;
  let reconnectDelay = 1000;
  const MAX_RECONNECT = 16000;

  function connectWS() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
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
    dot.className = "status-dot " + data.status;
    msgEl.textContent = data.message || data.status;
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
        renderQuestions(data.questions || []);
      })
      .catch(function () {});
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
        "<p>" + escapeHtml(q.question) + "</p>" +
        '<form data-qid="' + q.id + '">' +
        '<input type="text" placeholder="Your answer..." required />' +
        "<button type=\"submit\">Answer</button></form>";
      card.querySelector("form").addEventListener("submit", function (e) {
        e.preventDefault();
        var input = this.querySelector("input");
        submitAnswer(q.id, input.value);
      });
      questionsList.appendChild(card);
    });
  }

  function submitAnswer(qid, answer) {
    fetch("/api/questions/" + qid + "/answer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answer: answer }),
    })
      .then(function () { pollQuestions(); })
      .catch(function () {});
  }

  // ── Init ──────────────────────────────────────────────────────

  connectWS();
  setInterval(pollQuestions, 5000);
})();
