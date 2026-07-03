/* HuggingFace Browser — split layout with favorites & badges */
// $ and escapeHtml come from the shared utils module (note: that escapeHtml
// also escapes single quotes — a strict superset of the old local copy).
import { $, escapeHtml } from "/js/utils.js";

function hfToast(message) {
  let el = document.getElementById("hfToast");
  if (!el) {
    el = document.createElement("div");
    el.id = "hfToast";
    document.body.appendChild(el);
  }
  el.textContent = message;
  el.classList.add("show");
  clearTimeout(hfToast._t);
  hfToast._t = setTimeout(() => el.classList.remove("show"), 4000);
}

function hfConfirm(title, body, okLabel = "Delete", danger = true) {
  return new Promise(resolve => {
    const overlay = document.createElement("div");
    overlay.className = "hf-confirm-overlay";
    overlay.innerHTML =
      `<div class="hf-confirm-box">` +
        `<div class="hf-confirm-title">${escapeHtml(title)}</div>` +
        (body ? `<div class="hf-confirm-body">${escapeHtml(body)}</div>` : "") +
        `<div class="hf-confirm-actions">` +
          `<button class="hf-confirm-cancel">Cancel</button>` +
          `<button class="hf-confirm-ok ${danger ? "danger" : "primary"}">${escapeHtml(okLabel)}</button>` +
        `</div>` +
      `</div>`;
    const close = (val) => { overlay.remove(); resolve(val); };
    overlay.addEventListener("click", e => { if (e.target === overlay) close(false); });
    overlay.querySelector(".hf-confirm-cancel").addEventListener("click", () => close(false));
    overlay.querySelector(".hf-confirm-ok").addEventListener("click", () => close(true));
    document.body.appendChild(overlay);
    overlay.querySelector(".hf-confirm-ok").focus();
  });
}

const searchInput   = $("hfSearchInput");
const searchBtn     = $("hfSearchBtn");
const limitSelect   = $("hfLimitSelect");
const repoCol       = $("hfRepoCol");
const fileCol       = $("hfFileCol");
const dlPanel       = $("hfDownloadPanel");

// ── token ─────────────────────────────────────────────────────────────────────

const tokenStatus   = $("hfTokenStatus");
const tokenInput    = $("hfTokenInput");
const tokenSaveBtn  = $("hfTokenSaveBtn");
const tokenEditBtn  = $("hfTokenEditBtn");
const tokenClearBtn = $("hfTokenClearBtn");

function renderTokenState(data) {
  if (data.set) {
    tokenStatus.textContent = data.masked;
    tokenStatus.className = "hf-token-status is-set";
    tokenClearBtn.hidden = false;
  } else {
    tokenStatus.textContent = "not set — gated models unavailable";
    tokenStatus.className = "hf-token-status";
    tokenClearBtn.hidden = true;
  }
  tokenStatus.hidden = false;
  tokenInput.hidden = true;
  tokenSaveBtn.hidden = true;
  tokenEditBtn.hidden = false;
  tokenInput.value = "";
}

async function loadTokenStatus() {
  try {
    const data = await fetch("/api/hf/token").then(r => r.json());
    renderTokenState(data);
  } catch (_) {}
}

tokenEditBtn.addEventListener("click", async () => {
  if (!(await hfConfirm("Change HF token?", "", "Change", false))) return;
  tokenStatus.hidden = true;
  tokenEditBtn.hidden = true;
  tokenInput.hidden = false;
  tokenSaveBtn.hidden = false;
  tokenInput.focus();
});
tokenSaveBtn.addEventListener("click", saveToken);
tokenInput.addEventListener("keydown", e => {
  if (e.key === "Enter") saveToken();
  if (e.key === "Escape") loadTokenStatus();
});

async function saveToken() {
  const val = tokenInput.value.trim();
  tokenSaveBtn.disabled = true;
  try {
    const data = await fetch("/api/hf/token", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({token: val}),
    }).then(r => r.json());
    renderTokenState(data);
  } catch (e) {
    hfToast(e.message);
  } finally {
    tokenSaveBtn.disabled = false;
  }
}

tokenClearBtn.addEventListener("click", async () => {
  if (!(await hfConfirm("Clear HF token?", "", "Clear"))) return;
  await fetch("/api/hf/token", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({token: ""}),
  });
  await loadTokenStatus();
});

// ── favorites ─────────────────────────────────────────────────────────────────

let favRepos = [];
// [{id, downloads, likes}, ...]

// ── filter / sort state ───────────────────────────────────────────────────────

let filterParamRange = 'all';   // 'all'|'0-9'|'10-19'|'20-29'|'30-39'|'40-74'|'75+'
let filterTypes = new Set();    // активные типы ('it','mmproj','mtp')
let filterMask = '';            // подстрока по имени репо
let sortKey = 'downloads';      // 'downloads'|'likes'|'params'|'date'|'aa'|'olb'
let sortDir = 'desc';
let searchResults = [];         // repos из последнего поиска
let discoveredTypes = new Set(); // типы найденные при загрузке файлов
let _filesLoadDone = 0, _filesLoadTotal = 0;
let _benchLoadDone = 0, _benchLoadTotal = 0;

function isFav(repoId) { return favRepos.some(r => r.id === repoId); }

async function saveFavs() {
  try {
    await fetch("/api/hf/favorites", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({favorites: favRepos}),
    });
  } catch (_) {}
}

async function loadFavs() {
  try {
    const data = await fetch("/api/hf/favorites").then(r => r.json());
    if (data.ok && Array.isArray(data.favorites)) {
      favRepos = data.favorites;
      renderAll();
      loadAllFilesBg(favRepos);
      loadAllBenchmarksBg(favRepos);
    }
  } catch (_) {}
}

function toggleFavorite(repo) {
  if (isFav(repo.id)) {
    favRepos = favRepos.filter(r => r.id !== repo.id);
  } else {
    favRepos = [repo, ...favRepos];
  }
  saveFavs();
  renderAll();
  refreshStarButtons(repo.id);
}

function refreshStarButtons(repoId) {
  const starred = isFav(repoId);
  for (const btn of document.querySelectorAll(`.hf-repo-row[data-repo-id] .hf-star-btn`)) {
    const row = btn.closest(".hf-repo-row");
    if (row?.dataset.repoId === repoId) setStarBtn(btn, starred);
  }
}

function setStarBtn(btn, starred) {
  btn.textContent = starred ? "★" : "☆";
  btn.title = starred ? "Remove from favorites" : "Add to favorites";
  btn.classList.toggle("is-starred", starred);
}

// ── left panel structure ──────────────────────────────────────────────────────

const favSection  = document.createElement("div");
favSection.className = "hf-fav-section";
favSection.hidden = true;

const resultsList = document.createElement("div");
resultsList.className = "hf-results-list";
resultsList.innerHTML = `<div class="hf-file-empty" style="padding:20px;text-align:center;color:var(--muted)">Search to browse repositories</div>`;

repoCol.appendChild(buildFilterBar());
repoCol.appendChild(favSection);
repoCol.appendChild(resultsList);

let favExpanded = true;

// ── helper functions ──────────────────────────────────────────────────────────

function extractParamsNum(repoId) {
  const m = repoId.split("/").pop().match(/(?:^|[-_])(\d+(?:\.\d+)?)[Bb](?:[-_]|$)/);
  return m ? parseFloat(m[1]) : null;
}

function passesAllFilters(repo) {
  // param range
  if (filterParamRange !== 'all') {
    const n = extractParamsNum(repo.id);
    if (n !== null) {
      const ranges = {'0-9':[0,9],'10-19':[10,19],'20-29':[20,29],'30-39':[30,39],'40-74':[40,74],'75+':[75,Infinity]};
      const [lo, hi] = ranges[filterParamRange] || [0, Infinity];
      if (n < lo || n > hi) return false;
    }
  }
  // type filter
  if (filterTypes.size > 0) {
    const files = filesCache.get(repo.id);
    const kinds = files ? new Set(files.map(f => f.kind)) : new Set();
    if (inferIt(repo.id)) kinds.add('it');
    if (inferVision(repo.id, kinds)) kinds.add('vision');
    if (inferAudio(repo.id)) kinds.add('audio');
    if (inferUncensored(repo.id)) kinds.add('uncensored');
    const hasAny = [...filterTypes].some(t => kinds.has(t));
    if (!hasAny && files) return false; // exclude only when files loaded
  }
  // mask
  if (filterMask && !repo.id.toLowerCase().includes(filterMask.toLowerCase())) return false;
  return true;
}

