/* RPG Scribe - transcription feed */

import { state } from "./state.js";
import { escapeHtml, formatTime, setRefreshing } from "./utils.js";

var transcriptionFeed = document.getElementById("transcription-feed");
var currentAudio = null;

export function addTranscription(data) {
  // Remove placeholder
  var ph = transcriptionFeed.querySelector(".placeholder");
  if (ph) ph.remove();

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

  // Build audio URL: /audio/{session_id}/{timestamp}_{speaker_sanitized}.wav
  var speakerSanitized = (data.speaker_name || "").replace(/[^\w]/g, "_").substring(0, 30);
  var audioUrl = "/audio/" + encodeURIComponent(data.session_id) +
    "/" + data.timestamp + "_" + encodeURIComponent(speakerSanitized) + ".wav";

  entry.innerHTML =
    '<span class="entry-actions">' +
      '<button class="btn-meta" title="Marcar como META">M</button>' +
      '<button class="btn-delete" title="Eliminar">\u00d7</button>' +
    '</span>' +
    '<span class="meta-badge">[META]</span>' +
    '<span class="speaker">' + escapeHtml(data.speaker_name) + ":</span>" +
    '<span class="transcription-text">' + wordHtml + "</span>" +
    '<button class="btn-play" title="Reproducir audio" data-audio-url="' + escapeHtml(audioUrl) + '">\u25B6</button>' +
    '<span class="ts">' + formatTime(data.timestamp) + "</span>";

  // Store metadata for editing
  entry.dataset.timestamp = data.timestamp || "";
  entry.dataset.speakerId = data.speaker_id || "";
  entry.dataset.sessionId = data.session_id || "";
  entry.dataset.isIngame = isIngame ? "true" : "false";
  if (data.id) entry.dataset.transcriptionId = data.id;

  transcriptionFeed.appendChild(entry);
  if (!state.viewingHistorical) {
    trimTranscriptionFeed();
  }
  transcriptionFeed.scrollTop = transcriptionFeed.scrollHeight;
}

export function trimTranscriptionFeed() {
  var entries = transcriptionFeed.querySelectorAll(".feed-entry");
  var overflow = entries.length - state.maxFeedItems;
  for (var i = 0; i < overflow; i++) {
    entries[i].remove();
  }
}

export function clearTranscriptionFeed(placeholder) {
  transcriptionFeed.innerHTML = placeholder
    ? '<p class="placeholder">' + placeholder + '</p>'
    : "";
}

export function initTranscriptionListeners() {
  // ── Transcription word editing ─────────────────────────────
  transcriptionFeed.addEventListener("dblclick", function (e) {
    var wordSpan = e.target.closest(".editable-word");
    if (!wordSpan) return;
    if (wordSpan.querySelector("input")) return; // already editing
    startWordEdit(wordSpan);
  });

  // ── Play audio chunk ─────────────────────────────────────
  transcriptionFeed.addEventListener("click", function (e) {
    var btn = e.target.closest(".btn-play");
    if (!btn) return;
    var url = btn.dataset.audioUrl;
    if (!url) return;

    // Stop currently playing audio
    if (currentAudio) {
      currentAudio.pause();
      currentAudio = null;
      var prevBtn = transcriptionFeed.querySelector(".btn-play.playing");
      if (prevBtn) prevBtn.classList.remove("playing");
    }

    // If clicking the same button that was playing, just stop
    if (btn.classList.contains("playing")) {
      btn.classList.remove("playing");
      return;
    }

    var audio = new Audio(url);
    currentAudio = audio;
    btn.classList.add("playing");
    audio.play().catch(function () {
      btn.classList.remove("playing");
    });
    audio.addEventListener("ended", function () {
      btn.classList.remove("playing");
      currentAudio = null;
    });
  });

  // ── Delete transcription ──────────────────────────────────
  transcriptionFeed.addEventListener("click", function (e) {
    var btn = e.target.closest(".btn-delete");
    if (!btn) return;
    var entry = btn.closest(".feed-entry");
    if (!entry) return;
    if (!confirm("¿Eliminar esta transcripción?")) return;

    import("./utils.js").then(function (utils) {
      utils.withLoading(btn, function () {
        return resolveTranscriptionId(entry).then(function (id) {
          if (!id) return Promise.reject(new Error("No transcription ID"));
          return fetch("/api/transcriptions/" + id, { method: "DELETE" })
            .then(function (r) {
              if (r.ok) entry.remove();
              else return Promise.reject(new Error("Delete failed"));
            });
        });
      }, { loadingText: "Eliminando..." });
    });
  });

  // ── META toggle ───────────────────────────────────────────
  transcriptionFeed.addEventListener("click", function (e) {
    var btn = e.target.closest(".btn-meta");
    if (!btn) return;
    var entry = btn.closest(".feed-entry");
    if (!entry) return;
    var currentlyIngame = entry.dataset.isIngame !== "false";
    var newIngame = !currentlyIngame;

    setRefreshing(entry, true);
    resolveTranscriptionId(entry).then(function (id) {
      if (!id) {
        setRefreshing(entry, false);
        return;
      }
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
      }).finally(function () {
        setRefreshing(entry, false);
      });
    });
  });
}

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

