/* RPG Scribe - TTS narration (browser + discord).
 *
 * Both modes share the same WAV cache on the server and the same on-screen
 * controls panel. The "driver" abstraction below holds the verbs each mode
 * implements; the panel just calls them. Polling keeps the panel in sync
 * with server-side state for the Discord driver.
 */

import { state } from "./state.js";
import { createSpinner } from "./utils.js";

var sessionSummaryTab = document.getElementById("session-summary");
var sessionSummaryEl = sessionSummaryTab ? sessionSummaryTab.querySelector(".summary-content") : null;
var sessionChronologyTab = document.getElementById("session-chronology");
var sessionChronologyEl = sessionChronologyTab ? sessionChronologyTab.querySelector(".summary-content") : null;
var campaignSummaryTab = document.getElementById("campaign-summary");
var campaignSummaryEl = campaignSummaryTab ? campaignSummaryTab.querySelector(".summary-content") : null;

// ── Init ────────────────────────────────────────────────────────────

export function initTTS() {
  fetch("/api/tts/voices")
    .then(function (r) {
      if (r.ok) {
        state.ttsEnabled = true;
        document.querySelectorAll(".btn-narrate").forEach(function (btn) {
          btn.style.display = "";
        });
      }
    })
    .catch(function () { /* TTS not available — buttons stay hidden */ });

  ["btn-narrate-session", "btn-narrate-chronology", "btn-narrate-campaign"].forEach(function (id) {
    var btn = document.getElementById(id);
    if (btn) btn.addEventListener("click", function () { startNarration(btn); });
  });

  ["btn-narrate-session-discord"].forEach(function (id) {
    var btn = document.getElementById(id);
    if (btn) btn.addEventListener("click", function () { startNarrationDiscord(btn); });
  });
}

// ── Text extraction ─────────────────────────────────────────────────

function _getTextFromParagraphs(container) {
  if (!container) return "";
  var parts = [];
  container.querySelectorAll("p.editable-paragraph").forEach(function (p) {
    var t = p.textContent.trim();
    if (t) parts.push(t);
  });
  return parts.join("\n\n");
}

function _getNarrateText(btnId) {
  if (btnId === "btn-narrate-session" || btnId === "btn-narrate-session-discord")
    return _getTextFromParagraphs(sessionSummaryEl);
  if (btnId === "btn-narrate-chronology") return _getTextFromParagraphs(sessionChronologyEl);
  if (btnId === "btn-narrate-campaign") return _getTextFromParagraphs(campaignSummaryEl);
  return "";
}

// ── Shared controls panel ───────────────────────────────────────────

function _createNarrateControls(btn, driver) {
  var wrap = document.createElement("div");
  wrap.className = "narrate-controls";

  var btnPrev = document.createElement("button");
  btnPrev.className = "btn-narrate-ctrl btn-narrate-prev";
  btnPrev.title = "Chunk anterior";
  btnPrev.textContent = "⏮ Ant.";
  btnPrev.addEventListener("click", function () { driver.prev(); });

  var sep1 = document.createElement("div");
  sep1.className = "narrate-ctrl-sep";

  var btnRestart = document.createElement("button");
  btnRestart.className = "btn-narrate-ctrl btn-narrate-restart";
  btnRestart.title = "Reiniciar chunk actual";
  btnRestart.textContent = "↺";
  btnRestart.addEventListener("click", function () { driver.restart(); });

  var btnPlayPause = document.createElement("button");
  btnPlayPause.className = "btn-narrate-ctrl btn-narrate-playpause";
  btnPlayPause.title = "Pausa / Reanudar";
  btnPlayPause.addEventListener("click", function () { driver.pauseResume(); });

  var sep2 = document.createElement("div");
  sep2.className = "narrate-ctrl-sep";

  var btnNext = document.createElement("button");
  btnNext.className = "btn-narrate-ctrl btn-narrate-next";
  btnNext.title = "Chunk siguiente";
  btnNext.textContent = "Sig. ⏭";
  btnNext.addEventListener("click", function () { driver.next(); });

  wrap.appendChild(btnPrev);
  wrap.appendChild(sep1);
  wrap.appendChild(btnRestart);
  wrap.appendChild(btnPlayPause);
  wrap.appendChild(sep2);
  wrap.appendChild(btnNext);

  btn.style.display = "none";
  btn.parentNode.insertBefore(wrap, btn.nextSibling);
  return wrap;
}

