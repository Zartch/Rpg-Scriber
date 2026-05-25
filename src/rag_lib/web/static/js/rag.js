// rag.js — ES module for /rag page (A3: hybrid search + detail panel)
const API = "/api/rag";

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let activeManualId = null;       // selected manual for navigation mode
let currentOffset = 0;
const LIMIT = 50;
let openChunkId = null;          // chunk open in right panel
let checkedManualIds = new Set(); // checked manuals for search filter (empty = all)
let searchQuery = "";             // current query ("" = no search)
let searchDebounce = null;        // debounce timer
let ftsResults = [];              // latest FTS results
let semResults = [];              // latest semantic results
let searchInFlight = false;       // true while either search fetch is pending

// Upload state (A4)
let uploadFile = null;           // File object selected/dropped
let uploadJobId = null;          // active job id being polled
let uploadPollTimer = null;      // setInterval id for polling

// Edit state (A4)
let editOriginalChunk = null;   // snapshot of chunk before editing

// ---------------------------------------------------------------------------
// DOM refs (cached after DOMContentLoaded)
// ---------------------------------------------------------------------------
const $ = id => document.getElementById(id);

// ---------------------------------------------------------------------------
// Derived state
// ---------------------------------------------------------------------------
const isSearchMode = () => searchQuery.trim() !== "";
const isDetailOpen = () => openChunkId !== null;
const isState4 = () => isSearchMode() && isDetailOpen();

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------
async function fetchJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

