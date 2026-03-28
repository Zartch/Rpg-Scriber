/* RPG Scribe - relationship management */

import { state } from "../state.js";
import { escapeHtml, escapeAttr, locationName, withLoading } from "../utils.js";
import { normalizeEntityKey, entityDetailsFromKey, entityLabelFromKey, entityTypeFromKey, buildRelationshipEntities } from "../entities.js";

// DOM elements
var relationshipsList = document.getElementById("relationships-list");
var relationshipsCount = document.getElementById("relationships-count");
var relationshipsSection = document.getElementById("campaign-details-section");
var relationshipFilterQuery = document.getElementById("relationship-filter-query");
var relationshipFilterEntity = document.getElementById("relationship-filter-entity");
var relationshipFilterType = document.getElementById("relationship-filter-type");
var relationshipFilterCategory = document.getElementById("relationship-filter-category");
var relationshipFilterSourceKind = document.getElementById("relationship-filter-source-kind");
var relationshipFilterTargetKind = document.getElementById("relationship-filter-target-kind");
var relationshipFilterClearBtn = document.getElementById("relationship-filter-clear");
var addRelationshipBtn = document.getElementById("add-relationship-btn");
var addRelationshipForm = document.getElementById("add-relationship-form");
var addRelationshipCancel = document.getElementById("add-relationship-cancel");
var relSourceSelect = document.getElementById("new-rel-source");
var relTargetSelect = document.getElementById("new-rel-target");
var relSourceSearch = document.getElementById("new-rel-source-search");
var relTargetSearch = document.getElementById("new-rel-target-search");
var relSourceKind = document.getElementById("new-rel-source-kind");
var relTargetKind = document.getElementById("new-rel-target-kind");
var relTypeInput = document.getElementById("new-rel-type");
var relCategoryInput = document.getElementById("new-rel-category");
var relNotesInput = document.getElementById("new-rel-notes");
var relationshipEditParentsPanel = document.getElementById("relationship-edit-parents");
var relationshipGraphPanel = document.getElementById("relationship-graph-panel");
var relationshipGraphCanvas = document.getElementById("relationship-graph-canvas");
var relationshipGraphEmpty = document.getElementById("relationship-graph-empty");
var relationshipLegend = document.getElementById("relationship-legend");
var graphFilterPlayers = document.getElementById("graph-filter-players");
var graphFilterNpcs = document.getElementById("graph-filter-npcs");
var graphFilterLocations = document.getElementById("graph-filter-locations");
var graphFilterEntities = document.getElementById("graph-filter-entities");
var relationshipNodeTooltip = document.getElementById("relationship-node-tooltip");
var relationshipGraphSearch = document.getElementById("relationship-graph-search");
var relationshipGraphCommunity = document.getElementById("relationship-graph-community");
var relationshipGraphNeighborhood = document.getElementById("relationship-graph-neighborhood");
var relationshipGraphMetric = document.getElementById("relationship-graph-metric");
var relationshipGraphIsolateComponent = document.getElementById("relationship-graph-isolate-component");
var relationshipGraphStats = document.getElementById("relationship-graph-stats");
var relationshipGraphDetails = document.getElementById("relationship-graph-details");
var relationshipGraphPathSource = document.getElementById("relationship-graph-path-source");
var relationshipGraphPathTarget = document.getElementById("relationship-graph-path-target");
var relationshipGraphPathOutput = document.getElementById("relationship-graph-path-output");
var relationshipGraphTop = document.getElementById("relationship-graph-top");

// Callback for refreshing campaign info
var onRefreshCampaign = function () {};
export function setCampaignRefresher(fn) { onRefreshCampaign = fn; }

export function renderRelationships(relationships, campaign) {
  if (!relationshipsSection) return;
  relationshipsSection.classList.remove("hidden");

  var items = relationships || [];
  state.lastRelationshipAllItems = items.slice();
  state.lastRelationshipCampaign = campaign || {};

  populateRelationshipSelects(campaign || {});
  populateRelationshipListFilterOptions(items, campaign || {});
  renderRelationshipsFromCurrentState();
}

export function renderRelationshipsFromCurrentState() {
  var campaign = state.lastRelationshipCampaign || {};
  var filteredItems = filterRelationshipsForList(state.lastRelationshipAllItems, campaign);
  state.lastRelationshipItems = filteredItems.slice();

  if (relationshipsCount) {
    relationshipsCount.textContent = state.lastRelationshipAllItems.length === filteredItems.length
      ? "(" + state.lastRelationshipAllItems.length + ")"
      : "(" + filteredItems.length + " / " + state.lastRelationshipAllItems.length + ")";
  }

  renderRelationshipGraph(filteredItems, campaign);
  renderRelationshipCards(filteredItems, campaign);
}

export function setRelationshipGraphVisible(visible) {
  state.relationshipGraphVisible = !!visible;
  if (!relationshipGraphPanel) return;
  if (ensureRelationshipGraph3d()) {
    state.relationshipGraph3d.setVisible(state.relationshipGraphVisible);
    if (state.relationshipGraphVisible) state.relationshipGraph3d.resize();
  }
}

