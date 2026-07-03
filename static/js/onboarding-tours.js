// Tour definitions for the board (index), the llama.cpp config editor
// (te-/tr- modals) and the standalone kanban page. Strings live in
// i18n-data.js (en/ru; the rest falls back to English via t()).
import { LANGS, messages } from "./i18n-data.js";
import { lang, setLang, t } from "./i18n.js";
import { autoStartOnce, createTour, initTourButtons } from "./onboarding.js";
import { TOUR_STRINGS } from "./onboarding-strings.js";

// Merge tour strings into the shared dictionary for every language present.
Object.entries(TOUR_STRINGS).forEach(([code, dict]) => {
  if (messages[code]) Object.assign(messages[code], dict);
});

// Interface-language picker embedded into the welcome step: switches the
// whole app language (setLang) and re-renders the tour in place.
function langPicker(body, api) {
  const wrap = document.createElement("div");
  wrap.className = "ob-langs";
  wrap.innerHTML = `<div class="ob-langs-head">${t("tourLangPick")}</div>`
    + `<div class="ob-langs-grid">`
    + LANGS.map((l) => `<button type="button" class="ob-lang${l.code === lang ? " selected" : ""}"`
      + ` data-ob-lang="${l.code}">${l.emoji} ${l.label}</button>`).join("")
    + `</div>`;
  wrap.addEventListener("click", (ev) => {
    const btn = ev.target.closest("[data-ob-lang]");
    if (!btn) return;
    setLang(btn.dataset.obLang);
    api.rerender();
  });
  body.appendChild(wrap);
}

function labels() {
  return { next: t("tourNext"), back: t("tourBack"), done: t("tourDone"), skip: t("tourSkip") };
}

function indexSteps() {
  return [
    { center: true, title: t("tourIxWelcomeT"), body: t("tourIxWelcomeB"), onRender: langPicker },
    { center: true, title: t("tourIxWhyT"), body: t("tourIxWhyB") },
    { anchor: ".topology-board", title: t("tourIxBoardT"), body: t("tourIxBoardB") },
    { anchor: "#topologyClients", title: t("tourIxClientsT"), body: t("tourIxClientsB") },
    { anchor: "#topologyProxies", title: t("tourIxProxiesT"), body: t("tourIxProxiesB") },
    { anchor: "#topologyLlamaServers", title: t("tourIxServersT"), body: t("tourIxServersB") },
    { anchor: "#topologyLlamaServers .node-server:not(.ghost-server)", title: t("tourIxCellLifeT"), body: t("tourIxCellLifeB") },
    { anchor: "[data-node-reserve]", title: t("tourIxCellNewT"), body: t("tourIxCellNewB") },
    { anchor: "#topologyModelsBar", title: t("tourIxModelsT"), body: t("tourIxModelsB") },
    { anchor: "#topologyCloudProviders", title: t("tourIxCloudT"), body: t("tourIxCloudB") },
    { anchor: "#usageStatsBtn", title: t("tourIxStatsT"), body: t("tourIxStatsB") },
    { anchor: "#topologyRequestHistoryBtn", title: t("tourIxHistoryT"), body: t("tourIxHistoryB") },
    { anchor: ".monitor-drawer", title: t("tourIxMonitorT"), body: t("tourIxMonitorB") },
    { center: true, title: t("tourIxDoneT"), body: t("tourIxDoneB") },
  ];
}

