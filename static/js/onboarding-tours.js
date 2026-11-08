// Tour definitions for the main board (index), a machine's page, the cell editor (the tr- modal)
// and the standalone Routing page. Strings live in onboarding-strings.js, every language
// (scripts/check_tour_i18n.py).
import { BOARD_VIEW } from "./board-view.js";
import { LANGS, messages, onLanguageLoaded } from "./i18n-data.js";
import { lang, setLang, t } from "./i18n.js";
import { autoStartOnce, createTour, initTourButtons } from "./onboarding.js";
import { TOUR_STRINGS } from "./onboarding-strings.js";

// Merge tour strings into each language table as it arrives. Not a one-shot
// loop any more: tables load on demand, so at import time only English exists
// and a later language would have got the tour in English forever.
onLanguageLoaded((code, table) => {
  const dict = TOUR_STRINGS[code];
  if (dict) Object.assign(table, dict);
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
    // A step stands on a card of its section: the machines' on a machine's card. The pools stand in Routing (2026-10-12): its
    // card's step tells. A cell's life and a new cell are the machine's page's (machineSteps): the main board draws no cell.
    { anchor: "#topologyLlamaServers .node-card", title: t("tourIxServersT"), body: t("tourIxServersB") },
    { anchor: "[data-t=\"header-pages\"]", title: t("tourIxModelsT"), body: t("tourIxModelsB") },
    { anchor: "#usageStatsBtn", title: t("tourIxStatsT"), body: t("tourIxStatsB") },
    { anchor: "#topologyRequestHistoryBtn", title: t("tourIxHistoryT"), body: t("tourIxHistoryB") },
    { anchor: ".monitor-drawer", title: t("tourIxMonitorT"), body: t("tourIxMonitorB") },
    { center: true, title: t("tourIxDoneT"), body: t("tourIxDoneB") },
  ];
}

// A machine's page (BoardView, /machine?host=…; the owner, 2026-10-27: "check the tour on this page"): steps on its own parts.
// It ran the main board's tour — clients and Routing it does not have, and a ring around the whole page.
function machineSteps() {
  return [
    { center: true, title: t("tourMcWelcomeT"), body: t("tourMcWelcomeB"), onRender: langPicker },
    { anchor: ".machine-tools", title: t("tourMcToolsT"), body: t("tourMcToolsB") },
    { anchor: "[data-machine-map]", title: t("tourMcMapT"), body: t("tourMcMapB") },
    { anchor: "[data-t=\"machine-chosen\"]", title: t("tourMcChosenT"), body: t("tourMcChosenB") },
    { anchor: "[data-t=\"machine-models\"]", title: t("tourMcModelsT"), body: t("tourMcModelsB") },
    { anchor: "[data-t=\"machine-add\"]", title: t("tourMcAddT"), body: t("tourMcAddB") },
    { anchor: "[data-t=\"machine-side-engines\"]", title: t("tourMcEnginesT"), body: t("tourMcEnginesB") },
    { anchor: "[data-t=\"machine-side-disk\"]", title: t("tourMcDiskT"), body: t("tourMcDiskB") },
    { anchor: "[data-t=\"machine-side-incidents\"]", title: t("tourMcIncidentsT"), body: t("tourMcIncidentsB") },
    { anchor: "[data-t=\"machine-side-activity\"]", title: t("tourMcActivityT"), body: t("tourMcActivityB") },
    { center: true, title: t("tourMcDoneT"), body: t("tourMcDoneB") },
  ];
}

// The editor's steps stand on what the form shows: a model's select is hidden behind its picker, and a pair's behind its
// switch, so their steps stand on their rows; the command is llama.cpp's preview or the other runners' — the one shown
// (onboarding.js takes the first visible match). On the selects themselves, three steps never showed (2026-10-27).
function configSteps(pfx) {
  const form = "#llamaRemoteEditForm";
  const startBtn = "#llamaRemoteEditStart";
  return [
    { anchor: `${form} .cell-kind-toggle`, title: t("tourCfgKindT"), body: t("tourCfgKindB") },
    { anchor: `${form} .model-file-field`, title: t("tourCfgModelT"), body: t("tourCfgModelB") },
    { anchor: `${form} .companion-field:has(#${pfx}-MMPROJ_FILE)`, title: t("tourCfgMmprojT"), body: t("tourCfgMmprojB") },
    { anchor: `${form} .companion-field:has(#${pfx}-SPEC_DRAFT_MODEL_FILE)`, title: t("tourCfgSpecT"), body: t("tourCfgSpecB") },
    { anchor: `#${pfx}-modelInsight`, title: t("tourCfgInsightT"), body: t("tourCfgInsightB") },
    { anchor: `#${pfx}-computeTarget`, title: t("tourCfgComputeT"), body: t("tourCfgComputeB") },
    { anchor: `${form} .advanced-tab-bar`, title: t("tourCfgTabsT"), body: t("tourCfgTabsB") },
    { anchor: `#${pfx}-dynamicFields`, title: t("tourCfgFieldsT"), body: t("tourCfgFieldsB") },
    { anchor: `#${pfx}-asideVramBar`, title: t("tourCfgVramT"), body: t("tourCfgVramB") },
    { anchor: `#${pfx}-previewCmdline, #${pfx}-cmdPreview`, title: t("tourCfgCmdT"), body: t("tourCfgCmdB") },
    { anchor: `#${pfx}-backups`, title: t("tourCfgBackupsT"), body: t("tourCfgBackupsB") },
    { anchor: startBtn, title: t("tourCfgStartT"), body: t("tourCfgStartB") },
  ];
}