export function initRelationshipListeners() {
  if (graphFilterPlayers) graphFilterPlayers.addEventListener("change", onGraphFiltersChanged);
  if (graphFilterNpcs) graphFilterNpcs.addEventListener("change", onGraphFiltersChanged);
  if (graphFilterLocations) graphFilterLocations.addEventListener("change", onGraphFiltersChanged);
  if (graphFilterEntities) graphFilterEntities.addEventListener("change", onGraphFiltersChanged);
  if (relationshipFilterQuery) relationshipFilterQuery.addEventListener("input", renderRelationshipsFromCurrentState);
  if (relationshipFilterEntity) relationshipFilterEntity.addEventListener("change", renderRelationshipsFromCurrentState);
  if (relationshipFilterType) relationshipFilterType.addEventListener("change", renderRelationshipsFromCurrentState);
  if (relationshipFilterCategory) relationshipFilterCategory.addEventListener("change", renderRelationshipsFromCurrentState);
  if (relationshipFilterSourceKind) relationshipFilterSourceKind.addEventListener("change", renderRelationshipsFromCurrentState);
  if (relationshipFilterTargetKind) relationshipFilterTargetKind.addEventListener("change", renderRelationshipsFromCurrentState);
  if (relationshipFilterClearBtn) {
    relationshipFilterClearBtn.addEventListener("click", function () {
      if (relationshipFilterQuery) relationshipFilterQuery.value = "";
      if (relationshipFilterEntity) relationshipFilterEntity.value = "";
      if (relationshipFilterType) relationshipFilterType.value = "";
      if (relationshipFilterCategory) relationshipFilterCategory.value = "";
      if (relationshipFilterSourceKind) relationshipFilterSourceKind.value = "all";
      if (relationshipFilterTargetKind) relationshipFilterTargetKind.value = "all";
      renderRelationshipsFromCurrentState();
    });
  }
  if (relSourceSearch) {
    relSourceSearch.addEventListener("input", function () {
      applyRelationshipEntityFilters(relSourceSelect, relSourceSearch, relSourceKind);
    });
  }
  if (relTargetSearch) {
    relTargetSearch.addEventListener("input", function () {
      applyRelationshipEntityFilters(relTargetSelect, relTargetSearch, relTargetKind);
    });
  }
  if (relSourceKind) {
    relSourceKind.addEventListener("change", function () {
      applyRelationshipEntityFilters(relSourceSelect, relSourceSearch, relSourceKind);
    });
  }
  if (relTargetKind) {
    relTargetKind.addEventListener("change", function () {
      applyRelationshipEntityFilters(relTargetSelect, relTargetSearch, relTargetKind);
    });
  }

  // Add Relationship form
  if (addRelationshipBtn) {
    addRelationshipBtn.addEventListener("click", function () {
      state.relationshipEditOriginal = null;
      addRelationshipBtn.classList.add("hidden");
      addRelationshipForm.classList.remove("hidden");
      if (relationshipEditParentsPanel) {
        relationshipEditParentsPanel.classList.add("hidden");
        relationshipEditParentsPanel.innerHTML = "";
      }
      if (relTypeInput) relTypeInput.focus();
    });
  }
  if (addRelationshipCancel) {
    addRelationshipCancel.addEventListener("click", function () {
      addRelationshipForm.classList.add("hidden");
      addRelationshipBtn.classList.remove("hidden");
      state.relationshipEditOriginal = null;
      if (relationshipEditParentsPanel) {
        relationshipEditParentsPanel.classList.add("hidden");
        relationshipEditParentsPanel.innerHTML = "";
      }
      if (relSourceSearch) relSourceSearch.value = "";
      if (relTargetSearch) relTargetSearch.value = "";
      if (relSourceKind) relSourceKind.value = "all";
      if (relTargetKind) relTargetKind.value = "all";
      applyRelationshipEntityFilters(relSourceSelect, relSourceSearch, relSourceKind);
      applyRelationshipEntityFilters(relTargetSelect, relTargetSearch, relTargetKind);
    });
  }
  if (addRelationshipForm) {
    addRelationshipForm.addEventListener("submit", function (e) {
      e.preventDefault();
      if (!state.activeCampaignId) return;

      var reqBody = {
        source_key: (relSourceSelect && relSourceSelect.value) || "",
        target_key: (relTargetSelect && relTargetSelect.value) || "",
        relation_type: (relTypeInput && relTypeInput.value.trim()) || "",
        category: (relCategoryInput && relCategoryInput.value.trim()) || "general",
        notes: (relNotesInput && relNotesInput.value.trim()) || "",
      };

      if (!reqBody.source_key || !reqBody.target_key || !reqBody.relation_type) return;

      var saveBtn = addRelationshipForm.querySelector(".btn-save");
      var isEditing = !!state.relationshipEditOriginal;
      var url = "/api/campaigns/" + state.activeCampaignId + "/relationships";
      if (isEditing) {
        reqBody.old_source_key = state.relationshipEditOriginal.source_key;
        reqBody.old_target_key = state.relationshipEditOriginal.target_key;
        reqBody.old_type_key = state.relationshipEditOriginal.type_key;
      }

      if (!state.activeCampaignId) return;
      withLoading(saveBtn, function () {
        return fetch(url, {
          method: isEditing ? "PUT" : "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(reqBody),
        })
          .then(function (r) { return r.json(); })
          .then(function (data) {
            if (data.ok) {
              if (relTypeInput) relTypeInput.value = "";
              if (relNotesInput) relNotesInput.value = "";
              if (relCategoryInput) relCategoryInput.value = "general";
              addRelationshipForm.classList.add("hidden");
              addRelationshipBtn.classList.remove("hidden");
              state.relationshipEditOriginal = null;
              if (relationshipEditParentsPanel) {
                relationshipEditParentsPanel.classList.add("hidden");
                relationshipEditParentsPanel.innerHTML = "";
              }
              onRefreshCampaign();
            } else {
              alert("Error: " + (data.error || "Unknown error"));
            }
          })
          .catch(function () { alert("Failed to save relationship."); });
      }, { loadingText: "Saving..." });
    });
  }

  onGraphFiltersChanged();
  setRelationshipGraphVisible(false);
}

