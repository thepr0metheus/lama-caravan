// The consumers of the entry on the board: a name, its own key and the set of models it calls
// (the owner, 2026-10-11: the caravan speaks the OpenAI API as a company's gateway does;
// 2026-10-12: one cable goes on from a client, to its set, drawn in Routing).
//
// A consumer calls one address with its key; `GET /v1/models` lists the pools of its set by name
// and a request's `model` picks one (caravan/proxy/entry.py). The board makes it with a name,
// shows the key once beside the address and the models, and afterwards only the key's last four
// characters. A lost key is replaced, never shown again. Its set is the controller's reading
// (`set`, `setName`, `models`, caravan/common/entry_models.py). The card does not name it (the
// owner, 2026-10-12): Routing's card names the sets, and the client's cable goes there. It
// carries the client's recent requests instead, and says out loud when no cable leads anywhere.
import { appConfirm, appPrompt } from "./dialogs.js";
import { t } from "./i18n.js";
import { CONSUMER_ACCESS } from "./consumer-access.js";
import { setTopology, topology } from "./state.js";
import { topologyProxyActivity, topologyStateHealthClasses } from "./topology-activity.js";
import { renderTopology } from "./topology-render.js";
import { api, copyText, escapeHtml, toast } from "./utils.js";

export class ConsumerCards {
  constructor({ call = api, confirm = appConfirm, ask = appPrompt, notify = toast,
    copy = copyText, access = null, apply = (top) => { setTopology(top); renderTopology(); } } = {}) {
    this.call = call;
    this.confirm = confirm;
    this.ask = ask;
    this.notify = notify;
    this.copy = copy;
    this._access = access;
    this.apply = apply;
  }

  // The entry's own desk (consumer-access.js), read when it is used: the two modules and the
  // board's renderer import one another, and a value taken at load could still be unset.
  get access() {
    return this._access || CONSUMER_ACCESS;
  }

  // The consumers in the topology — the routes of kind "consumer" — in the operator's order (1.3.503:
  // carried by the grip in Routing, kept by the controller — caravan/admin/board_layout.py,
  // ClientOrder): the ones the order names first, in its order, then the rest by name, as before
  // there was an order.
  static of(top) {
    const order = (top?.layout?.clientOrder || []).map(Number);
    const rank = (p) => { const at = order.indexOf(Number(p.port)); return at < 0 ? Infinity : at; };
    return (top?.proxies || []).filter((p) => p.kind === "consumer")
      .sort((a, b) => (rank(a) - rank(b)) || String(a.label || "").localeCompare(String(b.label || "")));
  }

  consumer(port) {
    return ConsumerCards.of(topology).find((p) => Number(p.port) === Number(port)) || null;
  }

  // A client no cable leads anywhere, in the alarm colour: every request of its key is refused. A
  // topology that says nothing of its set (`set` absent) is said as not known, not drawn as none.
  // A client with a cable has no line here: its card shows its requests (activityHtml).
  setHtml(p) {
    if (p.set === undefined || p.set === null) {
      return `<span class="consumer-models unknown" data-t="consumer-set" data-t-state="unknown">${escapeHtml(t("consumerSetUnknown"))}</span>`;
    }
    if (!p.set) return `<span class="consumer-models none" data-t="consumer-set" data-t-state="none">${escapeHtml(t("consumerSetNone"))}</span>`;
    return `<span class="consumer-models" data-t="consumer-set" data-t-state="cabled"><span class="consumer-model">${escapeHtml(String(p.setName || p.set))}</span></span>`;
  }

