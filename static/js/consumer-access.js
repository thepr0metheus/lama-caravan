// How a consumer reaches the caravan, as Routing's clients panel shows it (2026-10-07).
//
// Every consumer goes to one address — the entry, https://caravan-api.…/v1 — with its
// own key, and the caravan finds it by the key (rust/crates/proxy/src/front.rs). A row says
// what a consumer has: a key (its last four characters, the way a token is shown), and
// when it last called. No port of its own: the proxy listens on the entry alone, and the
// ways to give a key to an old port, close it and open it again left with them (the owner,
// 2026-11-02). The address itself is the controller's word
// (ConsumerAddress, rust/crates/admin/src/proxies/entry_settings.rs): the board does not build one of its own.
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

  // One route's line in a consumer's row: its key and when it called. `p` is a board proxy
  // (topology.proxies): keyTail, port.
  lineHtml(p) {
    const seen = this.seenHtml(p.lastRequestAt);
    const tail = String(p.keyTail || "");
    if (!tail) {
      // In the alarm colour only where the ports have no door: the consumer then cannot get in
      // at all. Elsewhere an open port without a key is how consumers have always called, and
      // red read as a fault that was none.
      const stuck = topology?.portsReachable === false;
      return `<span class="cv-in-key none${stuck ? "" : " quiet"}" data-t="routing-consumer-key" data-t-state="none">${escapeHtml(t("consumerNoKey"))}</span>`
        + `<span class="cv-in-port-num">:${escapeHtml(String(p.port))}</span>${seen}`;
    }
    const key = `<span class="cv-in-key" data-t="routing-consumer-key" data-t-state="entry"`
      + ` title="${escapeHtml(t("consumerKeyTitle"))}">🔑 …${escapeHtml(tail)}</span>`;
    return `${key}<span class="cv-in-access entry">${escapeHtml(t("consumerEntryOnly"))}</span>${seen}`;
  }

  // The panel's line about the entry: the address every consumer with a key may call,
  // with copy and change — or why there is none, with the way to set it up. The entry used to
  // be settable only through the API, and "The entry is off" led nowhere (2026-10-08). "No
  // address" is two cases: the entry is off, or it listens where only this machine reaches it
  // and has no public name (topology.portsReachable === false).
  entryHtml(entry, { stays = false } = {}) {
    const url = String(entry?.url || "");
    const port = Number(entry?.port || 0);
    // ✕ wherever the entry has a port. Turning it off used to be an empty port in the second
    // window of ✎, which nobody found (the owner, 2026-10-11). None while the built-in client is
    // there (`stays`, 2026-10-27): it is not deleted and calls only through the entry, so the
    // controller refuses to close it.
    const off = port && !stays ? `<button class="cv-in-act quiet" type="button" data-cv-entry-off data-t="routing-entry-off"`
      + ` title="${escapeHtml(t("consumerEntryTurnOff"))}" aria-label="${escapeHtml(t("consumerEntryTurnOff"))}">✕</button>` : "";
    if (!url) {
      // Why it is worth setting up, said under the line (the owner, 2026-10-11): "The entry is
      // off" alone does not tell a first-time operator what the entry is for.
      return `<div class="cv-entry off" data-t="routing-entry" data-t-state="${port ? "nameless" : "off"}" title="${escapeHtml(t("consumerEntryOffTitle"))}">`
        + `<span>${escapeHtml(port ? t("consumerEntryNoName", { port: String(port) }) : t("consumerEntryOff"))}</span>`
        + `<button class="cv-in-act" type="button" data-cv-entry-setup data-t="routing-entry-setup">${escapeHtml(t("consumerEntrySetup"))}</button>${off}`
        + `<small class="cv-entry-why" data-t="routing-entry-why">${escapeHtml(t("consumerEntryWhy"))}</small></div>`;
    }
    const shown = url.replace(/^https?:\/\//, "");
    // The port, when the address does not already say it: the reverse proxy must lead the
    // public name to it, and it was shown only in the second window of ✎ (the owner, 2026-10-11).
    const portShown = port && !shown.includes(`:${port}`)
      ? `<span class="cv-entry-port" data-t="routing-entry-port" title="${escapeHtml(t("consumerEntryPortTitle", { port: String(port) }))}">`
        + `${escapeHtml(t("consumerEntryPort", { port: String(port) }))}</span>` : "";
    return `<div class="cv-entry" data-t="routing-entry" data-t-state="on" title="${escapeHtml(t("consumerEntryTitle"))}">`
      + `<span class="cv-entry-url">${escapeHtml(shown)}</span>${portShown}`
      + `<button class="cv-in-act quiet" type="button" data-cv-entry-copy data-t="routing-entry-copy"`
      + ` title="${escapeHtml(t("consumerCopyEntry"))}" aria-label="${escapeHtml(t("consumerCopyEntry"))}">⧉</button>`
      + `<button class="cv-in-act quiet" type="button" data-cv-entry-setup data-t="routing-entry-setup"`
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

  async copyEntry() {
    const url = String(topology?.entry?.url || "");
    if (!url) return false;
    const copied = await this.copy(url);
    this.notify(copied ? t("consumerEntryCopied") : url);
    return copied;
  }
}

export const CONSUMER_ACCESS = new ConsumerAccess();
