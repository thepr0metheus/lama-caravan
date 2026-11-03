/**
 * The live window: talk with a running cell that talks live — a stream both ways at once over the cell's own
 * WebSocket (MiniCPM-o) — from its card. The page sends the microphone as it records, and plays the cell's voice and
 * shows its words as they come. The controller passes the WebSocket on (GET /api/cell-live,
 * rust/crates/admin/src/fleet/cell_live.rs): the board is https and the cell plain http, which a secure page may not open.
 *
 * What a cell speaks there is its runner's to say (state.runners[].live.protocol); this module knows the protocols, not
 * the runners. The voice window (voice-talk.js) asks one thing at a time; this one keeps a line open.
 */
import { t } from "./i18n.js";
import { runnerRegistry } from "./llama-edit.js";
import { api, escapeHtml } from "./utils.js";
import { TalkError } from "./voice-talk.js";

/** Float samples as a stream carries them: little-endian 32-bit floats, in base64 — and back. */
export class PcmCodec {
  static toBase64(samples) {
    const f32 = Float32Array.from(samples);
    const bytes = new Uint8Array(f32.length * 4);
    const view = new DataView(bytes.buffer);
    for (let i = 0; i < f32.length; i += 1) view.setFloat32(i * 4, f32[i], true);
    let text = "";
    for (let i = 0; i < bytes.length; i += 0x8000) text += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
    return btoa(text);
  }

  /** The samples of base64 float32 little-endian; a cut last sample is dropped, not read as a number. */
  static fromBase64(text) {
    const raw = atob(String(text || ""));
    const n = Math.floor(raw.length / 4);
    const view = new DataView(new ArrayBuffer(n * 4));
    for (let i = 0; i < n * 4; i += 1) view.setUint8(i, raw.charCodeAt(i));
    const out = new Float32Array(n);
    for (let i = 0; i < n; i += 1) out[i] = view.getFloat32(i * 4, true);
    return out;
  }

  /** Samples at `from` Hz as `to` Hz, by straight lines between neighbours: down from a 48 kHz microphone, up to the
   *  card's rate for a voice. The same rate is the same samples. */
  static resample(samples, from, to) {
    if (!(from > 0 && to > 0) || from === to) return Float32Array.from(samples);
    const n = Math.floor(samples.length * to / from);
    const out = new Float32Array(n);
    for (let i = 0; i < n; i += 1) {
      const at = i * from / to;
      const a = Math.floor(at);
      const b = Math.min(samples.length - 1, a + 1);
      out[i] = samples[a] + (samples[b] - samples[a]) * (at - a);
    }
    return out;
  }
}

/** The microphone as a stream: chunks of `chunk` samples at `rate` Hz handed on as they fill, until stopped. Its world
 *  (the media devices, the AudioContext, whether the page is secure) is given to it, so a snapshot can be one. */
export class MicStream {
  constructor({ media = globalThis.navigator?.mediaDevices, Context = globalThis.AudioContext || globalThis.webkitAudioContext,
                secure = globalThis.isSecureContext === true } = {}) {
    this.media = media;
    this.Context = Context;
    this.secure = secure;
    this.stream = null;
    this.context = null;
    this.source = null;
    this.node = null;
    this.pending = new Float32Array(0);
  }

  /** The key of why the microphone cannot be had here, or "": a page of plain http gets none. */
  refusal() {
    if (!this.secure) return "talkMicNotSecure";
    if (!this.media?.getUserMedia || !this.Context) return "talkMicMissing";
    return "";
  }

  get open() { return !!this.stream; }