function startWordEdit(wordSpan) {
  var originalWord = wordSpan.textContent;
  var entry = wordSpan.closest(".feed-entry");
  var wordIndex = parseInt(wordSpan.dataset.wordIndex, 10);

  var input = document.createElement("input");
  input.type = "text";
  input.className = "word-edit-input";
  input.value = originalWord;
  input.style.width = Math.max(originalWord.length * 0.6 + 1.5, 3) + "em";

  var actions = document.createElement("span");
  actions.className = "word-edit-actions";
  actions.innerHTML =
    '<button class="word-confirm" title="Guardar">✓</button>' +
    '<button class="word-cancel" title="Cancelar">✗</button>';

  var replaceLabel = document.createElement("label");
  replaceLabel.className = "word-replace-option";
  replaceLabel.innerHTML =
    '<input type="checkbox" class="word-replace-check"> Reemplazar siempre';

  wordSpan.textContent = "";
  wordSpan.appendChild(input);
  wordSpan.appendChild(actions);
  wordSpan.appendChild(replaceLabel);
  input.focus();
  input.select();

  function doConfirm() {
    var newWord = input.value.trim();
    if (!newWord || newWord === originalWord) {
      doCancel();
      return;
    }
    var alwaysReplace = wordSpan.querySelector(".word-replace-check").checked;
    saveWordEdit(entry, wordIndex, originalWord, newWord, alwaysReplace);
  }

  function doCancel() {
    wordSpan.textContent = originalWord;
  }

  actions.querySelector(".word-confirm").addEventListener("click", function (e) {
    e.stopPropagation();
    doConfirm();
  });
  actions.querySelector(".word-cancel").addEventListener("click", function (e) {
    e.stopPropagation();
    doCancel();
  });
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter") { e.preventDefault(); doConfirm(); }
    if (e.key === "Escape") { e.preventDefault(); doCancel(); }
  });
  input.addEventListener("dblclick", function (e) { e.stopPropagation(); });
}

function saveWordEdit(entry, wordIndex, originalWord, newWord, alwaysReplace) {
  // Update the span immediately
  var wordSpans = entry.querySelectorAll(".editable-word");
  var targetWordSpan = null;
  for (var i = 0; i < wordSpans.length; i++) {
    if (parseInt(wordSpans[i].dataset.wordIndex, 10) === wordIndex) {
      targetWordSpan = wordSpans[i];
      wordSpans[i].textContent = newWord;
      break;
    }
  }

  // Add refreshing state to the word span
  if (targetWordSpan) {
    setRefreshing(targetWordSpan, true);
  }

  // Rebuild full text
  var textSpan = entry.querySelector(".transcription-text");
  var fullText = textSpan ? textSpan.textContent : "";

  var promises = [];

  resolveTranscriptionId(entry).then(function (id) {
    if (!id) {
      if (targetWordSpan) setRefreshing(targetWordSpan, false);
      return;
    }

    promises.push(
      fetch("/api/transcriptions/" + id, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: fullText,
          edits: [{ original: originalWord, "new": newWord, position: wordIndex }],
        }),
      })
    );

    if (alwaysReplace && state.activeCampaignId) {
      promises.push(
        fetch("/api/campaigns/" + encodeURIComponent(state.activeCampaignId) + "/word-replacements", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            original_word: originalWord,
            replacement_word: newWord,
          }),
        })
      );
    }

    Promise.all(promises).finally(function () {
      if (targetWordSpan) setRefreshing(targetWordSpan, false);
    });
  });
}
