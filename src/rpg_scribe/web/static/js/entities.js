/* RPG Scribe - entity management (players, NPCs, locations, entities, word replacements) */

import { state } from "./state.js";
import { escapeHtml, escapeAttr, locationName, locationDescription, entityType, entityDescription, withLoading, withPanelLoading } from "./utils.js";

// DOM elements
var playersList = document.getElementById("players-list");
var playersCount = document.getElementById("players-count");
var npcsList = document.getElementById("npcs-list");
var npcsCount = document.getElementById("npcs-count");
var addNpcBtn = document.getElementById("add-npc-btn");
var addNpcForm = document.getElementById("add-npc-form");
var addNpcCancel = document.getElementById("add-npc-cancel");
var locationsList = document.getElementById("locations-list");
var locationsCount = document.getElementById("locations-count");
var locationsSection = document.getElementById("campaign-details-section");
var addLocationBtn = document.getElementById("add-location-btn");
var addLocationForm = document.getElementById("add-location-form");
var addLocationCancel = document.getElementById("add-location-cancel");
var entitiesList = document.getElementById("entities-list");
var entitiesCount = document.getElementById("entities-count");
var entitiesSection = document.getElementById("campaign-details-section");
var addEntityBtn = document.getElementById("add-entity-btn");
var addEntityForm = document.getElementById("add-entity-form");
var addEntityCancel = document.getElementById("add-entity-cancel");
var replacementsSection = document.getElementById("replacements-section");
var replacementsList = document.getElementById("replacements-list");
var replacementsCount = document.getElementById("replacements-count");
var applyReplacementsBtn = document.getElementById("apply-replacements-btn");

// Callback for refreshing campaign info (set from campaign.js via setCampaignRefresher)
var onRefreshCampaign = function () {};
export function setCampaignRefresher(fn) { onRefreshCampaign = fn; }

export function renderPlayers(players) {
  if (!players || players.length === 0) {
    playersCount.textContent = "(0)";
    playersList.innerHTML = '<p class="placeholder">No players loaded.</p>';
    return;
  }
  playersCount.textContent = "(" + players.length + ")";
  playersList.innerHTML = "";

  players.forEach(function (p) {
    var isMaster = !!(state.currentCampaign && state.currentCampaign.dm_speaker_id && p.discord_id === state.currentCampaign.dm_speaker_id);
    var masterSuffix = isMaster ? " - Master" : "";
    var card = document.createElement("div");
    card.className = "entity-card";
    card.innerHTML =
      '<div class="entity-display">' +
        '<div class="entity-info">' +
          '<strong class="entity-name">' + escapeHtml(p.character_name) + '</strong>' +
          '<span class="entity-meta">' + escapeHtml((p.discord_name || "") + masterSuffix) + '</span>' +
        '</div>' +
        '<span class="entity-desc">' + escapeHtml(p.character_description) + '</span>' +
        '<button class="btn-small btn-edit-entity" title="Edit">Edit</button>' +
      '</div>' +
      '<form class="entity-edit-form hidden">' +
        '<div class="edit-row"><label>Discord</label>' +
          '<input type="text" class="edit-discord-name" value="' + escapeAttr(p.discord_name) + '" /></div>' +
        '<div class="edit-row"><label>Character</label>' +
          '<input type="text" class="edit-char-name" value="' + escapeAttr(p.character_name) + '" required /></div>' +
        '<div class="edit-row"><label>Description</label>' +
          '<textarea class="edit-char-desc" rows="2">' + escapeHtml(p.character_description) + '</textarea></div>' +
        '<div class="edit-actions">' +
          '<button type="submit" class="btn-small btn-save">Save</button>' +
          '<button type="button" class="btn-small btn-cancel entity-edit-cancel">Cancel</button>' +
        '</div>' +
      '</form>';

    // Toggle edit
    var displayEl = card.querySelector(".entity-display");
    var formEl = card.querySelector(".entity-edit-form");
    card.querySelector(".btn-edit-entity").addEventListener("click", function () {
      displayEl.classList.add("hidden");
      formEl.classList.remove("hidden");
    });
    card.querySelector(".entity-edit-cancel").addEventListener("click", function () {
      formEl.classList.add("hidden");
      displayEl.classList.remove("hidden");
    });

    // Save player
    formEl.addEventListener("submit", function (e) {
      e.preventDefault();
      var reqBody = {
        discord_id: p.discord_id,
        discord_name: formEl.querySelector(".edit-discord-name").value.trim(),
        character_name: formEl.querySelector(".edit-char-name").value.trim(),
        character_description: formEl.querySelector(".edit-char-desc").value.trim(),
      };
      var saveBtn = formEl.querySelector(".btn-save");

      if (!state.activeCampaignId) return;

      withLoading(saveBtn, function() {
        return fetch("/api/campaigns/" + state.activeCampaignId + "/players/" + p.id, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(reqBody),
        })
          .then(function (r) { return r.json(); })
          .then(function (data) {
            if (data.ok) {
              onRefreshCampaign();
            } else {
              alert("Error: " + (data.error || "Unknown error"));
            }
          })
          .catch(function () { alert("Failed to save player."); });
      }, { loadingText: "Saving..." });
    });

    playersList.appendChild(card);
  });
}