// ── Relationship cards ────────────────────────────────────

function renderRelationshipCards(items, campaign) {
  if (!items.length) {
    relationshipsList.innerHTML = state.lastRelationshipAllItems.length
      ? '<p class="placeholder">No relationships match the current filters.</p>'
      : '<p class="placeholder">No relationships yet.</p>';
    return;
  }

  relationshipsList.innerHTML = "";
  var relationshipTypes = ((campaign || {}).relationship_types || []).filter(function (row) {
    return !!(row && row.canonical_key);
  });
  items.forEach(function (rel) {
    var source = entityLabelFromKey(campaign, rel.source_key || "");
    var target = entityLabelFromKey(campaign, rel.target_key || "");
    var typeLabel = rel.type_label || rel.relation_type_label || rel.type_key || rel.relation_type_key || "(unknown)";
    var category = relationCategory(rel);
    var typeKey = rel.type_key || rel.relation_type_key || "";
    var mergeTypeOptions = relationshipTypes
      .filter(function (candidate) {
        return candidate.canonical_key && candidate.canonical_key !== typeKey;
      })
      .map(function (candidate) {
        var label = candidate.label || candidate.canonical_key;
        return '<option value="' + escapeAttr(candidate.canonical_key) + '">' +
          escapeHtml(label + " [" + (candidate.category || "general") + "]") +
          "</option>";
      })
      .join("");
    var card = document.createElement("div");
    card.className = "entity-card";
    card.innerHTML =
      '<div class="entity-display">' +
        '<div class="entity-info">' +
          '<strong class="entity-name">' + escapeHtml(source) + ' -> ' + escapeHtml(target) + '</strong>' +
          '<span class="entity-meta">' + escapeHtml(typeLabel) + ' [' + escapeHtml(category) + ']</span>' +
        '</div>' +
        '<span class="entity-desc">' + escapeHtml(rel.notes || "") + '</span>' +
        '<div class="entity-actions">' +
          '<button class="btn-small btn-edit-entity" title="Edit">Edit</button>' +
          '<button class="btn-small btn-merge-reltype" title="Merge relationship type" ' +
            ((typeKey && mergeTypeOptions) ? "" : "disabled") +
          '>Merge Type</button>' +
        '</div>' +
      '</div>' +
      '<form class="entity-edit-form hidden merge-reltype-form">' +
        '<div class="edit-row merge-row"><label>Type parent</label>' +
          '<select class="merge-reltype-target">' +
            (mergeTypeOptions ? ('<option value="">Select target...</option>' + mergeTypeOptions) : '<option value="">No compatible target</option>') +
          '</select>' +
          '<button type="button" class="btn-small btn-confirm-reltype-merge" ' +
            ((typeKey && mergeTypeOptions) ? "" : "disabled") +
          '>Merge</button>' +
          '<button type="button" class="btn-small btn-cancel-reltype-merge">Cancel</button>' +
        '</div>' +
      '</form>';
    var editBtn = card.querySelector(".btn-edit-entity");
    if (editBtn) {
      editBtn.addEventListener("click", function () {
        state.relationshipEditOriginal = {
          source_key: rel.source_key || "",
          target_key: rel.target_key || "",
          type_key: rel.type_key || rel.relation_type_key || "",
        };
        if (relSourceSearch) relSourceSearch.value = "";
        if (relTargetSearch) relTargetSearch.value = "";
        if (relSourceKind) relSourceKind.value = "all";
        if (relTargetKind) relTargetKind.value = "all";
        applyRelationshipEntityFilters(relSourceSelect, relSourceSearch, relSourceKind);
        applyRelationshipEntityFilters(relTargetSelect, relTargetSearch, relTargetKind);
        if (relSourceSelect) relSourceSelect.value = normalizeEntityKey(rel.source_key || "");
        if (relTargetSelect) relTargetSelect.value = normalizeEntityKey(rel.target_key || "");
        if (relTypeInput) relTypeInput.value = typeLabel;
        if (relCategoryInput) relCategoryInput.value = category;
        if (relNotesInput) relNotesInput.value = rel.notes || "";
        if (addRelationshipBtn) addRelationshipBtn.classList.add("hidden");
        if (addRelationshipForm) addRelationshipForm.classList.remove("hidden");
        if (relationshipEditParentsPanel) {
          relationshipEditParentsPanel.innerHTML = renderRelationshipEditParents(rel, campaign || {});
          relationshipEditParentsPanel.classList.remove("hidden");
          bindGlobalMergedAliasEditor(relationshipEditParentsPanel);
        }
        if (relTypeInput) relTypeInput.focus();
      });
    }
    var mergeTypeBtn = card.querySelector(".btn-merge-reltype");
    var mergeTypeForm = card.querySelector(".merge-reltype-form");
    var mergeTypeCancelBtn = card.querySelector(".btn-cancel-reltype-merge");
    var mergeTypeConfirmBtn = card.querySelector(".btn-confirm-reltype-merge");
    var mergeTypeTarget = card.querySelector(".merge-reltype-target");
    if (mergeTypeBtn && mergeTypeForm) {
      mergeTypeBtn.addEventListener("click", function () {
        if (!typeKey) return;
        mergeTypeForm.classList.remove("hidden");
      });
    }
    if (mergeTypeCancelBtn && mergeTypeForm) {
      mergeTypeCancelBtn.addEventListener("click", function () {
        mergeTypeForm.classList.add("hidden");
      });
    }
    if (mergeTypeConfirmBtn && mergeTypeTarget) {
      mergeTypeConfirmBtn.addEventListener("click", function () {
        if (state.appMode !== "live" || !state.activeCampaignId || !typeKey) return;
        var targetTypeKey = (mergeTypeTarget.value || "").trim();
        if (!targetTypeKey) {
          alert("Select a merge target first.");
          return;
        }
        withLoading(mergeTypeConfirmBtn, function () {
          return fetch("/api/campaigns/" + state.activeCampaignId + "/relationship-types/merge", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              source_type_key: typeKey,
              target_type_key: targetTypeKey,
            }),
          })
            .then(function (r) { return r.json(); })
            .then(function (data) {
              if (data.ok) onRefreshCampaign();
              else alert("Error: " + (data.error || "Unknown error"));
            })
            .catch(function () { alert("Failed to merge relationship type."); });
        }, { loadingText: "Merging..." });
      });
    }
    relationshipsList.appendChild(card);
  });
}