  /** Start the microphone; `onChunk(samples)` hears each `chunk` samples at `rate`. */
  async start(onChunk, { rate = 16000, chunk = 16000 } = {}) {
    const why = this.refusal();
    if (why) throw new TalkError(why);
    try {
      this.stream = await this.media.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
    } catch (err) {
      throw new TalkError(err?.name === "NotAllowedError" ? "talkMicDenied" : "talkMicFailed", String(err?.message || err || ""));
    }
    this.context = new this.Context();
    // Made after a click, but not in it (the talk began meanwhile): a context made outside a gesture may start
    // suspended, and a suspended one hears nothing.
    await this.context.resume?.();
    this.source = this.context.createMediaStreamSource(this.stream);
    // A script processor and not a worklet, as the voice window's recorder: a worklet is a module file of its own.
    this.node = this.context.createScriptProcessor(4096, 1, 1);
    const from = this.context.sampleRate;
    this.node.onaudioprocess = (e) => this.take(PcmCodec.resample(e.inputBuffer.getChannelData(0), from, rate), chunk, onChunk);
    this.source.connect(this.node);
    this.node.connect(this.context.destination);
  }

  /** Gather samples and hand on every whole chunk; the rest waits for the next. */
  take(samples, chunk, onChunk) {
    const all = new Float32Array(this.pending.length + samples.length);
    all.set(this.pending, 0);
    all.set(samples, this.pending.length);
    let at = 0;
    for (; at + chunk <= all.length; at += chunk) onChunk(all.slice(at, at + chunk));
    this.pending = all.slice(at);
  }

  /** Every exit lets the microphone go: a talk ended keeps no light on in the browser's bar. */
  stop() {
    try { this.node?.disconnect(); } catch { /* already gone */ }
    try { this.source?.disconnect(); } catch { /* already gone */ }
    for (const track of this.stream?.getTracks?.() || []) track.stop();
    try { this.context?.close(); } catch { /* already closed */ }
    this.stream = null;
    this.context = null;
    this.source = null;
    this.node = null;
    this.pending = new Float32Array(0);
  }
}

/** The cell's voice as it comes: chunks of samples played one after another with no gap, on one AudioContext. */
export class VoiceQueue {
  constructor({ Context = globalThis.AudioContext || globalThis.webkitAudioContext } = {}) {
    this.Context = Context;
    this.context = null;
    this.until = 0;
    this.sources = new Set();
  }

  /** Seconds of voice still to be heard. */
  get ahead() { return this.context ? Math.max(0, this.until - this.context.currentTime) : 0; }

  /** Make the player ready in the operator's click: a context made later, when the first voice comes, may stay
   *  suspended by the browser, and the voice is never heard. */
  wake() {
    if (!this.Context) return;
    this.context ||= new this.Context();
    this.context.resume?.();
  }

  push(samples, rate) {
    if (!this.Context || !samples?.length) return;
    this.context ||= new this.Context();
    const buffer = this.context.createBuffer(1, samples.length, rate);
    buffer.copyToChannel(Float32Array.from(samples), 0);
    const source = this.context.createBufferSource();
    source.buffer = buffer;
    source.connect(this.context.destination);
    const at = Math.max(this.context.currentTime + 0.05, this.until);
    source.start(at);
    this.until = at + buffer.duration;
    this.sources.add(source);
    source.onended = () => this.sources.delete(source);
  }

  /** Stop what is playing and what waits: the cell was cut off, or the window closed. */
  stop() {
    for (const source of this.sources) { try { source.stop(); } catch { /* already over */ } }
    this.sources.clear();
    this.until = 0;
  }

  close() {
    this.stop();
    try { this.context?.close(); } catch { /* already closed */ }
    this.context = null;
  }
}

/** A cell as the live window talks to it: the machine and port, the name the card shows, its runner. */
export class LiveCell {
  constructor({ hostId, port, name = "", runner = "" } = {}) {
    this.hostId = String(hostId || "");
    this.port = String(port || "");
    this.name = String(name || "");
    this.runner = String(runner || "");
  }

  /** How the runner talks live (its registry row's `live`), or null when it does not. */
  get spec() { return runnerRegistry().find((r) => r.id === this.runner)?.live || null; }