function sortRepos(repos) {
  return [...repos].sort((a, b) => {
    let va, vb;
    switch(sortKey) {
      case 'downloads': va = a.downloads||0; vb = b.downloads||0; break;
      case 'likes':     va = a.likes||0;     vb = b.likes||0;     break;
      case 'params':    va = extractParamsNum(a.id)??-1; vb = extractParamsNum(b.id)??-1; break;
      case 'date':      va = a.createdAt||''; vb = b.createdAt||''; break;
      case 'aa':        va = benchCache.get(a.id)?.scores?.aa_intelligence??-1; vb = benchCache.get(b.id)?.scores?.aa_intelligence??-1; break;
      case 'olb':       va = benchCache.get(a.id)?.scores?.open_llm_avg??-1;   vb = benchCache.get(b.id)?.scores?.open_llm_avg??-1;   break;
      default: return 0;
    }
    if (sortDir==='desc') return vb>va?1:vb<va?-1:0;
    return va>vb?1:va<vb?-1:0;
  });
}

// ── renderAll ─────────────────────────────────────────────────────────────────

function renderAll() {
  const filtFavs    = sortRepos(favRepos.filter(passesAllFilters));
  const filtResults = sortRepos(searchResults.filter(passesAllFilters));
  renderFavSection(filtFavs);
  renderResultsSection(filtResults);
}

// ── renderFavSection ──────────────────────────────────────────────────────────

function renderFavSection(filteredFavs) {
  if (!filteredFavs) filteredFavs = sortRepos(favRepos.filter(passesAllFilters));
  if (!favRepos.length) { favSection.hidden = true; return; }
  favSection.hidden = false;

  const label = document.createElement("div");
  label.className = "hf-section-header hf-fav-header";
  label.innerHTML =
    `<span>★ FAVORITES (${filteredFavs.length} of ${favRepos.length})</span>` +
    `<span class="hf-fav-chevron">${favExpanded ? "▲" : "▼"}</span>`;
  label.addEventListener("click", () => {
    favExpanded = !favExpanded;
    renderFavSection();
  });

  favSection.innerHTML = "";
  favSection.appendChild(label);

  if (favExpanded) {
    for (const repo of filteredFavs) favSection.appendChild(buildRepoRow(repo));
  }
  favSection.insertAdjacentHTML("beforeend", `<div class="hf-section-divider"></div>`);
}

// ── renderResultsSection ──────────────────────────────────────────────────────

function renderResultsSection(repos) {
  resultsList.innerHTML = '';
  if (!searchResults.length) {
    resultsList.innerHTML = `<div class="hf-file-empty" style="padding:20px;text-align:center;color:var(--muted)">Search to browse repositories</div>`;
    return;
  }
  const hdr = document.createElement('div');
  hdr.className = 'hf-section-header hf-results-header';
  hdr.innerHTML = `<span>🔍 Results ${repos.length < searchResults.length ? repos.length + ' of ' + searchResults.length : repos.length}</span>`;
  resultsList.appendChild(hdr);
  if (!repos.length) {
    const el = document.createElement('div');
    el.className = 'hf-status'; el.style.padding = '12px';
    el.textContent = 'No matches for the filter';
    resultsList.appendChild(el);
    return;
  }
  for (const repo of repos) resultsList.appendChild(buildRepoRow(repo));
}

// ── badge helpers ─────────────────────────────────────────────────────────────

function inferIt(repoId) {
  return /[-_]it[-_\/]|[-_]it-gguf|[-_]it$/i.test(repoId);
}

function inferUncensored(repoId) {
  return /uncensored|heretic|abliterat|unfiltered|unrestricted/i.test(repoId);
}

// Input modalities from the HF model record (pipeline_tag + tags). These are
// authoritative for what the model accepts: "image-text-to-text" → vision,
// "audio-text-to-text" → audio, "any-to-any" → both. A loaded mmproj file is a
// secondary signal for vision (covers repos with no modality tags).
function _modalityTokens(repoId) {
  const m = repoModality.get(repoId) || {};
  const toks = [String(m.pipelineTag || ""), ...(m.tags || [])];
  return toks.join(" ").toLowerCase();
}
function inferVision(repoId, extraKinds) {
  if (extraKinds?.has("mmproj")) return true;
  return /image-text-to-text|any-to-any|\bvision\b|\bvlm\b|multimodal/.test(_modalityTokens(repoId));
}
function inferAudio(repoId) {
  return /audio-text-to-text|any-to-any|automatic-speech-recognition|\baudio\b/.test(_modalityTokens(repoId));
}

const TYPE_LABELS = {
  it: '🤖 it', mmproj: '📷 mmproj', mtp: '⚡ mtp',
  vision: '👁 vision', audio: '🎙 audio', uncensored: '🔞 uncensored',
};

function mbadge(type, text) {
  return `<span class="mbadge mbadge-${type}">${text}</span>`;
}

function buildBadgesHtml(repoId, extraKinds) {
  const badges = [];
  if (inferIt(repoId))            badges.push(mbadge("it", "🤖 it"));
  if (inferVision(repoId, extraKinds)) badges.push(mbadge("vision", "👁 vision"));
  if (inferAudio(repoId))         badges.push(mbadge("audio", "🎙 audio"));
  if (extraKinds?.has("mmproj"))  badges.push(mbadge("mmproj", "📷 mmproj"));
  if (extraKinds?.has("mtp"))     badges.push(mbadge("mtp", "⚡ mtp"));
  if (inferUncensored(repoId))    badges.push(mbadge("uncensored", "🔞 uncensored"));
  return badges.join("");
}

function updateRepoBadges(repoId) {
  const files = filesCache.get(repoId) || [];
  const kinds = new Set(files.map(f => f.kind));
  for (const row of document.querySelectorAll(`.hf-repo-row[data-repo-id="${CSS.escape(repoId)}"]`)) {
    const container = row.querySelector(".hf-repo-badges");
    if (container) container.innerHTML = buildBadgesHtml(repoId, kinds);
  }
}

// ── state ─────────────────────────────────────────────────────────────────────

let activeRepoId = null;
const filesCache  = new Map();
const repoMetaCache = new Map(); // repoId → { lastModified }
const repoModality = new Map(); // repoId → { pipelineTag, tags:[] } from HF
const checkedMap  = new Map();
const localCache  = new Map(); // repoId → Set of local filenames

function getChecked(repoId) {
  if (!checkedMap.has(repoId)) checkedMap.set(repoId, new Set());
  return checkedMap.get(repoId);
}

// ── search ────────────────────────────────────────────────────────────────────

searchBtn.addEventListener("click", doSearch);
searchInput.addEventListener("keydown", e => { if (e.key === "Enter") doSearch(); });

async function doSearch() {
  const q = searchInput.value.trim();
  if (!q) return;

  resultsList.innerHTML = `<div class="hf-status">Searching…</div>`;
  fileCol.innerHTML = `<div class="hf-file-empty">← Select a repository</div>`;
  activeRepoId = null;
  filesCache.clear();
  checkedMap.clear();
  refreshDownloadPanel(); // clears selection rows but keeps active download progress
  searchBtn.disabled = true;
  searchResults = [];

  const limit = limitSelect?.value || "20";

  try {
    const data = await fetch(`/api/hf/search?q=${encodeURIComponent(q)}&limit=${limit}`).then(r => r.json());
    if (!data.ok) { resultsList.innerHTML = `<div class="hf-error">${escapeHtml(data.error || "Error")}</div>`; return; }
    if (!data.repos.length) { resultsList.innerHTML = `<div class="hf-status">No results</div>`; return; }

    searchResults = data.repos;
    for (const r of data.repos) {
      if (r.pipelineTag || (r.tags && r.tags.length))
        repoModality.set(r.id, {pipelineTag: r.pipelineTag || "", tags: r.tags || []});
    }
    renderAll();

    if (q.includes("/") && data.repos.length === 1) {
      selectRepo(data.repos[0].id);
    }

    // deduplicate by id
    const allRepos = [...favRepos, ...searchResults].filter(
      (r, i, arr) => arr.findIndex(x => x.id === r.id) === i
    );
    loadAllFilesBg(allRepos);
    loadAllBenchmarksBg(allRepos);
  } catch (e) {
    resultsList.innerHTML = `<div class="hf-error">${escapeHtml(e.message)}</div>`;
  } finally {
    searchBtn.disabled = false;
  }
}

