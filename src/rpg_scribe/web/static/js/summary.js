/* RPG Scribe - summary display and editing */

import { state } from "./state.js";
import { setRefreshing } from "./utils.js";

var sessionSummaryTab = document.getElementById("session-summary");
var sessionSummaryEl = sessionSummaryTab ? sessionSummaryTab.querySelector(".summary-content") : null;
var sessionChronologyTab = document.getElementById("session-chronology");
var sessionChronologyEl = sessionChronologyTab ? sessionChronologyTab.querySelector(".summary-content") : null;
var campaignSummaryTab = document.getElementById("campaign-summary");
var campaignSummaryEl = campaignSummaryTab ? campaignSummaryTab.querySelector(".summary-content") : null;

var generationLogTabMap = {
  narrative: sessionSummaryTab,
  chronology: sessionChronologyTab,
  campaign: campaignSummaryTab,
};

export function getSessionSummaryEl() { return sessionSummaryEl; }
export function getSessionChronologyEl() { return sessionChronologyEl; }
export function getCampaignSummaryEl() { return campaignSummaryEl; }
export function getSessionSummaryTab() { return sessionSummaryTab; }
export function getSessionChronologyTab() { return sessionChronologyTab; }
export function getCampaignSummaryTab() { return campaignSummaryTab; }

export function addLogEntry(tabEl, message) {
  if (!tabEl) return;
  var logDiv = tabEl.querySelector(".generation-log");
  if (!logDiv) return;
  logDiv.classList.remove("hidden");
  var entry = document.createElement("div");
  entry.className = "log-entry";
  var time = new Date().toLocaleTimeString();
  entry.textContent = "[" + time + "] " + message;
  logDiv.appendChild(entry);
  logDiv.scrollTop = logDiv.scrollHeight;
}

export function clearLog(tabEl) {
  if (!tabEl) return;
  var logDiv = tabEl.querySelector(".generation-log");
  if (!logDiv) return;
  logDiv.innerHTML = "";
  logDiv.classList.add("hidden");
}

export function handleGenerationProgress(data) {
  var tabEl = generationLogTabMap[data.target];
  if (tabEl) addLogEntry(tabEl, data.message);
}

export function updateSummary(data) {
  if (data.session_summary) {
    var sid = data.session_id || state.activeSessionId || "";
    renderEditableSummary(sessionSummaryEl, data.session_summary, "session", sid);
  }
  if (data.session_chronology) {
    var sid2 = data.session_id || state.activeSessionId || "";
    renderEditableSummary(sessionChronologyEl, data.session_chronology, "chronology", sid2);
    updateGenerateChronologyBtn(sid2);
  }
  if (data.campaign_summary) {
    renderEditableSummary(campaignSummaryEl, data.campaign_summary, "campaign", state.activeCampaignId || state.browseCampaignId || "");
  }
}

export function updateGenerateChronologyBtn(sessionId) {
  var btn = document.getElementById("btn-generate-chronology");
  if (!btn) return;
  btn.onclick = sessionId ? function () {
    clearLog(sessionChronologyTab);
    addLogEntry(sessionChronologyTab, "Generating chronology...");

    import("./utils.js").then(function (utils) {
      utils.withLoading(btn, function () {
        return fetch("/api/sessions/" + encodeURIComponent(sessionId) + "/generate-chronology", {
          method: "POST",
        })
          .then(function (r) { return r.json(); })
          .then(function (data) {
            if (data.session_chronology) {
              renderEditableSummary(sessionChronologyEl, data.session_chronology, "chronology", sessionId);
              addLogEntry(sessionChronologyTab, "Chronology generated");
            } else {
              addLogEntry(sessionChronologyTab, "Error: no chronology returned");
            }
          })
          .catch(function () {
            addLogEntry(sessionChronologyTab, "Error: request failed");
          });
      }, { loadingText: "Generating..." });
    });
  } : null;
}

