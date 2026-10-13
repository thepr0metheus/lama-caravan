// How a consumer reaches the caravan, as the kanban's clients panel shows it (2026-10-07).
//
// Every consumer goes to one address — the entry, https://caravan-api.…/v1 — with its
// own key, and the caravan finds it by the key (caravan/proxy/entry.py). A row says
// what a consumer has: a key (its last four characters, the way a token is shown),
// whether its old port is still open, and when it last called. What it lacks comes
// with the one action that gives it: a key — which closes the old port in the same
// step, no keyless window (the operator's word) — or closing the port of a consumer
// that had a key already. The address itself is the controller's word
// (ConsumerAddress, caravan/admin/proxy_entry.py): the board does not build one of its own.
import { appConfirm, appPrompt } from "./dialogs.js";
import { t } from "./i18n.js";
import { setTopology, topology } from "./state.js";
import { renderTopology } from "./topology-render.js";
import { api, copyText, escapeHtml, toast } from "./utils.js";

export class ConsumerAccess {
  // The entry's port offered when it has none: the top of the proxies' range, where the
  // entry has stood on the controller's machine since 1.3.442.
  static ENTRY_PORT = 23999;

  constructor({ call = api, confirm = appConfirm, ask = appPrompt, notify = toast, copy = copyText,
    apply = (top) => { setTopology(top); renderTopology(); }, now = () => Date.now() } = {}) {
    this.call = call;
    this.confirm = confirm;
    this.ask = ask;
    this.notify = notify;
    this.copy = copy;
    this.apply = apply;
    this.now = now;
  }

  // When the consumer last called: the time today, the day before that; nothing when
  // there is no request on record — not "never", which the board cannot know.
  seenHtml(at) {
    const sec = Number(at) || 0;
    if (!sec) return "";
    const when = new Date(sec * 1000), today = new Date(this.now());
    const same = when.toDateString() === today.toDateString();
    const text = same ? when.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
      : when.toLocaleDateString([], { day: "numeric", month: "short" });
    return `<span class="cv-in-seen" title="${escapeHtml(t("consumerSeenTitle"))}">· ${escapeHtml(text)}</span>`;
  }

  // One route's line in a consumer's row: its key, where it calls, and the one action
  // it is missing. `p` is a board proxy (topology.proxies): keyTail, portClosed, port.
  lineHtml(p) {
    const port = escapeHtml(String(p.port));
    const seen = this.seenHtml(p.lastRequestAt);
    const tail = String(p.keyTail || "");
    if (!tail) {
      // In the alarm colour only where the ports have no door: the consumer then cannot get in
      // at all. Elsewhere an open port without a key is how consumers have always called, and
      // red read as a fault that was none.
      const stuck = topology?.portsReachable === false;
      return `<span class="cv-in-key none${stuck ? "" : " quiet"}" data-t="kanban-consumer-key" data-t-state="none">${escapeHtml(t("consumerNoKey"))}</span>`
        + `<span class="cv-in-port-num">:${port}</span>${seen}`
        + `<button class="cv-in-act" type="button" data-cv-port-key="${port}" data-t="kanban-consumer-give-key">${escapeHtml(t("consumerGiveKey"))}</button>`;
    }
    const key = `<span class="cv-in-key" data-t="kanban-consumer-key" data-t-state="${p.portClosed ? "entry" : "open"}"`
      + ` title="${escapeHtml(t("consumerKeyTitle"))}">🔑 …${escapeHtml(tail)}</span>`;
    if (p.portClosed) {
      return `${key}<span class="cv-in-access entry">${escapeHtml(t("consumerEntryOnly"))}</span>${seen}`
        + `<button class="cv-in-act quiet" type="button" data-cv-port-reopen="${port}" data-t="kanban-consumer-reopen"`
        + ` title="${escapeHtml(t("consumerReopenTitle", { port: String(p.port) }))}" aria-label="${escapeHtml(t("consumerReopenTitle", { port: String(p.port) }))}">↺</button>`;
    }
    return `${key}<span class="cv-in-access open">${escapeHtml(t("consumerPortOpen", { port: String(p.port) }))}</span>${seen}`
      + `<button class="cv-in-act" type="button" data-cv-port-close="${port}" data-t="kanban-consumer-close">${escapeHtml(t("consumerClosePort"))}</button>`;
  }