// ── Graph ────────────────────────────────────────────────

function ensureRelationshipGraph3d() {
  if (state.relationshipGraph3d || !relationshipGraphCanvas || !window.RelationshipGraph3D) return state.relationshipGraph3d;
  state.relationshipGraph3d = window.RelationshipGraph3D.create({
    root: relationshipGraphPanel,
    canvas: relationshipGraphCanvas,
    emptyState: relationshipGraphEmpty,
    tooltip: relationshipNodeTooltip,
    legend: relationshipLegend,
    searchInput: relationshipGraphSearch,
    communitySelect: relationshipGraphCommunity,
    neighborhoodSelect: relationshipGraphNeighborhood,
    metricSelect: relationshipGraphMetric,
    isolateCheckbox: relationshipGraphIsolateComponent,
    stats: relationshipGraphStats,
    details: relationshipGraphDetails,
    pathSourceSelect: relationshipGraphPathSource,
    pathTargetSelect: relationshipGraphPathTarget,
    pathOutput: relationshipGraphPathOutput,
    topList: relationshipGraphTop,
  });
  return state.relationshipGraph3d;
}

function renderRelationshipGraph(relationships, campaign) {
  if (!relationshipGraphPanel) return;
  var renderer = ensureRelationshipGraph3d();
  if (!renderer) return;
  renderer.setVisible(state.relationshipGraphVisible);
  renderer.render(buildRelationshipGraphData(relationships, campaign));
}