export function renderEditableSummary(container, text, type, targetId) {
  container.innerHTML = "";
  if (!text) {
    // Clickable placeholder — allows creating a summary from scratch
    var emptyEl = document.createElement("p");
    emptyEl.className = "editable-paragraph editable-placeholder";
    emptyEl.dataset.paragraphIndex = "0";
    emptyEl.dataset.summaryType = type;
    emptyEl.dataset.targetId = targetId;
    emptyEl.textContent = type === "session"
      ? "No session summary yet. Click to add one."
      : "No campaign summary yet. Click to add one.";
    emptyEl.addEventListener("click", function () { startParagraphEdit(emptyEl, container); });
    container.appendChild(emptyEl);
    return;
  }
  var paragraphs = text.split(/\n\n+/);
  paragraphs.forEach(function (p, i) {
    if (!p.trim()) return;
    var pEl = document.createElement("p");
    pEl.className = "editable-paragraph";
    pEl.dataset.paragraphIndex = i;
    pEl.dataset.summaryType = type;
    pEl.dataset.targetId = targetId;
    pEl.textContent = p;
    pEl.addEventListener("click", function () { startParagraphEdit(pEl, container); });
    container.appendChild(pEl);
  });
}

function startParagraphEdit(pEl, container) {
  if (pEl.querySelector("textarea")) return; // already editing
  var isPlaceholder = pEl.classList.contains("editable-placeholder");
  var originalText = isPlaceholder ? "" : pEl.textContent;
  var type = pEl.dataset.summaryType;
  var targetId = pEl.dataset.targetId;

  var wrap = document.createElement("div");
  wrap.className = "paragraph-edit-wrap";

  var textarea = document.createElement("textarea");
  textarea.className = "paragraph-edit-textarea";
  textarea.value = originalText;
  textarea.rows = Math.max(3, Math.ceil(originalText.length / 80));

  var actions = document.createElement("div");
  actions.className = "paragraph-edit-actions";
  actions.innerHTML =
    '<button class="para-cancel">Cancelar</button>' +
    '<button class="para-save">Guardar</button>';

  wrap.appendChild(textarea);
  wrap.appendChild(actions);
  pEl.replaceWith(wrap);
  textarea.focus();

  actions.querySelector(".para-save").addEventListener("click", function () {
    saveParagraphEdit(container, wrap, textarea.value, type, targetId);
  });
  actions.querySelector(".para-cancel").addEventListener("click", function () {
    pEl.textContent = originalText;
    wrap.replaceWith(pEl);
  });
  textarea.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      e.preventDefault();
      pEl.textContent = originalText;
      wrap.replaceWith(pEl);
    }
  });
}

function saveParagraphEdit(container, editWrap, newText, type, targetId) {
  // Collect all paragraphs (edited and unedited)
  var parts = [];
  var children = container.children;
  for (var i = 0; i < children.length; i++) {
    var child = children[i];
    if (child === editWrap) {
      parts.push(newText.trim());
    } else if (child.classList.contains("editable-paragraph")) {
      parts.push(child.textContent);
    }
  }
  var fullText = parts.join("\n\n");

  var url, bodyKey;
  if (type === "session") {
    url = "/api/sessions/" + encodeURIComponent(targetId) + "/summary";
    bodyKey = "session_summary";
  } else if (type === "chronology") {
    url = "/api/sessions/" + encodeURIComponent(targetId) + "/chronology";
    bodyKey = "session_chronology";
  } else {
    url = "/api/campaigns/" + encodeURIComponent(targetId) + "/campaign-summary";
    bodyKey = "campaign_summary";
  }

  var payload = {};
  payload[bodyKey] = fullText;

  setRefreshing(container, true);

  fetch(url, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
    .then(function () {
      renderEditableSummary(container, fullText, type, targetId);
    })
    .catch(function (err) {
      console.error("Failed to save summary:", err);
    })
    .finally(function () {
      setRefreshing(container, false);
    });
}
