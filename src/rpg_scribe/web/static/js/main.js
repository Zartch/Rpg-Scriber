/* RPG Scribe - main entry point, wires all ES modules together */

import { state } from "./state.js";
import { connectWS, registerHandler } from "./websocket.js";
import { fetchCampaignInfo, setOnCampaignLoaded, initCampaignListeners } from "./campaign.js";
import { addTranscription, initTranscriptionListeners } from "./transcription.js";
import { updateSummary, handleGenerationProgress, addLogEntry, clearLog, renderEditableSummary, getCampaignSummaryEl, getCampaignSummaryTab, getSessionSummaryTab, getSessionChronologyTab } from "./summary.js";
import { renderPlayers, renderNpcs, renderLocations, renderEntities, fetchWordReplacements, initEntityFormListeners, setCampaignRefresher as setEntityCampaignRefresher } from "./entities.js";
import { renderRelationships, initRelationshipListeners, setCampaignRefresher as setRelCampaignRefresher } from "./relationships/index.js";
import { createRelationshipGraph3D } from "./relationships/graph-3d.js";
import { fetchSessionList, pollQuestions, setMode, initSessionListeners, setOnFetchCampaignInfo, setOnSelectBrowseCampaign } from "./sessions.js";
import { initTTS } from "./tts.js";
import { withLoading } from "./utils.js";

// Register the 3D graph constructor so relationships/index.js can still find it via window
window.RelationshipGraph3D = { create: createRelationshipGraph3D };

// ── WebSocket message handlers ──────────────────────────────────────────────

registerHandler("transcription", function (data) {
  addTranscription(data);
});

registerHandler("summary", function (data) {
  updateSummary(data);
});

registerHandler("status", function (data) {
  updateStatus(data);
});

registerHandler("entities_updated", function () {
  fetchCampaignInfo();
});

registerHandler("generation_progress", function (data) {
  handleGenerationProgress(data);
});

// ── Status update handler ───────────────────────────────────────────────────

var componentStatusEl = document.getElementById("component-status");

function updateStatus(data) {
  var card = componentStatusEl ? componentStatusEl.querySelector(
    '[data-component="' + data.component + '"]'
  ) : null;
  if (!card) return;
  var dot = card.querySelector(".status-dot");
  var msgEl = card.querySelector(".status-msg");
  var latencyEl = card.querySelector(".status-latency");

  dot.className = "status-dot " + data.status;
  msgEl.textContent = data.message || data.status;

  // Calculate and display latency between status updates
  if (latencyEl && data.timestamp) {
    var prev = state.lastStatusTimestamp[data.component];
    state.lastStatusTimestamp[data.component] = data.timestamp;

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

// ── Callback wiring (breaks circular deps via injection) ────────────────────

// When campaign loads: render all entity panels and word replacements
setOnCampaignLoaded(function (campaign) {
  renderPlayers(campaign.players || []);
  renderNpcs(campaign.npcs || []);
  renderLocations(campaign.locations || []);
  renderEntities(campaign.entities || []);
  renderRelationships(campaign.relationships || [], campaign);
  if (campaign.id) fetchWordReplacements(campaign.id);
});

// Inject fetchCampaignInfo into sessions.js (for live mode refresh)
setOnFetchCampaignInfo(fetchCampaignInfo);

// Inject entity rendering into sessions.js (for browse campaign switching)
setOnSelectBrowseCampaign(function (campaign) {
  renderPlayers(campaign.players || []);
  renderNpcs(campaign.npcs || []);
  renderLocations(campaign.locations || []);
  renderEntities(campaign.entities || []);
  renderRelationships(campaign.relationships || [], campaign);
  if (campaign.id) fetchWordReplacements(campaign.id);
});

// Inject fetchCampaignInfo into entities.js and relationships/index.js
setEntityCampaignRefresher(fetchCampaignInfo);
setRelCampaignRefresher(fetchCampaignInfo);

// ── Generate Campaign Summary button ────────────────────────────────────────

var generateCampaignSummaryBtn = document.getElementById("btn-generate-campaign-summary");
if (generateCampaignSummaryBtn) {
  generateCampaignSummaryBtn.addEventListener("click", function () {
    var campaignId = generateCampaignSummaryBtn.dataset.campaignId;
    if (!campaignId) return;
    var campaignSummaryTab = getCampaignSummaryTab();
    var campaignSummaryEl = getCampaignSummaryEl();
    clearLog(campaignSummaryTab);
    addLogEntry(campaignSummaryTab, "Requesting campaign summary generation...");
    withLoading(generateCampaignSummaryBtn, function () {
      return fetch("/api/campaigns/" + encodeURIComponent(campaignId) + "/campaign-summaries/generate", {
        method: "POST",
      })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data.status === "ok") {
            if (data.campaign_summary && campaignSummaryEl) {
              renderEditableSummary(campaignSummaryEl, data.campaign_summary, "campaign", campaignId);
            }
            var msg = "Completed: " + data.session_count + " session(s)";
            if (data.sessions_processed > 0) {
              msg += ", " + data.sessions_processed + " missing summary(s) generated";
            }
            addLogEntry(campaignSummaryTab, msg);
          } else {
            addLogEntry(campaignSummaryTab, "Error: " + (data.detail || "Unknown error"));
          }
        })
        .catch(function () {
          addLogEntry(campaignSummaryTab, "Error: request failed");
        });
    }, { loadingText: "Generating..." });
  });
}

// ── Summary tab switching ────────────────────────────────────────────────────

(function initSummaryTabs() {
  var summaryTabs = document.querySelectorAll(".summary-tab");
  var sessionSummaryTab = getSessionSummaryTab();
  var sessionChronologyTab = getSessionChronologyTab();
  var campaignSummaryTab = getCampaignSummaryTab();
  var summaryTabContents = [sessionSummaryTab, sessionChronologyTab, campaignSummaryTab];
  var summaryTabMap = { narrative: sessionSummaryTab, chronology: sessionChronologyTab, campaign: campaignSummaryTab };
  summaryTabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      summaryTabs.forEach(function (t) { t.classList.remove("active"); });
      tab.classList.add("active");
      var target = tab.getAttribute("data-tab");
      summaryTabContents.forEach(function (el) { if (el) el.classList.add("hidden"); });
      var activeTab = summaryTabMap[target];
      if (activeTab) activeTab.classList.remove("hidden");
    });
  });
})();

// ── Init all module listeners ────────────────────────────────────────────────

initCampaignListeners();
initTranscriptionListeners();
initEntityFormListeners();
initRelationshipListeners();
initSessionListeners();
initTTS();

// ── Bootstrap ────────────────────────────────────────────────────────────────

connectWS();
fetchCampaignInfo();
pollQuestions();
setInterval(function () {
  if (state.appMode === "live") pollQuestions();
}, 5000);

setTimeout(function () {
  fetchSessionList();
  setInterval(fetchSessionList, 30000);
}, 500);

setMode("live");