function buildRelationshipGraphData(relationships, campaign) {
  var items = relationships || [];
  var entityMap = {};
  var visibleEntities = buildRelationshipEntities(campaign || {}).filter(function (entity) {
    return graphGroupIncluded(entity.kind);
  });

  if (hasActiveRelationshipListFilters()) {
    var visibleKeys = {};
    items.forEach(function (rel) {
      var sourceKey = normalizeEntityKey(rel.source_key || "");
      var targetKey = normalizeEntityKey(rel.target_key || "");
      if (sourceKey) visibleKeys[sourceKey] = true;
      if (targetKey) visibleKeys[targetKey] = true;
    });
    visibleEntities = visibleEntities.filter(function (entity) {
      return !!visibleKeys[normalizeEntityKey(entity.key)];
    });
  }

  visibleEntities.forEach(function (entity) {
    entityMap[normalizeEntityKey(entity.key)] = entity;
  });

  var filteredItems = items.filter(function (rel) {
    var source = entityDetailsFromKey(campaign || {}, rel.source_key || "");
    var target = entityDetailsFromKey(campaign || {}, rel.target_key || "");
    return graphGroupIncluded(source.kind) && graphGroupIncluded(target.kind);
  });

  var nodeKeys = visibleEntities
    .map(function (entity) { return normalizeEntityKey(entity.key); })
    .filter(function (key, idx, arr) { return !!key && arr.indexOf(key) === idx; });

  filteredItems.forEach(function (rel) {
    var sourceKey = normalizeEntityKey(rel.source_key || "");
    var targetKey = normalizeEntityKey(rel.target_key || "");
    if (sourceKey && nodeKeys.indexOf(sourceKey) < 0) nodeKeys.push(sourceKey);
    if (targetKey && nodeKeys.indexOf(targetKey) < 0) nodeKeys.push(targetKey);
  });

  var nodes = nodeKeys.map(function (key) {
    var details = entityMap[key] || entityDetailsFromKey(campaign || {}, key);
    var rawLabel = (details.label || details.key || key)
      .replace("Player: ", "")
      .replace("NPC: ", "")
      .replace("Location: ", "")
      .replace(/^Entity \([^)]+\): /, "");
    return {
      id: key,
      label: rawLabel,
      shortLabel: rawLabel.length > 18 ? rawLabel.slice(0, 16) + ".." : rawLabel,
      kind: details.kind || "unknown",
      description: details.description || "",
      entityType: details.entityType || details.kind || "unknown",
    };
  });

  var links = filteredItems.map(function (rel, idx) {
    return {
      id: [
        normalizeEntityKey(rel.source_key || ""),
        normalizeEntityKey(rel.target_key || ""),
        relationTypeKey(rel),
        idx,
      ].join("|"),
      source: normalizeEntityKey(rel.source_key || ""),
      target: normalizeEntityKey(rel.target_key || ""),
      typeKey: relationTypeKey(rel),
      typeLabel: relationTypeLabel(rel),
      category: relationCategory(rel),
    };
  }).filter(function (link) {
    return !!(link.source && link.target);
  });

  return { nodes: nodes, links: links };
}

function onGraphFiltersChanged() {
  state.relationshipGraphFilters.players = !graphFilterPlayers || !!graphFilterPlayers.checked;
  state.relationshipGraphFilters.npcs = !graphFilterNpcs || !!graphFilterNpcs.checked;
  state.relationshipGraphFilters.locations = !graphFilterLocations || !!graphFilterLocations.checked;
  state.relationshipGraphFilters.entities = !graphFilterEntities || !!graphFilterEntities.checked;
  renderRelationshipGraph(state.lastRelationshipItems, state.lastRelationshipCampaign || {});
}

function graphGroupIncluded(kind) {
  if (kind === "player") return !!state.relationshipGraphFilters.players;
  if (kind === "npc") return !!state.relationshipGraphFilters.npcs;
  if (kind === "location") return !!state.relationshipGraphFilters.locations;
  if (kind === "entity") return !!state.relationshipGraphFilters.entities;
  return true;
}

// ── Relationship type key helpers ────────────────────────

function relationTypeKey(rel) {
  return rel.type_key || rel.relation_type_key || rel.type_label || rel.relation_type_label || "unknown";
}

function relationTypeLabel(rel) {
  return rel.type_label || rel.relation_type_label || rel.type_key || rel.relation_type_key || "unknown";
}

function relationCategory(rel) {
  return rel.type_category || rel.relation_type_category || rel.category || "general";
}

// ── Relationship filter helpers ───────────────────────────

function hasActiveRelationshipListFilters() {
  return !!(
    (relationshipFilterQuery && (relationshipFilterQuery.value || "").trim()) ||
    (relationshipFilterEntity && relationshipFilterEntity.value) ||
    (relationshipFilterType && relationshipFilterType.value) ||
    (relationshipFilterCategory && relationshipFilterCategory.value) ||
    (relationshipFilterSourceKind && relationshipFilterSourceKind.value !== "all") ||
    (relationshipFilterTargetKind && relationshipFilterTargetKind.value !== "all")
  );
}