  /** The address the window opens: the board's own, as a WebSocket — the controller passes it on. */
  url(location = globalThis.location) {
    const scheme = location?.protocol === "https:" ? "wss" : "ws";
    return `${scheme}://${location?.host}/api/cell-live?hostId=${encodeURIComponent(this.hostId)}&port=${encodeURIComponent(this.port)}`;
  }

  static fromButton(b) {
    const d = b?.dataset || {};
    return new LiveCell({ hostId: d.cellLive, port: d.nodeCellPort, name: d.cellLiveName, runner: d.cellLiveRunner });
  }

  /** The card's live button: open on a running cell whose runner talks live, shut (saying why) on a stopped one, none
   *  otherwise. `running` is the card's own word. */
  buttonHtml(running) {
    if (!this.spec) return "";
    const label = `📞<span class="nab-lbl">${escapeHtml(t("liveOpen"))}</span>`;
    if (!running) {
      return `<button class="node-action-btn muted" type="button" disabled title="${escapeHtml(t("liveOpenStopped"))}">${label}</button>`;
    }
    const id = `${this.hostId}:${this.port}`;
    return `<button class="node-action-btn ok live" type="button" data-t="cell-live" data-t-id="${escapeHtml(id)}"`
      + ` data-cell-live="${escapeHtml(this.hostId)}" data-node-cell-port="${escapeHtml(this.port)}"`
      + ` data-cell-live-runner="${escapeHtml(this.runner)}" data-cell-live-name="${escapeHtml(this.name)}"`
      + ` title="${escapeHtml(t("liveOpenTitle"))}">${label}</button>`;
  }
}

/**
 * MiniCPM-o's talk on its WebSocket (llama.cpp-omni's `/backend`), as its server at the launcher's commit reads and
 * writes it (cells/run_minicpm_omni.sh):
 *  - the first message is `session.init` with the mode. The models load then — 30 to 90 seconds the first time, with
 *    no word on the way — and `session.created` says the talk has begun;
 *  - the voice goes in as base64 float32 little-endian at 16 kHz: in full duplex a second at a time, and silence too,
 *    since the model decides once a second to listen or to speak and speaks on only while the seconds keep coming;
 *    turn by turn, one utterance in one message;
 *  - its voice comes back about a second at a time, float32 at 24 kHz, in the order it is made — not by answer: a
 *    second of voice may come after the step that made it was said done;
 *  - `listen` says the model listens again; `session.closed` says why the talk ended, and the socket closes.
 * Busy with another talk — or still closing the last one — or given a first message it cannot read, the server closes
 * the socket without a word. Its base64 reader kills the server on a character outside the alphabet: btoa writes none.
 */
export class MiniCpmOmniTalk {
  static RATE_IN = 16000;
  static RATE_OUT = 24000;
  /** A second of the microphone: what the server reads at once in full duplex, and pads to whole tenths. */
  static CHUNK = 16000;
  /** The window's modes, as the server names them, the first the default. */
  static MODES = ["full_duplex", "turn_based"];

  init(mode) {
    return JSON.stringify({ type: "session.init", payload: { mode, use_tts: true } });
  }

  /** A second of the microphone, in full duplex. */
  second(samples) {
    return JSON.stringify({ type: "input.append", input: { audio: PcmCodec.toBase64(samples) } });
  }

  /** One utterance, turn by turn: the answer comes in words and in voice. */
  utterance(samples) {
    return JSON.stringify({ type: "input.append", input: { messages: [{ role: "user", content: [{ type: "audio", data: PcmCodec.toBase64(samples) }] }],
                                                           streaming: true, tts: { enabled: true } } });
  }

  /** What a message of the server says: {kind: created | text | audio | listen | done | closed | unknown | unreadable}
   *  and its words, its samples (at RATE_OUT) or its reason. */
  read(text) {
    let doc;
    try {
      doc = JSON.parse(text);
    } catch {
      return { kind: "unreadable" };
    }
    const type = String(doc?.type || "");
    if (type === "session.created") return { kind: "created", session: String(doc.session_id || "") };
    if (type === "response.output.delta") {
      if (doc.kind === "text") return { kind: "text", text: String(doc.text || "") };
      if (doc.kind === "audio") return { kind: "audio", samples: PcmCodec.fromBase64(doc.audio), rate: MiniCpmOmniTalk.RATE_OUT };
      if (doc.kind === "listen") return { kind: "listen" };
    }
    if (type === "response.done") return { kind: "done", text: String(doc.text || "") };
    if (type === "session.closed") return { kind: "closed", reason: String(doc.reason || "") };
    return { kind: "unknown", type };
  }
}