// ── background loaders ────────────────────────────────────────────────────────

async function loadAllFilesBg(repos) {
  const toLoad = repos.filter(r => !filesCache.has(r.id));
  _filesLoadTotal = toLoad.length;
  _filesLoadDone = 0;
  if (!toLoad.length) { updateProgress(); return; }
  updateProgress();
  const CONCURRENCY = 5;
  const queue = [...toLoad];
  async function worker() {
    while (queue.length) {
      const repo = queue.shift();
      if (!repo) break;
      try {
        const data = await fetch(`/api/hf/files?repo=${encodeURIComponent(repo.id)}`).then(r => r.json());
        if (data.ok) {
          const ORDER = {model:0,mmproj:1,mtp:2,vocab:3};
          filesCache.set(repo.id, data.files.sort((a,b) => {
            const d = (ORDER[a.kind]??9) - (ORDER[b.kind]??9);
            return d !== 0 ? d : a.quant < b.quant ? -1 : 1;
          }));
          repoMetaCache.set(repo.id, {lastModified: data.lastModified||''});
          // update discovered types
          for (const f of data.files) {
            if (['mmproj','mtp','vision'].includes(f.kind)) discoveredTypes.add(f.kind);
          }
          const _kinds = new Set(data.files.map(f => f.kind));
          if (inferIt(repo.id)) discoveredTypes.add('it');
          if (inferVision(repo.id, _kinds)) discoveredTypes.add('vision');
          if (inferAudio(repo.id)) discoveredTypes.add('audio');
          if (inferUncensored(repo.id)) discoveredTypes.add('uncensored');
          updateRepoBadges(repo.id);
          refreshRepoRowDate(repo.id);
          updateTypeChips();
        }
      } catch (_) {}
      _filesLoadDone++;
      updateProgress();
    }
  }
  await Promise.all(Array.from({length: CONCURRENCY}, worker));
  updateProgress();
}

async function loadAllBenchmarksBg(repos) {
  const toLoad = repos.filter(r => !benchCache.has(r.id));
  _benchLoadTotal = toLoad.length;
  _benchLoadDone = 0;
  if (!toLoad.length) { updateProgress(); return; }
  updateProgress();
  for (const repo of toLoad) {
    try { await loadBenchmarks(repo.id); } catch(_) {}
    _benchLoadDone++;
    updateProgress();
    renderAll();
    await new Promise(r => setTimeout(r, 80));
  }
  updateProgress();
}

// ── progress & type chips ─────────────────────────────────────────────────────

function updateProgress() {
  const bar  = $('hfLoadProgress');
  const fill = $('hfLoadFill');
  const text = $('hfLoadText');
  if (!bar) return;
  const filesRunning = _filesLoadTotal > 0 && _filesLoadDone < _filesLoadTotal;
  const benchRunning = _benchLoadTotal > 0 && _benchLoadDone < _benchLoadTotal;
  if (!filesRunning && !benchRunning) { bar.style.display = 'none'; return; }
  bar.style.display = 'flex';
  if (filesRunning) {
    const pct = _filesLoadTotal ? (_filesLoadDone / _filesLoadTotal * 100) : 0;
    fill.style.width = pct + '%';
    text.textContent = `files ${_filesLoadDone}/${_filesLoadTotal}`;
  } else {
    const pct = _benchLoadTotal ? (_benchLoadDone / _benchLoadTotal * 100) : 0;
    fill.style.width = pct + '%';
    text.textContent = `benchmarks ${_benchLoadDone}/${_benchLoadTotal}`;
  }
}

function updateTypeChips() {
  const container = $('hfTypeChips');
  const row = $('hfTypeFilterRow');
  if (!container || !row) return;
  if (discoveredTypes.size === 0) { row.style.display = 'none'; return; }
  row.style.display = '';
  container.innerHTML = [...discoveredTypes].sort().map(t =>
    `<button class="hf-chip${filterTypes.has(t) ? ' is-active' : ''}" data-type="${escapeHtml(t)}">${escapeHtml(TYPE_LABELS[t] || t)}</button>`
  ).join('');
  container.querySelectorAll('.hf-chip').forEach(btn => {
    btn.addEventListener('click', () => {
      const t = btn.dataset.type;
      filterTypes.has(t) ? filterTypes.delete(t) : filterTypes.add(t);
      renderAll(); updateTypeChips();
    });
  });
}

// ── filter bar ────────────────────────────────────────────────────────────────

function buildFilterBar() {
  const bar = document.createElement('div');
  bar.className = 'hf-filter-bar';
  bar.id = 'hfFilterBar';
  bar.innerHTML = `
    <div class="hf-filter-row">
      <span class="hf-filter-label">Size:</span>
      <div class="hf-chips" id="hfParamChips">
        <button class="hf-chip is-active" data-range="all">All</button>
        <button class="hf-chip" data-range="0-9">≤9B</button>
        <button class="hf-chip" data-range="10-19">10–19B</button>
        <button class="hf-chip" data-range="20-29">20–29B</button>
        <button class="hf-chip" data-range="30-39">30–39B</button>
        <button class="hf-chip" data-range="40-74">40–74B</button>
        <button class="hf-chip" data-range="75+">75B+</button>
      </div>
    </div>
    <div class="hf-filter-row" id="hfTypeFilterRow" style="display:none">
      <span class="hf-filter-label">Type:</span>
      <div class="hf-chips" id="hfTypeChips"></div>
    </div>
    <div class="hf-filter-row">
      <input class="hf-mask-input" id="hfMaskInput" placeholder="filter by name…" type="text">
      <select class="hf-sort-select" id="hfSortSelect">
        <option value="downloads-desc">↓ Downloads</option>
        <option value="downloads-asc">↑ Downloads</option>
        <option value="likes-desc">↓ Likes</option>
        <option value="likes-asc">↑ Likes</option>
        <option value="params-desc">↓ Size</option>
        <option value="params-asc">↑ Size</option>
        <option value="date-desc">↓ Date</option>
        <option value="date-asc">↑ Date</option>
        <option value="aa-desc">↓ AA Score</option>
        <option value="olb-desc">↓ Open LLM</option>
      </select>
    </div>
    <div class="hf-load-progress" id="hfLoadProgress" style="display:none">
      <div class="hf-load-bar-track"><div class="hf-load-bar-fill" id="hfLoadFill"></div></div>
      <span class="hf-load-text" id="hfLoadText"></span>
    </div>
  `;
  // wire up param chips
  bar.querySelectorAll('#hfParamChips .hf-chip').forEach(btn => {
    btn.addEventListener('click', () => {
      bar.querySelectorAll('#hfParamChips .hf-chip').forEach(b => b.classList.remove('is-active'));
      btn.classList.add('is-active');
      filterParamRange = btn.dataset.range;
      renderAll();
    });
  });
  // wire up mask input
  bar.querySelector('#hfMaskInput').addEventListener('input', e => {
    filterMask = e.target.value;
    renderAll();
  });
  // wire up sort select
  bar.querySelector('#hfSortSelect').addEventListener('change', e => {
    const [k, d] = e.target.value.split('-');
    sortKey = k; sortDir = d;
    renderAll();
  });
  return bar;
}

// ── prefetchBadges (kept for compatibility, not called directly) ──────────────

async function prefetchBadges(repos) {
  // Replaced by loadAllFilesBg — kept as no-op to avoid reference errors
}

function _repoDateHtml(repoId, createdAt) {
  const iso = createdAt || repoMetaCache.get(repoId)?.lastModified || "";
  if (!iso) return "";
  return ` · <span class="hf-repo-date" title="${escapeHtml(iso)}">${escapeHtml(fmtDate(iso))}</span>`;
}

function refreshRepoRowDate(repoId) {
  for (const row of document.querySelectorAll(`.hf-repo-row[data-repo-id="${CSS.escape(repoId)}"]`)) {
    const slot = row.querySelector(".hf-repo-date-slot");
    if (slot) slot.innerHTML = _repoDateHtml(repoId, null);
  }
}

// ── repo row (left panel) ─────────────────────────────────────────────────────