export function renderNpcs(npcs) {
  if (!npcs || npcs.length === 0) {
    npcsCount.textContent = "(0)";
    npcsList.innerHTML = '<p class="placeholder">No NPCs yet.</p>';
    return;
  }
  npcsCount.textContent = "(" + npcs.length + ")";
  npcsList.innerHTML = "";
  var mergedByParent = (state.currentCampaign && state.currentCampaign.merged_npcs_by_parent) || {};
  var npcParentNames = npcs.map(function (item) { return item.name || ""; }).filter(function (v) { return !!v; });

  npcs.forEach(function (n) {
    var mergedChildren = mergedByParent[n.name] || [];
    var mergeTargetValues = npcs
      .filter(function (candidate) { return candidate && candidate.name && candidate.name !== n.name; })
      .map(function (candidate) { return candidate.name; });
    var card = document.createElement("div");
    card.className = "entity-card";
    card.innerHTML =
      '<div class="entity-display">' +
        '<div class="entity-info">' +
          '<strong class="entity-name">' + escapeHtml(n.name) + '</strong>' +
        '</div>' +
        '<span class="entity-desc">' + escapeHtml(n.description) + '</span>' +
        '<button class="btn-small btn-edit-entity" title="Edit">Edit</button>' +
      '</div>' +
      '<form class="entity-edit-form hidden">' +
        '<div class="edit-row"><label>Name</label>' +
          '<input type="text" class="edit-npc-name" value="' + escapeAttr(n.name) + '" required /></div>' +
        '<div class="edit-row"><label>Description</label>' +
          '<textarea class="edit-npc-desc" rows="2">' + escapeHtml(n.description) + '</textarea></div>' +
        '<div class="edit-row merge-row"><label>Merge into</label>' +
          '<div class="merge-select-tools">' +
            '<input type="text" class="merge-target-search" placeholder="Search target..." />' +
            '<select class="merge-npc-target"></select>' +
          '</div>' +
          '<button type="button" class="btn-small btn-merge-entity" ' + (mergeTargetValues.length ? "" : "disabled") + '>Merge</button>' +
        '</div>' +
        renderMergedChildrenEditor("npcs", mergedChildren, npcParentNames) +
        renderRelatedRelationshipsEditor("npcs", n.name, mergedChildren, state.currentCampaign || {}) +
        '<div class="edit-actions">' +
          '<button type="submit" class="btn-small btn-save">Save</button>' +
          '<button type="button" class="btn-small btn-cancel entity-edit-cancel">Cancel</button>' +
        '</div>' +
      '</form>';

    var displayEl = card.querySelector(".entity-display");
    var formEl = card.querySelector(".entity-edit-form");
    card.querySelector(".btn-edit-entity").addEventListener("click", function () {
      displayEl.classList.add("hidden");
      formEl.classList.remove("hidden");
    });
    card.querySelector(".entity-edit-cancel").addEventListener("click", function () {
      formEl.classList.add("hidden");
      displayEl.classList.remove("hidden");
    });

    // Save NPC
    formEl.addEventListener("submit", function (e) {
      e.preventDefault();
      var reqBody = {
        old_name: n.name,
        name: formEl.querySelector(".edit-npc-name").value.trim(),
        description: formEl.querySelector(".edit-npc-desc").value.trim(),
      };
      var saveBtn = formEl.querySelector(".btn-save");

      if (!state.activeCampaignId) return;

      withLoading(saveBtn, function() {
        return fetch("/api/campaigns/" + state.activeCampaignId + "/npcs/" + n.id, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(reqBody),
        })
          .then(function (r) { return r.json(); })
          .then(function (data) {
            if (data.ok) { onRefreshCampaign(); }
            else { alert("Error: " + (data.error || "Unknown error")); }
          })
          .catch(function () { alert("Failed to save NPC."); });
      }, { loadingText: "Saving..." });
    });

    var mergeNpcBtn = formEl.querySelector(".btn-merge-entity");
    var mergeNpcTarget = formEl.querySelector(".merge-npc-target");
    var mergeNpcSearch = formEl.querySelector(".merge-target-search");
    if (mergeNpcTarget) {
      setMergeTargetOptions(mergeNpcTarget, mergeTargetValues);
    }
    if (mergeNpcSearch && mergeNpcTarget) {
      mergeNpcSearch.addEventListener("input", function () {
        filterMergeTargetOptions(mergeNpcTarget, mergeNpcSearch.value);
      });
    }
    if (mergeNpcBtn && mergeNpcTarget) {
      mergeNpcBtn.addEventListener("click", function () {
        if (!state.activeCampaignId) return;
        var targetName = (mergeNpcTarget.value || "").trim();
        if (!targetName) {
          alert("Select a merge target first.");
          return;
        }
        withLoading(mergeNpcBtn, function() {
          return fetch("/api/campaigns/" + state.activeCampaignId + "/npcs/merge", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              source_name: n.name,
              target_name: targetName,
            }),
          })
            .then(function (r) { return r.json(); })
            .then(function (data) {
              if (data.ok) onRefreshCampaign();
              else alert("Error: " + (data.error || "Unknown error"));
            })
            .catch(function () { alert("Failed to merge NPC."); });
        }, { loadingText: "Merging..." });
      });
    }

    var mergedNpcButtons = formEl.querySelectorAll(".btn-save-merged-child");
    mergedNpcButtons.forEach(function (btn) {
      btn.addEventListener("click", function () {
        if (!state.activeCampaignId) return;
        var row = btn.closest(".merged-child-item");
        if (!row) return;
        var mergedId = row.getAttribute("data-merged-id") || "";
        var nameInput = row.querySelector(".merged-child-name");
        var descInput = row.querySelector(".merged-child-desc");
        var parentSelect = row.querySelector(".merged-child-parent");
        var reqBody = {
          name: ((nameInput || {}).value || "").trim(),
          description: ((descInput || {}).value || "").trim(),
          merged_into: ((parentSelect || {}).value || "").trim(),
        };
        if (!mergedId || !reqBody.name) {
          alert("Alias name is required.");
          return;
        }
        withLoading(btn, function() {
          return fetch("/api/campaigns/" + state.activeCampaignId + "/npcs/merged/" + encodeURIComponent(mergedId), {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(reqBody),
          })
            .then(function (r) { return r.json(); })
            .then(function (data) {
              if (data.ok) onRefreshCampaign();
              else alert("Error: " + (data.error || "Unknown error"));
            })
            .catch(function () { alert("Failed to update merged alias."); });
        }, { loadingText: "Saving..." });
      });
    });

    npcsList.appendChild(card);
  });
}