/** The protocols the window speaks, by the name a runner's `live.protocol` gives. */
export const LIVE_PROTOCOLS = { "minicpm-omni": MiniCpmOmniTalk };

/** One line of the talk: the model's words as they come (and the voice heard), or the operator's utterance. */
export class LiveLine {
  constructor(role, text = "") {
    this.role = role === "user" ? "user" : "assistant";
    this.text = text;
    this.seconds = 0;
    this.firstSound = null;
  }
}

/**
 * The live window over a cell: its phase — idle, checking, connecting, loading (the models), live, ended, failed — the
 * mode, the model's lines, and what went wrong in the window's words. Its world (the controller's API, the WebSocket,
 * the microphone, the player, the clock, the page) is given to it, so a snapshot can drive it.
 */
export class LiveWindow {
  static current = null;

  static open(cell, deps = {}) {
    LiveWindow.current?.close();
    const win = new LiveWindow(cell, deps);
    LiveWindow.current = win;
    win.mount();
    return win;
  }

  constructor(cell, { call = api, Socket = globalThis.WebSocket, mic = new MicStream(), voice = new VoiceQueue(),
                      clock = () => globalThis.performance?.now?.() ?? Date.now(), doc = globalThis.document,
                      location = globalThis.location } = {}) {
    this.cell = cell;
    this.call = call;
    this.Socket = Socket;
    this.mic = mic;
    this.voice = voice;
    this.clock = clock;
    this.doc = doc;
    this.location = location;
    const Protocol = LIVE_PROTOCOLS[cell.spec?.protocol] || null;
    this.talk = Protocol ? new Protocol() : null;
    this.modes = Protocol ? Protocol.MODES : [];
    this.mode = this.modes[0] || "";
    this.phase = "idle";
    this.lines = [];
    this.notice = null;
    this.muted = false;
    // Full duplex: whether the model listens now (it listens until it speaks); its next words begin a new line.
    this.modelListens = true;
    // Turn by turn: what the microphone gathers for the utterance, and whether an answer is awaited.
    this.utterance = null;
    this.waiting = false;
    this.sentAt = null;
    // Whether the cell said it answers (the plain GET of the talk's path), and why the talk ended when the cell said so.
    this.cellAnswers = null;
    this.closedReason = "";
    this.loadingSince = null;
    this.socket = null;
    this.root = null;
    this.onKey = (e) => { if (e.key === "Escape") this.close(); };
  }

  /** The words for a microphone that would not start: the voice window's, but a refusal of the browser points at this
   *  window's own button. */
  static micKey(err) {
    if (err?.key === "talkMicDenied") return "liveMicDenied";
    return err?.key || "talkMicFailed";
  }

  /** Say something in the window's words: {key, args}. */
  say(key, args = {}) {
    this.notice = { key, args };
    this.redraw();
  }

  /** Ask the controller whether the cell answers, then open the talk: a cell that does not answer is said, not dialled. */
  async start() {
    if (!this.talk || ["checking", "connecting", "loading", "live"].includes(this.phase)) return;
    this.notice = null;
    this.closedReason = "";
    this.lines = [];
    this.modelListens = true;
    this.muted = false;
    this.voice.wake();
    this.phase = "checking";
    this.redraw();
    let got;
    try {
      got = await this.call(`/api/cell-live?hostId=${encodeURIComponent(this.cell.hostId)}&port=${encodeURIComponent(this.cell.port)}`);
    } catch (err) {
      got = { health: { status: 0, error: String(err?.message || err) } };
    }
    if (LiveWindow.current !== this || this.phase !== "checking") return;
    const health = got?.health || {};
    this.cellAnswers = health.status >= 200 && health.status < 400;
    if (!this.cellAnswers) {
      this.phase = "failed";
      this.say("liveCellDown", { error: health.error || `HTTP ${health.status || 0}` });
      return;
    }
    this.connect();
  }