function _updateControls() {
  if (!state.ttsControlsEl) return;
  var btnPrev = state.ttsControlsEl.querySelector(".btn-narrate-prev");
  var btnRestart = state.ttsControlsEl.querySelector(".btn-narrate-restart");
  var btnPlayPause = state.ttsControlsEl.querySelector(".btn-narrate-playpause");
  var btnNext = state.ttsControlsEl.querySelector(".btn-narrate-next");
  var generating = state.ttsCurrentIndex < 0;
  var total = state.ttsTotalChunks || "?";

  if (generating) {
    btnPrev.disabled = true;
    btnRestart.disabled = true;
    btnNext.disabled = true;
    btnPlayPause.disabled = true;
    btnPlayPause.classList.remove("paused");
    btnPlayPause.innerHTML = "";
    btnPlayPause.appendChild(createSpinner());
    btnPlayPause.appendChild(document.createTextNode(" Generando"));
    return;
  }

  var progress = (state.ttsCurrentIndex + 1) + "/" + total;
  btnPrev.disabled = state.ttsCurrentIndex <= 0;
  btnRestart.disabled = false;
  btnNext.disabled = state.ttsCurrentIndex >= (state.ttsTotalChunks - 1);
  btnPlayPause.disabled = false;
  if (state.ttsPaused) {
    btnPlayPause.classList.add("paused");
    btnPlayPause.textContent = "▶ " + progress;
  } else {
    btnPlayPause.classList.remove("paused");
    btnPlayPause.textContent = "⏸ " + progress;
  }
}

function _markComplete() {
  if (!state.ttsControlsEl) return;
  var btnPlayPause = state.ttsControlsEl.querySelector(".btn-narrate-playpause");
  if (btnPlayPause) {
    btnPlayPause.classList.remove("paused");
    btnPlayPause.textContent = "✓ Listo";
  }
  setTimeout(stopNarration, 2000);
}

// ── Browser driver (HTML5 Audio) ────────────────────────────────────

function _browserPlayChunk(index) {
  if (index < 0 || index >= state.ttsAllChunks.length) return;
  state._ttsGen++;
  var myGen = state._ttsGen;
  if (state.ttsAudio) {
    state.ttsAudio.pause();
    state.ttsAudio.src = "";
    state.ttsAudio = null;
  }
  state.ttsCurrentIndex = index;
  state.ttsPaused = false;
  _updateControls();
  var url = state.ttsAllChunks[index];
  state.ttsAudio = new Audio(url);
  state.ttsAudio.addEventListener("ended", function () {
    if (state._ttsGen !== myGen) return;
    state.ttsAudio = null;
    var next = state.ttsCurrentIndex + 1;
    if (next < state.ttsAllChunks.length) {
      _browserPlayChunk(next);
    } else if (state.ttsAllChunks.length < state.ttsTotalChunks) {
      _updateControls();
    } else {
      _markComplete();
    }
  });
  state.ttsAudio.addEventListener("error", function () {
    if (state._ttsGen !== myGen) return;
    console.error("TTS audio error:", url);
    state.ttsAudio = null;
    var next = state.ttsCurrentIndex + 1;
    if (next < state.ttsAllChunks.length) _browserPlayChunk(next);
    else _markComplete();
  });
  state.ttsAudio.play().catch(function (err) { console.error("TTS play failed:", err); });
}

