// /system page entry: tabs over the Controller / llama.cpp / Security /
// Diagnostics panels (the former System modal), plus a hero strip with the
// numbers an operator checks first. The section renderers are shared with
// system-panels.js — this file only orchestrates the page.
import { applyLanguage, applyTheme, initLanguage, onLangChange, setupLangSelect, t } from "./i18n.js";
import { initDialogLlamas } from "./dialog-llamas.js";
import { appConfirm, settleAppConfirm } from "./dialogs.js";
import { setState, state, ui } from "./state.js";
import {
  bindModelGc,
  checkLlamaCpp,
  openRepairUserServiceModal,
  openUpdateLlamaModal,
  refreshSecurity,
  renderControllerInfo,
  renderKnownProblems,
  renderLlamaCpp,
  renderProjectGitBranch,
} from "./system-panels.js";
import { $, api, escapeHtml, markPageState, toast } from "./utils.js";

// The tabs the page actually has, read from the markup. This was a hand-written
// list, and adding a tab to system.html without remembering to add it here made
// clicking it open the FIRST tab instead — no error, no empty panel, just a
// different page than the one asked for, which reads as the button being dead.
const TABS = [...document.querySelectorAll(".sys-tab")].map((b) => b.dataset.tab).filter(Boolean);

function activateTab(name, pushHash = true) {
  if (!TABS.includes(name)) name = TABS[0];
  document.querySelectorAll(".sys-tab").forEach((b) => {
    const on = b.dataset.tab === name;
    b.classList.toggle("active", on);
    b.setAttribute("aria-selected", String(on));
  });
  document.querySelectorAll(".sys-panel").forEach((p) => {
    p.classList.toggle("active", p.dataset.panel === name);
  });
  if (pushHash) history.replaceState(null, "", `#${name}`);
}

function tabFromHash() {
  const h = (location.hash || "").replace("#", "");
  return TABS.includes(h) ? h : TABS[0];
}

// ── hero stats ────────────────────────────────────────────────────────────────
function stat(label, value, kind = "") {
  return `<div class="sys-stat ${kind}"><span>${escapeHtml(label)}</span><strong title="${escapeHtml(value)}">${escapeHtml(value)}</strong></div>`;
}

function renderHero(info) {
  const el = $("sysHeroStats");
  if (!el) return;
  const tiles = [];
  if (state.appVersion) tiles.push(stat("lama-caravan", `v${state.appVersion}`));
  const git = (info && info.projectGit) || state.projectGit || {};
  if (git.branch) tiles.push(stat("git", `${git.branch}${git.head ? " @ " + git.head : ""}`, git.dirtyCount ? "warn" : ""));
  const cells = (info && info.cells) || {};
  if (cells.total != null) tiles.push(stat(t("ctrlCells"), `${cells.running || 0} / ${cells.total || 0}`, cells.running ? "good" : ""));
  const disk = (info && info.disk) || {};
  if (disk.totalGb != null) tiles.push(stat(t("ctrlDisk"), `${disk.freeGb} GB ${t("ctrlDiskFree")}`, (disk.freeGb || 0) < 50 ? "warn" : "good"));
  const models = (info && info.models) || {};
  if (models.count != null) tiles.push(stat(t("ctrlModels"), `${models.count} · ${models.totalGb || 0} GB`));
  if (info && info.python) tiles.push(stat("Python", info.python));
  el.innerHTML = tiles.join("");
  const foot = $("sysFoot");
  if (foot) foot.textContent = state.appVersion ? `lama-caravan v${state.appVersion}` : "";
}

// ── data refresh ─────────────────────────────────────────────────────────────
let _lastInfo = null;

async function refreshAll() {
  try {
    const data = await api("/api/state");
    setState(data);
    renderLlamaCpp();
    renderKnownProblems();
    renderProjectGitBranch();
  } catch { /* state fetch failed — keep whatever is rendered */ }
  try {
    _lastInfo = await api("/api/controller-info");
    renderControllerInfo(_lastInfo);
  } catch (err) {
    const el = $("controllerInfo");
    if (el) el.innerHTML = `<span class="muted">${escapeHtml(String(err.message || err))}</span>`;
  }
  renderHero(_lastInfo);
  // Both fetches have settled — the page shows whatever it is going to show.
  markPageState(_lastInfo ? "ready" : "error", _lastInfo ? "" : "controller-info unavailable");
}