  connect() {
    this.phase = "connecting";
    this.redraw();
    const socket = new this.Socket(this.cell.url(this.location));
    this.socket = socket;
    socket.onopen = () => this.opened(socket);
    socket.onmessage = (e) => this.heard(socket, e.data);
    socket.onclose = (e) => this.ended(socket, e);
  }

  opened(socket) {
    if (socket !== this.socket) return;
    socket.send(this.talk.init(this.mode));
    this.phase = "loading";
    this.loadingSince = this.clock();
    this.redraw();
  }

  async heard(socket, data) {
    if (socket !== this.socket) return;
    const said = this.talk.read(data);
    if (said.kind === "created") {
      this.phase = "live";
      this.redraw();
      if (this.mode === "full_duplex") await this.listen();
      return;
    }
    if (said.kind === "text" && said.text) {
      this.speaking().text += said.text;
    } else if (said.kind === "audio") {
      const line = this.speaking();
      if (line.firstSound === null && this.sentAt !== null) line.firstSound = (this.clock() - this.sentAt) / 1000;
      this.voice.push(said.samples, said.rate);
    } else if (said.kind === "listen") {
      this.modelListens = true;
    } else if (said.kind === "done" && this.mode === "turn_based") {
      this.waiting = false;
      this.sentAt = null;
    } else if (said.kind === "closed") {
      this.closedReason = said.reason;
    }
    this.redraw();
  }

  /** The model's line being spoken: the last one while it speaks, a new one after it listened. */
  speaking() {
    const last = this.lines[this.lines.length - 1];
    if (last && last.role === "assistant" && !this.modelListens) return last;
    this.modelListens = false;
    const line = new LiveLine("assistant");
    this.lines.push(line);
    return line;
  }

  /** The socket closed: said by why — the cell's reason, a talk ended, a busy cell, or a door that drops WebSocket. */
  ended(socket, event) {
    if (socket !== this.socket) return;
    const before = this.phase;
    this.stopStreams();
    this.socket = null;
    if (before === "ended") return;
    if (this.closedReason) {
      this.phase = "ended";
      this.say("liveClosedBy", { reason: this.closedReason });
    } else if (before === "live") {
      this.phase = "ended";
      this.say("liveEnded");
    } else if (before === "loading" && event?.code === 1000) {
      this.phase = "failed";
      this.say("liveBusy");
    } else {
      this.phase = "failed";
      this.say(this.cellAnswers ? "liveDoorNoWs" : "liveCellDown", { error: `WebSocket ${event?.code ?? "?"}` });
    }
  }

  /** Full duplex: the microphone streams a second at a time — silence while muted, the model speaks on through it. */
  async listen() {
    try {
      await this.mic.start((samples) => this.socket?.send(this.talk.second(this.muted ? new Float32Array(samples.length) : samples)),
                           { rate: MiniCpmOmniTalk.RATE_IN, chunk: MiniCpmOmniTalk.CHUNK });
    } catch (err) {
      this.say(LiveWindow.micKey(err), { error: err?.detail || String(err?.message || err || "") });
      this.hangUp();
    }
  }