var browserDriver = {
  prev: function () { if (state.ttsCurrentIndex > 0) _browserPlayChunk(state.ttsCurrentIndex - 1); },
  next: function () { if (state.ttsCurrentIndex < state.ttsAllChunks.length - 1) _browserPlayChunk(state.ttsCurrentIndex + 1); },
  restart: function () { if (state.ttsCurrentIndex >= 0) _browserPlayChunk(state.ttsCurrentIndex); },
  pauseResume: function () {
    if (!state.ttsAudio) return;
    if (state.ttsPaused) {
      state.ttsAudio.play().catch(function (err) { console.error("TTS resume failed:", err); });
      state.ttsPaused = false;
    } else {
      state.ttsAudio.pause();
      state.ttsPaused = true;
    }
    _updateControls();
  },
};

// ── Discord driver (HTTP control endpoints + status polling) ────────

function _postDiscord(path, body) {
  return fetch("/api/tts/discord/" + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : "{}",
  })
    .then(function (r) { return r.ok ? r.json() : Promise.reject(new Error(r.status)); })
    .then(function (s) { _applyServerStatus(s); })
    .catch(function (err) { console.error("Discord control failed:", err); });
}

function _applyServerStatus(s) {
  if (!s) return;
  if (typeof s.index === "number") state.ttsCurrentIndex = s.index;
  if (typeof s.total === "number") state.ttsTotalChunks = s.total;
  if (typeof s.paused === "boolean") state.ttsPaused = s.paused;
  _updateControls();
  if (s.active === false && state.ttsCurrentIndex >= state.ttsTotalChunks - 1) {
    _markComplete();
  }
}

function _startDiscordPolling() {
  _stopDiscordPolling();
  state.ttsDiscordPoll = setInterval(function () {
    fetch("/api/tts/discord/status")
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (s) {
        if (!s || !s.connected) return;
        _applyServerStatus(s);
      })
      .catch(function () { /* ignore transient errors */ });
  }, 1000);
}

function _stopDiscordPolling() {
  if (state.ttsDiscordPoll) {
    clearInterval(state.ttsDiscordPoll);
    state.ttsDiscordPoll = null;
  }
}

var discordDriver = {
  prev: function () {
    if (state.ttsCurrentIndex > 0) _postDiscord("play-at", { index: state.ttsCurrentIndex - 1 });
  },
  next: function () {
    if (state.ttsCurrentIndex < state.ttsTotalChunks - 1) _postDiscord("play-at", { index: state.ttsCurrentIndex + 1 });
  },
  restart: function () {
    if (state.ttsCurrentIndex >= 0) _postDiscord("play-at", { index: state.ttsCurrentIndex });
  },
  pauseResume: function () {
    if (state.ttsPaused) _postDiscord("resume");
    else _postDiscord("pause");
  },
};

// ── Stop & start orchestration ──────────────────────────────────────

export function stopNarration() {
  state._ttsGen++;
  if (state.ttsAudio) {
    state.ttsAudio.pause();
    state.ttsAudio.src = "";
    state.ttsAudio = null;
  }
  if (state.ttsDriver === "discord") {
    // Fire-and-forget: server will release the queue.
    fetch("/api/tts/discord/stop", { method: "POST" }).catch(function () {});
  }
  _stopDiscordPolling();
  state.ttsAllChunks = [];
  state.ttsCurrentIndex = -1;
  state.ttsTotalChunks = 0;
  state.ttsPaused = false;
  state.ttsDriver = null;
  if (state.ttsControlsEl && state.ttsControlsEl.parentNode) {
    state.ttsControlsEl.parentNode.removeChild(state.ttsControlsEl);
  }
  state.ttsControlsEl = null;
  if (state.ttsActiveBtn) {
    state.ttsActiveBtn.style.display = "";
    state.ttsActiveBtn = null;
  }
}

