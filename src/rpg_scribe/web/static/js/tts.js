/* RPG Scribe - TTS narration */

import { state } from "./state.js";
import { createSpinner } from "./utils.js";

var sessionSummaryTab = document.getElementById("session-summary");
var sessionSummaryEl = sessionSummaryTab ? sessionSummaryTab.querySelector(".summary-content") : null;
var sessionChronologyTab = document.getElementById("session-chronology");
var sessionChronologyEl = sessionChronologyTab ? sessionChronologyTab.querySelector(".summary-content") : null;
var campaignSummaryTab = document.getElementById("campaign-summary");
var campaignSummaryEl = campaignSummaryTab ? campaignSummaryTab.querySelector(".summary-content") : null;

export function initTTS() {
  // Check if TTS is available and show buttons
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
}

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
  if (btnId === "btn-narrate-session") return _getTextFromParagraphs(sessionSummaryEl);
  if (btnId === "btn-narrate-chronology") return _getTextFromParagraphs(sessionChronologyEl);
  if (btnId === "btn-narrate-campaign") return _getTextFromParagraphs(campaignSummaryEl);
  return "";
}

function _createNarrateControls(btn) {
  var wrap = document.createElement("div");
  wrap.className = "narrate-controls";

  var btnPrev = document.createElement("button");
  btnPrev.className = "btn-narrate-ctrl btn-narrate-prev";
  btnPrev.title = "Chunk anterior";
  btnPrev.textContent = "⏮ Ant.";
  btnPrev.addEventListener("click", _prevChunk);

  var sep1 = document.createElement("div");
  sep1.className = "narrate-ctrl-sep";

  var btnRestart = document.createElement("button");
  btnRestart.className = "btn-narrate-ctrl btn-narrate-restart";
  btnRestart.title = "Reiniciar chunk actual";
  btnRestart.textContent = "↺";
  btnRestart.addEventListener("click", _restartChunk);

  var btnPlayPause = document.createElement("button");
  btnPlayPause.className = "btn-narrate-ctrl btn-narrate-playpause";
  btnPlayPause.title = "Pausa / Reanudar";
  btnPlayPause.addEventListener("click", _pauseResume);

  var sep2 = document.createElement("div");
  sep2.className = "narrate-ctrl-sep";

  var btnNext = document.createElement("button");
  btnNext.className = "btn-narrate-ctrl btn-narrate-next";
  btnNext.title = "Chunk siguiente";
  btnNext.textContent = "Sig. ⏭";
  btnNext.addEventListener("click", _nextChunk);

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
  var generating = state.ttsCurrentIndex === -1;
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
  } else {
    var progress = (state.ttsCurrentIndex + 1) + "/" + total;
    btnPrev.disabled = state.ttsCurrentIndex <= 0;
    btnRestart.disabled = false;
    btnNext.disabled = state.ttsCurrentIndex >= state.ttsAllChunks.length - 1;
    btnPlayPause.disabled = false;
    if (state.ttsPaused) {
      btnPlayPause.classList.add("paused");
      btnPlayPause.textContent = "▶ " + progress;
    } else {
      btnPlayPause.classList.remove("paused");
      btnPlayPause.textContent = "⏸ " + progress;
    }
  }
}

function _playChunk(index) {
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
    if (state._ttsGen !== myGen) return; // stale — a newer _playChunk or stop already took over
    state.ttsAudio = null;
    var next = state.ttsCurrentIndex + 1;
    if (next < state.ttsAllChunks.length) {
      _playChunk(next);
    } else if (state.ttsAllChunks.length < state.ttsTotalChunks) {
      // stream still delivering — wait; stream loop will resume playback
      _updateControls();
    } else {
      _onNarrationComplete();
    }
  });
  state.ttsAudio.addEventListener("error", function () {
    if (state._ttsGen !== myGen) return; // stale
    console.error("TTS audio error:", url);
    state.ttsAudio = null;
    var next = state.ttsCurrentIndex + 1;
    if (next < state.ttsAllChunks.length) _playChunk(next);
    else _onNarrationComplete();
  });
  state.ttsAudio.play().catch(function (err) {
    console.error("TTS play failed:", err);
  });
}

function _onNarrationComplete() {
  if (!state.ttsControlsEl) return;
  var btnPlayPause = state.ttsControlsEl.querySelector(".btn-narrate-playpause");
  if (btnPlayPause) { btnPlayPause.classList.remove("paused"); btnPlayPause.textContent = "✓ Listo"; }
  setTimeout(stopNarration, 2000);
}

function _pauseResume() {
  if (!state.ttsAudio) return;
  if (state.ttsPaused) {
    state.ttsAudio.play().catch(function (err) { console.error("TTS resume failed:", err); });
    state.ttsPaused = false;
  } else {
    state.ttsAudio.pause();
    state.ttsPaused = true;
  }
  _updateControls();
}

function _prevChunk() { if (state.ttsCurrentIndex > 0) _playChunk(state.ttsCurrentIndex - 1); }
function _nextChunk() { if (state.ttsCurrentIndex < state.ttsAllChunks.length - 1) _playChunk(state.ttsCurrentIndex + 1); }
function _restartChunk() { if (state.ttsCurrentIndex >= 0) _playChunk(state.ttsCurrentIndex); }

export function stopNarration() {
  state._ttsGen++; // invalidate any pending audio callbacks
  if (state.ttsAudio) {
    state.ttsAudio.pause();
    state.ttsAudio.src = "";
    state.ttsAudio = null;
  }
  state.ttsAllChunks = [];
  state.ttsCurrentIndex = -1;
  state.ttsTotalChunks = 0;
  state.ttsPaused = false;
  if (state.ttsControlsEl && state.ttsControlsEl.parentNode) {
    state.ttsControlsEl.parentNode.removeChild(state.ttsControlsEl);
  }
  state.ttsControlsEl = null;
  if (state.ttsActiveBtn) {
    state.ttsActiveBtn.style.display = "";
    state.ttsActiveBtn = null;
  }
}

export async function startNarration(btn) {
  var text = _getNarrateText(btn.id);
  if (!text) return;

  if (state.ttsActiveBtn === btn) { stopNarration(); return; }
  if (state.ttsActiveBtn) stopNarration();

  state.ttsActiveBtn = btn;
  state.ttsAllChunks = [];
  state.ttsCurrentIndex = -1;
  state.ttsTotalChunks = 0;
  state.ttsPaused = false;

  state.ttsControlsEl = _createNarrateControls(btn);
  _updateControls(); // shows generating state

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
          state.ttsTotalChunks = chunk.total;
          state.ttsAllChunks.push(chunk.audio_url);
          if (waitingForPlayback) {
            waitingForPlayback = false;
            _playChunk(0);
          } else if (!state.ttsAudio && !state.ttsPaused && state.ttsCurrentIndex < state.ttsAllChunks.length - 1) {
            // audio ended while waiting for this chunk — resume
            _playChunk(state.ttsCurrentIndex + 1);
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