  /** Turn by turn: the first press records, the second sends what was said and waits for the answer. */
  async toggleSpeak() {
    if (this.phase !== "live" || this.mode !== "turn_based" || this.waiting) return;
    if (this.utterance) {
      // The microphone's last part-chunk is the end of what was said: it goes too.
      const tail = this.mic.pending || new Float32Array(0);
      const samples = new Float32Array(this.utterance.length + tail.length);
      samples.set(this.utterance, 0);
      samples.set(tail, this.utterance.length);
      this.utterance = null;
      this.mic.stop();
      const line = new LiveLine("user");
      line.seconds = samples.length / MiniCpmOmniTalk.RATE_IN;
      this.lines.push(line);
      this.modelListens = true;
      this.waiting = true;
      this.sentAt = this.clock();
      this.socket?.send(this.talk.utterance(samples));
      this.redraw();
      return;
    }
    this.utterance = new Float32Array(0);
    try {
      await this.mic.start((samples) => {
        if (!this.utterance) return;
        const all = new Float32Array(this.utterance.length + samples.length);
        all.set(this.utterance, 0);
        all.set(samples, this.utterance.length);
        this.utterance = all;
      }, { rate: MiniCpmOmniTalk.RATE_IN, chunk: MiniCpmOmniTalk.RATE_IN / 10 });
    } catch (err) {
      this.utterance = null;
      this.say(LiveWindow.micKey(err), { error: err?.detail || String(err?.message || err || "") });
      return;
    }
    this.redraw();
  }

  toggleMute() {
    this.muted = !this.muted;
    this.redraw();
  }

  pick(mode) {
    if (!this.modes.includes(mode) || ["checking", "connecting", "loading", "live"].includes(this.phase)) return;
    this.mode = mode;
    this.redraw();
  }

  stopStreams() {
    this.mic.stop();
    this.voice.stop();
    this.utterance = null;
    this.waiting = false;
  }

  /** End the talk from this side: the socket closes, the microphone lets go, the voice stops. */
  hangUp() {
    const socket = this.socket;
    this.socket = null;
    this.stopStreams();
    if (["checking", "connecting", "loading", "live"].includes(this.phase)) this.phase = "ended";
    try { socket?.close(1000); } catch { /* already closed */ }
    this.redraw();
  }

  /** What the window is doing, for its testers. */
  get state() {
    if (this.phase !== "live") return this.phase;
    if (this.mode === "turn_based") return this.utterance ? "recording" : this.waiting ? "waiting" : "ready";
    return this.muted ? "muted" : "live";
  }

  statusText() {
    if (this.notice) return t(this.notice.key, this.notice.args);
    if (this.phase === "checking" || this.phase === "connecting") return t("liveConnecting");
    if (this.phase === "loading") return t("liveLoading");
    if (this.phase === "live" && this.mode === "full_duplex") return t(this.modelListens === false && this.lines.length ? "liveSpeaking" : "liveListening");
    if (this.phase === "live") return t(this.waiting ? "liveWaiting" : this.utterance ? "liveRecording" : "liveReady");
    return "";
  }