function buildSearchParams(extra = {}) {
  const params = new URLSearchParams(extra);
  if (checkedManualIds.size > 0) {
    params.set("manual_ids", [...checkedManualIds].join(","));
  }
  return params;
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// ---------------------------------------------------------------------------
// Render helpers
// ---------------------------------------------------------------------------
function makeResultItem(r, badgeClass, badgeLabel) {
  const div = document.createElement("div");
  div.className = "result-item" + (r.chunk_id === openChunkId ? " active" : "");
  div.dataset.chunkId = r.chunk_id;
  const meta = `#${r.chunk_id} · ${r.chunk.page ? `p.${r.chunk.page}` : ""} · <span class="badge ${badgeClass}">${badgeLabel}</span>`;
  const preview = escapeHtml((r.chunk.text || "").replace(/\n/g, " ").slice(0, 90));
  const score = `<span class="result-score">${r.score.toFixed(2)}</span>`;
  div.innerHTML = `
    <div class="result-meta">${meta}${score}</div>
    <div class="result-preview">${preview}</div>
  `;
  div.addEventListener("click", () => openDetail(r.chunk_id));
  return div;
}

function renderFtsResults(results) {
  const container = $("fts-results");
  container.innerHTML = "";
  if (!results.length) {
    container.innerHTML = '<div class="loading">Sin resultados</div>';
    return;
  }
  results.forEach(r => container.appendChild(makeResultItem(r, "badge-fts", "FTS")));
}

function renderSemResults(results) {
  const container = $("sem-results");
  container.innerHTML = "";
  if (!results.length) {
    container.innerHTML = '<div class="loading">Sin resultados</div>';
    return;
  }
  results.forEach(r => container.appendChild(makeResultItem(r, "badge-sem", "SEM")));
}

function renderMergedResults() {
  const container = $("merged-list");
  container.innerHTML = "";
  // Merge: FTS first, then SEM; deduplicate by chunk_id (FTS wins)
  const seen = new Set();
  const merged = [];
  for (const r of ftsResults) {
    if (!seen.has(r.chunk_id)) { seen.add(r.chunk_id); merged.push({ r, badge: "badge-fts", label: "FTS" }); }
  }
  for (const r of semResults) {
    if (!seen.has(r.chunk_id)) { seen.add(r.chunk_id); merged.push({ r, badge: "badge-sem", label: "SEM" }); }
  }
  if (!merged.length) {
    container.innerHTML = '<div class="loading">Sin resultados</div>';
    return;
  }
  merged.forEach(({ r, badge, label }) => container.appendChild(makeResultItem(r, badge, label)));
}

// ---------------------------------------------------------------------------
// Panel visibility
// ---------------------------------------------------------------------------
function applyLayout() {
  if (isSearchMode()) {
    $("chunks-area").hidden = true;
    $("search-results").hidden = false;
    if (isState4()) {
      $("search-columns").hidden = true;
      $("merged-results").hidden = false;
      renderMergedResults();
    } else {
      $("search-columns").hidden = false;
      $("merged-results").hidden = true;
    }
  } else {
    $("chunks-area").hidden = false;
    $("search-results").hidden = true;
  }
  $("detail-panel").hidden = !isDetailOpen();
}

// ---------------------------------------------------------------------------
// Manuals panel
// ---------------------------------------------------------------------------
async function loadManuals() {
  const list = $("manuals-list");
  list.innerHTML = '<li class="loading">Cargando…</li>';
  const manuals = await fetchJSON(`${API}/manuals`);
  list.innerHTML = "";
  if (!manuals.length) {
    list.innerHTML = '<li class="loading">Sin manuales. Usa el CLI para ingestar un PDF.</li>';
    return;
  }
  for (const m of manuals) {
    const li = document.createElement("li");
    li.dataset.id = m.id;
    const checked = checkedManualIds.has(m.id) ? "checked" : "";
    li.innerHTML = `
      <input type="checkbox" class="manual-check" data-id="${m.id}" ${checked}>
      <div style="flex:1;min-width:0;cursor:pointer" class="manual-label">
        <div class="manual-name" title="${escapeHtml(m.name)}">${escapeHtml(m.name)}</div>
        <div class="meta">${m.page_count} pp · ${m.chunk_count} chunks</div>
      </div>
      <button class="delete-btn" title="Eliminar manual" data-id="${m.id}">✕</button>
    `;
    li.querySelector(".manual-check").addEventListener("change", e => {
      const id = +e.target.dataset.id;
      if (e.target.checked) checkedManualIds.add(id);
      else checkedManualIds.delete(id);
      if (isSearchMode()) executeSearch(searchQuery);
    });
    li.querySelector(".manual-label").addEventListener("click", () => {
      clearSearch();
      selectManual(m.id, m.name);
    });
    li.querySelector(".delete-btn").addEventListener("click", async e => {
      e.stopPropagation();
      if (!confirm(`¿Eliminar "${m.name}" y todos sus chunks?`)) return;
      await fetch(`${API}/manuals/${m.id}`, { method: "DELETE" });
      checkedManualIds.delete(m.id);
      if (activeManualId === m.id) clearChunks();
      if (openChunkId !== null) closeDetail();
      loadManuals();
    });
    if (!isSearchMode() && activeManualId === m.id) li.classList.add("active");
    list.appendChild(li);
  }
}

// ---------------------------------------------------------------------------
// Chunks panel (navigation mode)
// ---------------------------------------------------------------------------
function clearChunks() {
  activeManualId = null;
  $("chunks-title").textContent = "Selecciona un manual";
  $("chunks-table").hidden = true;
  $("chunks-body").innerHTML = "";
  $("load-more").hidden = true;
}

async function selectManual(id, name) {
  activeManualId = id;
  currentOffset = 0;
  document.querySelectorAll("#manuals-list li").forEach(li =>
    li.classList.toggle("active", +li.dataset.id === id)
  );
  $("chunks-title").textContent = name;
  $("chunks-body").innerHTML = "";
  $("chunks-table").hidden = false;
  applyLayout();
  await loadChunks(true);
}

async function loadChunks(replace = false) {
  const rows = await fetchJSON(`${API}/manuals/${activeManualId}/chunks?offset=${currentOffset}&limit=${LIMIT}`);
  const tbody = $("chunks-body");
  if (replace) tbody.innerHTML = "";
  for (const c of rows) {
    const tr = document.createElement("tr");
    tr.dataset.id = c.id;
    if (c.id === openChunkId) tr.classList.add("active");
    const sp = c.section_path
      ? `<small title="${escapeHtml(c.section_path)}">${escapeHtml(c.section_path.slice(0, 30))}${c.section_path.length > 30 ? "…" : ""}</small>`
      : "—";
    const preview = escapeHtml((c.text || "").replace(/\n/g, " ").slice(0, 80));
    tr.innerHTML = `
      <td>${c.seq}</td>
      <td>${c.page}${c.page_end ? `–${c.page_end}` : ""}</td>
      <td><span class="badge badge-${c.chunk_type}">${c.chunk_type}</span></td>
      <td title="${c.section_path || ""}">${sp}</td>
      <td title="${preview}">${preview}</td>
    `;
    tr.addEventListener("click", () => openDetail(c.id));
    tbody.appendChild(tr);
  }
  currentOffset += rows.length;
  $("load-more").hidden = rows.length < LIMIT;
}

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------
function clearSearch() {
  searchQuery = "";
  $("search-input").value = "";
  $("search-clear").hidden = true;
  ftsResults = [];
  semResults = [];
  searchInFlight = false;
  applyLayout();
}

async function executeSearch(q) {
  searchQuery = q;
  ftsResults = [];
  semResults = [];
  searchInFlight = true;

  // Show loading states immediately
  $("fts-results").innerHTML = '<div class="loading">Buscando…</div>';
  $("sem-results").innerHTML = '<div class="loading">Buscando… ◌</div>';
  applyLayout();

  const params = buildSearchParams({ q, k: 20 });

  // Fire both requests in parallel — FTS renders first, semantic when ready
  const ftsFetch = fetchJSON(`${API}/search/fts?${params}`)
    .then(results => {
      if (searchQuery !== q) return; // stale — a newer query superseded this one
      ftsResults = results;
      if (!isState4()) renderFtsResults(results);
      else renderMergedResults();
    })
    .catch(() => {
      if (searchQuery !== q) return;
      $("fts-results").innerHTML = '<div class="loading">Error en búsqueda FTS</div>';
    });

  const semFetch = fetchJSON(`${API}/search/semantic?${params}`)
    .then(results => {
      if (searchQuery !== q) return; // stale
      semResults = results;
      if (!isState4()) renderSemResults(results);
      else renderMergedResults();
    })
    .catch(() => {
      if (searchQuery !== q) return;
      $("sem-results").innerHTML = '<div class="loading">Error en búsqueda semántica</div>';
    });

  await Promise.allSettled([ftsFetch, semFetch]);
  if (searchQuery === q) searchInFlight = false;
}

// ---------------------------------------------------------------------------
// Detail panel
// ---------------------------------------------------------------------------
async function openDetail(chunkId) {
  openChunkId = chunkId;
  $("detail-title").textContent = `Cargando #${chunkId}…`;
  $("detail-text").textContent = "";
  $("similar-list").innerHTML = '<div class="similar-loading">Cargando similares…</div>';
  applyLayout();

  // Mark active in current results
  document.querySelectorAll(".result-item").forEach(el =>
    el.classList.toggle("active", +el.dataset.chunkId === chunkId)
  );
  document.querySelectorAll("#chunks-body tr").forEach(tr =>
    tr.classList.toggle("active", +tr.dataset.id === chunkId)
  );

  // Load chunk detail
  const chunk = await fetchJSON(`${API}/chunks/${chunkId}`);
  const sp = chunk.section_path || "";
  $("detail-title").textContent = `#${chunk.id} · p.${chunk.page} · ${chunk.chunk_type}${sp ? " · " + sp : ""}`;
  $("detail-text").textContent = chunk.text;

  // Load similar
  const similar = await fetchJSON(`${API}/chunks/${chunkId}/similar?k=5`);
  const simList = $("similar-list");
  simList.innerHTML = "";
  if (!similar.length) {
    simList.innerHTML = '<div class="similar-loading">Sin similares</div>';
    return;
  }
  similar.forEach(r => {
    const div = makeResultItem(r, "badge-sem", "SEM");
    simList.appendChild(div);
  });
}

function closeDetail() {
  openChunkId = null;
  document.querySelectorAll(".result-item, #chunks-body tr").forEach(el =>
    el.classList.remove("active")
  );
  applyLayout();
  if (isSearchMode()) {
    if (searchInFlight) {
      // Fetches still pending — restore loading indicators instead of "Sin resultados"
      $("fts-results").innerHTML = '<div class="loading">Buscando…</div>';
      $("sem-results").innerHTML = '<div class="loading">Buscando… ◌</div>';
    } else {
      renderFtsResults(ftsResults);
      renderSemResults(semResults);
    }
  }
}

// ---------------------------------------------------------------------------
// Upload (A4)
// ---------------------------------------------------------------------------
function setUploadStatus(html, hidden = false) {
  const el = $("upload-status");
  el.hidden = hidden;
  el.innerHTML = html;
}

function resetUploadZone() {
  uploadFile = null;
  $("upload-file-input").value = "";
  $("upload-name-input").value = "";
  $("upload-name-input").disabled = true;
  $("upload-submit-btn").disabled = true;
  $("upload-drop-area").classList.remove("dragging");
  setUploadStatus("", true);
}

function onFileSelected(file) {
  if (!file || !file.name.toLowerCase().endsWith(".pdf")) {
    setUploadStatus('<span class="upload-error">⚠ Solo se admiten archivos PDF.</span>');
    return;
  }
  uploadFile = file;
  $("upload-name-input").value = file.name.replace(/\.pdf$/i, "");
  $("upload-name-input").disabled = false;
  $("upload-submit-btn").disabled = false;
  setUploadStatus("", true);
}

async function startUpload() {
  if (!uploadFile) return;
  const manualName = $("upload-name-input").value.trim();
  if (!manualName) {
    setUploadStatus('<span class="upload-error">⚠ Introduce un nombre para el manual.</span>');
    return;
  }

  $("upload-submit-btn").disabled = true;
  $("upload-name-input").disabled = true;
  setUploadStatus(`<span class="upload-loading">⏳ Subiendo ${escapeHtml(manualName)}…</span>`);

  const formData = new FormData();
  formData.append("file", uploadFile, uploadFile.name);
  formData.append("manual_name", manualName);

  let jobId;
  try {
    const resp = await fetch(`${API}/manuals/upload`, { method: "POST", body: formData });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${resp.status}`);
    }
    const job = await resp.json();
    jobId = job.id;
    uploadJobId = jobId;
  } catch (e) {
    setUploadStatus(`<span class="upload-error">⚠ Error al subir: ${escapeHtml(e.message)}</span>`);
    $("upload-submit-btn").disabled = false;
    $("upload-name-input").disabled = false;
    return;
  }

  setUploadStatus(`<span class="upload-loading">⏳ Procesando ${escapeHtml(manualName)}… (esto puede tardar 1-2 min)</span>`);
  pollUploadJob(jobId, manualName);
}

function pollUploadJob(jobId, manualName) {
  if (uploadPollTimer) clearInterval(uploadPollTimer);
  uploadPollTimer = setInterval(async () => {
    try {
      const resp = await fetch(`${API}/jobs/${jobId}`);
      if (!resp.ok) return;
      const job = await resp.json();
      if (job.status === "done") {
        clearInterval(uploadPollTimer);
        uploadPollTimer = null;
        if (job.was_duplicate) {
          setUploadStatus(
            `<span class="upload-dup">ℹ ${escapeHtml(manualName)} ya está importado. Para reimportarlo, elimínalo primero.</span>`
          );
        } else {
          setUploadStatus(`<span class="upload-ok">✓ ${escapeHtml(manualName)} importado.</span>`);
          setTimeout(() => { setUploadStatus("", true); resetUploadZone(); }, 3000);
        }
        loadManuals();
      } else if (job.status === "error") {
        clearInterval(uploadPollTimer);
        uploadPollTimer = null;
        setUploadStatus(`<span class="upload-error">⚠ Error: ${escapeHtml(job.error || "desconocido")}</span>`);
        $("upload-submit-btn").disabled = false;
        $("upload-name-input").disabled = false;
      }
    } catch (_) { /* network error, retry next tick */ }
  }, 2000);
}

// ---------------------------------------------------------------------------
// Chunk editing (A4)
// ---------------------------------------------------------------------------
function enterEditMode(chunk) {
  editOriginalChunk = chunk;
  $("edit-chunk-type").value = chunk.chunk_type;
  $("edit-section-path").value = chunk.section_path || "";
  $("edit-text").value = chunk.text;
  $("detail-view").hidden = true;
  $("detail-edit").hidden = false;
  $("detail-edit-btn").hidden = true;
}

function exitEditMode() {
  editOriginalChunk = null;
  $("detail-view").hidden = false;
  $("detail-edit").hidden = true;
  $("detail-edit-btn").hidden = false;
}

async function saveChunkEdit() {
  if (!editOriginalChunk || !openChunkId) return;

  const body = {};
  const newText = $("edit-text").value;
  const newSection = $("edit-section-path").value.trim() || null;
  const newType = $("edit-chunk-type").value;

  if (newText !== editOriginalChunk.text) body.text = newText;
  if (newSection !== (editOriginalChunk.section_path || null)) body.section_path = newSection;
  if (newType !== editOriginalChunk.chunk_type) body.chunk_type = newType;

  if (!Object.keys(body).length) { exitEditMode(); return; }

  $("edit-save-btn").disabled = true;
  $("edit-save-btn").textContent = "Guardando…";

  try {
    const resp = await fetch(`${API}/chunks/${openChunkId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${resp.status}`);
    }
    const updated = await resp.json();
    exitEditMode();
    const sp = updated.section_path || "";
    $("detail-title").textContent =
      `#${updated.id} · p.${updated.page} · ${updated.chunk_type}${sp ? " · " + sp : ""}`;
    $("detail-text").textContent = updated.text;
    editOriginalChunk = updated;
  } catch (e) {
    alert(`Error al guardar: ${e.message}`);
  } finally {
    $("edit-save-btn").disabled = false;
    $("edit-save-btn").textContent = "Guardar";
  }
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
$("load-more").addEventListener("click", () => loadChunks(false));

$("detail-close").addEventListener("click", closeDetail);

$("search-clear").addEventListener("click", () => {
  clearSearch();
  if (activeManualId) {
    currentOffset = 0;
    $("chunks-body").innerHTML = "";
    loadChunks(true);
  }
});

$("search-input").addEventListener("input", e => {
  const q = e.target.value;
  $("search-clear").hidden = !q;
  clearTimeout(searchDebounce);
  if (!q.trim()) {
    clearSearch();
    return;
  }
  searchDebounce = setTimeout(() => executeSearch(q), 320);
});

// Upload listeners (A4)
const dropArea = $("upload-drop-area");
dropArea.addEventListener("dragover", e => { e.preventDefault(); dropArea.classList.add("dragging"); });
dropArea.addEventListener("dragleave", () => dropArea.classList.remove("dragging"));
dropArea.addEventListener("drop", e => {
  e.preventDefault();
  dropArea.classList.remove("dragging");
  const file = e.dataTransfer.files[0];
  if (file) onFileSelected(file);
});
$("upload-file-input").addEventListener("change", e => {
  if (e.target.files[0]) onFileSelected(e.target.files[0]);
});
$("upload-submit-btn").addEventListener("click", startUpload);

// Edit listeners (A4)
$("detail-edit-btn").addEventListener("click", () => {
  if (!openChunkId) return;
  fetchJSON(`${API}/chunks/${openChunkId}`).then(chunk => enterEditMode(chunk));
});
$("edit-cancel-btn").addEventListener("click", exitEditMode);
$("edit-save-btn").addEventListener("click", saveChunkEdit);

loadManuals();
