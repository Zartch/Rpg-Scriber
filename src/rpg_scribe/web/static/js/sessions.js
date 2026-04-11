/* RPG Scribe - session list, browse mode, merge, questions */

import { state } from "./state.js";
import { escapeHtml, escapeAttr, formatDate, formatDuration, withLoading, withPanelLoading, showSkeleton, setRefreshing } from "./utils.js";
import { addTranscription, clearTranscriptionFeed } from "./transcription.js";
import { renderEditableSummary, updateGenerateChronologyBtn, getSessionSummaryEl, getSessionChronologyEl, getCampaignSummaryEl, getSessionSummaryTab, getSessionChronologyTab } from "./summary.js";

// DOM elements
var sessionListEl = document.getElementById("session-list");
var backToLiveBtn = document.getElementById("back-to-live");
var openTranscriptBtn = document.getElementById("open-transcript-btn");
var exportSessionBtn = document.getElementById("export-session-btn");
var modeLiveBtn = document.getElementById("mode-live-btn");
var modeBrowseBtn = document.getElementById("mode-browse-btn");
var browseCampaignsPanel = document.getElementById("browse-campaigns-panel");
var browseCampaignListEl = document.getElementById("browse-campaign-list");
var sessionsTitleEl = document.getElementById("sessions-title");
var summaryPanel = document.getElementById("summary-panel");
var questionsPanel = document.getElementById("questions-panel");
var questionsList = document.getElementById("questions-list");
var statusPanel = document.getElementById("status-panel");
var sessionLogLinkEl = document.getElementById("session-log-link");
var sessionExportListEl = document.getElementById("session-export-list");
var finalizeBtn = document.getElementById("finalize-btn");
var extractEntitiesBtn = document.getElementById("extract-entities-btn");
var refreshSummaryBtn = document.getElementById("refresh-summary-btn");

// Merge sessions DOM
var mergeBtnEl = document.getElementById("merge-sessions-btn");
var mergeConfirmPanel = document.getElementById("merge-confirm-panel");
var mergeExecuteBtn = document.getElementById("merge-execute-btn");
var mergeCancelBtn = document.getElementById("merge-cancel-btn");

// Callback injected from main.js to refresh browse campaign data
var onSelectBrowseCampaign = null;
export function setOnSelectBrowseCampaign(fn) { onSelectBrowseCampaign = fn; }

// Callback from main.js to refresh campaign info in live mode
var onFetchCampaignInfo = function () {};
export function setOnFetchCampaignInfo(fn) { onFetchCampaignInfo = fn; }

export function setMode(mode) {
  state.appMode = mode === "browse" ? "browse" : "live";
  if (modeLiveBtn) modeLiveBtn.classList.toggle("active", state.appMode === "live");
  if (modeBrowseBtn) modeBrowseBtn.classList.toggle("active", state.appMode === "browse");

  if (browseCampaignsPanel) {
    if (state.appMode === "browse") browseCampaignsPanel.classList.remove("hidden");
    else browseCampaignsPanel.classList.add("hidden");
  }

  if (statusPanel) statusPanel.classList.toggle("hidden", state.appMode !== "live");
  if (questionsPanel) questionsPanel.classList.toggle("hidden", state.appMode !== "live");
  if (sessionsTitleEl) sessionsTitleEl.textContent = state.appMode === "browse" ? "Campaign Sessions" : "Sessions";

  if (state.appMode === "browse") {
    state.viewingHistorical = true;
    state.loadedLiveSessionId = null;
    backToLiveBtn.classList.add("hidden");
    state.currentHistoricalSessionId = null;
    if (sessionLogLinkEl) { sessionLogLinkEl.classList.add("hidden"); sessionLogLinkEl.innerHTML = ""; }
    clearTranscriptionFeed("Select a session to view transcriptions.");
    var sessionSummaryEl = getSessionSummaryEl();
    var campaignSummaryEl = getCampaignSummaryEl();
    if (sessionSummaryEl) sessionSummaryEl.innerHTML = '<p class="placeholder">Select a session to view summary.</p>';
    if (campaignSummaryEl) campaignSummaryEl.innerHTML = '<p class="placeholder">Select a session to view campaign summary.</p>';
    fetchBrowseCampaigns();
  } else {
    state.viewingHistorical = false;
    state.currentHistoricalSessionId = null;
    state.browseCampaignId = null;
    if (sessionLogLinkEl) sessionLogLinkEl.classList.add("hidden");
    onFetchCampaignInfo();
    var addNpcBtn = document.getElementById("add-npc-btn");
    var addLocationBtn = document.getElementById("add-location-btn");
    var addEntityBtn = document.getElementById("add-entity-btn");
    var addRelationshipBtn = document.getElementById("add-relationship-btn");
    if (addNpcBtn) addNpcBtn.classList.remove("hidden");
    if (addLocationBtn) addLocationBtn.classList.remove("hidden");
    if (addEntityBtn) addEntityBtn.classList.remove("hidden");
    if (addRelationshipBtn) addRelationshipBtn.classList.remove("hidden");
    fetchSessionList();
    pollQuestions();
  }

  updateFinalizeButton();
}