  html() {
    const id = `${this.cell.hostId}:${this.cell.port}`;
    const name = this.cell.name || id;
    const close = escapeHtml(t("close"));
    const active = ["checking", "connecting", "loading", "live"].includes(this.phase);
    const head = `<div class="talk-head"><strong class="talk-name">📞 ${escapeHtml(t("liveTitle", { name }))}</strong>`
      + `<span class="talk-port">:${escapeHtml(this.cell.port)}</span>`
      + `<button type="button" class="talk-close" data-live-close="1" data-t="live-close" title="${close}" aria-label="${close}">✕</button></div>`;
    const modeKey = { full_duplex: "liveModeDuplex", turn_based: "liveModeTurns" };
    const modes = `<div class="talk-modes" role="group">${this.modes.map((m) => `<button type="button" class="talk-mode" data-live-mode="${escapeHtml(m)}"`
      + ` data-t="live-mode" data-t-id="${escapeHtml(m)}" aria-pressed="${m === this.mode}"${active ? " disabled" : ""}>${escapeHtml(t(modeKey[m] || m))}</button>`).join("")}</div>`;
    const hint = this.mode === "full_duplex" ? `<p class="live-hint">${escapeHtml(t("liveHeadphones"))}</p>` : "";
    const lines = this.lines.length
      ? this.lines.map((line, i) => {
        const who = line.role === "user" ? t("talkYou") : name;
        const words = line.role === "user" ? t("talkSeconds", { seconds: line.seconds.toFixed(1) }) : line.text;
        const sound = line.firstSound !== null ? `<div class="talk-timing">${escapeHtml(t("liveFirstSound", { seconds: line.firstSound.toFixed(1) }))}</div>` : "";
        return `<div class="talk-turn ${line.role}" data-t="live-line" data-t-id="${i}"><div class="talk-who">${escapeHtml(who)}</div>`
          + `<div class="talk-text">${escapeHtml(words)}</div>${sound}</div>`;
      }).join("")
      : `<p class="talk-empty">${escapeHtml(t(this.mode === "full_duplex" ? "liveHintDuplex" : "liveHintTurns"))}</p>`;
    const status = this.statusText();
    const failed = this.notice && (this.phase === "failed" || this.phase === "ended") ? " failed" : "";
    const statusHtml = status ? `<p class="live-status${failed}" role="status" data-t="live-status">${escapeHtml(status)}</p>` : "";
    let controls;
    if (!active) {
      controls = `<button type="button" class="talk-go" data-live-start="1" data-t="live-start"${this.talk ? "" : " disabled"}>${escapeHtml(t("liveStart"))}</button>`;
    } else if (this.mode === "turn_based") {
      const can = this.phase === "live" && !this.waiting;
      controls = `<button type="button" class="talk-go${this.utterance ? " recording" : ""}" data-live-speak="1" data-t="live-speak"`
        + ` aria-pressed="${!!this.utterance}"${can ? "" : " disabled"}>${escapeHtml(t(this.utterance ? "liveSend" : "liveSpeak"))}</button>`;
    } else {
      controls = `<button type="button" class="talk-go${this.muted ? " recording" : ""}" data-live-mute="1" data-t="live-mute"`
        + ` aria-pressed="${this.muted}"${this.phase === "live" ? "" : " disabled"}>${escapeHtml(t(this.muted ? "liveUnmute" : "liveMute"))}</button>`;
    }
    const hangUp = active ? `<button type="button" class="talk-clear" data-live-hangup="1" data-t="live-hangup">${escapeHtml(t("liveHangUp"))}</button>` : "";
    return `<div class="talk-backdrop" data-live-close="1" aria-hidden="true"></div>`
      + `<div class="talk-window live-window" role="dialog" aria-modal="true" aria-label="${escapeHtml(t("liveTitle", { name }))}"`
      + ` data-t="live-window" data-t-id="${escapeHtml(id)}" data-t-state="${this.state}">`
      + `${head}${modes}${hint}<div class="talk-turns" data-t="live-lines">${lines}</div>${statusHtml}`
      + `<div class="talk-input">${controls}${hangUp}</div></div>`;
  }

  mount() {
    if (!this.doc?.createElement) return;
    this.root = this.doc.createElement("div");
    this.root.className = "talk-overlay";
    this.root.addEventListener("click", (e) => this.onClick(e));
    this.doc.body.appendChild(this.root);
    this.doc.addEventListener("keydown", this.onKey);
    this.redraw();
  }

  redraw() {
    if (this.root) this.root.innerHTML = this.html();
  }

  onClick(e) {
    const el = e.target?.closest?.("[data-live-close],[data-live-mode],[data-live-start],[data-live-speak],[data-live-mute],[data-live-hangup]");
    if (!el) return;
    const d = el.dataset || {};
    if (d.liveClose) this.close();
    else if (d.liveMode) this.pick(d.liveMode);
    else if (d.liveStart) this.start();
    else if (d.liveSpeak) this.toggleSpeak();
    else if (d.liveMute) this.toggleMute();
    else if (d.liveHangup) this.hangUp();
  }

  close() {
    this.hangUp();
    this.voice.close();
    this.doc?.removeEventListener?.("keydown", this.onKey);
    this.root?.remove?.();
    this.root = null;
    if (LiveWindow.current === this) LiveWindow.current = null;
  }
}
