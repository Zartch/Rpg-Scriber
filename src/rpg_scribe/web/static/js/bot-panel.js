/* RPG Scribe - Panel de control de voz del bot.
 *
 * Aparece dentro de #status-panel cuando un bot reproduce una respuesta
 * (evento WebSocket "bot_speech") y controla el audio en Discord vía los
 * endpoints /api/tts/discord/*. Solo transporte: no re-consulta a Claude.
 */

var els = {};            // nodos DOM cacheados
var pollTimer = null;
var st = { index: 0, total: 0, paused: false, active: false };

function _post(path, body) {
  return fetch("/api/tts/discord/" + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : "{}",
  })
    .then(function (r) { return r.ok ? r.json() : Promise.reject(new Error(r.status)); })
    .then(function (s) { _applyStatus(s); })
    .catch(function (err) { console.error("bot-panel control failed:", err); });
}

function _applyStatus(s) {
  if (!s) return;
  if (typeof s.index === "number") st.index = s.index;
  if (typeof s.total === "number") st.total = s.total;
  if (typeof s.paused === "boolean") st.paused = s.paused;
  if (typeof s.active === "boolean") st.active = s.active;
  _render();
}

function _startPolling() {
  _stopPolling();
  pollTimer = setInterval(function () {
    fetch("/api/tts/discord/status")
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (s) {
        if (!s) return;
        if (s.connected === false) { _setDisconnected(); return; }
        _applyStatus(s);
        if (s.active === false) _stopPolling();  // reproducción terminada
      })
      .catch(function () { /* errores transitorios: ignorar */ });
  }, 500);
}

function _stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

function _setDisconnected() {
  _stopPolling();
  if (els.status) els.status.textContent = "voz desconectada";
  [els.prev, els.next, els.restart, els.playpause, els.stop].forEach(function (b) {
    if (b) b.disabled = true;
  });
}

function _render() {
  if (!els.playpause) return;
  var progress = (st.index + 1) + "/" + (st.total || "?");
  var estado = st.paused ? " · pausado" : (st.active ? " · sonando" : "");
  els.status.textContent = "frase " + progress + estado;
  els.prev.disabled = st.index <= 0;
  els.next.disabled = st.index >= (st.total - 1);
  els.restart.disabled = false;
  els.stop.disabled = false;
  els.playpause.disabled = false;
  els.playpause.textContent = st.paused ? "▶ Reanudar" : "⏸ Pausar";
}

function _hide() {
  _stopPolling();
  if (els.root) els.root.classList.add("hidden");
}

export function initBotPanel() {
  els.root = document.getElementById("bot-speech-panel");
  if (!els.root) return;
  els.header = els.root.querySelector(".bot-panel-header");
  els.question = els.root.querySelector(".bot-panel-question");
  els.answer = els.root.querySelector(".bot-panel-answer");
  els.status = els.root.querySelector(".bot-panel-status");
  els.prev = els.root.querySelector(".bot-panel-prev");
  els.next = els.root.querySelector(".bot-panel-next");
  els.restart = els.root.querySelector(".bot-panel-restart");
  els.playpause = els.root.querySelector(".bot-panel-playpause");
  els.stop = els.root.querySelector(".bot-panel-stop");
  els.close = els.root.querySelector(".bot-panel-close");

  els.prev.addEventListener("click", function () {
    if (st.index > 0) _post("play-at", { index: st.index - 1 });
  });
  els.next.addEventListener("click", function () {
    if (st.index < st.total - 1) _post("play-at", { index: st.index + 1 });
  });
  els.restart.addEventListener("click", function () { _post("play-at", { index: 0 }); });
  els.playpause.addEventListener("click", function () {
    if (st.paused) _post("resume"); else _post("pause");
  });
  els.stop.addEventListener("click", function () { _post("stop").then(_hide); });
  els.close.addEventListener("click", _hide);
}

export function showBotPanel(data) {
  if (!els.root) return;
  els.header.textContent = "🔊 " + (data.bot_keyword || "bot") +
    (data.speaker_name ? " · " + data.speaker_name : "");
  els.question.textContent = data.question || "";
  els.answer.textContent = data.answer_md || "";  // texto escapado; CSS pre-wrap
  st.index = 0;
  st.total = typeof data.total_chunks === "number" ? data.total_chunks : 0;
  st.paused = false;
  st.active = true;
  els.root.classList.remove("hidden");
  _render();
  _startPolling();
}
