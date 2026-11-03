// The consumers of the entry on the board: a name and its own key (the owner, 2026-10-11: the caravan
// speaks the OpenAI API as a company's gateway does; 2026-10-12: one cable goes on from a client to
// Routing).
//
// A consumer calls one address with its key; `GET /v1/models` lists every pool and every model that
// runs, but what is blocked for the client, and a request's `model` picks one (rust/crates/proxy/src/front.rs,
// rust/crates/rules/src/entry_models.rs — the owner, 2026-10-27: "every client we make has every model and
// every pool"). The board makes it with a name, shows the key once beside the address and the models,
// and afterwards only the key's last four characters. A lost key is replaced, never shown again. What
// is blocked for it is set on its card in Routing (pool-board.js); this card carries the client's
// recent requests.
import { appConfirm, appPrompt } from "./dialogs.js";
import { t } from "./i18n.js";
import { CONSUMER_ACCESS } from "./consumer-access.js";
import { EntryClients } from "./entry-clients.js";
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
    // The rows that show how their program is connected, by port: closed unless asked (it took 315 px of a client nobody connected),
    // open by itself on a client just made.
    this.howto = new Set();
    // The clients made here since the page opened: their key was shown when they were made, and a second "give a key" would replace
    // the one just pasted into the program.
    this.keyShown = new Set();
  }

  // The entry's own desk (consumer-access.js), read when it is used: the two modules and the
  // board's renderer import one another, and a value taken at load could still be unset.
  get access() {
    return this._access || CONSUMER_ACCESS;
  }

  // The consumers in the topology — the routes of kind "consumer" — in the operator's order (1.3.503:
  // carried by the grip in Routing, kept by the controller — rust/crates/admin/src/board_layout.rs,
  // ClientOrder): the ones the order names first, in its order, then the rest by name, as before
  // there was an order.
  static of(top) {
    const order = (top?.layout?.clientOrder || []).map(Number);
    const rank = (p) => { const at = order.indexOf(Number(p.port)); return at < 0 ? Infinity : at; };
    // The built-in clients stand first, in their kinds' order, whatever the order (the owner, 2026-10-27: "at the top of the
    // clients"). Two clients that are no built-in one rank equal there (Infinity - Infinity is NaN, which goes on to the next).
    const own = (a, b) => EntryClients.rank(a) - EntryClients.rank(b);
    return (top?.proxies || []).filter((p) => p.kind === "consumer")
      .sort((a, b) => own(a, b) || (rank(a) - rank(b)) || String(a.label || "").localeCompare(String(b.label || "")));
  }

  consumer(port) {
    return ConsumerCards.of(topology).find((p) => Number(p.port) === Number(port)) || null;
  }

  // The card lights while the client's request runs, as an agent's row does, and its cable leaves
  // from the handle on its right (cables.js) to Routing, where the pools and models it calls stand.
  // One line says who it is — its name, its key's last four characters,
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
    return `<article class="topology-card consumer-card${paused ? " paused" : ""}${lit ? ` ${lit}` : ""}" data-t="board-consumer-card" data-t-id="${port}"
      data-topology-proxy="1" data-proxy-id="${id}">
      <span class="topology-handle output consumer-out" data-topology-proxy-output="1" data-proxy-id="${id}" aria-hidden="true"></span>
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
      ${this.activityHtml(p)}
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

  // The lane's top: the address every consumer is given, with copy and change; the built-in clients under it, then a line, then
  // the other clients (the owner, 2026-10-27: "at the top of the clients, under a dividing line"). With a built-in client the
  // entry has no off switch: the client is not deleted, and it calls only through the entry. Under the line, when no client
  // stands there and no client of the old kind follows (`others`), what the place is for.
  laneHtml(top, { others = false } = {}) {
    const all = ConsumerCards.of(top);
    const own = all.filter((p) => EntryClients.builtin(p)), rest = all.filter((p) => !EntryClients.builtin(p));
    const entry = `<div class="consumer-entry">${this.access.entryHtml(top?.entry, { stays: own.length > 0 })}</div>`;
    if (!own.length) return entry + rest.map((p) => this.cardHtml(p)).join("");
    const empty = rest.length || others ? "" : `<p class="consumer-empty" data-t="consumer-others-none">${escapeHtml(t("consumerOthersNone"))}</p>`;
    const blocks = Object.keys(EntryClients.KINDS).map((kind) => this.blockHtml(kind, own.filter((p) => EntryClients.kind(p) === kind), top));
    return entry + blocks.join("")
      + `<div class="consumer-divider" role="separator" data-t="consumer-divider"><span>${escapeHtml(t("consumerOthers"))}</span></div>`
      + rest.map((p) => this.cardHtml(p)).join("") + empty;
  }

  // The words of a built-in client's card that name its program, by its kind (EntryClients.KINDS): each a t() of its own, so
  // scripts/check_i18n_calls.py finds every key.
  static WORDS = {
    "open-webui": () => ({ title: t("consumerBuiltinTitle"), none: t("consumerLiveNone") }),
    opencode: () => ({ title: t("consumerOcBuiltinTitle"), none: t("consumerOcLiveNone") }),
  };

  static words(p) {
    return (ConsumerCards.WORDS[EntryClients.kind(p)] || ConsumerCards.WORDS["open-webui"])();
  }

  // A built-in client's card: its name, what it is, its key and when it last called, with a new key and a new name, and a ✕ while
  // another of its kind stands (the owner: "no need to delete it, and no need to turn it off"; 2026-10-30: "as many as you like"); how
  // many models it sees; then its requests — or, until
  // its first one, how its program is connected to it, and the way to move an older client of that program in.
  builtinHtml(p, top, { live = true, file = true } = {}) {
    const entry = top?.entry;
    const port = escapeHtml(String(p.port));
    const id = escapeHtml(String(p.id || ""));
    const lit = topologyStateHealthClasses(topologyProxyActivity(p));
    const fresh = !Number(p.lastRequestAt);
    const kind = EntryClients.kind(p);
    // The last of its kind stays: the caravan would make it again at its next start (BuiltinClient.audit).
    const sole = ConsumerCards.of(top).filter((c) => EntryClients.kind(c) === kind).length < 2;
    const sees = EntryClients.sees(p, top?.entryModels);
    const open = this.howto.has(String(p.port));
    const connect = kind === "opencode" ? this.opencodeHtml(p, entry) : this.connectHtml(p, entry);
    const howto = `<button class="consumer-act consumer-howto" type="button" data-consumer-howto="${port}" data-t="consumer-howto" aria-expanded="${open}">`
      + `${escapeHtml(t(open ? "consumerHowToHide" : "consumerHowTo"))}</button>`;
    return `<article class="topology-card consumer-card builtin${lit ? ` ${lit}` : ""}" data-t="board-consumer-card" data-t-id="${port}" data-t-state="builtin"
      data-builtin="${escapeHtml(kind)}" data-topology-proxy="1" data-proxy-id="${id}">
      <span class="topology-handle output consumer-out" data-topology-proxy-output="1" data-proxy-id="${id}" aria-hidden="true"></span>
      <div class="consumer-head">
        <strong class="consumer-name">${escapeHtml(String(p.label || ""))}</strong>
        <span class="consumer-key" data-t="consumer-key" title="${escapeHtml(t("consumerKeyTitle"))}">🔑 …${escapeHtml(String(p.keyTail || ""))}</span>${this.access.seenHtml(p.lastRequestAt)}
        <span class="consumer-acts">
          <button class="consumer-act quiet" type="button" data-consumer-key="${port}" data-t="consumer-new-key">${escapeHtml(t("consumerNewKey"))}</button>
          <button class="consumer-act quiet" type="button" data-consumer-rename="${port}" data-t="consumer-rename"
            title="${escapeHtml(t("consumerRename"))}" aria-label="${escapeHtml(t("consumerRename"))}">✎</button>${sole ? "" : `
          <button class="consumer-act quiet consumer-del" type="button" data-consumer-delete="${port}" data-t="consumer-delete"
            title="${escapeHtml(t("consumerDelete"))}" aria-label="${escapeHtml(t("consumerDelete"))}">✕</button>`}
        </span>
      </div>
      ${live ? `<div class="consumer-line" data-t="consumer-live" data-t-state="${sees}">${ConsumerCards.liveHtml(p, top?.entryModels)}</div>` : ""}
      ${fresh ? `<div class="consumer-line">${howto}</div>${open ? connect : ""}` : this.activityHtml(p)}
      ${file && kind === "opencode" ? `<div class="consumer-line consumer-oc-file">${this.opencodeFileHtml(p, entry)}</div>` : ""}
    </article>`;
  }

  // All the clients of one program in one block (the owner, 2026-11-01: "opencode clients can be many: put them in one block and
  // create them from it; Open WebUI the same, but one, without the plus"): the program's name, how many, what they all see, the file
  // they all take, and the ＋; under it a row a client, each with its key, its ✕ and its cable; at the foot of a kind of many, the way
  // to move an older client in. What the clients do not share is said on their rows.
  blockHtml(kind, clients, top) {
    if (!clients.length) return "";
    const { name, many, config } = EntryClients.KINDS[kind];
    const all = top?.entryModels;
    const oneLive = new Set(clients.map((p) => ConsumerCards.seesText(p, all))).size === 1;
    const file = config ? this.blockFile(clients, top?.entry) : { html: "", rows: false };
    const add = many ? `<button class="consumer-act consumer-block-add" type="button" data-client-add-kind="${escapeHtml(kind)}" data-t="client-add-kind" data-t-id="${escapeHtml(kind)}"`
      + ` title="${escapeHtml(t("consumerAddOpencode"))}" aria-label="${escapeHtml(t("consumerAddOpencode"))}">＋</button>` : "";
    return `<section class="consumer-block" data-t="consumer-block" data-t-id="${escapeHtml(kind)}">
      <div class="consumer-block-head">
        <strong class="consumer-block-name">${escapeHtml(name)}</strong>
        ${many ? `<span class="consumer-block-count" data-t="consumer-block-count">${clients.length}</span>` : ""}
        <span class="consumer-chip" data-t="consumer-builtin" title="${escapeHtml(ConsumerCards.words(clients[0]).title)}">${escapeHtml(t("consumerBuiltinChip"))}</span>
        ${oneLive ? `<span data-t="consumer-live" data-t-state="${EntryClients.sees(clients[0], all)}">${ConsumerCards.liveHtml(clients[0], all)}</span>` : ""}
        <span class="consumer-block-tools">${file.html}${add}</span>
      </div>
      ${clients.map((p) => this.builtinHtml(p, top, { live: !oneLive, file: file.rows })).join("")}
    </section>`;
  }

  // opencode.json in the block's head when every client of it would get the same one (the file carries no key). Their lists differ
  // when something is closed to one of them; not there, the entry off or the models not read — each row says so in its own words.
  blockFile(clients, entry) {
    const lists = new Set(clients.map((p) => JSON.stringify(Array.isArray(p.offer) ? p.offer.map((m) => m.id) : null)));
    const p = clients[0];
    if (lists.size > 1 || !String(entry?.url || "") || !Array.isArray(p.offer)) return { html: "", rows: true };
    const words = `${t("consumerOcConfigCopy")} · ${t("consumerOcConfigModels", { n: String(p.offer.length) })} · ${t("consumerOcConfigWhere")}`;
    return { rows: false, html: `<button class="consumer-act" type="button" data-consumer-oc-config="${escapeHtml(String(p.port))}" data-t="consumer-oc-config"`
      + ` title="${escapeHtml(words)}">⧉ opencode.json</button>` };
  }

  // How many models the built-in client sees (EntryClients.sees), as Routing's card says it: "Sees all 20", "Sees 17 of 20". Not
  // read — said as not known, never as none.
  static liveHtml(p, all) {
    const state = EntryClients.sees(p, all);
    if (state === "unknown") return `<span class="consumer-live unknown">${escapeHtml(t("consumerLiveUnknown"))}</span>`;
    if (state === "none") return `<span class="consumer-live none">${escapeHtml(ConsumerCards.words(p).none)}</span>`;
    return `<span class="consumer-live">${escapeHtml(ConsumerCards.seesText(p, all))}</span>`;
  }

  // "Sees all 20", "Sees 17 of 20", "Sees 0 of 20": a client's count against what a client blocked for nothing sees — the words of
  // the main board's built-in card and of Routing's every card. Only "all" says all: a client that sees nothing is not drawn as
  // one that sees everything. Not read — not known.
  static seesText(p, all) {
    const state = EntryClients.sees(p, all);
    if (state === "unknown") return t("pbClientModelsUnknown");
    return state === "all" ? t("pbClientSeesAll", { all: String(all.length) })
      : t("pbClientSeesSome", { n: String(p.models.length), all: String(all.length) });
  }

  // How Open WebUI is connected, until it first calls: where in Open WebUI, the entry's address with copy, and its key — given
  // here, shown once (the key the caravan made it with was shown to nobody). An entry that is off says so: the line above opens it.
  connectHtml(p, entry) {
    const url = String(entry?.url || "");
    const step = (n, html) => `<li><span class="consumer-step" aria-hidden="true">${n}</span><span class="consumer-step-body">${html}</span></li>`;
    const address = url
      ? `<span class="consumer-step-label">${escapeHtml(t("consumerConnectAddress"))}</span><code class="consumer-url">${escapeHtml(url)}</code>`
        + `<button class="consumer-act" type="button" data-cv-entry-copy data-t="consumer-connect-copy">${escapeHtml(t("consumerCopyEntry"))}</button>`
      : `<span class="consumer-step-label">${escapeHtml(t("consumerConnectAddress"))}</span><span class="consumer-live none">${escapeHtml(t("consumerConnectNoEntry"))}</span>`;
    const key = `<span class="consumer-step-label">${escapeHtml(t("consumerConnectKey"))}</span>`
      + `<button class="consumer-act give" type="button" data-consumer-first-key="${escapeHtml(String(p.port))}" data-t="consumer-give-key">${escapeHtml(t("consumerConnectGiveKey"))}</button>`
      + `<span class="consumer-step-note">${escapeHtml(t("consumerConnectOnce"))}</span>`;
    return `<div class="consumer-connect" data-t="consumer-connect">
      <b>${escapeHtml(t("consumerConnectTitle"))}</b>
      <ol class="consumer-steps">${step(1, escapeHtml(t("consumerConnectWhere")))}${step(2, address)}${step(3, key)}</ol>
      <small class="consumer-step-note">${escapeHtml(t("consumerConnectVoice"))}</small>
    </div>`;
  }

  // How opencode is connected, until it first calls (the owner, 2026-10-27: "let it work the same way"). opencode reads no model
  // list from the entry: its models are written in opencode.json, which the card gives whole — the address, and every model the
  // controller offers it (`offer`, rust/crates/rules/src/entry_models.rs EntryModels.offer). Its key is given once, here, and typed into
  // opencode by /connect: the file carries no key.
  opencodeHtml(p, entry) {
    const port = escapeHtml(String(p.port));
    const step = (n, html) => `<li><span class="consumer-step" aria-hidden="true">${n}</span><span class="consumer-step-body">${html}</span></li>`;
    const key = `<span class="consumer-step-label">${escapeHtml(t("consumerConnectKey"))}</span>`
      + (this.keyShown.has(String(p.port))
        ? `<span class="consumer-step-note">${escapeHtml(t("consumerKeyWasShown"))} · ${escapeHtml(t("consumerOcKeyWhere"))}</span>`
        : `<button class="consumer-act give" type="button" data-consumer-first-key="${port}" data-t="consumer-give-key">${escapeHtml(t("consumerConnectGiveKey"))}</button>`
          + `<span class="consumer-step-note">${escapeHtml(t("consumerConnectOnce"))} · ${escapeHtml(t("consumerOcKeyWhere"))}</span>`);
    return `<div class="consumer-connect" data-t="consumer-connect">
      <b>${escapeHtml(t("consumerOcTitle"))}</b>
      <ol class="consumer-steps">${step(1, key)}${step(2, this.opencodeFileHtml(p, entry))}</ol>
    </div>`;
  }

  // opencode.json's copy, with how many models it holds: in the steps until opencode first calls, and on its card ever after —
  // the file changes when a model is added, and opencode does not learn of it by itself. None while the entry is off; not known
  // while the models were not read.
  opencodeFileHtml(p, entry) {
    const url = String(entry?.url || "");
    const offer = Array.isArray(p.offer) ? p.offer : null;
    const label = `<span class="consumer-step-label">${escapeHtml(t("consumerOcConfig"))}</span>`;
    if (!url) return `${label}<span class="consumer-live none">${escapeHtml(t("consumerConnectNoEntry"))}</span>`;
    if (!offer) return `${label}<span class="consumer-live unknown">${escapeHtml(t("consumerOcConfigUnknown"))}</span>`;
    return label + `<button class="consumer-act" type="button" data-consumer-oc-config="${escapeHtml(String(p.port))}" data-t="consumer-oc-config">${escapeHtml(t("consumerOcConfigCopy"))}</button>`
      + `<span class="consumer-step-note">${escapeHtml(t("consumerOcConfigModels", { n: String(offer.length) }))} · ${escapeHtml(t("consumerOcConfigWhere"))}</span>`;
  }

  // opencode.json for the built-in opencode client (opencode's own format — https://opencode.ai/docs/providers: a provider of
  // @ai-sdk/openai-compatible at the entry's address, its models by the names the entry calls them), or null while the entry is
  // off or the models are not known. No `limit`: opencode's file wants the output's limit with the window's, and the caravan does
  // not know a model's — a guessed figure is worse than none.
  static opencodeConfig(p, url) {
    if (!url || !Array.isArray(p?.offer)) return null;
    return {
      $schema: "https://opencode.ai/config.json",
      provider: { caravan: { npm: "@ai-sdk/openai-compatible", name: "Caravan", options: { baseURL: String(url) },
        models: Object.fromEntries(p.offer.map((m) => [String(m.id), { name: String(m.name || m.id) }])) } },
    };
  }

  async copyOpencodeConfig(port) {
    const p = this.consumer(port);
    const config = ConsumerCards.opencodeConfig(p, topology?.entry?.url);
    if (!config) return false;
    const text = JSON.stringify(config, null, 2);
    const copied = await this.copy(text);
    this.notify(copied ? t("consumerOcConfigCopied", { n: String(p.offer.length) }) : text);
    return copied;
  }

  // ＋ — a name, then the key once. The entry first: a consumer has no other way in. It sees every
  // pool and every model that runs at once (the owner, 2026-10-27: "everything, at once"); what it
  // must not call is closed on its card in Routing.
  async create() {
    if (!(await this.entryReady())) return null;
    const raw = await this.ask(t("consumerNameAsk"), { text: t("consumerNameText"), placeholder: "Hermes" });
    const name = String(raw ?? "").trim();
    if (!name) return null;
    return this.made({ name });
  }

  // The ＋ of a program's block (the owner, 2026-11-01): a name that tells this client from the others, or none, for the kind's name
  // numbered; its row opens on how the program is connected to it. Cancelled, nothing is made.
  async createOf(kind) {
    if (!(await this.entryReady())) return null;
    const raw = await this.ask(t("consumerNameAsk"), { text: t("consumerKindNameText"), placeholder: `${EntryClients.KINDS[kind]?.name || ""} m2` });
    if (raw === null || raw === undefined) return null;
    const res = await this.made({ kind, name: String(raw).trim() });
    if (res?.port) {
      this.howto.add(String(res.port));
      this.keyShown.add(String(res.port));
      this.apply(topology);
    }
    return res;
  }

  async entryReady() {
    if (String(topology?.entry?.url || "")) return true;
    this.notify(t("entryNeedsSetupFirst"));
    const set = await this.access.setupEntry();
    return !!set && !!String(topology?.entry?.url || "");
  }

  async made(body) {
    let res;
    try {
      res = await this.call("/api/consumers/create", { method: "POST", body: JSON.stringify(body) });
    } catch (err) {
      this.notify(err.message);
      return null;
    }
    if (res?.topology) this.apply(res.topology);
    await this.showKey(res);
    return res;
  }

  // The key, this once, with the two other values the consumer needs: the address and the
  // models its key calls — or that none runs yet. "Copy the key" copies it; closing the window
  // loses it for good.
  async showKey(res) {
    const mine = this.consumer(res?.port);
    const model = (mine?.models || []).length ? mine.models.join(", ") : t("consumerNoModels");
    const copy = await this.confirm(t("consumerKeyShownText", { name: String(res?.name || ""), key: String(res?.key || ""),
      address: String(res?.entryUrl || topology?.entry?.url || ""), model }),
    { title: t("consumerKeyShownTitle", { name: String(res?.name || "") }), danger: false,
      confirmLabel: t("consumerCopyKey"), cancelLabel: t("consumerDone") });
    if (copy && res?.key) this.notify((await this.copy(res.key)) ? t("consumerKeyCopied") : res.key);
  }

  // The built-in client's first key, from its card's steps: the one it was made with was shown to nobody, so there is nothing
  // to lose and no window to ask first.
  async firstKey(port) {
    const res = await this.send("/api/consumers/key", { port: Number(port) }, "");
    if (res) await this.showKey(res);
    return res;
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
  // How a row's program is connected, shown or put away.
  toggleHowto(port) {
    const key = String(port);
    if (!this.howto.delete(key)) this.howto.add(key);
    this.apply(topology);
  }

  bind(lane) {
    if (!lane || lane.dataset.consumersBound) return;
    lane.dataset.consumersBound = "1";
    lane.addEventListener("click", (e) => {
      const btn = e.target.closest?.("[data-consumer-key],[data-consumer-rename],[data-consumer-delete],[data-consumer-first-key],"
        + "[data-consumer-oc-config],[data-consumer-howto],[data-client-add-kind],[data-cv-entry-setup],[data-cv-entry-copy],[data-cv-entry-off]");
      if (!btn) return;
      e.stopPropagation();
      if (btn.dataset.clientAddKind) this.createOf(btn.dataset.clientAddKind);
      else if (btn.dataset.consumerHowto) this.toggleHowto(btn.dataset.consumerHowto);
      else if (btn.hasAttribute("data-cv-entry-setup")) this.access.setupEntry();
      else if (btn.hasAttribute("data-cv-entry-copy")) this.access.copyEntry();
      else if (btn.hasAttribute("data-cv-entry-off")) this.access.turnOffEntry();
      else if (btn.dataset.consumerFirstKey) this.firstKey(btn.dataset.consumerFirstKey);
      else if (btn.dataset.consumerOcConfig) this.copyOpencodeConfig(btn.dataset.consumerOcConfig);
      else if (btn.dataset.consumerKey) this.newKey(btn.dataset.consumerKey);
      else if (btn.dataset.consumerRename) this.rename(btn.dataset.consumerRename);
      else this.remove(btn.dataset.consumerDelete);
    });
  }
}

export const CONSUMER_CARDS = new ConsumerCards();