function buildRepoRow(repo) {
  const div = document.createElement("div");
  div.className = "hf-repo-row";
  div.dataset.repoId = repo.id;

  const starred = isFav(repo.id);
  div.innerHTML =
    `<div class="hf-repo-row-top">` +
      `<span class="hf-repo-row-id">${escapeHtml(repo.id)}</span>` +
      `<button class="hf-star-btn${starred ? " is-starred" : ""}" title="${starred ? "Remove from favorites" : "Add to favorites"}">${starred ? "★" : "☆"}</button>` +
    `</div>` +
    `<div class="hf-repo-row-bottom">` +
      `<span class="hf-repo-row-meta">↓ ${fmtNum(repo.downloads)} · ♥ ${fmtNum(repo.likes)}${extractParams(repo.id) ? ` · <span class="hf-repo-params">${extractParams(repo.id)}</span>` : ""}<span class="hf-repo-date-slot">${_repoDateHtml(repo.id, repo.createdAt)}</span></span>` +
      `<div class="hf-repo-badges">${buildBadgesHtml(repo.id, filesCache.get(repo.id) ? new Set(filesCache.get(repo.id).map(f=>f.kind)) : null)}</div>` +
      `<button class="hf-bench-toggle" title="Show benchmarks">📊</button>` +
    `</div>` +
    `<div class="hf-bench-inline"></div>`;

  div.querySelector(".hf-star-btn").addEventListener("click", e => {
    e.stopPropagation();
    toggleFavorite(repo);
  });

  const benchBtn = div.querySelector(".hf-bench-toggle");
  benchBtn.addEventListener("click", e => {
    e.stopPropagation();
    toggleBenchPanel(repo.id, benchBtn);
  });

  // If benchmarks are already cached, fill inline chips directly on this element
  const bdata = benchCache.get(repo.id);
  if (bdata && bdata.scores) _applyBenchInline(div, bdata);

  div.addEventListener("click", () => selectRepo(repo.id));
  return div;
}

// ── select repo → load files into right panel ─────────────────────────────────

async function selectRepo(repoId) {
  activeRepoId = repoId;

  document.querySelectorAll(".hf-repo-row").forEach(el =>
    el.classList.toggle("is-active", el.dataset.repoId === repoId)
  );

  if (filesCache.has(repoId)) {
    renderFilePanel(repoId);
    // Refresh local markers in the background without re-fetching the file list.
    fetch(`/api/hf/local-check?repo=${encodeURIComponent(repoId)}`)
      .then(r => r.json()).then(d => {
        if (d?.ok) { localCache.set(repoId, new Set(d.localNames)); renderFilePanel(repoId); }
      }).catch(() => {});
    return;
  }

  fileCol.innerHTML =
    `<div class="hf-file-col-header"><span class="hf-file-col-title">${escapeHtml(repoId)}</span></div>` +
    `<div class="hf-status">Loading…</div>`;

  try {
    const [filesData, localData] = await Promise.all([
      fetch(`/api/hf/files?repo=${encodeURIComponent(repoId)}`).then(r => r.json()),
      fetch(`/api/hf/local-check?repo=${encodeURIComponent(repoId)}`).then(r => r.json()).catch(() => null),
    ]);

    if (localData?.ok) localCache.set(repoId, new Set(localData.localNames));

    if (!filesData.ok) {
      fileCol.innerHTML =
        `<div class="hf-file-col-header"><span class="hf-file-col-title">${escapeHtml(repoId)}</span></div>` +
        `<div class="hf-error" style="margin:12px">${escapeHtml(filesData.error || "Error")}</div>`;
      return;
    }
    const ORDER = { model: 0, mmproj: 1, mtp: 2, vocab: 3 };
    filesCache.set(repoId, filesData.files.sort((a, b) => {
      const d = (ORDER[a.kind] ?? 9) - (ORDER[b.kind] ?? 9);
      return d !== 0 ? d : a.quant < b.quant ? -1 : 1;
    }));
    repoMetaCache.set(repoId, { lastModified: filesData.lastModified || "" });
    updateRepoBadges(repoId);
    refreshRepoRowDate(repoId);
    renderFilePanel(repoId);
  } catch (e) {
    fileCol.innerHTML =
      `<div class="hf-file-col-header"><span class="hf-file-col-title">${escapeHtml(repoId)}</span></div>` +
      `<div class="hf-error" style="margin:12px">${escapeHtml(e.message)}</div>`;
  }
}

// ── file panel (right column) ─────────────────────────────────────────────────

const LOW_QUANT_RE = /\b(IQ[123]_|Q[23]_)/i;

function isLowQuant(quant) {
  return !!quant && LOW_QUANT_RE.test(quant);
}

function renderFilePanel(repoId) {
  const files   = filesCache.get(repoId) || [];
  const checked = getChecked(repoId);

  fileCol.innerHTML = "";

  const meta = repoMetaCache.get(repoId) || {};
  const header = document.createElement("div");
  header.className = "hf-file-col-header";
  header.innerHTML =
    `<span class="hf-file-col-title">${escapeHtml(repoId)}</span>` +
    (meta.lastModified
      ? `<span class="hf-repo-last-modified" title="Last modified: ${escapeHtml(meta.lastModified)}">updated ${escapeHtml(fmtDate(meta.lastModified))}</span>`
      : "");
  fileCol.appendChild(header);

  if (!files.length) {
    fileCol.insertAdjacentHTML("beforeend", `<div class="hf-status">No GGUF files found</div>`);
    return;
  }

  const list = document.createElement("div");
  list.className = "hf-file-list";

  const localNames = localCache.get(repoId) || new Set();

  for (const f of files) {
    const isLocal = localNames.has(f.name);
    let cls = "hf-file";
    if (f.kind === "model" && isLowQuant(f.quant)) cls += " is-low-quant";
    if (isLocal) cls += " is-local";
    const row = document.createElement("div");
    row.className = cls;
    row._fileData = f;

    const chk = document.createElement("input");
    chk.type = "checkbox";
    chk.className = "hf-file-check";
    chk.checked = checked.has(f.path);
    chk.title = "Select for download";

    chk.addEventListener("change", () => {
      if (chk.checked) checked.add(f.path);
      else checked.delete(f.path);
      refreshDownloadPanel();
      updateRecommendations(repoId);
    });

    row.appendChild(chk);
    row.insertAdjacentHTML("beforeend",
      `<span class="hf-file-local">${isLocal ? "✓" : ""}</span>` +
      `<span class="hf-file-kind hf-kind-${f.kind}">${f.kind}</span>` +
      `<span class="hf-file-name" title="${escapeHtml(f.path)}">${escapeHtml(f.name)}</span>` +
      `<span class="hf-file-quant">${escapeHtml(f.quant)}</span>` +
      `<span class="hf-file-size">${fmtBytes(f.size)}</span>` +
      `<span class="hf-file-date"${f.date ? ` title="${escapeHtml(f.date)}"` : ""}>${f.date ? escapeHtml(fmtDate(f.date)) : ""}</span>` +
      `<span class="hf-file-rec" hidden></span>` +
      (isLocal ? `<button class="hf-file-del" title="Delete local file">🗑</button>` : `<span class="hf-file-del"></span>`)
    );

    if (isLocal) {
      const delBtn = row.querySelector(".hf-file-del");
      delBtn.addEventListener("click", async (e) => {
        e.stopPropagation();
        if (!await hfConfirm("Delete local file?", f.name)) return;
        delBtn.disabled = true;
        delBtn.textContent = "…";
        const res = await fetch(
          `/api/hf/local-file?repo=${encodeURIComponent(repoId)}&name=${encodeURIComponent(f.name)}`,
          { method: "DELETE" }
        ).then(r => r.json()).catch(() => ({ ok: false, error: "network error" }));
        if (res.ok) {
          localCache.get(repoId)?.delete(f.name);
          renderFilePanel(repoId);
        } else {
          delBtn.disabled = false;
          delBtn.textContent = "🗑";
          hfToast(`Failed to delete: ${res.error}`);
        }
      });
    }

    list.appendChild(row);
  }

  fileCol.appendChild(list);
}

// ── recommendations ───────────────────────────────────────────────────────────

const QUANT_RANK = {
  'IQ1_S':0.5,'IQ1_M':0.6,
  'IQ2_XXS':1,'IQ2_XS':1.2,'IQ2_S':1.4,'IQ2_M':1.6,
  'Q2_K':2,'Q2_K_S':2,'Q2_K_L':2.1,'Q2_K_XL':2.2,'Q2_K_XXL':2.3,
  'IQ3_XXS':2.5,'IQ3_XS':2.6,'IQ3_S':2.8,'IQ3_M':3,
  'Q3_K_S':3,'Q3_K_M':3.3,'Q3_K_L':3.6,'Q3_K_XL':3.8,'Q3_K_XXL':3.9,
  'IQ4_XS':3.8,'IQ4_NL':4,
  'Q4_0':4,'Q4_1':4.1,'Q4_K_S':4.2,'Q4_K_M':4.5,'Q4_K_L':4.8,'Q4_K_XL':4.9,'Q4_K_XXL':4.95,
  'Q5_0':5,'Q5_1':5.1,'Q5_K_S':5,'Q5_K_M':5.3,'Q5_K_L':5.6,'Q5_K_XL':5.8,'Q5_K_XXL':5.9,
  'Q6_K':6,'Q6_K_L':6.3,'Q6_K_XL':6.5,
  'Q8_0':8,
  'F16':15,'BF16':16,'F32':32,
};