export function renderLocations(locations) {
  if (!locationsSection) return;

  var items = (locations || []).map(function (loc) {
    return {
      name: locationName(loc),
      description: locationDescription(loc),
    };
  }).filter(function (loc) { return !!loc.name; });

  locationsCount.textContent = "(" + items.length + ")";
  var mergedByParent = (state.currentCampaign && state.currentCampaign.merged_locations_by_parent) || {};
  var locationParentNames = items.map(function (item) { return item.name || ""; }).filter(function (v) { return !!v; });

  if (!items.length) {
    locationsList.innerHTML = '<p class="placeholder">No locations yet.</p>';
    return;
  }

  locationsList.innerHTML = "";
  items.forEach(function (loc) {
    var name = loc.name;
    var description = loc.description;
    var mergedChildren = mergedByParent[name] || [];
    var mergeTargetValues = items
      .filter(function (candidate) { return candidate && candidate.name && candidate.name !== name; })
      .map(function (candidate) { return candidate.name; });
    var card = document.createElement("div");
    card.className = "entity-card";
    card.innerHTML =
      '<div class="entity-display">' +
        '<div class="entity-info">' +
          '<strong class="entity-name">' + escapeHtml(name) + '</strong>' +
        '</div>' +
        '<span class="entity-desc">' + escapeHtml(description || "") + '</span>' +
        '<button class="btn-small btn-edit-entity" title="Edit">Edit</button>' +
      '</div>' +
      '<form class="entity-edit-form hidden">' +
        '<div class="edit-row"><label>Name</label>' +
          '<input type="text" class="edit-location-name" value="' + escapeAttr(name) + '" required /></div>' +
        '<div class="edit-row"><label>Description</label>' +
          '<textarea class="edit-location-desc" rows="2">' + escapeHtml(description || "") + '</textarea></div>' +
        '<div class="edit-row merge-row"><label>Merge into</label>' +
          '<div class="merge-select-tools">' +
            '<input type="text" class="merge-target-search" placeholder="Search target..." />' +
            '<select class="merge-location-target"></select>' +
          '</div>' +
          '<button type="button" class="btn-small btn-merge-entity" ' + (mergeTargetValues.length ? "" : "disabled") + '>Merge</button>' +
        '</div>' +
        renderMergedChildrenEditor("locations", mergedChildren, locationParentNames) +
        renderRelatedRelationshipsEditor("locations", name, mergedChildren, state.currentCampaign || {}) +
        '<div class="edit-actions">' +
          '<button type="submit" class="btn-small btn-save">Save</button>' +
          '<button type="button" class="btn-small btn-cancel entity-edit-cancel">Cancel</button>' +
        '</div>' +
      '</form>';

    var displayEl = card.querySelector(".entity-display");
    var formEl = card.querySelector(".entity-edit-form");
    card.querySelector(".btn-edit-entity").addEventListener("click", function () {
      displayEl.classList.add("hidden");
      formEl.classList.remove("hidden");
    });
    card.querySelector(".entity-edit-cancel").addEventListener("click", function () {
      formEl.classList.add("hidden");
      displayEl.classList.remove("hidden");
    });

    formEl.addEventListener("submit", function (e) {
      e.preventDefault();
      if (!state.activeCampaignId) return;

      var reqBody = {
        old_name: name,
        name: formEl.querySelector(".edit-location-name").value.trim(),
        description: ((formEl.querySelector(".edit-location-desc") || {}).value || "").trim(),
      };
      if (!reqBody.name) return;
      var saveBtn = formEl.querySelector(".btn-save");

      withLoading(saveBtn, function() {
        return fetch("/api/campaigns/" + state.activeCampaignId + "/locations", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(reqBody),
        })
          .then(function (r) { return r.json(); })
          .then(function (data) {
            if (data.ok) { onRefreshCampaign(); }
            else { alert("Error: " + (data.error || "Unknown error")); }
          })
          .catch(function () { alert("Failed to save location."); });
      }, { loadingText: "Saving..." });
    });

    var mergeLocBtn = formEl.querySelector(".btn-merge-entity");
    var mergeLocTarget = formEl.querySelector(".merge-location-target");
    var mergeLocSearch = formEl.querySelector(".merge-target-search");
    if (mergeLocTarget) {
      setMergeTargetOptions(mergeLocTarget, mergeTargetValues);
    }
    if (mergeLocSearch && mergeLocTarget) {
      mergeLocSearch.addEventListener("input", function () {
        filterMergeTargetOptions(mergeLocTarget, mergeLocSearch.value);
      });
    }
    if (mergeLocBtn && mergeLocTarget) {
      mergeLocBtn.addEventListener("click", function () {
        if (!state.activeCampaignId) return;
        var targetName = (mergeLocTarget.value || "").trim();
        if (!targetName) {
          alert("Select a merge target first.");
          return;
        }
        withLoading(mergeLocBtn, function() {
          return fetch("/api/campaigns/" + state.activeCampaignId + "/locations/merge", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              source_name: name,
              target_name: targetName,
            }),
          })
            .then(function (r) { return r.json(); })
            .then(function (data) {
              if (data.ok) onRefreshCampaign();
              else alert("Error: " + (data.error || "Unknown error"));
            })
            .catch(function () { alert("Failed to merge location."); });
        }, { loadingText: "Merging..." });
      });
    }

    var mergedLocButtons = formEl.querySelectorAll(".btn-save-merged-child");
    mergedLocButtons.forEach(function (btn) {
      btn.addEventListener("click", function () {
        if (!state.activeCampaignId) return;
        var row = btn.closest(".merged-child-item");
        if (!row) return;
        var mergedId = row.getAttribute("data-merged-id") || "";
        var nameInput = row.querySelector(".merged-child-name");
        var descInput = row.querySelector(".merged-child-desc");
        var parentSelect = row.querySelector(".merged-child-parent");
        var reqBody = {
          name: ((nameInput || {}).value || "").trim(),
          description: ((descInput || {}).value || "").trim(),
          merged_into: ((parentSelect || {}).value || "").trim(),
        };
        if (!mergedId || !reqBody.name) {
          alert("Alias name is required.");
          return;
        }
        withLoading(btn, function () {
          return fetch("/api/campaigns/" + state.activeCampaignId + "/locations/merged/" + encodeURIComponent(mergedId), {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(reqBody),
          })
            .then(function (r) { return r.json(); })
            .then(function (data) {
              if (data.ok) onRefreshCampaign();
              else alert("Error: " + (data.error || "Unknown error"));
            })
            .catch(function () { alert("Failed to update merged alias."); });
        }, { loadingText: "Saving..." });
      });
    });

    locationsList.appendChild(card);
  });
}