function filterRelationshipsForList(relationships, campaign) {
  var query = relationshipFilterQuery ? (relationshipFilterQuery.value || "").trim().toLowerCase() : "";
  var entity = relationshipFilterEntity ? normalizeEntityKey(relationshipFilterEntity.value || "") : "";
  var typeValue = relationshipFilterType ? (relationshipFilterType.value || "") : "";
  var categoryValue = relationshipFilterCategory ? (relationshipFilterCategory.value || "").toLowerCase() : "";
  var sourceKind = relationshipFilterSourceKind ? (relationshipFilterSourceKind.value || "all") : "all";
  var targetKind = relationshipFilterTargetKind ? (relationshipFilterTargetKind.value || "all") : "all";

  return (relationships || []).filter(function (rel) {
    var sourceKey = normalizeEntityKey(rel.source_key || "");
    var targetKey = normalizeEntityKey(rel.target_key || "");
    var sourceDetails = entityDetailsFromKey(campaign || {}, sourceKey);
    var targetDetails = entityDetailsFromKey(campaign || {}, targetKey);
    var relTypeValue = relationTypeKey(rel);
    var relTypeLabel = relationTypeLabel(rel);
    var relCategory = String(relationCategory(rel)).toLowerCase();

    if (entity && sourceKey !== entity && targetKey !== entity) return false;
    if (typeValue && relTypeValue !== typeValue) return false;
    if (categoryValue && relCategory !== categoryValue) return false;
    if (sourceKind !== "all" && sourceDetails.kind !== sourceKind) return false;
    if (targetKind !== "all" && targetDetails.kind !== targetKind) return false;

    if (!query) return true;

    var haystack = [
      sourceDetails.label || sourceKey,
      targetDetails.label || targetKey,
      relTypeLabel,
      relationCategory(rel),
      rel.notes || "",
    ].join(" ").toLowerCase();

    return haystack.indexOf(query) >= 0;
  });
}

function populateRelationshipListFilterOptions(relationships, campaign) {
  var items = relationships || [];
  var entityMap = {};
  var typeMap = {};
  var categoryMap = {};
  var relationshipTypes = ((campaign || {}).relationship_types || []).filter(function (row) {
    return !!(row && row.canonical_key);
  });

  relationshipTypes.forEach(function (row) {
    var typeValue = row.canonical_key;
    var typeCategory = row.category || "general";
    typeMap[typeValue] = {
      value: typeValue,
      label: (row.label || row.canonical_key) + " [" + typeCategory + "]",
    };
    categoryMap[String(typeCategory).toLowerCase()] = {
      value: String(typeCategory).toLowerCase(),
      label: typeCategory,
    };
  });

  items.forEach(function (rel) {
    [rel.source_key, rel.target_key].forEach(function (key) {
      var normalized = normalizeEntityKey(key || "");
      if (!normalized || entityMap[normalized]) return;
      var details = entityDetailsFromKey(campaign || {}, normalized);
      entityMap[normalized] = {
        value: normalized,
        label: details.label || normalized,
      };
    });

    var typeValue = relationTypeKey(rel);
    var typeLabel = relationTypeLabel(rel);
    var typeCategory = relationCategory(rel);
    if (typeValue && !typeMap[typeValue]) {
      typeMap[typeValue] = {
        value: typeValue,
        label: typeLabel + " [" + typeCategory + "]",
      };
    }
    categoryMap[String(typeCategory).toLowerCase()] = {
      value: String(typeCategory).toLowerCase(),
      label: typeCategory,
    };
  });

  var entityOptions = Object.keys(entityMap)
    .map(function (key) { return entityMap[key]; })
    .sort(function (a, b) { return a.label.localeCompare(b.label); });
  var typeOptions = Object.keys(typeMap)
    .map(function (key) { return typeMap[key]; })
    .sort(function (a, b) { return a.label.localeCompare(b.label); });
  var categoryOptions = Object.keys(categoryMap)
    .map(function (key) { return categoryMap[key]; })
    .sort(function (a, b) { return a.label.localeCompare(b.label); });

  setSelectOptions(
    relationshipFilterEntity,
    "All entities",
    entityOptions,
    relationshipFilterEntity ? relationshipFilterEntity.value : ""
  );
  setSelectOptions(
    relationshipFilterType,
    "All types",
    typeOptions,
    relationshipFilterType ? relationshipFilterType.value : ""
  );
  setSelectOptions(
    relationshipFilterCategory,
    "All categories",
    categoryOptions,
    relationshipFilterCategory ? relationshipFilterCategory.value : ""
  );
}

function setSelectOptions(selectEl, placeholder, options, selectedValue) {
  if (!selectEl) return;
  selectEl.innerHTML = "";

  var placeholderOpt = document.createElement("option");
  placeholderOpt.value = "";
  placeholderOpt.textContent = placeholder;
  selectEl.appendChild(placeholderOpt);

  (options || []).forEach(function (option) {
    if (!option || !option.value) return;
    var opt = document.createElement("option");
    opt.value = option.value;
    opt.textContent = option.label || option.value;
    selectEl.appendChild(opt);
  });

  selectEl.value = selectedValue && selectEl.querySelector('option[value="' + cssEscapeValue(selectedValue) + '"]')
    ? selectedValue
    : "";
}

