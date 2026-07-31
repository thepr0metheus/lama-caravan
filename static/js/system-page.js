// /system page entry: tabs over the Controller / llama.cpp / Security /
// Diagnostics panels (the former System modal), plus a hero strip with the
// numbers an operator checks first. The section renderers are shared with
// system-panels.js — this file only orchestrates the page.
import { applyLanguage, applyTheme, initLanguage, onLangChange, setupLangSelect, t } from "./i18n.js";
import { initDialogLlamas } from "./dialog-llamas.js";
import { settleAppConfirm } from "./dialogs.js";
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
import { $, api, escapeHtml, markPageState } from "./utils.js";

const TABS = ["controller", "llama", "security", "diag"];

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
  refreshSecurity();

  refreshAll();
  setInterval(refreshAll, 30000);
});