export function renderEntities(entities) {
  if (!entitiesSection) return;

  var items = (entities || []).filter(function (ent) {
    return !!(ent && ent.name);
  });

  entitiesCount.textContent = "(" + items.length + ")";
  var mergedByParent = (state.currentCampaign && state.currentCampaign.merged_entities_by_parent) || {};
  var entityParentNames = items.map(function (item) { return item.name || ""; }).filter(function (v) { return !!v; });

  if (!items.length) {
    entitiesList.innerHTML = '<p class="placeholder">No entities yet.</p>';
    return;
  }

  entitiesList.innerHTML = "";
  items.forEach(function (ent) {
    var mergedChildren = mergedByParent[ent.name] || [];
    var mergeTargetValues = items
      .filter(function (candidate) { return candidate && candidate.name && candidate.name !== ent.name; })
      .map(function (candidate) { return candidate.name; });
    var card = document.createElement("div");
    card.className = "entity-card";
    card.innerHTML =
      '<div class="entity-display">' +
        '<div class="entity-info">' +
          '<strong class="entity-name">' + escapeHtml(ent.name) + '</strong>' +
          '<span class="entity-meta">' + escapeHtml(entityType(ent)) + '</span>' +
        '</div>' +
        '<span class="entity-desc">' + escapeHtml(entityDescription(ent)) + '</span>' +
        '<button class="btn-small btn-edit-entity" title="Edit">Edit</button>' +
      '</div>' +
      '<form class="entity-edit-form hidden">' +
        '<div class="edit-row"><label>Name</label>' +
          '<input type="text" class="edit-entity-name" value="' + escapeAttr(ent.name) + '" required /></div>' +
        '<div class="edit-row"><label>Type</label>' +
          '<input type="text" class="edit-entity-type" value="' + escapeAttr(entityType(ent)) + '" /></div>' +
        '<div class="edit-row"><label>Description</label>' +
          '<textarea class="edit-entity-desc" rows="2">' + escapeHtml(entityDescription(ent)) + '</textarea></div>' +
        '<div class="edit-row merge-row"><label>Merge into</label>' +
          '<div class="merge-select-tools">' +
            '<input type="text" class="merge-target-search" placeholder="Search target..." />' +
            '<select class="merge-entity-target"></select>' +
          '</div>' +
          '<button type="button" class="btn-small btn-merge-entity" ' + (mergeTargetValues.length ? "" : "disabled") + '>Merge</button>' +
        '</div>' +
        renderMergedChildrenEditor("entities", mergedChildren, entityParentNames) +
        renderRelatedRelationshipsEditor("entities", ent.name, mergedChildren, state.currentCampaign || {}) +
        '<div class="edit-actions">' +
          '<button type="submit" class="btn-small btn-save">Save</button>' +
          '<button type="button" class="btn-small btn-cancel">Cancel</button>' +
        '</div>' +
      '</form>';

    var editBtn = card.querySelector(".btn-edit-entity");
    var form = card.querySelector(".entity-edit-form");
    var cancelBtn = card.querySelector(".btn-cancel");

    if (editBtn && form) {
      editBtn.addEventListener("click", function () {
        form.classList.remove("hidden");
        editBtn.classList.add("hidden");
        var input = form.querySelector(".edit-entity-name");
        if (input) input.focus();
      });
    }

    if (cancelBtn && form && editBtn) {
      cancelBtn.addEventListener("click", function () {
        form.classList.add("hidden");
        editBtn.classList.remove("hidden");
      });
    }

    if (form) {
      form.addEventListener("submit", function (e) {
        e.preventDefault();
        if (!state.activeCampaignId) return;

        var reqBody = {
          old_name: ent.name || "",
          name: ((form.querySelector(".edit-entity-name") || {}).value || "").trim(),
          entity_type: ((form.querySelector(".edit-entity-type") || {}).value || "").trim(),
          description: ((form.querySelector(".edit-entity-desc") || {}).value || "").trim(),
        };
        if (!reqBody.name) return;
        if (!reqBody.entity_type) reqBody.entity_type = "group";

        var saveBtn = form.querySelector(".btn-save");
        withLoading(saveBtn, function () {
          return fetch("/api/campaigns/" + state.activeCampaignId + "/entities/" + ent.id, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(reqBody),
          })
            .then(function (r) { return r.json(); })
            .then(function (data) {
              if (data.ok) { onRefreshCampaign(); }
              else { alert("Error: " + (data.error || "Unknown error")); }
            })
            .catch(function () { alert("Failed to update entity."); });
        }, { loadingText: "Saving..." });
      });
    }

    var mergeEntBtn = form.querySelector(".btn-merge-entity");
    var mergeEntTarget = form.querySelector(".merge-entity-target");
    var mergeEntSearch = form.querySelector(".merge-target-search");
    if (mergeEntTarget) {
      setMergeTargetOptions(mergeEntTarget, mergeTargetValues);
    }
    if (mergeEntSearch && mergeEntTarget) {
      mergeEntSearch.addEventListener("input", function () {
        filterMergeTargetOptions(mergeEntTarget, mergeEntSearch.value);
      });
    }
    if (mergeEntBtn && mergeEntTarget) {
      mergeEntBtn.addEventListener("click", function () {
        if (!state.activeCampaignId) return;
        var targetName = (mergeEntTarget.value || "").trim();
        if (!targetName) {
          alert("Select a merge target first.");
          return;
        }
        withLoading(mergeEntBtn, function () {
          return fetch("/api/campaigns/" + state.activeCampaignId + "/entities/merge", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              source_name: ent.name,
              target_name: targetName,
            }),
          })
            .then(function (r) { return r.json(); })
            .then(function (data) {
              if (data.ok) onRefreshCampaign();
              else alert("Error: " + (data.error || "Unknown error"));
            })
            .catch(function () { alert("Failed to merge entity."); });
        }, { loadingText: "Merging..." });
      });
    }

    var mergedEntButtons = form.querySelectorAll(".btn-save-merged-child");
    mergedEntButtons.forEach(function (btn) {
      btn.addEventListener("click", function () {
        if (!state.activeCampaignId) return;
        var row = btn.closest(".merged-child-item");
        if (!row) return;
        var mergedId = row.getAttribute("data-merged-id") || "";
        var nameInput = row.querySelector(".merged-child-name");
        var typeInput = row.querySelector(".merged-child-type");
        var descInput = row.querySelector(".merged-child-desc");
        var parentSelect = row.querySelector(".merged-child-parent");
        var reqBody = {
          name: ((nameInput || {}).value || "").trim(),
          entity_type: ((typeInput || {}).value || "").trim() || "group",
          description: ((descInput || {}).value || "").trim(),
          merged_into: ((parentSelect || {}).value || "").trim(),
        };
        if (!mergedId || !reqBody.name) {
          alert("Alias name is required.");
          return;
        }
        withLoading(btn, function () {
          return fetch("/api/campaigns/" + state.activeCampaignId + "/entities/merged/" + encodeURIComponent(mergedId), {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(reqBody),
          })
            .then(function (r) { return r.json(); })
            .then(function (data) {
              if (data.ok) onRefreshCampaign();
              else alert("Error: " + (data.error || "Unknown error"));
            })
            .catch(function () { alert("Failed to update merged alias."); });
        }, { loadingText: "Saving..." });
      });
    });

    entitiesList.appendChild(card);
  });
}