function fetchBrowseCampaigns() {
  if (browseCampaignListEl) showSkeleton(browseCampaignListEl, 4);

  withPanelLoading(browseCampaignsPanel, function () {
    return fetch("/api/browse/campaigns")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var campaigns = [{
          id: state.UNCATEGORIZED_BROWSE_ID,
          name: "Sin campana",
          game_system: "",
          is_active: false
        }].concat(data.campaigns || []);
        state.browseCampaignsCache = campaigns.slice();
        renderBrowseCampaignList(campaigns);

        var preferred = state.browseCampaignId || data.active_campaign_id || state.UNCATEGORIZED_BROWSE_ID;
        if (preferred) {
          selectBrowseCampaign(preferred);
        } else {
          sessionListEl.innerHTML = '<p class="placeholder">No sessions yet.</p>';
        }
      })
      .catch(function () {
        if (browseCampaignListEl) browseCampaignListEl.innerHTML = '<p class="placeholder">Failed to load campaigns.</p>';
      });
  });
}

function renderBrowseCampaignList(campaigns) {
  if (!browseCampaignListEl) return;
  if (!campaigns.length) {
    browseCampaignListEl.innerHTML = '<p class="placeholder">No campaigns in database.</p>';
    return;
  }

  browseCampaignListEl.innerHTML = "";
  campaigns.forEach(function (campaign) {
    var item = document.createElement("div");
    item.className = "campaign-item" + (campaign.id === state.browseCampaignId ? " active" : "");
    item.dataset.campaignId = campaign.id;

    var meta = [];
    if (campaign.game_system) meta.push(campaign.game_system);
    if (campaign.is_active) meta.push("active");
    item.innerHTML =
      '<div class="campaign-item-name">' + escapeHtml(campaign.name || campaign.id) + "</div>" +
      '<div class="campaign-item-meta">' + escapeHtml(meta.join(" | ")) + "</div>";

    item.addEventListener("click", function () {
      selectBrowseCampaign(campaign.id);
    });
    browseCampaignListEl.appendChild(item);
  });
}

function selectBrowseCampaign(campaignId) {
  state.browseCampaignId = campaignId;

  if (campaignId === state.UNCATEGORIZED_BROWSE_ID) {
    state.currentCampaign = null;
    state.activeCampaignId = null;
    var campaignBar = document.getElementById("campaign-bar");
    var campaignNameEl = document.getElementById("campaign-name");
    var campaignSystemEl = document.getElementById("campaign-system");
    var campaignMasterEl = document.getElementById("campaign-master");
    var campaignEditBtn = document.getElementById("campaign-edit-btn");
    var campaignDetailsSection = document.getElementById("campaign-details-section");
    var replacementsSection = document.getElementById("replacements-section");
    if (campaignBar) campaignBar.classList.remove("hidden");
    if (campaignNameEl) campaignNameEl.textContent = "Sin campana";
    if (campaignSystemEl) campaignSystemEl.textContent = "";
    if (campaignMasterEl) campaignMasterEl.textContent = "";
    if (campaignEditBtn) campaignEditBtn.classList.add("hidden");
    if (campaignDetailsSection) campaignDetailsSection.classList.add("hidden");
    if (replacementsSection) replacementsSection.classList.add("hidden");
    import("./campaign.js").then(function (camp) { camp.updateCampaignSummaryStats({}); });
    renderBrowseCampaignList(state.browseCampaignsCache);
    fetchSessionList();
    return;
  }

  var campaignBar = document.getElementById("campaign-bar");
  withPanelLoading(campaignBar, function () {
    return fetch("/api/browse/campaigns/" + encodeURIComponent(campaignId))
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var campaign = data.campaign;
        if (!campaign) {
          return;
        }
        state.currentCampaign = campaign;
        state.activeCampaignId = campaign.id;
        import("./campaign.js").then(function (camp) {
          camp.renderCampaignBar(campaign);
          camp.updateCampaignSummaryStats(campaign);
        });
        var campaignDetailsSection = document.getElementById("campaign-details-section");
        var replacementsSection = document.getElementById("replacements-section");
        if (campaignDetailsSection) campaignDetailsSection.classList.remove("hidden");
        onFetchCampaignInfo.__browse = true;
        // Trigger entity rendering via the campaign loaded callback
        if (onSelectBrowseCampaign) onSelectBrowseCampaign(campaign);
        if (replacementsSection && campaign.id) {
          replacementsSection.classList.remove("hidden");
          import("./entities.js").then(function (ents) { ents.fetchWordReplacements(campaign.id); });
        }
        renderBrowseCampaignList(state.browseCampaignsCache);
        fetchSessionList();
      })
      .catch(function () {});
  });
}

