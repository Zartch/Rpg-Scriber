/* RPG Scribe - campaign info and editing */

import { state } from "./state.js";
import { escapeHtml, escapeAttr, withLoading, withPanelLoading } from "./utils.js";

// DOM elements
var campaignBar = document.getElementById("campaign-bar");
var campaignDisplay = document.getElementById("campaign-display");
var campaignNameEl = document.getElementById("campaign-name");
var campaignSystemEl = document.getElementById("campaign-system");
var campaignMasterEl = document.getElementById("campaign-master");
var campaignExportBtn = document.getElementById("campaign-export-btn");
var campaignEditBtn = document.getElementById("campaign-edit-btn");
var campaignEditForm = document.getElementById("campaign-edit-form");
var campaignEditCancel = document.getElementById("campaign-edit-cancel");
var editNameInput = document.getElementById("edit-campaign-name");
var editSystemInput = document.getElementById("edit-campaign-system");
var editDescInput = document.getElementById("edit-campaign-desc");
var editInstructionsInput = document.getElementById("edit-campaign-instructions");
var editMasterSelect = document.getElementById("edit-campaign-master");
var campaignDetailsSection = document.getElementById("campaign-details-section");
var replacementsSection = document.getElementById("replacements-section");
var statPlayers = document.getElementById("stat-players");
var statNpcs = document.getElementById("stat-npcs");
var statLocations = document.getElementById("stat-locations");
var statEntities = document.getElementById("stat-entities");
var statRelationships = document.getElementById("stat-relationships");

// Callback injected from main.js when campaign is loaded
var onCampaignLoaded = function () {};
export function setOnCampaignLoaded(fn) { onCampaignLoaded = fn; }

export function fetchCampaignInfo() {
  withPanelLoading(campaignBar, function () {
    return fetch("/api/campaigns")
    .then(function (r) { return r.json(); })
    .then(function (data) {
      if (data.campaign) {
        state.currentCampaign = data.campaign;
        state.activeCampaignId = data.campaign.id;
        renderCampaignBar(data.campaign);
        if (data.campaign.is_generic) {
          if (campaignDetailsSection) campaignDetailsSection.classList.add("hidden");
          if (replacementsSection) replacementsSection.classList.add("hidden");
        } else {
          if (campaignDetailsSection) campaignDetailsSection.classList.remove("hidden");
          onCampaignLoaded(data.campaign);
          updateCampaignSummaryStats(data.campaign);
          if (replacementsSection && data.campaign.id) {
            replacementsSection.classList.remove("hidden");
          }
        }
        // Show "View all" link and "Generate" button for campaign summaries
        var summariesLink = document.getElementById("campaign-summaries-link");
        var generateBtn = document.getElementById("btn-generate-campaign-summary");
        if (summariesLink && data.campaign.id) {
          summariesLink.href = "/campaign-summaries.html?campaign=" + encodeURIComponent(data.campaign.id);
          summariesLink.classList.remove("hidden");
        }
        if (generateBtn && data.campaign.id) {
          generateBtn.dataset.campaignId = data.campaign.id;
        }
        // Load campaign summary on init
        if (data.campaign.id) {
          fetch("/api/campaigns/" + encodeURIComponent(data.campaign.id) + "/campaign-summaries/latest")
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (csData) {
              if (csData && csData.campaign_summary && csData.campaign_summary.content) {
                import("./summary.js").then(function (summary) {
                  summary.renderEditableSummary(summary.getCampaignSummaryEl(), csData.campaign_summary.content, "campaign", data.campaign.id);
                });
              }
            })
            .catch(function () {});
        }
      } else {
        // No campaign loaded - show "Resume mode"
        campaignBar.classList.remove("hidden");
        campaignNameEl.textContent = "No campaign \u2014 Resume mode";
        campaignSystemEl.textContent = "";
        campaignMasterEl.textContent = "";
        campaignEditBtn.classList.add("hidden");
        if (campaignExportBtn) campaignExportBtn.classList.add("hidden");
        if (campaignDetailsSection) campaignDetailsSection.classList.add("hidden");
        if (replacementsSection) replacementsSection.classList.add("hidden");
        state.currentCampaign = null;
        state.activeCampaignId = null;
      }
    })
    .catch(function () {});
  });
}