export function fetchWordReplacements(campaignId) {
  withPanelLoading(replacementsSection, function () {
    return fetch("/api/campaigns/" + encodeURIComponent(campaignId) + "/word-replacements")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var rules = data.replacements || [];
        if (replacementsCount) replacementsCount.textContent = "(" + rules.length + ")";
        replacementsList.innerHTML = "";
        if (rules.length === 0) {
          replacementsList.innerHTML = '<p class="placeholder">No replacement rules.</p>';
          return;
        }
        rules.forEach(function (rule) {
          var row = document.createElement("div");
          row.className = "replacement-row";
          row.innerHTML =
            '<span class="replacement-original">' + escapeHtml(rule.original_word) + "</span>" +
            '<span class="replacement-arrow">\u2192</span>' +
            '<span class="replacement-new">' + escapeHtml(rule.replacement_word) + "</span>" +
            '<button class="replacement-delete" title="Eliminar">\u2717</button>';
          row.querySelector(".replacement-delete").addEventListener("click", function (e) {
            var btn = e.target;
            withLoading(btn, function () {
              return fetch("/api/campaigns/" + encodeURIComponent(campaignId) + "/word-replacements/" + rule.id, {
                method: "DELETE",
              }).then(function () { fetchWordReplacements(campaignId); });
            }, { loadingText: "×" });
          });
          replacementsList.appendChild(row);
        });
      });
  });
}