// Every panel here renders translated text into innerHTML, so a language
// change has to re-run them — from the data already in hand, since switching
// language is no reason to hit the controller again.
function repaintForLanguage() {
  renderHero(_lastInfo);
  if (_lastInfo) renderControllerInfo(_lastInfo);
  renderLlamaCpp();
  renderKnownProblems();
  renderProjectGitBranch();
  refreshSecurity();
}

// ── auth chip (same behavior as the board header) ────────────────────────────
function bindUserChip() {
  const doLogout = async () => {
    try { await api("/api/auth/logout", { method: "POST", body: "{}" }); } catch { /* ignore */ }
    window.location = "/login";
  };
  $("authLogoutBtn")?.addEventListener("click", doLogout);
  api("/api/auth/me").then((me) => {
    if (!me.enabled || !me.authenticated) return;
    $("userChipName").textContent = me.user + (me.role === "viewer" ? t("userViewerSuffix") : "");
    $("userChip").hidden = false;
    const menu = $("userMenu");
    const closeMenu = () => { menu.hidden = true; $("userChipBtn").setAttribute("aria-expanded", "false"); };
    $("userChipBtn").addEventListener("click", (e) => {
      e.stopPropagation();
      menu.hidden = !menu.hidden;
      $("userChipBtn").setAttribute("aria-expanded", String(!menu.hidden));
    });
    document.addEventListener("click", (e) => { if (!$("userChip").contains(e.target)) closeMenu(); }, true);
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !menu.hidden) closeMenu(); });
    $("userMenuLogout").addEventListener("click", doLogout);
  }).catch(() => {});
}


