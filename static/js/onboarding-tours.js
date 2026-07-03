// Tour definitions for the board (index), the llama.cpp config editor
// (te-/tr- modals) and the standalone kanban page. Strings live in
// i18n-data.js (en/ru; the rest falls back to English via t()).
import { LANGS, messages } from "./i18n-data.js";
import { lang, setLang, t } from "./i18n.js";
import { autoStartOnce, createTour, initTourButtons } from "./onboarding.js";
import { TOUR_EN, TOUR_RU } from "./onboarding-strings.js";

// Merge tour strings into the shared dictionary (en/ru; others fall back to en).
Object.assign(messages.en, TOUR_EN);
if (messages.ru) Object.assign(messages.ru, TOUR_RU);

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
    { anchor: ".topology-board", title: t("tourIxBoardT"), body: t("tourIxBoardB") },
    { anchor: "#topologyClients", title: t("tourIxClientsT"), body: t("tourIxClientsB") },
    { anchor: "#topologyProxies", title: t("tourIxProxiesT"), body: t("tourIxProxiesB") },
    { anchor: "#topologyLlamaServers", title: t("tourIxServersT"), body: t("tourIxServersB") },
    { anchor: "#topologyModelsBar", title: t("tourIxModelsT"), body: t("tourIxModelsB") },
    { anchor: "#topologyCloudProviders", title: t("tourIxCloudT"), body: t("tourIxCloudB") },
    { anchor: "#usageStatsBtn", title: t("tourIxStatsT"), body: t("tourIxStatsB") },
    { anchor: "#topologyRequestHistoryBtn", title: t("tourIxHistoryT"), body: t("tourIxHistoryB") },
    { anchor: ".monitor-drawer", title: t("tourIxMonitorT"), body: t("tourIxMonitorB") },
    { center: true, title: t("tourIxDoneT"), body: t("tourIxDoneB") },
  ];
}

function configSteps(pfx) {
  const startBtn = pfx === "te" ? "#topologyLlamaEditSaveRestart" : "#llamaRemoteEditStart";
  return [
    { anchor: `#${pfx}-MODEL_FILE`, title: t("tourCfgModelT"), body: t("tourCfgModelB") },
    { anchor: `#${pfx}-asideVramBar`, title: t("tourCfgVramT"), body: t("tourCfgVramB") },
    { anchor: `#${pfx}-dynamicFields`, title: t("tourCfgFieldsT"), body: t("tourCfgFieldsB") },
    { anchor: `#${pfx}-cmdPreview`, title: t("tourCfgCmdT"), body: t("tourCfgCmdB") },
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
}