export function initEntityFormListeners() {
  if (applyReplacementsBtn) {
    applyReplacementsBtn.addEventListener("click", function () {
      if (!state.activeCampaignId) return;

      withLoading(applyReplacementsBtn, function () {
        return fetch("/api/campaigns/" + encodeURIComponent(state.activeCampaignId) + "/word-replacements/apply", {
          method: "POST",
        })
          .then(function (r) { return r.json(); })
          .then(function (data) {
            alert("Modified " + (data.modified_count || 0) + " transcription(s).");
          })
          .catch(function () { alert("Error applying replacements."); });
      }, { loadingText: "Applying\u2026" });
    });
  }

  // Add Location form
  if (addLocationBtn) {
    addLocationBtn.addEventListener("click", function () {
      addLocationBtn.classList.add("hidden");
      addLocationForm.classList.remove("hidden");
      var input = document.getElementById("new-location-name");
      if (input) input.focus();
    });
  }
  if (addLocationCancel) {
    addLocationCancel.addEventListener("click", function () {
      addLocationForm.classList.add("hidden");
      addLocationBtn.classList.remove("hidden");
    });
  }
  if (addLocationForm) {
    addLocationForm.addEventListener("submit", function (e) {
      e.preventDefault();
      if (!state.activeCampaignId) return;

      var nameInput = document.getElementById("new-location-name");
      var descInput = document.getElementById("new-location-desc");
      var reqBody = {
        name: nameInput ? nameInput.value.trim() : "",
        description: descInput ? descInput.value.trim() : "",
      };
      if (!reqBody.name) return;

      var saveBtn = addLocationForm.querySelector(".btn-save");
      withLoading(saveBtn, function () {
        return fetch("/api/campaigns/" + state.activeCampaignId + "/locations", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(reqBody),
        })
          .then(function (r) { return r.json(); })
          .then(function (data) {
            if (data.ok) {
              if (nameInput) nameInput.value = "";
              if (descInput) descInput.value = "";
              addLocationForm.classList.add("hidden");
              addLocationBtn.classList.remove("hidden");
              onRefreshCampaign();
            } else {
              alert("Error: " + (data.error || "Unknown error"));
            }
          })
          .catch(function () { alert("Failed to add location."); });
      }, { loadingText: "Saving..." });
    });
  }

  // Add Entity form
  if (addEntityBtn) {
    addEntityBtn.addEventListener("click", function () {
      addEntityBtn.classList.add("hidden");
      addEntityForm.classList.remove("hidden");
      var input = document.getElementById("new-entity-name");
      if (input) input.focus();
    });
  }
  if (addEntityCancel) {
    addEntityCancel.addEventListener("click", function () {
      addEntityForm.classList.add("hidden");
      addEntityBtn.classList.remove("hidden");
    });
  }
  if (addEntityForm) {
    addEntityForm.addEventListener("submit", function (e) {
      e.preventDefault();
      if (!state.activeCampaignId) return;

      var nameInput = document.getElementById("new-entity-name");
      var typeInput = document.getElementById("new-entity-type");
      var descInput = document.getElementById("new-entity-desc");
      var reqBody = {
        name: nameInput ? nameInput.value.trim() : "",
        entity_type: typeInput ? typeInput.value.trim() : "group",
        description: descInput ? descInput.value.trim() : "",
      };
      if (!reqBody.name) return;
      if (!reqBody.entity_type) reqBody.entity_type = "group";

      var saveBtn = addEntityForm.querySelector(".btn-save");
      withLoading(saveBtn, function () {
        return fetch("/api/campaigns/" + state.activeCampaignId + "/entities", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(reqBody),
        })
          .then(function (r) { return r.json(); })
          .then(function (data) {
            if (data.ok) {
              if (nameInput) nameInput.value = "";
              if (typeInput) typeInput.value = "group";
              if (descInput) descInput.value = "";
              addEntityForm.classList.add("hidden");
              addEntityBtn.classList.remove("hidden");
              onRefreshCampaign();
            } else {
              alert("Error: " + (data.error || "Unknown error"));
            }
          })
          .catch(function () { alert("Failed to add entity."); });
      }, { loadingText: "Saving..." });
    });
  }

  // Add NPC form
  addNpcBtn.addEventListener("click", function () {
    addNpcBtn.classList.add("hidden");
    addNpcForm.classList.remove("hidden");
    document.getElementById("new-npc-name").focus();
  });
  addNpcCancel.addEventListener("click", function () {
    addNpcForm.classList.add("hidden");
    addNpcBtn.classList.remove("hidden");
  });
  addNpcForm.addEventListener("submit", function (e) {
    e.preventDefault();
    var reqBody = {
      name: document.getElementById("new-npc-name").value.trim(),
      description: document.getElementById("new-npc-desc").value.trim(),
    };
    if (!reqBody.name) return;
    var saveBtn = addNpcForm.querySelector(".btn-save");
    if (!state.activeCampaignId) return;
    withLoading(saveBtn, function () {
      return fetch("/api/campaigns/" + state.activeCampaignId + "/npcs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(reqBody),
      })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data.ok) {
            document.getElementById("new-npc-name").value = "";
            document.getElementById("new-npc-desc").value = "";
            addNpcForm.classList.add("hidden");
            addNpcBtn.classList.remove("hidden");
            onRefreshCampaign();
          } else {
            alert("Error: " + (data.error || "Unknown error"));
          }
        })
        .catch(function () { alert("Failed to add NPC."); });
    }, { loadingText: "Saving..." });
  });
}