function populateRelationshipSelects(campaign) {
  if (!relSourceSelect || !relTargetSelect) return;
  var entities = buildRelationshipEntities(campaign);
  setRelationshipEntityOptions(relSourceSelect, entities);
  setRelationshipEntityOptions(relTargetSelect, entities);
  applyRelationshipEntityFilters(relSourceSelect, relSourceSearch, relSourceKind);
  applyRelationshipEntityFilters(relTargetSelect, relTargetSearch, relTargetKind);

  relSourceSelect.disabled = entities.length < 2;
  relTargetSelect.disabled = entities.length < 2;
  if (relSourceSearch) relSourceSearch.disabled = entities.length < 2;
  if (relTargetSearch) relTargetSearch.disabled = entities.length < 2;
  if (relSourceKind) relSourceKind.disabled = entities.length < 2;
  if (relTargetKind) relTargetKind.disabled = entities.length < 2;
}

function setRelationshipEntityOptions(selectEl, entities) {
  if (!selectEl) return;
  var previous = selectEl.value;
  selectEl.__allEntityOptions = (entities || []).map(function (e) {
    return { value: e.key, label: e.label, kind: e.kind || "unknown" };
  });

  selectEl.innerHTML = "";
  selectEl.__allEntityOptions.forEach(function (item) {
    var opt = document.createElement("option");
    opt.value = item.value;
    opt.textContent = item.label;
    selectEl.appendChild(opt);
  });

  if (previous && selectEl.querySelector('option[value="' + cssEscapeValue(previous) + '"]')) {
    selectEl.value = previous;
  }
}

function filterRelationshipEntityOptions(selectEl, query, kindFilter) {
  if (!selectEl) return;
  var allItems = selectEl.__allEntityOptions || [];
  var previous = selectEl.value;
  var q = (query || "").trim().toLowerCase();
  var kind = (kindFilter || "all").trim().toLowerCase();
  var filtered = !q ? allItems : allItems.filter(function (item) {
    return item.label.toLowerCase().indexOf(q) >= 0 || item.value.toLowerCase().indexOf(q) >= 0;
  });
  if (kind && kind !== "all") {
    filtered = filtered.filter(function (item) {
      return (item.kind || "").toLowerCase() === kind;
    });
  }

  selectEl.innerHTML = "";
  filtered.forEach(function (item) {
    var opt = document.createElement("option");
    opt.value = item.value;
    opt.textContent = item.label;
    selectEl.appendChild(opt);
  });

  if (!filtered.length) {
    var emptyOpt = document.createElement("option");
    emptyOpt.value = "";
    emptyOpt.textContent = "No matches";
    selectEl.appendChild(emptyOpt);
    selectEl.value = "";
    return;
  }

  if (previous && filtered.some(function (item) { return item.value === previous; })) {
    selectEl.value = previous;
  } else {
    selectEl.selectedIndex = 0;
  }
}

function applyRelationshipEntityFilters(selectEl, searchEl, kindEl) {
  var query = searchEl ? searchEl.value : "";
  var kind = kindEl ? kindEl.value : "all";
  filterRelationshipEntityOptions(selectEl, query, kind);
}