function configSteps(pfx) {
  const form = pfx === "te" ? "#topologyLlamaEditForm" : "#llamaRemoteEditForm";
  const startBtn = pfx === "te" ? "#topologyLlamaEditSaveRestart" : "#llamaRemoteEditStart";
  return [
    { anchor: `${form} .cell-kind-toggle`, title: t("tourCfgKindT"), body: t("tourCfgKindB") },
    { anchor: `#${pfx}-MODEL_FILE`, title: t("tourCfgModelT"), body: t("tourCfgModelB") },
    { anchor: `#${pfx}-MMPROJ_FILE`, title: t("tourCfgMmprojT"), body: t("tourCfgMmprojB") },
    { anchor: `#${pfx}-SPEC_DRAFT_MODEL_FILE`, title: t("tourCfgSpecT"), body: t("tourCfgSpecB") },
    { anchor: `#${pfx}-modelInsight`, title: t("tourCfgInsightT"), body: t("tourCfgInsightB") },
    { anchor: `#${pfx}-computeTarget`, title: t("tourCfgComputeT"), body: t("tourCfgComputeB") },
    { anchor: `${form} .advanced-tab-bar`, title: t("tourCfgTabsT"), body: t("tourCfgTabsB") },
    { anchor: `#${pfx}-dynamicFields`, title: t("tourCfgFieldsT"), body: t("tourCfgFieldsB") },
    { anchor: `#${pfx}-asideVramBar`, title: t("tourCfgVramT"), body: t("tourCfgVramB") },
    { anchor: `#${pfx}-cmdPreview`, title: t("tourCfgCmdT"), body: t("tourCfgCmdB") },
    { anchor: `#${pfx}-backups`, title: t("tourCfgBackupsT"), body: t("tourCfgBackupsB") },
    { anchor: startBtn, title: t("tourCfgStartT"), body: t("tourCfgStartB") },
  ];
}

function kanbanSteps() {
  return [
    { center: true, title: t("tourKbWelcomeT"), body: t("tourKbWelcomeB"), onRender: langPicker },
    { anchor: "[data-cv-viewport]", title: t("tourKbCanvasT"), body: t("tourKbCanvasB") },
    { anchor: ".cv-palette-btn", title: t("tourKbNodesT"), body: t("tourKbNodesB") },
    { anchor: ".rw-head-standalone", title: t("tourKbHeadT"), body: t("tourKbHeadB") },
  ];
}

function currentSteps() {
  const teOpen = document.getElementById("topologyLlamaEditOverlay")?.hidden === false;
  const trOpen = document.getElementById("llamaRemoteEditOverlay")?.hidden === false;
  if (teOpen) return configSteps("te");
  if (trOpen) return configSteps("tr");
  if (window.ROUTER_STANDALONE) return kanbanSteps();
  return indexSteps();
}

function startTour() {
  createTour({ steps: currentSteps, labels }).start();
}

export function initOnboarding() {
  initTourButtons({ title: () => t("tourBtnTitle"), onClick: startTour });
  const pageKey = window.ROUTER_STANDALONE ? "kanban" : "index";
  const contentReady = window.ROUTER_STANDALONE
    ? () => !document.getElementById("appLoader") && !!document.querySelector("[data-cv-viewport]")
    : () => !document.getElementById("appLoader") && !!document.querySelector(".topology-board");
  autoStartOnce(pageKey, contentReady, () => {
    // Don't interrupt if the user already opened something.
    if (document.querySelector(".ob-root")) return;
    startTour();
  });
  watchEditorFirstOpen();
}

// The cell editor has its own detailed tour — auto-run it the FIRST time
// either editor modal opens (the header ? button is hidden behind the modal,
// so discoverability needs this nudge; afterwards the in-modal ? re-runs it).
function watchEditorFirstOpen() {
  const KEY = "caravanTourSeen:config";
  if (localStorage.getItem(KEY)) return;
  const overlays = ["topologyLlamaEditOverlay", "llamaRemoteEditOverlay"]
    .map((id) => document.getElementById(id)).filter(Boolean);
  if (!overlays.length) return;
  const obs = new MutationObserver(() => {
    if (localStorage.getItem(KEY)) { obs.disconnect(); return; }
    if (!overlays.some((el) => el.hidden === false)) return;
    localStorage.setItem(KEY, "1");
    obs.disconnect();
    // Give the form a beat to render its fields so more steps have anchors.
    setTimeout(() => { if (!document.querySelector(".ob-root")) startTour(); }, 900);
  });
  overlays.forEach((el) => obs.observe(el, { attributes: true, attributeFilter: ["hidden"] }));
}