// ── Helper functions ────────────────────────────────────────

function mergedParentOptionsHtml(parentNames, currentParent, currentChildName) {
  var options = '<option value="">Unmerge (show separately)</option>';
  (parentNames || []).forEach(function (parentName) {
    if (!parentName || parentName === currentChildName) return;
    options += '<option value="' + escapeAttr(parentName) + '"' +
      (parentName === (currentParent || "") ? " selected" : "") +
      ">" + escapeHtml(parentName) + "</option>";
  });
  return options;
}

function renderMergedChildrenEditor(kind, mergedChildren, parentNames) {
  var children = mergedChildren || [];
  if (!children.length) {
    return (
      '<div class="merged-children merged-children-empty">' +
      "No merged aliases." +
      "</div>"
    );
  }
  var rows = children.map(function (child) {
    var childName = String(child.name || "");
    var childDesc = String(child.description || "");
    var childParent = String(child.merged_into || "");
    var childType = String(child.entity_type || "group");
    return (
      '<div class="merged-child-item" data-merged-kind="' + escapeAttr(kind) + '" data-merged-id="' + escapeAttr(String(child.id || "")) + '">' +
        '<div class="merged-child-grid">' +
          '<input type="text" class="merged-child-name" value="' + escapeAttr(childName) + '" placeholder="Alias name" />' +
          (kind === "entities"
            ? ('<input type="text" class="merged-child-type" value="' + escapeAttr(childType) + '" placeholder="Type" />')
            : "") +
          '<select class="merged-child-parent">' +
            mergedParentOptionsHtml(parentNames || [], childParent, childName) +
          "</select>" +
          '<button type="button" class="btn-small btn-save-merged-child">Save Alias</button>' +
        "</div>" +
        '<textarea class="merged-child-desc" rows="2" placeholder="Alias description...">' + escapeHtml(childDesc) + "</textarea>" +
      "</div>"
    );
  }).join("");

  return (
    '<div class="merged-children">' +
      '<div class="merged-children-title">Merged aliases</div>' +
      rows +
    "</div>"
  );
}

function entityRelationshipKeyVariants(kind, name) {
  var rawName = String(name || "").trim();
  if (!rawName) return [];
  if (kind === "npcs") return [normalizeEntityKey("npc:" + rawName)];
  if (kind === "locations") {
    return [
      normalizeEntityKey("loc:" + rawName),
      normalizeEntityKey("location:" + rawName),
    ];
  }
  if (kind === "entities") {
    return [
      normalizeEntityKey("ent:" + rawName),
      normalizeEntityKey("entity:" + rawName),
    ];
  }
  return [];
}

export function normalizeEntityKey(key) {
  var raw = (key || "").trim();
  if (!raw) return "";
  if (raw.indexOf("location:") === 0) return "loc:" + raw.slice("location:".length);
  if (raw.indexOf("entity:") === 0) return "ent:" + raw.slice("entity:".length);
  return raw;
}

export function entityTypeFromKey(key) {
  key = normalizeEntityKey(key);
  if (!key) return "unknown";
  if (key.indexOf("player:") === 0) return "player";
  if (key.indexOf("npc:") === 0) return "npc";
  if (key.indexOf("loc:") === 0 || key.indexOf("location:") === 0) return "location";
  if (key.indexOf("ent:") === 0 || key.indexOf("entity:") === 0) return "entity";
  return "unknown";
}