function renderSessionLogLink(sessionId) {
  if (!sessionLogLinkEl || !sessionId) return;
  fetch("/api/sessions/" + encodeURIComponent(sessionId) + "/logs")
    .then(function (r) { return r.json(); })
    .then(function (data) {
      if (!data.exists || !data.explorer_url) {
        sessionLogLinkEl.classList.add("hidden");
        sessionLogLinkEl.innerHTML = "";
        return;
      }
      sessionLogLinkEl.classList.remove("hidden");
      sessionLogLinkEl.innerHTML = '<a href="' + escapeAttr(data.explorer_url) + '" target="_blank" rel="noopener">Open session logs</a>';
    })
    .catch(function () {
      sessionLogLinkEl.classList.add("hidden");
    });
}

function renderSessionExports(sessionId) {
  if (!sessionExportListEl || !sessionId) return;
  fetch("/api/sessions/" + encodeURIComponent(sessionId) + "/exports")
    .then(function (r) { return r.json(); })
    .then(function (data) {
      var exports = data.exports || [];
      if (!exports.length) {
        sessionExportListEl.classList.add("hidden");
        sessionExportListEl.innerHTML = "";
        return;
      }
      sessionExportListEl.classList.remove("hidden");
      sessionExportListEl.innerHTML =
        "<strong>Recent exports</strong><ul>" +
        exports.slice(0, 5).map(function (item) {
          return (
            "<li>" +
              '<span class="export-date">' + escapeHtml(item.display_date || item.created_at || "") + "</span>" +
              '<a href="' + escapeAttr(item.download_url || "#") + '">Download ZIP</a>' +
            "</li>"
          );
        }).join("") +
        "</ul>";
    })
    .catch(function () {
      sessionExportListEl.classList.add("hidden");
      sessionExportListEl.innerHTML = "";
    });
}

export function fetchSessionList() {
  fetch("/api/status")
    .then(function (r) { return r.json(); })
    .then(function (data) {
      state.activeSessionId = data.active_session_id;
      var limits = data.web_limits || {};
      if (typeof limits.live_feed_max_items === "number" && limits.live_feed_max_items > 0) {
        state.maxFeedItems = limits.live_feed_max_items;
      }
      updateFinalizeButton();

      if (state.appMode === "live" && !state.viewingHistorical && state.activeSessionId && state.loadedLiveSessionId !== state.activeSessionId) {
        loadLiveSessionSnapshot(state.activeSessionId);
      }
    })
    .catch(function () {});

  var sessionsUrl;
  if (state.appMode === "browse") {
    if (state.browseCampaignId === state.UNCATEGORIZED_BROWSE_ID) {
      sessionsUrl = "/api/browse/sessions/uncategorized";
    } else if (state.browseCampaignId) {
      sessionsUrl = "/api/campaigns/" + state.browseCampaignId + "/sessions";
    } else {
      sessionsUrl = "/api/sessions";
    }
  } else if (state.activeCampaignId) {
    sessionsUrl = "/api/campaigns/" + state.activeCampaignId + "/sessions";
  } else {
    sessionsUrl = "/api/sessions";
  }

  if (!state.sessionListLoaded) {
    showSkeleton(sessionListEl, 5);
  } else {
    setRefreshing(sessionListEl, true);
  }

  fetch(sessionsUrl)
    .then(function (r) { return r.json(); })
    .then(function (data) {
      renderSessionList(data.sessions || []);
      state.sessionListLoaded = true;
    })
    .catch(function () {})
    .finally(function () {
      setRefreshing(sessionListEl, false);
    });
}