// ── The settings file ────────────────────────────────────────────────────────
// One file holding everything the panel can change, and a way back from it.
// Per-cell snapshots answer "undo this cell"; this answers "put the whole thing
// back", which is what you want after letting something loose in the UI to see
// what the buttons do.
function _stamp() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}`;
}

async function exportSettings() {
  const secrets = !!$("settingsWithSecrets")?.checked;
  const res = await api(`/api/settings/export?secrets=${secrets ? 1 : 0}`);
  if (!res?.ok) { toast(t("settingsExportFailed")); return; }
  const text = JSON.stringify(res.bundle, null, 2);
  // Handed over as a download rather than written server-side: the operator
  // decides where their settings live, and a file in the browser's downloads is
  // reachable from the machine they are actually sitting at.
  const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = `caravan-settings-${_stamp()}.json`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
  renderSettingsInfo(res.bundle);
  toast(t("settingsExported"));
}

function renderSettingsInfo(bundle, preview) {
  const box = $("settingsBundleInfo");
  if (!box) return;
  const files = Object.entries(bundle?.files || {}).map(([name, f]) => {
    const c = f.content;
    const size = c === null || c === undefined ? "—"
      : (typeof c === "string" ? `${c.length} chars` : `${Object.keys(c).length}`);
    return `<li><code>${escapeHtml(name)}</code> <span class="muted">${escapeHtml(size)}</span></li>`;
  }).join("");
  // A file that carries accounts and cloud keys is a different object to look
  // after than one that does not, so the panel says so where the file is made
  // rather than in documentation nobody reads at the moment of making it.
  const creds = (bundle?.containsCredentials || []).length
    ? `<p class="settings-warn">⚠ ${escapeHtml(t("settingsHasCredentials"))}</p>` : "";
  const red = (bundle?.redacted || []).length
    ? `<p class="muted">${escapeHtml(t("settingsRedacted", { n: bundle.redacted.length }))}</p>` : "";
  // What the file does NOT carry, said out loud: the moment someone reaches for
  // a restore is the moment they need to know it will not bring their API keys
  // or their token history back.
  const exc = Object.entries(bundle?.excluded || {})
    .map(([k, why]) => `<li><code>${escapeHtml(k)}</code> — ${escapeHtml(why)}</li>`).join("");
  const changes = preview ? `<h3>${escapeHtml(t("settingsWouldChange"))}</h3><ul>${
    preview.changes.map((c) => `<li><code>${escapeHtml(c.name)}</code> — ${escapeHtml(c.action)}${
      c.note ? ` <span class="muted">(${escapeHtml(c.note)})</span>` : ""}</li>`).join("")}</ul>` : "";
  box.innerHTML = `<ul class="settings-file-list">${files}</ul>${creds}${red}${changes}` +
    (exc ? `<h3>${escapeHtml(t("settingsNotIncluded"))}</h3><ul class="settings-file-list">${exc}</ul>` : "");
}

async function importSettings(file) {
  let bundle;
  try {
    bundle = JSON.parse(await file.text());
  } catch (err) {
    toast(t("settingsFileUnreadable"));
    return;
  }
  // Dry run first, always: the operator sees what will be replaced before
  // anything is. A restore is reached for in a hurry, which is exactly when a
  // surprise costs the most.
  const dry = await api("/api/settings/import", { method: "POST", body: { bundle, dryRun: true } });
  if (!dry?.ok) { toast(dry?.error || t("settingsImportFailed")); return; }
  renderSettingsInfo(bundle, dry);
  const willChange = dry.changes.filter((c) => c.action === "replace").map((c) => c.name);
  const ok = await appConfirm(
    t("settingsImportConfirm", { n: willChange.length, list: willChange.join(", ") || "—" }),
    { confirmLabel: t("settingsImport"), scene: "danger" });
  if (!ok) return;
  const res = await api("/api/settings/import", { method: "POST", body: { bundle } });
  if (!res?.ok) { toast(res?.error || t("settingsImportFailed")); return; }
  toast(t("settingsImported"));
  refreshAll();
}

function bindSettingsBundle() {
  const secrets = $("settingsWithSecrets");
  const warn = () => {
    let el = document.querySelector(".settings-secrets-warn");
    if (!el) {
      el = document.createElement("p");
      el.className = "settings-warn settings-secrets-warn";
      secrets?.closest(".settings-secrets-row")?.after(el);
    }
    el.textContent = secrets?.checked ? `⚠ ${t("settingsHasCredentials")}` : "";
  };
  secrets?.addEventListener("change", warn);
  warn();
  $("settingsExportBtn")?.addEventListener("click", () => {
    exportSettings().catch((err) => { console.warn(err); toast(t("settingsExportFailed")); });
  });
  $("settingsImportBtn")?.addEventListener("click", () => $("settingsImportFile")?.click());
  $("settingsImportFile")?.addEventListener("change", (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";                      // same file can be picked twice
    if (file) importSettings(file).catch((err) => { console.warn(err); toast(t("settingsImportFailed")); });
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  initDialogLlamas();
  applyTheme();
  // The language table is its own module now (see i18n-data.js), so it has
  // to arrive before the first render — otherwise the page paints English
  // and only repaints on the next language change.
  await initLanguage();
  applyLanguage();
  setupLangSelect();
  onLangChange(repaintForLanguage);

  // Tabs + deep links (/system#security etc.).
  $("sysTabs").addEventListener("click", (e) => {
    const btn = e.target.closest(".sys-tab");
    if (btn) activateTab(btn.dataset.tab);
  });
  window.addEventListener("hashchange", () => activateTab(tabFromHash(), false));
  activateTab(tabFromHash(), false);

  // Shared confirm dialog wiring (repair / update / GC delete all use it).
  $("confirmCancel").addEventListener("click", () => settleAppConfirm(false));
  $("confirmDelete").addEventListener("click", () => { if (ui.pendingConfirm) ui.pendingConfirm(); });
  $("confirmOverlay").addEventListener("click", (e) => {
    if (e.target.id === "confirmOverlay") settleAppConfirm(false);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("confirmOverlay").hidden) settleAppConfirm(false);
  });

  // Section actions.
  bindModelGc();
  $("checkLlamaBtn")?.addEventListener("click", () => { checkLlamaCpp().catch((err) => console.warn(err)); });
  $("updateLlamaBtn")?.addEventListener("click", openUpdateLlamaModal);
  $("repairUserServiceBtn")?.addEventListener("click", openRepairUserServiceModal);
  bindUserChip();
  bindSettingsBundle();
  refreshSecurity();

  refreshAll();
  setInterval(refreshAll, 30000);
});