  // The panel's line about the entry: the address every consumer with a key may call,
  // with copy and change — or why there is none, with the way to set it up. The entry used to
  // be settable only through the API, and "The entry is off" led nowhere (2026-10-08). "No
  // address" is two cases: the entry is off, or it listens where only this machine reaches it
  // and has no public name (topology.portsReachable === false).
  entryHtml(entry) {
    const url = String(entry?.url || "");
    const port = Number(entry?.port || 0);
    // ✕ wherever the entry has a port. Turning it off used to be an empty port in the second
    // window of ✎, which nobody found (the owner, 2026-10-11).
    const off = port ? `<button class="cv-in-act quiet" type="button" data-cv-entry-off data-t="kanban-entry-off"`
      + ` title="${escapeHtml(t("consumerEntryTurnOff"))}" aria-label="${escapeHtml(t("consumerEntryTurnOff"))}">✕</button>` : "";
    if (!url) {
      // Why it is worth setting up, said under the line (the owner, 2026-10-11): "The entry is
      // off" alone does not tell a first-time operator what the entry is for.
      return `<div class="cv-entry off" data-t="kanban-entry" data-t-state="${port ? "nameless" : "off"}" title="${escapeHtml(t("consumerEntryOffTitle"))}">`
        + `<span>${escapeHtml(port ? t("consumerEntryNoName", { port: String(port) }) : t("consumerEntryOff"))}</span>`
        + `<button class="cv-in-act" type="button" data-cv-entry-setup data-t="kanban-entry-setup">${escapeHtml(t("consumerEntrySetup"))}</button>${off}`
        + `<small class="cv-entry-why" data-t="kanban-entry-why">${escapeHtml(t("consumerEntryWhy"))}</small></div>`;
    }
    const shown = url.replace(/^https?:\/\//, "");
    // The port, when the address does not already say it: the reverse proxy must lead the
    // public name to it, and it was shown only in the second window of ✎ (the owner, 2026-10-11).
    const portShown = port && !shown.includes(`:${port}`)
      ? `<span class="cv-entry-port" data-t="kanban-entry-port" title="${escapeHtml(t("consumerEntryPortTitle", { port: String(port) }))}">`
        + `${escapeHtml(t("consumerEntryPort", { port: String(port) }))}</span>` : "";
    return `<div class="cv-entry" data-t="kanban-entry" data-t-state="on" title="${escapeHtml(t("consumerEntryTitle"))}">`
      + `<span class="cv-entry-url">${escapeHtml(shown)}</span>${portShown}`
      + `<button class="cv-in-act quiet" type="button" data-cv-entry-copy data-t="kanban-entry-copy"`
      + ` title="${escapeHtml(t("consumerCopyEntry"))}" aria-label="${escapeHtml(t("consumerCopyEntry"))}">⧉</button>`
      + `<button class="cv-in-act quiet" type="button" data-cv-entry-setup data-t="kanban-entry-setup"`
      + ` title="${escapeHtml(t("consumerEntryEdit"))}" aria-label="${escapeHtml(t("consumerEntryEdit"))}">✎</button>${off}</div>`;
  }

  // The public address offered for the entry: the board's own name with "-api" — the two names
  // the operator chose (2026-10-07): caravan.… for the board, caravan-api.… for the consumers.
  // A board opened by its IP has no name to offer.
  static suggestedAddress(hostname) {
    const host = String(hostname || "");
    if (!host.includes(".") || /^[\d.]+$/.test(host) || host.includes(":")) return "";
    const [first, ...rest] = host.split(".");
    return `https://${first}-api.${rest.join(".")}/v1`;
  }

  // The entry's public address, then its port — asked one after the other; the controller
  // opens the listener by itself (EntrySettings). The address first: it is what consumers are
  // given, and where the ports have no door it is the only way in. An empty port turns the
  // entry off (the controller refuses while a port is closed, and says which).
  async setupEntry(hostname = globalThis.location?.hostname) {
    const entry = topology?.entry || {};
    // The question is each window's title: a title of its own ("Entry for keys") took its place,
    // and the window no longer said whether it wanted the address or the port.
    const url = await this.ask(t("entryAddressAsk"), { text: t("entryAddressText"),
      value: String(entry.publicUrl || ""), placeholder: ConsumerAccess.suggestedAddress(hostname) });
    if (url === null) return null;
    const port = await this.ask(t("entryPortAsk"), { text: t("entryPortText"),
      value: entry.port ? String(entry.port) : "", placeholder: String(ConsumerAccess.ENTRY_PORT) });
    if (port === null) return null;
    let res;
    try {
      res = await this.call("/api/agent-proxy-entry", { method: "POST",
        body: JSON.stringify({ port: String(port).trim() ? Number(String(port).trim()) : 0, publicUrl: String(url).trim() }) });
    } catch (err) {
      this.notify(err.message);
      return null;
    }
    const top = await this.call("/api/topology").catch(() => null);
    if (top) this.apply(top);
    this.notify(res?.port ? t("entrySaved", { port: String(res.port), url: String(res.publicUrl || "") || "—" }) : t("consumerEntryOff"));
    return res;
  }

  // "✕": the entry off — its port closes and its address stops answering; asked first. The
  // controller refuses while a client calls only through the entry and names it (EntrySettings):
  // the board does not count the clients a second time.
  async turnOffEntry() {
    const port = Number(topology?.entry?.port || 0);
    if (!port) return null;
    const sure = await this.confirm(t("entryOffText", { port: String(port) }),
      { title: t("entryOffAsk"), danger: true, confirmLabel: t("entryOffConfirm") });
    if (!sure) return null;
    let res;
    try {
      res = await this.call("/api/agent-proxy-entry", { method: "POST", body: JSON.stringify({ port: 0, publicUrl: "" }) });
    } catch (err) {
      this.notify(err.message);
      return null;
    }
    const top = await this.call("/api/topology").catch(() => null);
    if (top) this.apply(top);
    this.notify(t("consumerEntryOff"));
    return res;
  }

  route(port) {
    return (topology?.proxies || []).find((p) => Number(p.port) === Number(port)) || null;
  }

  name(port) {
    const p = this.route(port);
    return String(p?.label || "").replace(/\s+(primary|fallback)$/i, "").trim() || `:${port}`;
  }

  // "Give a key": the controller makes it and closes the old port in the same step; the
  // window shows the key once beside the address to give the consumer, and copies it on the
  // operator's word. With the entry off there is nowhere to send the consumer: it says so.
  async giveKey(port) {
    const name = this.name(port);
    const address = String(topology?.entry?.url || "");
    if (!address) {
      // A key works only through the entry: the entry first, then the key — the press used to
      // end in "the entry is off" with no way to turn it on.
      this.notify(t("entryNeedsSetupFirst"));
      const set = await this.setupEntry();
      if (!set || !String(topology?.entry?.url || "")) return null;
      return this.giveKey(port);
    }
    const sure = await this.confirm(t("consumerGiveKeyText", { name, port: String(port), address }),
      { title: t("consumerGiveKeyTitle", { name }), danger: true, confirmLabel: t("consumerGiveKey") });
    if (!sure) return null;
    let res;
    try {
      res = await this.call("/api/agent-proxies/route-key", { method: "POST", body: JSON.stringify({ port: Number(port) }) });
    } catch (err) {
      this.notify(err.message);
      return null;
    }
    if (res?.topology) this.apply(res.topology);
    const copy = await this.confirm(t("consumerKeyGivenText", { name, key: String(res?.key || ""), address: res?.entryUrl || address }),
      { title: t("consumerKeyGivenTitle", { name }), danger: false, confirmLabel: t("consumerCopyKey"), cancelLabel: t("consumerDone") });
    if (copy && res?.key) this.notify((await this.copy(res.key)) ? t("consumerKeyCopied") : res.key);
    return res;
  }

  // "Close port": the consumer then reaches the caravan only at the entry with its key.
  // The question names both, since a consumer still calling the port loses its way in.
  async closePort(port) {
    const name = this.name(port);
    const address = String(topology?.entry?.url || "");
    const sure = await this.confirm(t("consumerCloseText", { name, port: String(port), address }),
      { title: t("consumerCloseTitle", { port: String(port) }), danger: true, confirmLabel: t("consumerClosePort") });
    if (!sure) return null;
    return this.policy(port, true, t("consumerClosed", { port: String(port) }));
  }

  // "↺": the port listens again — the way back for a consumer that had to keep it.
  async reopenPort(port) {
    return this.policy(port, false, t("consumerReopened", { port: String(port) }));
  }

  async policy(port, closed, said) {
    try {
      const res = await this.call("/api/agent-proxies/route-policy", { method: "POST",
        body: JSON.stringify({ port: Number(port), portClosed: closed }) });
      this.notify(said);
      const top = await this.call("/api/topology");
      if (top) this.apply(top);
      return res;
    } catch (err) {
      this.notify(err.message);
      return null;
    }
  }

  async copyEntry() {
    const url = String(topology?.entry?.url || "");
    if (!url) return false;
    const copied = await this.copy(url);
    this.notify(copied ? t("consumerEntryCopied") : url);
    return copied;
  }
}

export const CONSUMER_ACCESS = new ConsumerAccess();