export function renderCampaignBar(campaign) {
  campaignBar.classList.remove("hidden");
  campaignNameEl.textContent = campaign.name || "Unnamed Campaign";

  var systemText = "";
  if (campaign.game_system) systemText += campaign.game_system;
  if (campaign.language) {
    systemText += (systemText ? " \u00b7 " : "") + campaign.language.toUpperCase();
  }
  campaignSystemEl.textContent = systemText ? "(" + systemText + ")" : "";
  campaignMasterEl.textContent = getMasterDisplayName(campaign);

  // Hide edit for generic campaigns
  if (campaign.is_generic) {
    campaignEditBtn.classList.add("hidden");
    if (campaignExportBtn) campaignExportBtn.classList.add("hidden");
    campaignNameEl.textContent = "No campaign \u2014 Resume mode";
    campaignSystemEl.textContent = "";
    campaignMasterEl.textContent = "";
    if (campaignDetailsSection) campaignDetailsSection.classList.add("hidden");
    if (replacementsSection) replacementsSection.classList.add("hidden");
    updateCampaignSummaryStats({});
  } else {
    campaignEditBtn.classList.remove("hidden");
    if (campaignExportBtn) {
      var showExport = state.appMode === "browse" && !!campaign.id;
      campaignExportBtn.classList.toggle("hidden", !showExport);
    }
  }
}

export function updateCampaignSummaryStats(campaign) {
  var mapping = [
    { el: statPlayers, key: "players" },
    { el: statNpcs, key: "npcs" },
    { el: statLocations, key: "locations" },
    { el: statEntities, key: "entities" },
    { el: statRelationships, key: "relationships" }
  ];
  mapping.forEach(function(item) {
    if (!item.el) return;
    var count = (campaign[item.key] || []).length;
    item.el.textContent = count;
    var parent = item.el.closest(".summary-stat");
    if (parent) parent.classList.toggle("dimmed", count === 0);
  });
}

function getMasterDisplayName(campaign) {
  var players = campaign.players || [];
  var dmId = campaign.dm_speaker_id || "";
  if (!dmId) return "";
  for (var i = 0; i < players.length; i++) {
    if (players[i].discord_id === dmId) {
      return "Master: " + (players[i].discord_name || players[i].character_name || dmId);
    }
  }
  return "Master: " + dmId;
}

function populateMasterSelect(players, selectedDmId) {
  editMasterSelect.innerHTML = "";
  var noneOpt = document.createElement("option");
  noneOpt.value = "";
  noneOpt.textContent = "(No master selected)";
  editMasterSelect.appendChild(noneOpt);

  players.forEach(function (p) {
    var opt = document.createElement("option");
    opt.value = p.discord_id || "";
    opt.textContent = (p.discord_name || "?") + " -> " + (p.character_name || "?");
    editMasterSelect.appendChild(opt);
  });

  editMasterSelect.value = selectedDmId || "";
  editMasterSelect.disabled = !players || players.length === 0;
}

function openCampaignEdit() {
  if (!state.currentCampaign) return;
  editNameInput.value = state.currentCampaign.name || "";
  editSystemInput.value = state.currentCampaign.game_system || "";
  editDescInput.value = state.currentCampaign.description || "";
  editInstructionsInput.value = state.currentCampaign.custom_instructions || "";
  populateMasterSelect(state.currentCampaign.players || [], state.currentCampaign.dm_speaker_id || "");

  campaignDisplay.classList.add("hidden");
  campaignEditForm.classList.remove("hidden");
  editNameInput.focus();
}