function renderSessionList(sessions) {
  if (sessions.length === 0) {
    sessionListEl.innerHTML = '<p class="placeholder">No sessions yet.</p>';
    return;
  }
  sessionListEl.innerHTML = "";
  sessions.forEach(function (s) {
    var item = document.createElement("div");
    var isActive = s.id === state.activeSessionId;
    item.className = "session-item" + (isActive ? " active" : "") +
      (s.status === "completed" ? " completed" : "");
    item.dataset.sessionId = s.id;

    var label = isActive ? "LIVE" : (s.status || "");
    var dateStr = s.started_at ? formatDate(s.started_at) : "";
    var preview = s.summary_preview || "";
    var duration = s.duration_minutes ? formatDuration(s.duration_minutes) : "";

    var metaLine = "";
    if (dateStr || duration) {
      metaLine += '<div class="session-date">';
      metaLine += escapeHtml(dateStr);
      if (duration) {
        metaLine += ' <span class="session-duration">(' + escapeHtml(duration) + ')</span>';
      }
      metaLine += "</div>";
    }

    var indicators = "";
    if (s.has_summary) {
      indicators += '<span class="session-indicator" title="Has summary">S</span>';
    }

    var titleLine = s.title
      ? '<div class="session-title">' + escapeHtml(s.title) + '</div>'
      : '<div class="session-title session-title-empty">Sin título</div>';

    item.innerHTML =
      '<div class="session-header">' +
      '<span class="session-id">' + escapeHtml(s.id.substring(0, 8)) + "</span>" +
      '<div class="session-header-right">' +
      indicators +
      '<span class="session-badge ' + (isActive ? 'live' : s.status) + '">' +
      escapeHtml(label) + '</span>' +
      '</div>' +
      '</div>' +
      titleLine +
      metaLine +
      (preview ? '<div class="session-preview">' + escapeHtml(preview) + '</div>' : "");

    (function (session, el) {
      el.addEventListener("click", function () {
        if (state.mergeMode) {
          toggleMergeSelect(session, el);
          return;
        }
        if (state.appMode === "browse" || !isActive) {
          loadHistoricalSession(session.id);
          highlightSession(session.id);
        } else {
          switchToLive();
        }
      });
    })(s, item);

    sessionListEl.appendChild(item);
  });
}

function highlightSession(sessionId) {
  var items = sessionListEl.querySelectorAll(".session-item");
  for (var i = 0; i < items.length; i++) {
    items[i].classList.remove("selected");
    if (items[i].dataset.sessionId === sessionId) {
      items[i].classList.add("selected");
    }
  }
}

function loadLiveSessionSnapshot(sessionId) {
  showSkeleton(document.getElementById("transcription-feed"), 6);

  withPanelLoading(summaryPanel, function () {
    return Promise.all([
      fetch("/api/sessions/" + sessionId + "/transcriptions").then(function (r) { return r.json(); }),
      fetch("/api/sessions/" + sessionId + "/summary").then(function (r) { return r.json(); })
    ])
      .then(function (results) {
        var transData = results[0];
        var summData = results[1];

        var transcriptionFeed = document.getElementById("transcription-feed");
        transcriptionFeed.innerHTML = "";
        var transcriptions = transData.transcriptions || [];
        if (transcriptions.length === 0) {
          transcriptionFeed.innerHTML = '<p class="placeholder">No transcriptions yet.</p>';
        } else {
          transcriptions.forEach(function (t) { addTranscription(t); });
        }

        var sessionSummaryEl = getSessionSummaryEl();
        var sessionChronologyEl = getSessionChronologyEl();
        var campaignSummaryEl = getCampaignSummaryEl();

        renderEditableSummary(sessionSummaryEl, summData.session_summary || "", "session", sessionId);
        if (summData.session_chronology) {
          renderEditableSummary(sessionChronologyEl, summData.session_chronology, "chronology", sessionId);
          updateGenerateChronologyBtn(sessionId);
        } else {
          sessionChronologyEl.innerHTML = '<p class="placeholder">No chronology yet.</p>';
          updateGenerateChronologyBtn(sessionId);
        }
        renderEditableSummary(campaignSummaryEl, summData.campaign_summary || "", "campaign", state.activeCampaignId || state.browseCampaignId || "");
        state.loadedLiveSessionId = sessionId;
        renderSessionLogLink(sessionId);
        renderSessionExports(sessionId);
      })
      .catch(function () {});
  });
}