function quantRank(q) {
  if (!q) return 5; // unknown → above threshold, show by default
  const v = QUANT_RANK[q];
  if (v !== undefined) return v;
  // pattern fallback for unlisted variants
  const u = q.toUpperCase();
  if (/^IQ1_/.test(u)) return 0.6;
  if (/^IQ2_/.test(u)) return 1.5;
  if (/^IQ3_/.test(u)) return 2.8;
  if (/^Q2_/.test(u))  return 2;
  if (/^Q3_/.test(u))  return 3.5;
  if (/^IQ4_/.test(u)) return 3.9;
  return 5; // anything else → show
}

function updateRecommendations(repoId) {
  const files   = filesCache.get(repoId) || [];
  const checked = getChecked(repoId);

  let modelRank = null;
  for (const f of files) {
    if (f.kind === "model" && checked.has(f.path)) {
      const r = quantRank(f.quant);
      if (modelRank === null || r > modelRank) modelRank = r;
    }
  }

  let recMtpPath = null;
  if (modelRank !== null) {
    let best = Infinity;
    for (const f of files) {
      if (f.kind !== "mtp") continue;
      const diff = Math.abs(quantRank(f.quant) - modelRank);
      if (diff < best) { best = diff; recMtpPath = f.path; }
    }
  }

  for (const row of fileCol.querySelectorAll(".hf-file")) {
    const f = row._fileData;
    if (!f) continue;
    const rec = row.querySelector(".hf-file-rec");
    if (!rec) continue;
    let label = null;
    if (modelRank !== null) {
      if (f.kind === "mtp" && f.path === recMtpPath) label = "rec";
      if (f.kind === "mmproj") label = "rec";
    }
    row.classList.toggle("is-recommended", label !== null);
    rec.hidden = label === null;
    rec.textContent = label || "";
  }
}

// ── download panel ────────────────────────────────────────────────────────────

// Active downloads — decoupled from the DOM so the panel can always re-render,
// and an array so several can run/render at once. Each entry is
// { uid, jobId, title, totalFiles, pct, labelText, labelCls, cancelled }.
let dlJobs = [];
let dlJobSeq = 0;

// Persist active downloads to localStorage so a page reload can re-attach to
// jobs still running on the server (their download threads outlive the page).
// Only live jobs are stored; done / error / cancelled ones are dropped.
const DL_STORE_KEY = "hfDlJobs";
function saveDlJobs() {
  try {
    const live = dlJobs
      .filter(j => j.jobId && !j.cancelled && j.labelCls !== "hf-dl-done" && j.labelCls !== "hf-dl-error")
      .map(j => ({ jobId: j.jobId, title: j.title, totalFiles: j.totalFiles }));
    localStorage.setItem(DL_STORE_KEY, JSON.stringify(live));
  } catch (_) { /* storage unavailable — skip */ }
}
async function restoreDlJobs() {
  // Prefer the server-side registry — it's shared across devices and survives a
  // hard reload. Fall back to localStorage if the endpoint isn't reachable.
  let jobs = null;
  try {
    const r = await fetch("/api/hf/download/jobs").then(x => x.json());
    if (r && r.ok && Array.isArray(r.jobs)) {
      jobs = r.jobs.map(j => ({ jobId: j.jobId, title: j.title, totalFiles: j.total_files }));
    }
  } catch (_) {}
  if (!jobs) {
    try { jobs = JSON.parse(localStorage.getItem(DL_STORE_KEY) || "[]"); } catch (_) { jobs = []; }
  }
  if (!Array.isArray(jobs)) return;
  for (const st of jobs) {
    if (!st || !st.jobId || dlJobs.some(j => j.jobId === st.jobId)) continue;
    const job = {
      uid: "dlj" + (++dlJobSeq), jobId: st.jobId, title: st.title || "",
      totalFiles: st.totalFiles || 1, pct: 0, labelText: "Resuming…", labelCls: "", cancelled: false,
    };
    dlJobs.push(job);
    pollDownload(job);
  }
  refreshDownloadPanel();
}

function refreshDownloadPanel() {
  saveDlJobs();
  const allFiles = [];
  for (const [repoId, paths] of checkedMap) {
    if (!paths.size) continue;
    for (const f of (filesCache.get(repoId) || [])) {
      if (paths.has(f.path)) allFiles.push({ repoId, file: f });
    }
  }

  const hasSelection = allFiles.length > 0;
  const hasJobs = dlJobs.length > 0;

  if (!hasSelection && !hasJobs) { dlPanel.hidden = true; dlPanel.innerHTML = ""; return; }

  // ── active job progress sections (one row per concurrent download) ──
  let progressHTML = "";
  for (const job of dlJobs) {
    const pct      = job.pct || 0;
    const labelCls = job.labelCls ? ` ${job.labelCls}` : "";
    const isTerminal = job.labelCls === "hf-dl-done" || job.labelCls === "hf-dl-error";
    const cancelBtn  = (!isTerminal && !job.cancelled)
      ? `<button class="hf-dl-btn hf-dl-btn-cancel" data-action="cancel-job" data-job="${job.uid}">Cancel</button>` : "";
    const titleHTML  = job.title
      ? `<div class="hf-dl-job-title" style="font-size:12px;opacity:.75;margin-bottom:2px">${escapeHtml(job.title)}</div>` : "";
    progressHTML +=
      `<div class="hf-dl-progress-row" style="display:flex;align-items:center;gap:10px;padding:8px 18px 4px">` +
        `<div style="flex:1;min-width:0">` +
          titleHTML +
          `<div class="hf-progress-bar"><div class="hf-progress-fill" style="width:${pct}%"></div></div>` +
          `<div class="hf-progress-label${labelCls}" style="margin-top:3px">${escapeHtml(job.labelText || "Starting…")}</div>` +
        `</div>` +
        cancelBtn +
      `</div>`;
  }

  // ── new selection section ──
  let selectionHTML = "";
  if (hasSelection) {
    const totalSize  = allFiles.reduce((s, { file: f }) => s + (f.size || 0), 0);
    const n          = allFiles.length;
    const lines      = allFiles.map(({ repoId, file: f }) => {
      const dir = computeDestDir(repoId, f);
      return `<div class="hf-dl-file">` +
        `<span class="hf-file-kind hf-kind-${f.kind}">${f.kind}</span>` +
        `<span class="hf-dl-dest">${escapeHtml(dir)}/<b>${escapeHtml(f.name)}</b></span>` +
        `<span class="hf-file-size">${fmtBytes(f.size)}</span>` +
        `</div>`;
    }).join("");
    const wasExpanded = dlPanel.querySelector(".hf-dl-body") && !dlPanel.querySelector(".hf-dl-body[hidden]");
    selectionHTML =
      `<div class="hf-dl-bar"${hasJobs ? ' style="border-top:1px solid var(--line)"' : ""}>` +
        `<span class="hf-dl-bar-label">↓ ${n} file${n !== 1 ? "s" : ""} selected — ${fmtBytes(totalSize)}</span>` +
        `<button class="hf-dl-toggle" data-expand>${wasExpanded ? "▲ hide" : "▼ details"}</button>` +
        `<button class="hf-dl-btn" data-action="start">↓ Download ${n} file${n !== 1 ? "s" : ""}</button>` +
      `</div>` +
      `<div class="hf-dl-body"${wasExpanded ? "" : " hidden"}>` +
        `<div class="hf-dl-preview">${lines}</div>` +
      `</div>`;
  }

  dlPanel.innerHTML = progressHTML + selectionHTML;
  dlPanel.hidden = false;

  dlPanel.querySelector("[data-expand]")?.addEventListener("click", () => {
    const body = dlPanel.querySelector(".hf-dl-body");
    const btn  = dlPanel.querySelector("[data-expand]");
    body.hidden = !body.hidden;
    btn.textContent = body.hidden ? "▼ details" : "▲ hide";
  });

  dlPanel.querySelectorAll("[data-action=cancel-job]").forEach(btn => {
    btn.addEventListener("click", () => {
      const job = dlJobs.find(j => j.uid === btn.getAttribute("data-job"));
      if (job) {
        job.cancelled = true;
        job.labelText = "Cancelled (current file will finish)";
        setTimeout(() => { dlJobs = dlJobs.filter(j => j !== job); refreshDownloadPanel(); }, 4000);
      }
      refreshDownloadPanel();
    });
  });

  if (hasSelection) {
    // One job per repo: the download endpoint takes a single repo id, so a
    // mixed-repo selection must not send other repos' paths under it (they
    // would 404 on the wrong repo URL and fail the whole job).
    dlPanel.querySelector("[data-action=start]").addEventListener("click", () => {
      const byRepo = new Map();
      for (const { repoId, file } of allFiles) {
        if (!byRepo.has(repoId)) byRepo.set(repoId, []);
        byRepo.get(repoId).push(file);
      }
      for (const [rid, files] of byRepo) {
        const payload = files.map(f => ({
          path: f.path, name: f.name, size: f.size, destDir: computeDestDir(rid, f),
        }));
        startDownload(rid, files, payload);
      }
    });
  }
}