export function buildRelationshipEntities(campaign) {
  var allEntities = [];
  var players = campaign.players || [];
  var npcs = campaign.npcs || [];
  var locations = campaign.locations || [];
  var campaignEntities = campaign.entities || [];

  players.forEach(function (p) {
    allEntities.push({
      key: "player:" + (p.discord_id || ""),
      label: "Player: " + (p.character_name || p.discord_name || p.discord_id || "?"),
      kind: "player",
      description: p.character_description || "",
      entityType: "player",
    });
  });

  npcs.forEach(function (n) {
    allEntities.push({
      key: "npc:" + (n.name || ""),
      label: "NPC: " + (n.name || "?"),
      kind: "npc",
      description: n.description || "",
      entityType: "npc",
    });
  });

  locations.forEach(function (loc) {
    var name = locationName(loc);
    if (!name) return;
    allEntities.push({
      key: "loc:" + name,
      label: "Location: " + name,
      kind: "location",
      description: locationDescription(loc),
      entityType: "location",
    });
  });

  campaignEntities.forEach(function (ent) {
    if (!ent || !ent.name) return;
    allEntities.push({
      key: "ent:" + ent.name,
      label: "Entity (" + entityType(ent) + "): " + ent.name,
      kind: "entity",
      description: entityDescription(ent),
      entityType: entityType(ent),
    });
  });

  return allEntities.filter(function (e) { return !!e.key && !e.key.endsWith(":"); });
}

export function entityDetailsFromKey(campaign, key) {
  var normalized = normalizeEntityKey(key);
  var entities = buildRelationshipEntities(campaign);
  for (var i = 0; i < entities.length; i++) {
    if (normalizeEntityKey(entities[i].key) === normalized) return entities[i];
  }
  var kind = entityTypeFromKey(normalized);
  return { key: normalized, label: normalized, kind: kind, description: "" };
}

export function entityLabelFromKey(campaign, key) {
  return entityDetailsFromKey(campaign, key).label;
}

function renderRelatedRelationshipsEditor(kind, parentName, mergedChildren, campaign) {
  var keySet = {};
  entityRelationshipKeyVariants(kind, parentName).forEach(function (k) { keySet[k] = true; });
  (mergedChildren || []).forEach(function (child) {
    entityRelationshipKeyVariants(kind, child && child.name).forEach(function (k) { keySet[k] = true; });
  });

  var keys = Object.keys(keySet);
  if (!keys.length) {
    return (
      '<div class="related-relationships related-relationships-empty">' +
      "No relationships for this entity." +
      "</div>"
    );
  }

  var rows = [];
  ((campaign && campaign.relationships) || []).forEach(function (rel) {
    var sourceKey = normalizeEntityKey(rel.source_key || "");
    var targetKey = normalizeEntityKey(rel.target_key || "");
    var matchSource = !!keySet[sourceKey];
    var matchTarget = !!keySet[targetKey];
    if (!matchSource && !matchTarget) return;

    var otherKey = matchSource ? targetKey : sourceKey;
    var relationLabel = relationTypeLabel(rel);
    var otherLabel = entityLabelFromKey(campaign || {}, otherKey || "");
    var direction = matchSource ? "->" : "<-";
    var notes = String(rel.notes || "").trim();
    rows.push(
      '<div class="related-rel-item">' +
        '<span class="related-rel-main">' + escapeHtml(relationLabel) + " " + direction + " " + escapeHtml(otherLabel) + "</span>" +
        (notes ? ('<span class="related-rel-notes">' + escapeHtml(notes) + "</span>") : "") +
      "</div>"
    );
  });

  if (!rows.length) {
    return (
      '<div class="related-relationships related-relationships-empty">' +
      "No relationships for this entity." +
      "</div>"
    );
  }

  return (
    '<div class="related-relationships">' +
      '<div class="merged-children-title">Related relationships</div>' +
      rows.join("") +
    "</div>"
  );
}

function relationTypeLabel(rel) {
  return rel.type_label || rel.relation_type_label || rel.type_key || rel.relation_type_key || "unknown";
}

function setMergeTargetOptions(selectEl, values) {
  if (!selectEl) return;
  selectEl.__allMergeValues = (values || []).slice();
  filterMergeTargetOptions(selectEl, "");
}

function filterMergeTargetOptions(selectEl, query) {
  if (!selectEl) return;
  var previous = selectEl.value || "";
  var allValues = selectEl.__allMergeValues || [];
  var q = (query || "").trim().toLowerCase();
  var filtered = !q
    ? allValues
    : allValues.filter(function (value) {
        return String(value).toLowerCase().indexOf(q) >= 0;
      });

  selectEl.innerHTML = "";
  var firstOpt = document.createElement("option");
  firstOpt.value = "";
  firstOpt.textContent = filtered.length ? "Select target..." : "No matches";
  selectEl.appendChild(firstOpt);
  filtered.forEach(function (value) {
    var opt = document.createElement("option");
    opt.value = value;
    opt.textContent = value;
    selectEl.appendChild(opt);
  });

  if (previous && filtered.indexOf(previous) >= 0) selectEl.value = previous;
  else selectEl.value = "";
}