function loadHistoricalSession(sessionId) {
  state.viewingHistorical = true;
  state.currentHistoricalSessionId = sessionId;
  if (state.appMode === "live") backToLiveBtn.classList.remove("hidden");
  renderSessionLogLink(sessionId);
  renderSessionExports(sessionId);
  updateFinalizeButton();

  showSkeleton(document.getElementById("transcription-feed"), 6);

  withPanelLoading(summaryPanel, function () {
    return Promise.all([
      fetch("/api/sessions/" + sessionId + "/transcriptions").then(function (r) { return r.json(); }),
      fetch("/api/sessions/" + sessionId + "/summary").then(function (r) { return r.json(); })
    ])
      .then(function (results) {
        var transData = results[0];
        var summData = results[1];

        var transcriptionFeed = document.getElementById("transcription-feed");
        transcriptionFeed.innerHTML = "";
        var transcriptions = transData.transcriptions || [];
        if (transcriptions.length === 0) {
          transcriptionFeed.innerHTML = '<p class="placeholder">No transcriptions for this session.</p>';
        } else {
          transcriptions.forEach(function (t) { addTranscription(t); });
        }

        var sessionSummaryEl = getSessionSummaryEl();
        var sessionChronologyEl = getSessionChronologyEl();
        var campaignSummaryEl = getCampaignSummaryEl();

        renderEditableSummary(sessionSummaryEl, summData.session_summary || "", "session", sessionId);
        if (summData.session_chronology) {
          renderEditableSummary(sessionChronologyEl, summData.session_chronology, "chronology", sessionId);
          updateGenerateChronologyBtn(sessionId);
        } else {
          sessionChronologyEl.innerHTML = '<p class="placeholder">No chronology yet.</p>';
          updateGenerateChronologyBtn(sessionId);
        }
        renderEditableSummary(campaignSummaryEl, summData.campaign_summary || "", "campaign", state.activeCampaignId || state.browseCampaignId || "");
      })
      .catch(function () {
        var transcriptionFeed = document.getElementById("transcription-feed");
        transcriptionFeed.innerHTML = '<p class="placeholder">Failed to load session data.</p>';
      });
  });
}

function switchToLive() {
  if (state.appMode !== "live") return;
  state.viewingHistorical = false;
  state.currentHistoricalSessionId = null;
  state.loadedLiveSessionId = null;
  backToLiveBtn.classList.add("hidden");
  updateFinalizeButton();

  if (sessionLogLinkEl) {
    sessionLogLinkEl.classList.add("hidden");
    sessionLogLinkEl.innerHTML = "";
  }
  if (sessionExportListEl) {
    sessionExportListEl.classList.add("hidden");
    sessionExportListEl.innerHTML = "";
  }

  var items = sessionListEl.querySelectorAll(".session-item");
  for (var i = 0; i < items.length; i++) {
    items[i].classList.remove("selected");
  }

  var transcriptionFeed = document.getElementById("transcription-feed");
  transcriptionFeed.innerHTML = "";
  var sessionSummaryEl = getSessionSummaryEl();
  var campaignSummaryEl = getCampaignSummaryEl();
  if (sessionSummaryEl) sessionSummaryEl.innerHTML = '<p class="placeholder">Waiting for summary updates&hellip;</p>';
  if (campaignSummaryEl) campaignSummaryEl.innerHTML = '<p class="placeholder">No campaign summary yet.</p>';
  if (state.activeSessionId) {
    loadLiveSessionSnapshot(state.activeSessionId);
  }
}

function getSessionIdForTranscriptView() {
  if (state.currentHistoricalSessionId) {
    return state.currentHistoricalSessionId;
  }
  if (state.appMode === "live" && state.activeSessionId) {
    return state.activeSessionId;
  }
  return null;
}