// ── models-disk headroom: header badge + pre-download fit check ─────────────
let _diskInfo = null;
async function refreshDiskInfo() {
  try {
    _diskInfo = await fetch("/api/models/disk").then(r => r.json());
  } catch (_) { _diskInfo = null; }
  const el = document.getElementById("hfDiskBadge");
  if (!el) return;
  if (!_diskInfo || !_diskInfo.ok) { el.hidden = true; return; }
  const free = _diskInfo.freeGb;
  el.hidden = false;
  el.textContent = `disk: ${free} GB free`;
  el.title = `${_diskInfo.path} — ${free} GB free of ${_diskInfo.totalGb} GB`;
  el.classList.toggle("low", free < 50);
  el.classList.toggle("critical", free < 15);
}

// Returns true when the download should proceed. Blocks with a confirm()
// when the selection clearly does not fit (sizes are known from the file
// list; +5 GB slack for the .tmp copy during multi-part assembly).
function diskFitCheck(files) {
  if (!_diskInfo || !_diskInfo.ok) return true;
  const needGb = files.reduce((a, f) => a + (Number(f.size) || 0), 0) / 2 ** 30 + 5;
  const freeGb = Number(_diskInfo.freeGb) || 0;
  if (needGb <= freeGb) return true;
  return confirm(
    `This download needs ~${needGb.toFixed(1)} GB but the models disk has only `
    + `${freeGb} GB free (${_diskInfo.path}).\n\nFree up space first (or press OK to try anyway).`);
}

async function startDownload(repoId, files, payload) {
  if (!diskFitCheck(files)) return;
  const job = {
    // Full repo id, not just the model name — concurrent jobs for the same
    // model from different authors must be distinguishable in the panel.
    uid: "dlj" + (++dlJobSeq), jobId: null, title: repoId,
    totalFiles: files.length, pct: 0, labelText: "Starting…", labelCls: "", cancelled: false,
  };
  dlJobs.push(job);
  refreshDownloadPanel();

  try {
    const data = await fetch("/api/hf/download", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ repo: repoId, files: payload }),
    }).then(r => r.json());

    if (!data.ok) {
      job.labelText = "Error: " + (data.error || "unknown"); job.labelCls = "hf-dl-error";
      refreshDownloadPanel();
      return;
    }
    job.jobId = data.jobId;
    // The files now belong to the job — drop them from the selection so the
    // Download button can't start a duplicate job for the same destinations.
    const startedPaths = new Set(payload.map(p => p.path));
    const checked = checkedMap.get(repoId);
    if (checked) startedPaths.forEach(p => checked.delete(p));
    document.querySelectorAll(".hf-file-list .hf-file").forEach(row => {
      if (activeRepoId === repoId && row._fileData && startedPaths.has(row._fileData.path)) {
        const chk = row.querySelector(".hf-file-check");
        if (chk) chk.checked = false;
      }
    });
    saveDlJobs();
    pollDownload(job);
  } catch (e) {
    job.labelText = "Error: " + e.message; job.labelCls = "hf-dl-error";
    refreshDownloadPanel();
  }
}

function pollDownload(job) {
  async function tick() {
    if (!dlJobs.includes(job) || job.cancelled) return;
    try {
      const s = await fetch(`/api/hf/download/status?job=${encodeURIComponent(job.jobId)}`).then(r => r.json());
      if (!dlJobs.includes(job) || job.cancelled) return;
      if (!s.ok) { dlJobs = dlJobs.filter(j => j !== job); refreshDownloadPanel(); return; }

      const pct = s.total_bytes > 0
        ? Math.round((s.total_bytes_done / s.total_bytes) * 100)
        : s.total_files > 0 ? Math.round((s.current_idx / s.total_files) * 100) : 0;
      job.pct = pct;

      if (s.status === "running") {
        const fileNum = Math.min(s.current_idx + 1, job.totalFiles);
        const filePct = s.file_bytes_total > 0
          ? Math.round((s.file_bytes_done / s.file_bytes_total) * 100) : 0;
        // Smoothed transfer speed from poll-to-poll byte deltas.
        const now = performance.now();
        if (job._pBytes != null && now > job._pTime) {
          const inst = (s.total_bytes_done - job._pBytes) / ((now - job._pTime) / 1000);
          if (inst >= 0) job._speed = job._speed ? job._speed * 0.7 + inst * 0.3 : inst;
        }
        job._pBytes = s.total_bytes_done; job._pTime = now;
        const speedTxt = job._speed > 0 ? ` — ${(job._speed / 1048576).toFixed(1)} MB/s` : "";
        job.labelText = `File ${fileNum}/${job.totalFiles} — ${s.current_file} (${filePct}%)${speedTxt}`;
        refreshDownloadPanel();
        setTimeout(tick, 600);
      } else if (s.status === "done") {
        job.pct = 100;
        job.labelText = `Done — ${job.totalFiles} file${job.totalFiles !== 1 ? "s" : ""} downloaded`;
        job.labelCls = "hf-dl-done";
        refreshDownloadPanel();
        // The files are on disk now — refresh the ✓ local markers for the repo.
        if (s.repo) {
          fetch(`/api/hf/local-check?repo=${encodeURIComponent(s.repo)}`)
            .then(r => r.json()).then(d => {
              if (d?.ok) {
                localCache.set(s.repo, new Set(d.localNames));
                if (activeRepoId === s.repo) renderFilePanel(s.repo);
              }
            }).catch(() => {});
        }
        setTimeout(() => { dlJobs = dlJobs.filter(j => j !== job); refreshDownloadPanel(); }, 4000);
      } else if (s.status === "error") {
        job.labelText = "Error: " + (s.error || "unknown");
        job.labelCls = "hf-dl-error";
        refreshDownloadPanel();
      }
    } catch (e) {
      if (dlJobs.includes(job)) { job.labelText = "Poll error: " + e.message; refreshDownloadPanel(); }
    }
  }
  tick();
}

// ── path helpers ──────────────────────────────────────────────────────────────

function deriveModelName(repoId) {
  return repoId.includes("/") ? repoId.split("/").pop() : repoId;
}

function computeDestDir(repoId, file) {
  const author    = repoId.includes("/") ? repoId.split("/")[0] : "unknown";
  const modelName = deriveModelName(repoId);
  const quant     = file.quant || "default";
  return `${modelName}/${author}/${quant}`;
}

// ── benchmarks ───────────────────────────────────────────────────────────────

const benchCache = new Map();   // repoId → data | null
const benchExpanded = new Set(); // repoIds with panel open

async function loadBenchmarks(repoId, force = false) {
  if (!force && benchCache.has(repoId)) return benchCache.get(repoId);
  benchCache.set(repoId, null); // mark as loading
  try {
    const url = `/api/hf/benchmarks?repo=${encodeURIComponent(repoId)}${force ? "&force=1" : ""}`;
    const data = await fetch(url).then(r => r.json());
    benchCache.set(repoId, data.ok ? data : null);
    return benchCache.get(repoId);
  } catch (_) {
    benchCache.set(repoId, null);
    return null;
  }
}

function _benchBarPct(key, val) {
  if (key === "arena_elo") return Math.min(100, Math.max(0, Math.round((val - 800) / 6)));
  if (key === "mt_bench")  return Math.round((val / 10) * 100);
  return Math.min(100, Math.max(0, Math.round(val)));
}