function cssEscapeValue(value) {
  if (window.CSS && typeof window.CSS.escape === "function") {
    return window.CSS.escape(value);
  }
  return String(value).replace(/["\\]/g, "\\$&");
}

// ── Merged alias editor (global) ──────────────────────────

function bindGlobalMergedAliasEditor(container) {
  if (!container) return;
  var buttons = container.querySelectorAll(".btn-save-merged-child-global");
  buttons.forEach(function (btn) {
    if (btn.dataset.boundMergedEditor === "1") return;
    btn.dataset.boundMergedEditor = "1";
    btn.addEventListener("click", function () {
      if (!state.activeCampaignId) return;
      var row = btn.closest(".merged-child-item");
      if (!row) return;
      var kind = row.getAttribute("data-merged-kind") || "";
      var id = row.getAttribute("data-merged-id") || "";
      var nameInput = row.querySelector(".merged-child-name");
      var descInput = row.querySelector(".merged-child-desc");
      var parentSelect = row.querySelector(".merged-child-parent");
      var typeInput = row.querySelector(".merged-child-type");
      var body = {
        name: ((nameInput || {}).value || "").trim(),
        description: ((descInput || {}).value || "").trim(),
        merged_into: ((parentSelect || {}).value || "").trim(),
      };
      if (kind === "entities") body.entity_type = ((typeInput || {}).value || "").trim() || "group";
      if (!id || !body.name || !kind) {
        alert("Alias name is required.");
        return;
      }

      var endpoint = "";
      if (kind === "npcs") endpoint = "/api/campaigns/" + state.activeCampaignId + "/npcs/merged/" + encodeURIComponent(id);
      else if (kind === "locations") endpoint = "/api/campaigns/" + state.activeCampaignId + "/locations/merged/" + encodeURIComponent(id);
      else if (kind === "entities") endpoint = "/api/campaigns/" + state.activeCampaignId + "/entities/merged/" + encodeURIComponent(id);
      if (!endpoint) return;

      withLoading(btn, function () {
        return fetch(endpoint, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
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
}

// ── Relationship edit parents panel helpers ───────────────

function renderRelationshipEditParents(rel, campaign) {
  var relObj = rel || {};
  var descriptors = [];
  var sourceDesc = relationshipParentFromKey(relObj.source_key || "");
  var targetDesc = relationshipParentFromKey(relObj.target_key || "");
  if (sourceDesc) descriptors.push(sourceDesc);
  if (targetDesc && (!sourceDesc || sourceDesc.kind !== targetDesc.kind || sourceDesc.name !== targetDesc.name)) {
    descriptors.push(targetDesc);
  }

  if (!descriptors.length) {
    return '<div class="related-relationships-empty">No parent aliases for this relationship.</div>';
  }

  var npcParents = ((campaign || {}).npcs || []).map(function (n) { return n.name || ""; }).filter(function (v) { return !!v; });
  var locationParents = ((campaign || {}).locations || []).map(function (l) { return locationName(l); }).filter(function (v) { return !!v; });
  var entityParents = ((campaign || {}).entities || []).map(function (e) { return e.name || ""; }).filter(function (v) { return !!v; });

  var sections = descriptors.map(function (desc) {
    var kindLabel = desc.kind === "npc" ? "NPC" : (desc.kind === "location" ? "Location" : "Entity");
    var kindPlural = desc.kind === "npc" ? "npcs" : (desc.kind === "location" ? "locations" : "entities");
    var parentNames = desc.kind === "npc" ? npcParents : (desc.kind === "location" ? locationParents : entityParents);
    var aliases = mergedAliasesByParent(desc.kind, desc.name, campaign);
    if (!aliases.length) {
      return (
        '<div class="merged-children merged-children-empty">' +
        escapeHtml(kindLabel + " parent: " + desc.name + " (no aliases merged)") +
        "</div>"
      );
    }
    var parentMap = {};
    parentMap[desc.name] = aliases;
    return renderMergedChildrenGlobalSection(
      kindPlural,
      kindLabel + " parent: " + desc.name,
      parentMap,
      parentNames
    );
  }).join("");

  return (
    '<div class="merged-children-title">Entities merged into relationship parents</div>' +
    sections
  );
}

function mergedAliasesByParent(kind, parentName, campaign) {
  if (!parentName) return [];
  if (kind === "npc") return (((campaign || {}).merged_npcs_by_parent || {})[parentName] || []);
  if (kind === "location") return (((campaign || {}).merged_locations_by_parent || {})[parentName] || []);
  if (kind === "entity") return (((campaign || {}).merged_entities_by_parent || {})[parentName] || []);
  return [];
}

function relationshipParentFromKey(key) {
  var normalized = normalizeEntityKey(key || "");
  if (!normalized) return null;
  if (normalized.indexOf("npc:") === 0) {
    return { kind: "npc", name: normalized.slice("npc:".length) };
  }
  if (normalized.indexOf("loc:") === 0) {
    return { kind: "location", name: normalized.slice("loc:".length) };
  }
  if (normalized.indexOf("ent:") === 0) {
    return { kind: "entity", name: normalized.slice("ent:".length) };
  }
  return null;
}

function renderMergedChildrenGlobalSection(kind, title, mergedByParent, parentNames) {
  var keys = Object.keys(mergedByParent || {});
  var items = [];
  keys.forEach(function (parent) {
    var children = mergedByParent[parent] || [];
    children.forEach(function (child) {
      items.push({
        id: child.id || "",
        name: child.name || "",
        description: child.description || "",
        entity_type: child.entity_type || "group",
        merged_into: child.merged_into || parent || "",
      });
    });
  });
  if (!items.length) {
    return (
      '<div class="merged-children merged-children-empty">' +
      escapeHtml(title + ": no merged aliases.") +
      "</div>"
    );
  }

  var rows = items.map(function (child) {
    return (
      '<div class="merged-child-item" data-merged-kind="' + escapeAttr(kind) + '" data-merged-id="' + escapeAttr(String(child.id || "")) + '">' +
        '<div class="merged-child-grid">' +
          '<input type="text" class="merged-child-name" value="' + escapeAttr(String(child.name || "")) + '" placeholder="Alias name" />' +
          (kind === "entities"
            ? ('<input type="text" class="merged-child-type" value="' + escapeAttr(String(child.entity_type || "group")) + '" placeholder="Type" />')
            : "") +
          '<select class="merged-child-parent">' +
            mergedParentOptionsHtml(parentNames || [], String(child.merged_into || ""), String(child.name || "")) +
          "</select>" +
          '<button type="button" class="btn-small btn-save-merged-child-global">Save Alias</button>' +
        "</div>" +
        '<textarea class="merged-child-desc" rows="2" placeholder="Alias description...">' + escapeHtml(String(child.description || "")) + "</textarea>" +
      "</div>"
    );
  }).join("");

  return (
    '<div class="merged-children">' +
      '<div class="merged-children-title">' + escapeHtml(title) + "</div>" +
      rows +
    "</div>"
  );
}

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