function updateFinalizeButton() {
  var show = !!(state.appMode === "live" && state.activeSessionId && !state.viewingHistorical);
  var exportTarget = !!getSessionIdForTranscriptView();
  var extractTarget = !!getSessionIdForTranscriptView();

  if (finalizeBtn) {
    if (show) {
      finalizeBtn.classList.remove("hidden");
    } else {
      finalizeBtn.classList.add("hidden");
    }
  }

  if (exportSessionBtn) {
    exportSessionBtn.disabled = !exportTarget;
    exportSessionBtn.title = exportTarget
      ? "Generate a session export bundle"
      : "Select a session first";
  }

  if (extractEntitiesBtn) {
    if (extractTarget) {
      extractEntitiesBtn.classList.remove("hidden");
    } else {
      extractEntitiesBtn.classList.add("hidden");
    }
  }
}

export function pollQuestions() {
  fetch("/api/questions")
    .then(function (r) { return r.json(); })
    .then(function (data) {
      var questions = data.questions || [];
      renderQuestions(questions);
      var questionsBadge = document.querySelector(".questions-badge");
      if (questionsBadge) {
        updateQuestionsBadge(questionsBadge, questions.length);
      }
    })
    .catch(function () {});
}

function updateQuestionsBadge(questionsBadge, count) {
  if (!questionsBadge) return;
  if (count > 0) {
    questionsBadge.textContent = count;
    questionsBadge.classList.remove("hidden");
    if (count > state.previousQuestionCount) {
      questionsBadge.classList.remove("pulse");
      void questionsBadge.offsetWidth;
      questionsBadge.classList.add("pulse");
    }
  } else {
    questionsBadge.classList.add("hidden");
  }
  state.previousQuestionCount = count;
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

      withLoading(btn, function () {
        return fetch("/api/questions/" + q.id + "/answer", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ answer: input.value }),
        })
          .then(function (r) { return r.json(); })
          .then(function (data) {
            if (data.ok) {
              feedback.textContent = "Answer saved!";
              feedback.className = "q-feedback success";
              form.classList.add("hidden");
              setTimeout(function () { pollQuestions(); }, 1200);
            } else {
              feedback.textContent = "Failed to save. Try again.";
              feedback.className = "q-feedback error";
              throw new Error("Failed to save answer");
            }
          })
          .catch(function () {
            feedback.textContent = "Failed to save. Try again.";
            feedback.className = "q-feedback error";
            throw new Error("Failed to save answer");
          });
      }, { loadingText: "Sending..." });
    });
    questionsList.appendChild(card);
  });
}

// ── Merge sessions ─────────────────────────────────────────

function enterMergeMode() {
  state.mergeMode = true;
  state.mergeSelected = [];
  mergeBtnEl.textContent = "Cancel Merge";
  mergeBtnEl.classList.add("active");
  mergeConfirmPanel.classList.add("hidden");
  // Re-render to show selection styling
  var items = sessionListEl.querySelectorAll(".session-item");
  for (var i = 0; i < items.length; i++) {
    items[i].classList.remove("merge-selected");
  }
}

function exitMergeMode() {
  state.mergeMode = false;
  state.mergeSelected = [];
  mergeBtnEl.textContent = "Merge";
  mergeBtnEl.classList.remove("active");
  mergeConfirmPanel.classList.add("hidden");
  var items = sessionListEl.querySelectorAll(".session-item");
  for (var i = 0; i < items.length; i++) {
    items[i].classList.remove("merge-selected");
  }
}

function toggleMergeSelect(session, el) {
  var idx = state.mergeSelected.findIndex(function (s) { return s.id === session.id; });
  if (idx >= 0) {
    state.mergeSelected.splice(idx, 1);
    el.classList.remove("merge-selected");
  } else if (state.mergeSelected.length < 2) {
    state.mergeSelected.push(session);
    el.classList.add("merge-selected");
  }
  updateMergeConfirmPanel();
}

