/* RPG Scribe - full transcription page with editing */

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

  // ── Render transcriptions with editing controls ──────────────

  function addTranscription(data) {
    var entry = document.createElement("div");
    var isIngame = data.is_ingame !== false && data.is_ingame !== 0;
    entry.className = "feed-entry" + (data.is_partial ? " partial" : "") + (isIngame ? "" : " meta");

    // Wrap each word in a span for inline editing
    var tokens = (data.text || "").split(/(\s+)/);
    var wordIdx = 0;
    var wordHtml = tokens.map(function (tok) {
      if (/^\s+$/.test(tok)) return tok;
      var html = '<span class="editable-word" data-word-index="' + wordIdx + '">' +
        escapeHtml(tok) + "</span>";
      wordIdx++;
      return html;
    }).join("");

    entry.innerHTML =
      '<span class="entry-actions">' +
        '<button class="btn-meta" title="Marcar como META">M</button>' +
        '<button class="btn-delete" title="Eliminar">\u00d7</button>' +
      '</span>' +
      '<span class="meta-badge">[META]</span>' +
      '<span class="speaker">' + escapeHtml(data.speaker_name) + ":</span>" +
      '<span class="transcription-text">' + wordHtml + "</span>" +
      '<span class="ts">' + formatTime(data.timestamp) + "</span>";

    entry.dataset.timestamp = data.timestamp || "";
    entry.dataset.speakerId = data.speaker_id || "";
    entry.dataset.sessionId = data.session_id || "";
    entry.dataset.isIngame = isIngame ? "true" : "false";
    if (data.id) entry.dataset.transcriptionId = data.id;

    feed.appendChild(entry);
  }

  function renderRows(rows) {
    feed.innerHTML = "";
    if (!rows || rows.length === 0) {
      feed.innerHTML = '<p class="placeholder">No transcriptions for this session.</p>';
      return;
    }
    rows.forEach(function (data) {
      addTranscription(data);
    });
  }

  // ── Transcription ID resolution ─────────────────────────────

  function resolveTranscriptionId(entry) {
    return new Promise(function (resolve) {
      if (entry.dataset.transcriptionId) {
        resolve(Number(entry.dataset.transcriptionId));
        return;
      }
      var sid = entry.dataset.sessionId;
      if (!sid) { resolve(null); return; }
      fetch("/api/sessions/" + encodeURIComponent(sid) + "/transcriptions/full")
        .then(function (r) { return r.json(); })
        .then(function (data) {
          var ts = parseFloat(entry.dataset.timestamp);
          var spk = entry.dataset.speakerId;
          var rows = data.transcriptions || [];
          for (var i = 0; i < rows.length; i++) {
            if (rows[i].timestamp === ts && rows[i].speaker_id === spk) {
              entry.dataset.transcriptionId = rows[i].id;
              resolve(rows[i].id);
              return;
            }
          }
          resolve(null);
        })
        .catch(function () { resolve(null); });
    });
  }

  // ── Delete transcription ────────────────────────────────────

  feed.addEventListener("click", function (e) {
    var btn = e.target.closest(".btn-delete");
    if (!btn) return;
    var entry = btn.closest(".feed-entry");
    if (!entry) return;
    if (!confirm("\u00bfEliminar esta transcripci\u00f3n?")) return;
    resolveTranscriptionId(entry).then(function (id) {
      if (!id) return;
      fetch("/api/transcriptions/" + id, { method: "DELETE" })
        .then(function (r) { if (r.ok) entry.remove(); });
    });
  });

  // ── META toggle ─────────────────────────────────────────────

  feed.addEventListener("click", function (e) {
    var btn = e.target.closest(".btn-meta");
    if (!btn) return;
    var entry = btn.closest(".feed-entry");
    if (!entry) return;
    var currentlyIngame = entry.dataset.isIngame !== "false";
    var newIngame = !currentlyIngame;
    resolveTranscriptionId(entry).then(function (id) {
      if (!id) return;
      fetch("/api/transcriptions/" + id + "/meta", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_ingame: newIngame }),
      }).then(function (r) {
        if (r.ok) {
          entry.dataset.isIngame = newIngame ? "true" : "false";
          if (newIngame) {
            entry.classList.remove("meta");
          } else {
            entry.classList.add("meta");
          }
        }
      });
    });
  });

  // ── Word editing (double-click) ─────────────────────────────

  feed.addEventListener("dblclick", function (e) {
    var wordSpan = e.target.closest(".editable-word");
    if (!wordSpan) return;
    if (wordSpan.querySelector("input")) return;
    startWordEdit(wordSpan);
  });

  function startWordEdit(wordSpan) {
    var originalWord = wordSpan.textContent;
    var entry = wordSpan.closest(".feed-entry");

    var input = document.createElement("input");
    input.type = "text";
    input.className = "word-edit-input";
    input.value = originalWord;
    input.style.width = Math.max(originalWord.length * 0.6 + 1.5, 3) + "em";

    wordSpan.textContent = "";
    wordSpan.appendChild(input);
    input.focus();
    input.select();

    function commit() {
      var newWord = input.value.trim();
      if (!newWord || newWord === originalWord) {
        wordSpan.textContent = originalWord;
        return;
      }
      wordSpan.textContent = newWord;
      saveTranscriptionText(entry, originalWord, newWord);
    }

    input.addEventListener("blur", commit);
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter") { e.preventDefault(); input.blur(); }
      if (e.key === "Escape") { e.preventDefault(); wordSpan.textContent = originalWord; }
    });
  }

  function saveTranscriptionText(entry, originalWord, newWord) {
    var textSpan = entry.querySelector(".transcription-text");
    if (!textSpan) return;
    var words = textSpan.querySelectorAll(".editable-word");
    var fullText = "";
    for (var i = 0; i < words.length; i++) {
      if (i > 0) fullText += " ";
      fullText += words[i].textContent;
    }

    var edits = [{ original: originalWord, "new": newWord, position: 0 }];

    resolveTranscriptionId(entry).then(function (id) {
      if (!id) return;
      fetch("/api/transcriptions/" + id, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: fullText, edits: edits }),
      });
    });
  }

  // ── Load session ────────────────────────────────────────────

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