function _resetSharedState(btn, driver) {
  if (state.ttsActiveBtn === btn) { stopNarration(); return false; }
  if (state.ttsActiveBtn) stopNarration();
  state.ttsActiveBtn = btn;
  state.ttsAllChunks = [];
  state.ttsCurrentIndex = -1;
  state.ttsTotalChunks = 0;
  state.ttsPaused = false;
  state.ttsDriver = driver;
  state.ttsControlsEl = _createNarrateControls(btn, driver === "discord" ? discordDriver : browserDriver);
  _updateControls();
  return true;
}

export async function startNarration(btn) {
  var text = _getNarrateText(btn.id);
  if (!text) return;
  if (!_resetSharedState(btn, "browser")) return;

  try {
    var resp = await fetch("/api/tts/narrate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: text }),
    });
    if (!resp.ok) throw new Error("TTS request failed: " + resp.status);

    var reader = resp.body.getReader();
    var decoder = new TextDecoder();
    var buffer = "";
    var waitingForPlayback = true;

    while (true) {
      var result = await reader.read();
      if (result.done) break;
      buffer += decoder.decode(result.value, { stream: true });
      var lines = buffer.split("\n");
      buffer = lines.pop();
      for (var i = 0; i < lines.length; i++) {
        var line = lines[i].trim();
        if (!line) continue;
        try {
          var chunk = JSON.parse(line);
          if (chunk.error) { console.warn("TTS paragraph error:", chunk.error); continue; }
          if (typeof chunk.total === "number") state.ttsTotalChunks = chunk.total;
          if (chunk.audio_url) state.ttsAllChunks.push(chunk.audio_url);
          if (waitingForPlayback && state.ttsAllChunks.length > 0) {
            waitingForPlayback = false;
            _browserPlayChunk(0);
          } else if (!state.ttsAudio && !state.ttsPaused && state.ttsCurrentIndex < state.ttsAllChunks.length - 1) {
            _browserPlayChunk(state.ttsCurrentIndex + 1);
          } else {
            _updateControls();
          }
        } catch (e) { console.warn("TTS NDJSON parse error:", line); }
      }
    }
  } catch (err) {
    console.error("TTS narration failed:", err);
    stopNarration();
  }
}

export async function startNarrationDiscord(btn) {
  var text = _getNarrateText(btn.id);
  if (!text) return;
  if (!_resetSharedState(btn, "discord")) return;

  try {
    var resp = await fetch("/api/tts/narrate-discord", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: text }),
    });

    if (!resp.ok) {
      var detail = "TTS Discord request failed: " + resp.status;
      try {
        var errBody = await resp.json();
        if (errBody && errBody.detail) detail = errBody.detail;
      } catch (e) { /* not JSON */ }
      if (resp.status === 409 && detail.indexOf("not connected") !== -1) {
        alert("El bot no está en un canal de voz. Usa /scribe start primero.");
      } else {
        alert("Error al narrar en Discord: " + detail);
      }
      stopNarration();
      return;
    }

    var reader = resp.body.getReader();
    var decoder = new TextDecoder();
    var buffer = "";

    while (true) {
      var result = await reader.read();
      if (result.done) break;
      buffer += decoder.decode(result.value, { stream: true });
      var lines = buffer.split("\n");
      buffer = lines.pop();
      for (var i = 0; i < lines.length; i++) {
        var line = lines[i].trim();
        if (!line) continue;
        try {
          var event = JSON.parse(line);
          if (event.error) {
            console.error("TTS Discord error:", event.error);
            alert("Error al narrar en Discord: " + event.error);
            stopNarration();
            return;
          }
          if (typeof event.total === "number") state.ttsTotalChunks = event.total;
          if (typeof event.index === "number") {
            // First chunk ready → assume playback at index 0 will start.
            if (state.ttsCurrentIndex < 0) state.ttsCurrentIndex = 0;
            _updateControls();
          }
          if (event.status === "started") {
            _startDiscordPolling();
          }
        } catch (e) { console.warn("TTS Discord NDJSON parse error:", line); }
      }
    }
  } catch (err) {
    console.error("TTS Discord narration failed:", err);
    stopNarration();
  }
}