function updateMergeConfirmPanel() {
  if (state.mergeSelected.length !== 2) {
    mergeConfirmPanel.classList.add("hidden");
    return;
  }
  // Target = earlier session, source = later session
  var a = state.mergeSelected[0];
  var b = state.mergeSelected[1];
  var target, source;
  if ((a.started_at || 0) <= (b.started_at || 0)) {
    target = a; source = b;
  } else {
    target = b; source = a;
  }
  state.mergeSelected = [target, source]; // normalize order

  var info = mergeConfirmPanel.querySelector(".merge-info");
  var targetDate = target.started_at ? formatDate(target.started_at) : target.id.substring(0, 8);
  var sourceDate = source.started_at ? formatDate(source.started_at) : source.id.substring(0, 8);
  info.innerHTML =
    "Merge <strong>" + escapeHtml(sourceDate) + "</strong> into " +
    "<strong>" + escapeHtml(targetDate) + "</strong>?<br>" +
    "<small>Transcriptions and summaries will be combined into the earlier session.</small>";
  mergeConfirmPanel.classList.remove("hidden");
}

function executeMerge() {
  if (state.mergeSelected.length !== 2) return;
  var target = state.mergeSelected[0];
  var source = state.mergeSelected[1];

  withLoading(mergeExecuteBtn, function () {
    return fetch("/api/sessions/merge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_id: source.id, target_id: target.id })
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.ok) {
          exitMergeMode();
          fetchSessionList();
        } else {
          alert("Merge failed: " + (data.error || "Unknown error"));
        }
      })
      .catch(function (err) {
        alert("Merge error: " + err.message);
      });
  }, { loadingText: "Merging..." });
}