// Routing is three columns (pool-board.js; the owner, 2026-10-12, and since 1.3.675 without sets): one step for each, «Напрямую»
// on the top of the pools' column, and the models' queue at the head of the last (1.3.663).
function routingSteps() {
  return [
    { center: true, title: t("tourKbWelcomeT"), body: t("tourKbWelcomeB"), onRender: langPicker },
    { anchor: "[data-t='pb-clients']", title: t("tourKbClientsT"), body: t("tourKbClientsB") },
    { anchor: "[data-t='pb-direct']", title: t("tourKbDirectT"), body: t("tourKbDirectB") },
    { anchor: "[data-t='pb-pools']", title: t("tourKbPoolsT"), body: t("tourKbPoolsB") },
    { anchor: "[data-t='pb-models']", title: t("tourKbModelsT"), body: t("tourKbModelsB") },
    { anchor: "[data-t='pb-queue-settings']", title: t("tourKbQueueT"), body: t("tourKbQueueB") },
  ];
}

/** Every tour by its page, for the tests that hold each step to what its page draws (scripts/test_js_onboarding_tours.py). */
export const TOURS = { index: indexSteps, machine: machineSteps, config: () => configSteps("tr"), routing: routingSteps };

function currentSteps() {
  const trOpen = document.getElementById("llamaRemoteEditOverlay")?.hidden === false;
  if (trOpen) return configSteps("tr");
  if (window.ROUTER_STANDALONE) return routingSteps();
  if (BOARD_VIEW.isMachine) return machineSteps();
  return indexSteps();
}

function startTour() {
  createTour({ steps: currentSteps, labels }).start();
}

export function initOnboarding() {
  initTourButtons({ title: () => t("tourBtnTitle"), onClick: startTour });
  const pageKey = window.ROUTER_STANDALONE ? "routing" : BOARD_VIEW.isMachine ? "machine" : "index";
  const contentReady = window.ROUTER_STANDALONE
    ? () => !document.getElementById("appLoader") && !!document.querySelector("[data-pb-root]")
    : BOARD_VIEW.isMachine
      ? () => !document.getElementById("appLoader") && !!document.querySelector("[data-machine-head]")
      : () => !document.getElementById("appLoader") && !!document.querySelector(".topology-board");
  autoStartOnce(pageKey, contentReady, () => {
    // Don't interrupt if the user already opened something.
    if (document.querySelector(".ob-root")) return;
    startTour();
  });
  watchEditorFirstOpen();
}

// The cell editor has its own detailed tour — auto-run it the FIRST time
// the editor modal opens (the header ? button is hidden behind the modal,
// so discoverability needs this nudge; afterwards the in-modal ? re-runs it).
function watchEditorFirstOpen() {
  const KEY = "caravanTourSeen:config";
  if (localStorage.getItem(KEY)) return;
  const overlays = ["llamaRemoteEditOverlay"]
    .map((id) => document.getElementById(id)).filter(Boolean);
  if (!overlays.length) return;
  const obs = new MutationObserver(() => {
    if (localStorage.getItem(KEY)) { obs.disconnect(); return; }
    if (!overlays.some((el) => el.hidden === false)) return;
    localStorage.setItem(KEY, "1");
    obs.disconnect();
    // Give the form a beat to render its fields so more steps have anchors.
    // That beat is also a window: someone who starts editing inside it has
    // moved past needing a tour, and the overlay would steal their click.
    // Listeners arm HERE — after the opening click's pointerdown — so the
    // click that opened the editor cannot cancel its own nudge.
    let interacted = false;
    const note = () => { interacted = true; unhook(); };
    const unhook = () => {
      document.removeEventListener("pointerdown", note, true);
      document.removeEventListener("keydown", note, true);
    };
    document.addEventListener("pointerdown", note, true);
    document.addEventListener("keydown", note, true);
    setTimeout(() => {
      unhook();
      if (!interacted && !document.querySelector(".ob-root")) startTour();
    }, 900);
  });
  overlays.forEach((el) => obs.observe(el, { attributes: true, attributeFilter: ["hidden"] }));
}