  // The card lights while the client's request runs, as an agent's row does, and its cable leaves
  // from the handle on its right (cables.js) to Routing, where its set stands. A client with no
  // set has no cable, and no handle to draw one from. One line says who it is — its name, its key's last four characters,
  // when it last called — with its three actions at the end, quiet until the card is pointed at or
  // holds the focus (the owner, 2026-10-12: as clean as Routing's card, with nothing lost); under
  // it, its requests.
  cardHtml(p) {
    const port = escapeHtml(String(p.port));
    const name = escapeHtml(String(p.label || ""));
    const tail = String(p.keyTail || "");
    const paused = ["paused", "drain"].includes(String(p.mode || "open"));
    const id = escapeHtml(String(p.id || ""));
    const lit = topologyStateHealthClasses(topologyProxyActivity(p));
    const goes = Boolean(p.set);
    return `<article class="topology-card consumer-card${paused ? " paused" : ""}${lit ? ` ${lit}` : ""}" data-t="board-consumer-card" data-t-id="${port}"
      data-topology-proxy="1" data-proxy-id="${id}">
      ${goes ? `<span class="topology-handle output consumer-out" data-topology-proxy-output="1" data-proxy-id="${id}" aria-hidden="true"></span>` : ""}
      <div class="consumer-head">
        <strong class="consumer-name">${name}</strong>
        <span class="consumer-key" data-t="consumer-key" title="${escapeHtml(t("consumerKeyTitle"))}">🔑 …${escapeHtml(tail)}</span>${this.access.seenHtml(p.lastRequestAt)}
        <span class="consumer-acts">
          <button class="consumer-act quiet" type="button" data-consumer-key="${port}" data-t="consumer-new-key">${escapeHtml(t("consumerNewKey"))}</button>
          <button class="consumer-act quiet" type="button" data-consumer-rename="${port}" data-t="consumer-rename"
            title="${escapeHtml(t("consumerRename"))}" aria-label="${escapeHtml(t("consumerRename"))}">✎</button>
          <button class="consumer-act quiet consumer-del" type="button" data-consumer-delete="${port}" data-t="consumer-delete"
            title="${escapeHtml(t("consumerDelete"))}" aria-label="${escapeHtml(t("consumerDelete"))}">✕</button>
        </span>
      </div>
      ${goes ? this.activityHtml(p) : `<div class="consumer-line">${this.setHtml(p)}</div>`}
    </article>`;
  }

  // The client's recent requests, one row of the activity chart on its own card (the owner,
  // 2026-10-12: the strip under the clients said the same, apart from them). charts.js
  // drawClientActivity draws it by the client's name — the name the requests carry; a click opens
  // every client's, ⤢ (topology-dnd.js binds [data-open-route-activity]).
  activityHtml(p) {
    return `<canvas class="consumer-activity" data-consumer-activity="${escapeHtml(String(p.label || ""))}" data-open-route-activity`
      + ` data-t="consumer-activity" data-t-id="${escapeHtml(String(p.port))}" width="320" height="16"`
      + ` title="${escapeHtml(t("consumerActivityTitle"))}"></canvas>`;
  }

  // The lane's top: the address every consumer is given, with copy and change.
  laneHtml(top) {
    const cards = ConsumerCards.of(top).map((p) => this.cardHtml(p)).join("");
    return `<div class="consumer-entry">${this.access.entryHtml(top?.entry)}</div>${cards}`;
  }

  // ＋ — a name, then the key once. The entry first: a consumer has no other way in. Its set comes
  // with a cable in Routing.
  async create() {
    if (!String(topology?.entry?.url || "")) {
      this.notify(t("entryNeedsSetupFirst"));
      const set = await this.access.setupEntry();
      if (!set || !String(topology?.entry?.url || "")) return null;
    }
    const raw = await this.ask(t("consumerNameAsk"), { text: t("consumerNameText"), placeholder: "Hermes" });
    const name = String(raw ?? "").trim();
    if (!name) return null;
    let res;
    try {
      res = await this.call("/api/consumers/create", { method: "POST", body: JSON.stringify({ name }) });
    } catch (err) {
      this.notify(err.message);
      return null;
    }
    if (res?.topology) this.apply(res.topology);
    await this.showKey(res);
    return res;
  }