export function initSessionListeners() {
  backToLiveBtn.addEventListener("click", switchToLive);

  if (openTranscriptBtn) {
    openTranscriptBtn.addEventListener("click", function () {
      var sessionId = getSessionIdForTranscriptView();
      if (!sessionId) {
        alert("No active or selected session.");
        return;
      }
      var url = "/transcript.html?session_id=" + encodeURIComponent(sessionId);
      window.open(url, "_blank");
    });
  }

  if (exportSessionBtn) {
    exportSessionBtn.addEventListener("click", function () {
      var sessionId = getSessionIdForTranscriptView();
      if (!sessionId) {
        alert("No active or selected session.");
        return;
      }
      withLoading(exportSessionBtn, function() {
        return fetch("/api/sessions/" + encodeURIComponent(sessionId) + "/export", {
          method: "POST",
        })
          .then(function (r) { return r.json(); })
          .then(function (data) {
            if (!data.ok) {
              alert("Failed to generate export.");
              return;
            }
            renderSessionExports(sessionId);
            // Show success feedback for 1.8s
            exportSessionBtn.textContent = "Exported";
            setTimeout(function () {
              if (exportSessionBtn.textContent === "Exported") {
                exportSessionBtn.textContent = "Export";
              }
            }, 1800);
          })
          .catch(function () {
            alert("Failed to generate export.");
          });
      }, { loadingText: "Exporting..." });
    });
  }

  if (finalizeBtn) {
    finalizeBtn.addEventListener("click", function () {
      if (!state.activeSessionId) return;
      if (!confirm("Finalize the current session? This will generate the final summary and end the session.")) {
        return;
      }
      withLoading(finalizeBtn, function () {
        return fetch("/api/sessions/" + state.activeSessionId + "/finalize", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
        })
          .then(function (r) { return r.json(); })
          .then(function (data) {
            if (data.ok) {
              state.activeSessionId = null;
              updateFinalizeButton();
              setTimeout(fetchSessionList, 2000);
            } else {
              alert("Error: " + (data.error || "Failed to finalize"));
            }
          })
          .catch(function () {
            alert("Failed to finalize session.");
          });
      }, { loadingText: "Finalizing..." });
    });
  }

  if (refreshSummaryBtn) {
    refreshSummaryBtn.addEventListener("click", function () {
      var sessionId = state.activeSessionId || state.currentHistoricalSessionId;
      if (!sessionId) return;

      import("./summary.js").then(function (summary) {
        summary.clearLog(summary.getSessionSummaryTab());
        summary.addLogEntry(summary.getSessionSummaryTab(), "Generating summary...");

        withLoading(refreshSummaryBtn, function() {
          return fetch("/api/sessions/" + encodeURIComponent(sessionId) + "/generate-summary", {
            method: "POST",
          })
            .then(function (r) { return r.json(); })
            .then(function (data) {
              if (data.ok) {
                if (data.session_summary) {
                  summary.renderEditableSummary(summary.getSessionSummaryEl(), data.session_summary, "session", sessionId);
                }
                summary.addLogEntry(summary.getSessionSummaryTab(), "Summary updated");
              } else {
                summary.addLogEntry(summary.getSessionSummaryTab(), "Error: " + (data.error || "Failed"));
              }
            })
            .catch(function () {
              summary.addLogEntry(summary.getSessionSummaryTab(), "Error: request failed");
            });
        }, { loadingText: "Generating..." });
      });
    });
  }

  if (extractEntitiesBtn) {
    extractEntitiesBtn.addEventListener("click", function () {
      var sessionId = getSessionIdForTranscriptView();
      if (!sessionId) return;

      withLoading(extractEntitiesBtn, function () {
        return fetch("/api/sessions/" + sessionId + "/extract-entities", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
        })
          .then(function (r) { return r.json(); })
          .then(function (data) {
            if (data.ok) {
              var total = (data.new_npcs || []).length + (data.new_locations || []).length + (data.new_entities || []).length + (data.new_relationships || []).length;
              extractEntitiesBtn.textContent = total > 0 ? ("+" + total + " found!") : "Nothing new";
              onFetchCampaignInfo();
              setTimeout(function () {
                extractEntitiesBtn.textContent = "Extract Entities";
              }, 3000);
            } else {
              alert("Extraction failed: " + (data.error || "Unknown error"));
            }
          })
          .catch(function () {
            alert("Failed to run entity extraction.");
          });
      }, { loadingText: "Extracting..." });
    });
  }

  if (mergeBtnEl) {
    mergeBtnEl.addEventListener("click", function () {
      if (state.mergeMode) {
        exitMergeMode();
      } else {
        enterMergeMode();
      }
    });
  }
  if (mergeExecuteBtn) {
    mergeExecuteBtn.addEventListener("click", executeMerge);
  }
  if (mergeCancelBtn) {
    mergeCancelBtn.addEventListener("click", exitMergeMode);
  }

  if (modeLiveBtn) {
    modeLiveBtn.addEventListener("click", function () {
      setMode("live");
    });
  }

  if (modeBrowseBtn) {
    modeBrowseBtn.addEventListener("click", function () {
      setMode("browse");
    });
  }

  // Generate Campaign Summary button
  var generateCampaignSummaryBtn = document.getElementById("btn-generate-campaign-summary");
  if (generateCampaignSummaryBtn) {
    generateCampaignSummaryBtn.addEventListener("click", function () {
      var campaignId = generateCampaignSummaryBtn.dataset.campaignId;
      if (!campaignId) return;
      import("./summary.js").then(function (summary) {
        summary.clearLog(summary.getCampaignSummaryTab());
        summary.addLogEntry(summary.getCampaignSummaryTab(), "Requesting campaign summary generation...");
        withLoading(generateCampaignSummaryBtn, function () {
          return fetch("/api/campaigns/" + encodeURIComponent(campaignId) + "/campaign-summaries/generate", {
            method: "POST",
          })
            .then(function (r) { return r.json(); })
            .then(function (data) {
              if (data.status === "ok") {
                if (data.campaign_summary && summary.getCampaignSummaryEl()) {
                  summary.renderEditableSummary(summary.getCampaignSummaryEl(), data.campaign_summary, "campaign", campaignId);
                }
                var msg = "Completed: " + data.session_count + " session(s)";
                if (data.sessions_processed > 0) {
                  msg += ", " + data.sessions_processed + " missing summary(s) generated";
                }
                summary.addLogEntry(summary.getCampaignSummaryTab(), msg);
              } else {
                summary.addLogEntry(summary.getCampaignSummaryTab(), "Error: " + (data.detail || "Unknown error"));
              }
            })
            .catch(function () {
              summary.addLogEntry(summary.getCampaignSummaryTab(), "Error: request failed");
            });
        }, { loadingText: "Generating..." });
      });
    });
  }

  // Summary tab switching
  var summaryTabs = document.querySelectorAll(".summary-tab");
  var summaryTabContents = [
    document.getElementById("session-summary"),
    document.getElementById("session-chronology"),
    document.getElementById("campaign-summary")
  ];
  var summaryTabMap = {
    narrative: document.getElementById("session-summary"),
    chronology: document.getElementById("session-chronology"),
    campaign: document.getElementById("campaign-summary")
  };
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
}