function _buildBenchPanel(repoId, data, onRefresh) {
  const panel = document.createElement("div");
  panel.className = "hf-bench-panel";

  if (!data || !data.scores || !Object.keys(data.scores).length) {
    // Header with refresh even when empty
    const hdr = document.createElement("div");
    hdr.className = "hf-bench-panel-header";
    hdr.innerHTML = `<span class="hf-bench-data-from">No benchmark data</span>`;
    const ref = _buildRefreshBtn(onRefresh, data?.from_cache);
    hdr.appendChild(ref);
    panel.appendChild(hdr);
    return panel;
  }

  const { scores, groups, meta, data_from, repo, from_cache } = data;

  // Header: source note + refresh button
  const hdr = document.createElement("div");
  hdr.className = "hf-bench-panel-header";
  const showSource = data_from && data_from !== repo;
  hdr.innerHTML = showSource
    ? `<span class="hf-bench-data-from">📌 data for: <strong>${escapeHtml(data_from)}</strong></span>`
    : `<span class="hf-bench-data-from">${from_cache ? "cached" : "fresh data"}</span>`;
  hdr.appendChild(_buildRefreshBtn(onRefresh, from_cache));
  panel.appendChild(hdr);

  for (const g of (groups || [])) {
    if (!g.keys || !g.keys.length) continue;
    const grpDiv = document.createElement("div");
    grpDiv.className = "hf-bench-group";
    grpDiv.innerHTML = `<div class="hf-bench-group-label">${escapeHtml(g.label)}</div>`;
    for (const key of g.keys) {
      const val = scores[key];
      if (val === undefined) continue;
      const m = (meta || {})[key] || [key, "", "0–100 %", "", ""];
      const [engName, ruDesc, scale, , url] = m;
      const pct = _benchBarPct(key, val);
      const isElo = key === "arena_elo";
      const displayVal = key === "mt_bench" ? val.toFixed(1) + "/10" : val + (scale.includes("%") ? " %" : "");
      const nameHtml = url
        ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener">${escapeHtml(engName)}</a>`
        : escapeHtml(engName);
      const row = document.createElement("div");
      row.className = "hf-bench-row" + (isElo ? " is-elo" : "");
      row.innerHTML =
        `<span class="hf-bench-row-name" title="${escapeHtml(engName)}">${nameHtml}</span>` +
        `<span class="hf-bench-row-desc" title="${escapeHtml(ruDesc)}">${escapeHtml(ruDesc)}</span>` +
        `<div class="hf-bench-bar-wrap"><div class="hf-bench-bar-fill" style="width:${pct}%"></div></div>` +
        `<span class="hf-bench-row-val">${escapeHtml(String(displayVal))}</span>`;
      grpDiv.appendChild(row);
    }
    panel.appendChild(grpDiv);
  }
  return panel;
}

function _buildRefreshBtn(onRefresh, fromCache) {
  const btn = document.createElement("button");
  btn.className = "hf-bench-refresh";
  btn.title = "Refresh from the server";
  btn.innerHTML = fromCache ? "🔄 refresh" : "🔄";
  btn.addEventListener("click", e => { e.stopPropagation(); onRefresh && onRefresh(); });
  return btn;
}

function _onRefresh(repoId) {
  benchCache.delete(repoId);
  // Show loading in existing panel
  for (const row of document.querySelectorAll(`.hf-repo-row[data-repo-id="${CSS.escape(repoId)}"]`)) {
    const p = row.querySelector(".hf-bench-panel");
    if (p) p.innerHTML = `<div class="hf-bench-loading">Refreshing…</div>`;
  }
  loadBenchmarks(repoId, true).then(() => {
    if (benchExpanded.has(repoId)) _refreshBenchUI(repoId);
  });
}

function _applyBenchInline(rowEl, data) {
  const inlineEl = rowEl.querySelector(".hf-bench-inline");
  if (!inlineEl || !data || !data.scores) return;
  const inline = data.inline || [];
  if (!inline.length) { inlineEl.innerHTML = ""; return; }
  inlineEl.innerHTML = inline.map(key => {
    const val = data.scores[key];
    if (val === undefined) return "";
    const m = (data.meta || {})[key] || [key, "", "0–100 %", "", ""];
    const engName = m[0];
    const scale = m[2] || "";
    const displayVal = key === "mt_bench" ? val.toFixed(1) : val;
    const isElo = key === "arena_elo";
    return `<span class="hf-bench-chip${isElo ? " is-elo" : ""}">` +
      `<span class="hf-bench-chip-name">${escapeHtml(engName)}</span>` +
      `<span class="hf-bench-chip-val">${escapeHtml(String(displayVal))}${scale.includes("%") && key !== "arena_elo" ? "%" : ""}</span>` +
      `</span>`;
  }).join("");
}

function _refreshBenchUI(repoId) {
  const data = benchCache.get(repoId);
  const rows = document.querySelectorAll(`.hf-repo-row[data-repo-id="${CSS.escape(repoId)}"]`);
  for (const row of rows) {
    _applyBenchInline(row, data);
    // Update panel if expanded
    if (benchExpanded.has(repoId)) {
      const existing = row.querySelector(".hf-bench-panel");
      const newPanel = _buildBenchPanel(repoId, data, () => _onRefresh(repoId));
      if (existing) existing.replaceWith(newPanel);
      else row.appendChild(newPanel);
    }
  }
}

async function toggleBenchPanel(repoId, toggleBtn) {
  const isOpen = benchExpanded.has(repoId);
  if (isOpen) {
    benchExpanded.delete(repoId);
    toggleBtn.textContent = "📊";
    toggleBtn.classList.remove("is-active");
    for (const row of document.querySelectorAll(`.hf-repo-row[data-repo-id="${CSS.escape(repoId)}"]`)) {
      row.querySelector(".hf-bench-panel")?.remove();
    }
    return;
  }

  benchExpanded.add(repoId);
  toggleBtn.textContent = "📊▲";
  toggleBtn.classList.add("is-active");

  // Show loading placeholder
  for (const row of document.querySelectorAll(`.hf-repo-row[data-repo-id="${CSS.escape(repoId)}"]`)) {
    if (!row.querySelector(".hf-bench-panel")) {
      const ph = document.createElement("div");
      ph.className = "hf-bench-panel";
      ph.innerHTML = `<div class="hf-bench-loading">Loading benchmarks…</div>`;
      row.appendChild(ph);
    }
  }

  const data = await loadBenchmarks(repoId);
  if (benchExpanded.has(repoId)) {
    _refreshBenchUI(repoId);
  }
}

// ── helpers ───────────────────────────────────────────────────────────────────

function extractParams(repoId) {
  const name = repoId.split("/").pop();
  // Match e.g. 8B, 70B, 1.5B, 0.5B, 405B — as a dash/underscore-delimited token
  const m = name.match(/(?:^|[-_])(\d+(?:\.\d+)?)[Bb](?:[-_]|$)/);
  if (!m) return "";
  const n = parseFloat(m[1]);
  if (n < 0.1 || n > 10000) return "";
  return n + "B";
}

function fmtNum(n) {
  if (!n) return "0";
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "k";
  return String(n);
}

function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return "";
  const now = new Date();
  const diffDays = Math.floor((now - d) / 86400000);
  if (diffDays === 0) return "today";
  if (diffDays === 1) return "yesterday";
  if (diffDays < 30) return `${diffDays}d ago`;
  if (diffDays < 365) return `${Math.floor(diffDays / 30)}mo ago`;
  return `${Math.floor(diffDays / 365)}y ago`;
}

function fmtBytes(b) {
  if (!b) return "—";
  if (b >= 1073741824) return (b / 1073741824).toFixed(1) + " GB";
  return Math.round(b / 1048576) + " MB";
}

// ── frontier reference panel ──────────────────────────────────────────────────

const refSection = document.createElement("div");
refSection.className = "hf-ref-section";
repoCol.appendChild(refSection);

let refExpanded = false;
let _refData = null;

const ORG_COLOR = {
  Google: "#4285f4", OpenAI: "#10a37f", Anthropic: "#d97757",
  Meta: "#0064e0", DeepSeek: "#5b6cf9", Qwen: "#ff6b00", Mistral: "#fa5252",
};