  // The key, this once, with the two other values the consumer needs: the address and the
  // models its key calls — its set's, or none yet. "Copy the key" copies it; closing the window
  // loses it for good.
  async showKey(res) {
    const mine = this.consumer(res?.port);
    const model = (mine?.models || []).length ? mine.models.join(", ") : t("consumerSetNone");
    const copy = await this.confirm(t("consumerKeyShownText", { name: String(res?.name || ""), key: String(res?.key || ""),
      address: String(res?.entryUrl || topology?.entry?.url || ""), model }),
    { title: t("consumerKeyShownTitle", { name: String(res?.name || "") }), danger: false,
      confirmLabel: t("consumerCopyKey"), cancelLabel: t("consumerDone") });
    if (copy && res?.key) this.notify((await this.copy(res.key)) ? t("consumerKeyCopied") : res.key);
  }

  // A new key: the old one stops working in the same write, so the window says it first.
  async newKey(port) {
    const p = this.consumer(port);
    if (!p) return null;
    const sure = await this.confirm(t("consumerNewKeyText", { name: p.label }),
      { title: t("consumerNewKeyTitle", { name: p.label }), danger: true, confirmLabel: t("consumerNewKey") });
    if (!sure) return null;
    const res = await this.send("/api/consumers/key", { port: Number(port) }, "");
    if (res) await this.showKey(res);
    return res;
  }

  async rename(port) {
    const p = this.consumer(port);
    if (!p) return null;
    const raw = await this.ask(t("consumerRename"), { value: String(p.label || "") });
    const name = String(raw ?? "").trim();
    if (!name || name === p.label) return null;
    return this.send("/api/agent-proxies/route-policy", { port: Number(port), label: name }, t("consumerRenamed", { name }), true);
  }

  async remove(port) {
    const p = this.consumer(port);
    if (!p) return null;
    const sure = await this.confirm(t("consumerDeleteText", { name: p.label }),
      { title: t("consumerDeleteTitle", { name: p.label }), danger: true, confirmLabel: t("deleteAction") });
    if (!sure) return null;
    return this.send("/api/agent-proxies/route-delete", { port: Number(port) }, t("consumerDeleted", { name: p.label }));
  }

  // One request and the board that follows it: the answer's topology, or a fresh read for a
  // door that answers none.
  async send(path, body, said, fetchTopology = false) {
    let res;
    try {
      res = await this.call(path, { method: "POST", body: JSON.stringify(body) });
    } catch (err) {
      this.notify(err.message);
      return null;
    }
    const top = res?.topology || (fetchTopology ? await this.call("/api/topology").catch(() => null) : null);
    if (top) this.apply(top);
    if (said) this.notify(said);
    return res;
  }

  // The lane's buttons, bound once on the lane: its cards are drawn anew on every render.
  bind(lane) {
    if (!lane || lane.dataset.consumersBound) return;
    lane.dataset.consumersBound = "1";
    lane.addEventListener("click", (e) => {
      const btn = e.target.closest?.("[data-consumer-key],[data-consumer-rename],[data-consumer-delete],"
        + "[data-cv-entry-setup],[data-cv-entry-copy],[data-cv-entry-off]");
      if (!btn) return;
      e.stopPropagation();
      if (btn.hasAttribute("data-cv-entry-setup")) this.access.setupEntry();
      else if (btn.hasAttribute("data-cv-entry-copy")) this.access.copyEntry();
      else if (btn.hasAttribute("data-cv-entry-off")) this.access.turnOffEntry();
      else if (btn.dataset.consumerKey) this.newKey(btn.dataset.consumerKey);
      else if (btn.dataset.consumerRename) this.rename(btn.dataset.consumerRename);
      else this.remove(btn.dataset.consumerDelete);
    });
  }
}

export const CONSUMER_CARDS = new ConsumerCards();
