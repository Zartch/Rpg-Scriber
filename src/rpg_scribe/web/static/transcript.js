/* RPG Scribe - full transcription page */

(function () {
  "use strict";

  var label = document.getElementById("session-label");
  var feed = document.getElementById("full-transcription-feed");
  var refreshBtn = document.getElementById("refresh-btn");

  function getSessionIdFromUrl() {
    var params = new URLSearchParams(location.search);
    return params.get("session_id");
  }

  function formatTime(ts) {
    if (!ts) return "";
    var d = new Date(ts * 1000);
    return d.toLocaleTimeString();
  }

  function escapeHtml(str) {
    var div = document.createElement("div");
    div.appendChild(document.createTextNode(str || ""));
    return div.innerHTML;
  }

  function renderRows(rows) {
    feed.innerHTML = "";
    if (!rows || rows.length === 0) {
      feed.innerHTML = '<p class="placeholder">No transcriptions for this session.</p>';
      return;
    }

    rows.forEach(function (data) {
      var entry = document.createElement("div");
      entry.className = "feed-entry" + (data.is_partial ? " partial" : "");
      entry.innerHTML =
        '<span class="speaker">' + escapeHtml(data.speaker_name) + ":</span>" +
        escapeHtml(data.text) +
        '<span class="ts">' + formatTime(data.timestamp) + "</span>";
      feed.appendChild(entry);
    });
  }

  function loadSession(sessionId) {
    label.textContent = "Session: " + sessionId;

    fetch("/api/sessions/" + encodeURIComponent(sessionId) + "/transcriptions/full")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        renderRows(data.transcriptions || []);
      })
      .catch(function () {
        feed.innerHTML = '<p class="placeholder">Failed to load transcriptions.</p>';
      });
  }

  var sessionId = getSessionIdFromUrl();
  if (!sessionId) {
    feed.innerHTML = '<p class="placeholder">Missing session_id in URL.</p>';
    return;
  }

  refreshBtn.addEventListener("click", function () {
    loadSession(sessionId);
  });

  loadSession(sessionId);
})();