function closeCampaignEdit() {
  campaignEditForm.classList.add("hidden");
  campaignDisplay.classList.remove("hidden");
}

function saveCampaignEdit(e) {
  e.preventDefault();
  if (!state.currentCampaign || !state.activeCampaignId) return;

  var body = {
    name: editNameInput.value.trim(),
    game_system: editSystemInput.value.trim(),
    description: editDescInput.value.trim(),
    custom_instructions: editInstructionsInput.value.trim(),
    dm_speaker_id: editMasterSelect.value,
  };

  var saveBtn = campaignEditForm.querySelector(".btn-save");

  withLoading(saveBtn, function () {
    return fetch("/api/campaigns/" + state.activeCampaignId, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.ok && data.campaign) {
          state.currentCampaign = data.campaign;
          renderCampaignBar(data.campaign);
          closeCampaignEdit();
        } else {
          alert("Error: " + (data.error || "Unknown error"));
        }
      })
      .catch(function () {
        alert("Failed to save campaign changes.");
      });
  }, { loadingText: "Saving..." });
}

export function initCampaignListeners() {
  if (campaignExportBtn) {
    campaignExportBtn.addEventListener("click", function () {
      if (!state.currentCampaign || !state.currentCampaign.id) return;
      withLoading(campaignExportBtn, function () {
        return fetch("/api/campaigns/" + encodeURIComponent(state.currentCampaign.id) + "/export", {
          method: "POST",
        })
          .then(function (r) { return r.json(); })
          .then(function (data) {
            if (!data.ok || !data.download_url) {
              alert("Failed to generate campaign export.");
              return;
            }
            campaignExportBtn.textContent = "Exported";
            window.location.href = data.download_url;
            setTimeout(function () {
              if (campaignExportBtn.textContent === "Exported") {
                campaignExportBtn.textContent = "Export";
              }
            }, 1800);
          })
          .catch(function () {
            alert("Failed to generate campaign export.");
          });
      }, { loadingText: "Exporting..." });
    });
  }
  campaignEditBtn.addEventListener("click", openCampaignEdit);
  campaignEditCancel.addEventListener("click", closeCampaignEdit);
  campaignEditForm.addEventListener("submit", saveCampaignEdit);

  // Collapse toggle for campaign details
  var campaignDetailsHeader = document.getElementById("campaign-details-header");
  var campaignDetailsBody = document.getElementById("campaign-details-body");
  var replacementsHeader = document.getElementById("replacements-header");
  var replacementsBody = document.getElementById("replacements-body");

  if (campaignDetailsHeader) {
    campaignDetailsHeader.addEventListener("click", function () {
      campaignDetailsBody.classList.toggle("collapsed");
      campaignDetailsHeader.querySelector(".collapse-arrow").classList.toggle("rotated");
    });
  }
  if (replacementsHeader) {
    replacementsHeader.addEventListener("click", function () {
      replacementsBody.classList.toggle("collapsed");
      replacementsHeader.querySelector(".collapse-arrow").classList.toggle("rotated");
    });
  }

  // Campaign details tab switching
  (function initCampaignDetailsTabs() {
    var tabButtons = document.querySelectorAll(".campaign-details-tabs .summary-tab");
    tabButtons.forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.stopPropagation();
        var tabName = btn.getAttribute("data-detail-tab");
        tabButtons.forEach(function (b) { b.classList.remove("active"); });
        btn.classList.add("active");
        document.querySelectorAll(".detail-tab-content").forEach(function (panel) {
          panel.classList.remove("active");
        });
        var target = document.getElementById(tabName + "-tab");
        if (target) target.classList.add("active");
        import("./relationships/index.js").then(function (rels) {
          rels.setRelationshipGraphVisible(tabName === "graph");
          if (tabName === "graph") {
            rels.renderRelationshipsFromCurrentState();
          }
        });
      });
    });
  })();
}
