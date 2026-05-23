// rag.js — ES module for /rag page
const API = "/api/rag";
let activeManualId = null;
let currentOffset = 0;
const LIMIT = 50;

async function fetchJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

// --- Manuals panel ---

async function loadManuals() {
  const list = document.getElementById("manuals-list");
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
    li.innerHTML = `
      <div>
        <div>${m.name}</div>
        <div class="meta">${m.page_count} pp · ${m.chunk_count} chunks</div>
      </div>
      <button class="delete-btn" title="Eliminar manual" data-id="${m.id}">✕</button>
    `;
    li.querySelector(".delete-btn").addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!confirm(`¿Eliminar "${m.name}" y todos sus chunks?`)) return;
      await fetch(`${API}/manuals/${m.id}`, { method: "DELETE" });
      if (activeManualId === m.id) clearChunks();
      loadManuals();
    });
    li.addEventListener("click", () => selectManual(m.id, m.name));
    list.appendChild(li);
  }
}

function clearChunks() {
  activeManualId = null;
  document.getElementById("chunks-title").textContent = "Selecciona un manual";
  document.getElementById("chunks-table").hidden = true;
  document.getElementById("chunks-body").innerHTML = "";
  document.getElementById("load-more").hidden = true;
  hideDetail();
}

async function selectManual(id, name) {
  activeManualId = id;
  currentOffset = 0;
  document.querySelectorAll("#manuals-list li").forEach(li => li.classList.toggle("active", +li.dataset.id === id));
  document.getElementById("chunks-title").textContent = name;
  document.getElementById("chunks-body").innerHTML = "";
  document.getElementById("chunks-table").hidden = false;
  hideDetail();
  await loadChunks(true);
}

// --- Chunks panel ---

async function loadChunks(replace = false) {
  const rows = await fetchJSON(`${API}/manuals/${activeManualId}/chunks?offset=${currentOffset}&limit=${LIMIT}`);
  const tbody = document.getElementById("chunks-body");
  if (replace) tbody.innerHTML = "";
  for (const c of rows) {
    const tr = document.createElement("tr");
    tr.dataset.id = c.id;
    const sp = c.section_path ? `<small>${c.section_path}</small>` : "—";
    const preview = (c.text || "").replace(/\n/g, " ").slice(0, 80);
    tr.innerHTML = `
      <td>${c.seq}</td>
      <td>${c.page}${c.page_end ? `–${c.page_end}` : ""}</td>
      <td><span class="badge badge-${c.chunk_type}">${c.chunk_type}</span></td>
      <td>${sp}</td>
      <td title="${preview}">${preview}</td>
    `;
    tr.addEventListener("click", () => showDetail(c.id));
    tbody.appendChild(tr);
  }
  currentOffset += rows.length;
  document.getElementById("load-more").hidden = rows.length < LIMIT;
}

// --- Chunk detail ---

async function showDetail(chunkId) {
  const c = await fetchJSON(`${API}/chunks/${chunkId}`);
  document.getElementById("chunk-text").textContent = c.text;
  document.getElementById("chunk-detail").hidden = false;
}

function hideDetail() {
  document.getElementById("chunk-detail").hidden = true;
}

// --- Init ---

document.getElementById("load-more").addEventListener("click", () => loadChunks(false));
document.getElementById("close-detail").addEventListener("click", hideDetail);
loadManuals();