function renderRefSection() {
  refSection.innerHTML = "";
  const hdr = document.createElement("div");
  hdr.className = "hf-section-header hf-ref-header";
  hdr.innerHTML =
    `<span>📊 Reference models (frontier)</span>` +
    `<span class="hf-fav-chevron">${refExpanded ? "▲" : "▼"}</span>`;
  hdr.addEventListener("click", () => {
    refExpanded = !refExpanded;
    if (refExpanded && !_refData) loadRefModels();
    else renderRefSection();
  });
  refSection.appendChild(hdr);

  if (!refExpanded) return;

  if (!_refData) {
    const loading = document.createElement("div");
    loading.className = "hf-status"; loading.style.padding = "12px";
    loading.textContent = "Loading data from Artificial Analysis…";
    refSection.appendChild(loading);
    return;
  }

  const table = document.createElement("div");
  table.className = "hf-ref-table";

  const maxAA = Math.max(..._refData.filter(m => m.aa != null).map(m => m.aa));

  for (const m of _refData) {
    const row = document.createElement("div");
    row.className = "hf-ref-row";
    const orgColor = ORG_COLOR[m.org] || "#888";
    const pct = m.aa != null ? Math.round((m.aa / (maxAA || 100)) * 100) : 0;
    row.innerHTML =
      `<span class="hf-ref-org" style="color:${escapeHtml(orgColor)}">${escapeHtml(m.org)}</span>` +
      `<span class="hf-ref-name">${escapeHtml(m.name)}</span>` +
      `<div class="hf-ref-bar-wrap"><div class="hf-ref-bar-fill" style="width:${pct}%;background:${escapeHtml(orgColor)}40;border-right:2px solid ${escapeHtml(orgColor)}"></div></div>` +
      `<span class="hf-ref-val">${m.aa != null ? m.aa : "—"}</span>`;
    table.appendChild(row);
  }

  const footer = document.createElement("div");
  footer.className = "hf-ref-footer";
  const isDefault = !_refData || _refData.every(m => !m._live);
  footer.innerHTML =
    `AA Intelligence Index · <a href="https://artificialanalysis.ai/leaderboards/models" target="_blank" rel="noopener">artificialanalysis.ai</a>` +
    (isDefault ? ` · <span title="Data snapshot from June 2026">~Jun 2026</span>` : "") +
    `<button class="hf-bench-refresh" id="hfRefRefresh" title="Fetch fresh data from AA">🔄</button>`;
  footer.querySelector("#hfRefRefresh").addEventListener("click", () => {
    _refData = null;
    renderRefSection();
    loadRefModels(true);
  });

  refSection.appendChild(table);
  refSection.appendChild(footer);
}

async function loadRefModels(force = false) {
  try {
    const url = `/api/hf/reference-models${force ? "?force=1" : ""}`;
    const data = await fetch(url).then(r => r.json());
    if (data.ok) {
      _refData = data.models.filter(m => m.aa != null).sort((a, b) => (b.aa || 0) - (a.aa || 0));
      renderRefSection();
    }
  } catch (_) {}
}

// ── init ──────────────────────────────────────────────────────────────────────

const _initLoads = [loadTokenStatus(), loadFavs(), restoreDlJobs()];
refreshDiskInfo();
setInterval(refreshDiskInfo, 60_000);
renderRefSection();
// Пиксельный лоадер (inline в hf.html) прячем, когда стартовые данные пришли.
Promise.allSettled(_initLoads).then(() => window.__plHide?.());

const _urlQ = new URLSearchParams(location.search).get("q");
if (_urlQ) {
  searchInput.value = _urlQ;
  doSearch();
} else {
  searchInput.focus();
}

// ── onboarding tour (?) ───────────────────────────────────────────────────────
// The engine is dependency-free; strings live here so this page keeps NOT
// importing the big i18n dictionary. RU + EN; the language follows the main
// app's localStorage key.
import { autoStartOnce, createTour, initTourButtons } from "/js/onboarding.js";

const HF_TOUR = {
  en: {
    btn: "How to use this page",
    label: "Tour",
    langPick: "Language",
    next: "Next →", back: "← Back", done: "Done", skip: "Close",
    steps: [
      [null, "HuggingFace model browser",
       "Search HuggingFace for <b>GGUF</b> models and download them straight to the controller's models directory — they become available to every llama server cell.<br><br>Navigate with <b>→</b>/<b>←</b>, close with <b>Esc</b>."],
      [".hf-search", "Search",
       "Type a repo name (<code>bartowski/Qwen3-…-GGUF</code>) or free words. Only GGUF repositories are shown."],
      ["#hfRepoCol", "Repositories",
       "Pick a repository — stars, downloads and benchmark badges help choose. ★ favorites stay on top."],
      ["#hfFileCol", "Files & quants",
       "Every GGUF in the repo with its size. Pick a quantization that fits your VRAM (the board's editor shows a fit estimate) and press download; multi-part files are handled automatically. Files land as <code>&lt;model&gt;/&lt;author&gt;/&lt;quant&gt;/file.gguf</code> — use the same layout when adding models by hand."],
      [".hf-token-row", "HF token",
       "Needed only for gated or private repos. Stored on the controller, never in the browser."],
    ],
  },
  ru: {
    btn: "Как пользоваться этой страницей",
    label: "Тур",
    langPick: "Язык",
    next: "Дальше →", back: "← Назад", done: "Готово", skip: "Закрыть",
    steps: [
      [null, "Браузер моделей HuggingFace",
       "Ищите на HuggingFace <b>GGUF</b>-модели и скачивайте их прямо в каталог моделей контроллера — они станут доступны всем llama-ячейкам.<br><br>Навигация: <b>→</b>/<b>←</b>, закрыть — <b>Esc</b>."],
      [".hf-search", "Поиск",
       "Введите имя репозитория (<code>bartowski/Qwen3-…-GGUF</code>) или просто слова. Показываются только GGUF-репозитории."],
      ["#hfRepoCol", "Репозитории",
       "Выберите репозиторий — помогут звёзды, загрузки и бейджи бенчмарков. ★ избранное всегда сверху."],
      ["#hfFileCol", "Файлы и кванты",
       "Все GGUF репозитория с размерами. Выберите квант под вашу VRAM (оценку «влезет ли» покажет редактор на доске) и жмите download; многочастные файлы склеиваются сами. Файлы ложатся как <code>&lt;модель&gt;/&lt;автор&gt;/&lt;квант&gt;/файл.gguf</code> — кладите руками в ту же структуру."],
      [".hf-token-row", "HF-токен",
       "Нужен только для gated/приватных репозиториев. Хранится на контроллере, не в браузере."],
    ],
  },
};

function hfTourStrings() {
  const lang = localStorage.getItem("llamacppAdminLang") || "en";
  return HF_TOUR[lang] || HF_TOUR.en;
}

function hfTourBtnLabel() {
  const el = document.getElementById("obBtnLabel");
  if (el) el.textContent = hfTourStrings().label;
}

// The tour dictionary here is EN/RU only, so the welcome step offers exactly
// those two; the choice is written to the shared app language key.
function hfLangPicker(body, api) {
  const s = hfTourStrings();
  const cur = localStorage.getItem("llamacppAdminLang") || "en";
  const wrap = document.createElement("div");
  wrap.className = "ob-langs";
  wrap.innerHTML = `<div class="ob-langs-head">${s.langPick}</div><div class="ob-langs-grid">`
    + [["en", "☕ English"], ["ru", "🪆 Русский"]].map(([code, label]) =>
      `<button type="button" class="ob-lang${code === cur ? " selected" : ""}" data-ob-lang="${code}">${label}</button>`).join("")
    + `</div>`;
  wrap.addEventListener("click", (ev) => {
    const btn = ev.target.closest("[data-ob-lang]");
    if (!btn) return;
    localStorage.setItem("llamacppAdminLang", btn.dataset.obLang);
    hfTourBtnLabel();
    api.rerender();
  });
  body.appendChild(wrap);
}

function hfStartTour() {
  createTour({
    steps: () => hfTourStrings().steps.map(([anchor, title, body], i) => ({
      anchor, title, body, center: !anchor,
      onRender: !anchor && i === 0 ? hfLangPicker : undefined,
    })),
    labels: () => {
      const s = hfTourStrings();
      return { next: s.next, back: s.back, done: s.done, skip: s.skip };
    },
  }).start();
}

hfTourBtnLabel();
initTourButtons({ title: () => hfTourStrings().btn, onClick: hfStartTour });
autoStartOnce("hf", () => !document.getElementById("appLoader"), hfStartTour);
