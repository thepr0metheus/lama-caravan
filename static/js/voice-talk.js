/**
 * The voice window: talk to a running cell by voice or by text, from its card (the owner, 2026-10-21: run the voice
 * models from the board and talk to them somewhere, "as I talk to a new text model in Open WebUI").
 *
 * The page records the microphone into a wav itself (WavRecorder → WavFile): the cells read wav, and a recording in
 * the browser's own format (webm, ogg) is what two of the fleet's recognisers cannot read. The controller asks the
 * cell (POST /api/cell-talk, rust/crates/admin/src/fleet/cell_talk.rs): the board is https and a cell is plain http, which a page
 * may not ask — and a browser gives the microphone to a secure page only.
 *
 * What a cell can do here is its runner's to say (state.runners[].talk) and its modes' (state.talkModes): this module
 * keeps no list of runners and no paths. A cell that keeps voices (Qwen3-TTS) is asked its list through the controller
 * too, and reads a text in the voice of a sample recorded here — on the operator's word that the voice is theirs, or
 * that its owner agreed — or keeps that voice under a name, for any client of its port to ask.
 */
import { t } from "./i18n.js";
import { runnerRegistry } from "./llama-edit.js";
import { state } from "./state.js";
import { api, escapeHtml } from "./utils.js";

/** A recording as the cells read it: 16-bit PCM, mono. */
export class WavFile {
  /** The rate a recording is sent at: what every recogniser of the fleet reads, a third of a 48 kHz microphone. */
  static RATE = 16000;

  /** Float samples (-1..1) at `from` Hz as `to` Hz, each new sample the mean of the ones it covers. A rate that is
   *  not lower is kept as it is: a wav says its own rate. */
  static downsample(samples, from, to) {
    if (!(to < from)) return Float32Array.from(samples);
    const ratio = from / to;
    const out = new Float32Array(Math.floor(samples.length / ratio));
    for (let i = 0; i < out.length; i += 1) {
      const a = Math.floor(i * ratio);
      const b = Math.min(samples.length, Math.floor((i + 1) * ratio));
      let sum = 0;
      for (let j = a; j < b; j += 1) sum += samples[j];
      out[i] = b > a ? sum / (b - a) : 0;
    }
    return out;
  }

  /** The bytes of a wav of float samples at `rate`: a 44-byte header, then the samples, clipped to -1..1. */
  static encode(samples, rate) {
    const data = samples.length * 2;
    const view = new DataView(new ArrayBuffer(44 + data));
    const tag = (at, text) => { for (let i = 0; i < text.length; i += 1) view.setUint8(at + i, text.charCodeAt(i)); };
    tag(0, "RIFF"); view.setUint32(4, 36 + data, true); tag(8, "WAVE");
    tag(12, "fmt "); view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
    view.setUint32(24, rate, true); view.setUint32(28, rate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
    tag(36, "data"); view.setUint32(40, data, true);
    for (let i = 0; i < samples.length; i += 1) {
      const s = Math.max(-1, Math.min(1, samples[i]));
      view.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    }
    return new Uint8Array(view.buffer);
  }

  static base64(bytes) {
    let text = "";
    for (let i = 0; i < bytes.length; i += 0x8000) text += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
    return btoa(text);
  }
}

/** Why the window cannot have the microphone, as a key of the window's words. */
export class TalkError extends Error {
  constructor(key, detail = "") {
    super(detail || key);
    this.key = key;
    this.detail = detail;
  }
}

/** The microphone, recorded into a wav in the page: an AudioContext's samples gathered while it records. Its world
 *  (the media devices, the AudioContext, whether the page is secure) is given to it, so a snapshot can be one. */
export class WavRecorder {
  /** The longest recording: the window stops by itself after it. */
  static MAX_SECONDS = 60;

  constructor({ media = globalThis.navigator?.mediaDevices, Context = globalThis.AudioContext || globalThis.webkitAudioContext,
                secure = globalThis.isSecureContext === true } = {}) {
    this.media = media;
    this.Context = Context;
    this.secure = secure;
    this.chunks = [];
    this.stream = null;
    this.context = null;
    this.source = null;
    this.node = null;
    this.rate = 0;
  }

  /** The key of why the microphone cannot be had here, or "": named before asking — a page of plain http gets none. */
  refusal() {
    if (!this.secure) return "talkMicNotSecure";
    if (!this.media?.getUserMedia || !this.Context) return "talkMicMissing";
    return "";
  }

  get recording() { return !!this.stream; }

  /** Seconds recorded so far. */
  get seconds() {
    const samples = this.chunks.reduce((n, c) => n + c.length, 0);
    return this.rate ? samples / this.rate : 0;
  }

  async start() {
    const why = this.refusal();
    if (why) throw new TalkError(why);
    try {
      this.stream = await this.media.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
    } catch (err) {
      throw new TalkError(err?.name === "NotAllowedError" ? "talkMicDenied" : "talkMicFailed", String(err?.message || err || ""));
    }
    this.chunks = [];
    this.context = new this.Context();
    this.rate = this.context.sampleRate;
    this.source = this.context.createMediaStreamSource(this.stream);
    // A script processor and not a worklet: a worklet is a module file of its own for 20 lines of copying.
    this.node = this.context.createScriptProcessor(4096, 1, 1);
    this.node.onaudioprocess = (e) => { this.chunks.push(Float32Array.from(e.inputBuffer.getChannelData(0))); };
    this.source.connect(this.node);
    this.node.connect(this.context.destination);
  }

  /** The recording as a wav at WavFile.RATE and its length in seconds; the microphone let go. */
  stop() {
    const total = this.chunks.reduce((n, c) => n + c.length, 0);
    const samples = new Float32Array(total);
    let at = 0;
    for (const chunk of this.chunks) { samples.set(chunk, at); at += chunk.length; }
    const rate = this.rate || WavFile.RATE;
    this.release();
    return { wav: WavFile.encode(WavFile.downsample(samples, rate, WavFile.RATE), WavFile.RATE), seconds: total / rate };
  }

  /** Every exit lets the microphone go: a recording abandoned keeps no light on in the browser's bar. */
  release() {
    try { this.node?.disconnect(); } catch { /* already gone */ }
    try { this.source?.disconnect(); } catch { /* already gone */ }
    for (const track of this.stream?.getTracks?.() || []) track.stop();
    try { this.context?.close(); } catch { /* already closed */ }
    this.stream = null;
    this.context = null;
    this.source = null;
    this.node = null;
    this.chunks = [];
  }
}

/** A cell as the window talks to it: the machine and port, the name the card shows, its runner, and whether its
 *  running server said it hears (true / false; null when it did not say). */
export class TalkCell {
  constructor({ hostId, port, name = "", runner = "", hears = null } = {}) {
    this.hostId = String(hostId || "");
    this.port = String(port || "");
    this.name = String(name || "");
    this.runner = String(runner || "");
    this.hears = hears === true ? true : hears === false ? false : null;
  }

  /** How the runner talks (its registry row's `talk`), or null when it does not. */
  get spec() { return runnerRegistry().find((r) => r.id === this.runner)?.talk || null; }

  /** True for a mode with a voice in it — a recording asked or a voice answered: this window's. A typed question answered
   *  in words (text-chat) is the cell window's Talk tab (cell-chat.js); offered here it would put 🎙 on every chat cell. */
  static voiced(mode) {
    return !!mode && (mode.takes === "voice" || (Array.isArray(mode.gives) && mode.gives.includes("voice")));
  }

  /** The modes the window offers this cell: its runner's voiced ones, in the runner's order. A mode that needs a model
   *  that hears is offered only when the server said it hears — not said is not yes. A mode the page does not know
   *  (a page older than the controller) is left out: there is nothing to draw it with. */
  modes() {
    const spec = this.spec;
    if (!spec) return [];
    const table = new Map((state.talkModes || []).map((m) => [m.id, m]));
    return (spec.modes || []).map((id) => table.get(id))
      .filter((m) => TalkCell.voiced(m) && (!m.needsHearing || this.hears === true));
  }

  /** The cell a card's 🎙 button names. */
  static fromButton(b) {
    const d = b?.dataset || {};
    return new TalkCell({ hostId: d.cellTalk, port: d.nodeCellPort, name: d.cellTalkName, runner: d.cellTalkRunner,
                          hears: d.cellTalkHears === "true" ? true : d.cellTalkHears === "false" ? false : null });
  }

  /** True when a cell of this runner talks whatever its model: one of its modes needs no model that hears. A stopped
   *  llama.cpp cell says nothing of hearing, and most of its models do not. */
  get talksAlways() {
    const table = new Map((state.talkModes || []).map((m) => [m.id, m]));
    return (this.spec?.modes || []).some((id) => TalkCell.voiced(table.get(id)) && !table.get(id).needsHearing);
  }

  /** The card's 🎙: open on a running cell that can talk, shut (saying why) on a stopped cell whose runner always
   *  talks, none at all otherwise. `running` is the card's own word. */
  buttonHtml(running) {
    if (!this.spec) return "";
    const id = `${this.hostId}:${this.port}`;
    const label = `🎙<span class="nab-lbl">${escapeHtml(t("talkOpen"))}</span>`;
    if (!running) {
      return this.talksAlways
        ? `<button class="node-action-btn muted" type="button" disabled title="${escapeHtml(t("talkOpenStopped"))}">${label}</button>` : "";
    }
    if (!this.modes().length) return "";
    return `<button class="node-action-btn ok talk" type="button" data-t="cell-talk" data-t-id="${escapeHtml(id)}"`
      + ` data-cell-talk="${escapeHtml(this.hostId)}" data-node-cell-port="${escapeHtml(this.port)}"`
      + ` data-cell-talk-runner="${escapeHtml(this.runner)}" data-cell-talk-name="${escapeHtml(this.name)}"`
      + ` data-cell-talk-hears="${this.hears === null ? "" : String(this.hears)}" title="${escapeHtml(t("talkOpenTitle"))}">${label}</button>`;
  }
}

/** One message of the talk: who said it, its words, its voice (base64) and, for an answer, its time and status. */
export class TalkTurn {
  constructor({ role, text = "", audio = "", audioType = "", seconds = 0, ms = null, sound = null, error = "", mode = "" } = {}) {
    this.role = role === "assistant" ? "assistant" : "user";
    this.text = String(text || "");
    this.audio = String(audio || "");
    this.audioType = String(audioType || "");
    this.seconds = Number(seconds) || 0;
    this.ms = ms;
    this.sound = sound;
    this.error = String(error || "");
    this.mode = String(mode || "");
  }

  /** What the talk so far carries of this message: an answer that failed carries nothing — the model never said it. */
  sent() {
    if (this.role === "assistant") return this.error ? null : { role: "assistant", text: this.text };
    return { role: "user", text: this.text, audio: this.audio };
  }
}

/**
 * The window over the board, one at a time. It is its own element on the page — the board repaints its cards every
 * few seconds, and a window drawn inside one would lose its talk at the next repaint.
 */
export class TalkWindow {
  /** The window open now, or null; cleared on every way out (close). */
  static current = null;

  static open(cell, deps = {}) {
    TalkWindow.current?.close();
    const win = new TalkWindow(cell, deps);
    TalkWindow.current = win;
    win.mount();
    return win;
  }

  constructor(cell, { call = api, recorder = new WavRecorder(), clock = () => globalThis.performance?.now?.() ?? Date.now(),
                      play = TalkWindow.playAudio, doc = globalThis.document } = {}) {
    this.cell = cell;
    this.call = call;
    this.recorder = recorder;
    this.clock = clock;
    this.play = play;
    this.doc = doc;
    this.modes = cell.modes();
    this.mode = this.modes[0]?.id || "";
    this.turns = [];
    this.busy = false;
    this.notice = "";
    this.draft = "";
    this.system = cell.spec?.system || "";
    // The cell's own voices, of a runner whose cell says them (talk.asksVoices): null while they are asked, then
    // {voices, stored} or {error}. Asked when the window is up, and again after a voice is kept.
    this.asked = null;
    this.voice = this.voicesOf(this.mode)[0] || "";
    // A sample of a voice to read the text in (talk.clone): {audio, seconds}, the words it says, the operator's word
    // that the voice is theirs or its owner agreed, and the name to keep it under on the cell.
    this.sample = null;
    this.sampleText = "";
    this.consent = false;
    this.keepName = "";
    // What the microphone records now: "talk" (a message) or "sample".
    this.recordingFor = "";
    this.root = null;
    this.ticker = null;
    this.onKey = (e) => { if (e.key === "Escape") this.close(); };
  }

  /** Play a voice the cell answered; `onStart` hears the moment it is heard. */
  static playAudio(src, onStart) {
    const audio = new Audio(src);
    audio.addEventListener("playing", onStart, { once: true });
    return audio.play();
  }

  get modeRow() { return this.modes.find((m) => m.id === this.mode) || null; }

  /** The voices offered in `mode`: the runner's own there, else — of a cell that says its voices — the ones it said
   *  (its model's, then those kept on it). None while they are asked or when the cell did not say them. */
  voicesOf(mode) {
    const own = this.cell.spec?.voices?.[mode] || [];
    if (own.length || !this.cell.spec?.asksVoices || !this.asked || this.asked.error) return own;
    return [...this.asked.voices, ...this.asked.stored.map((v) => v.name)];
  }

  /** True when the window offers a sample of a voice: the mode reads a text in a sample's voice, on a cell whose runner
   *  can (talk.clone), and the cell named no voices of its own — a checkpoint that has them (Qwen3-TTS CustomVoice)
   *  refuses a sample, as vLLM-Omni says, and a sample offered there always failed (found live, 2026-10-22). Nothing is
   *  offered while the list is asked; a list the cell did not give leaves it to the runner's word. */
  get takesSample() {
    if (!(this.cell.spec?.clone && this.modeRow?.takesSample)) return false;
    if (!this.cell.spec?.asksVoices) return true;
    if (!this.asked) return false;
    return !!this.asked.error || this.asked.voices.length === 0;
  }

  /** The rule of a voice's name on the cell (the runner row's `talk.voiceName`, the controller's own). */
  get voiceName() { return new RegExp(`^(?:${this.cell.spec?.voiceName || "(?!)"})$`); }

  /** True when the sample can be kept on the cell under the name typed. */
  get canKeep() { return !this.busy && !this.recorder.recording && !!this.sample && this.consent && this.voiceName.test(this.keepName); }

  /** How many messages one request carries, the new one included (the runner's `turns`). */
  get turnsCarried() { return Math.max(1, Number(this.cell.spec?.turns) || 1); }

  /** The talk so far as it goes with a new message: the runner's last `turns - 1` of what was said. */
  history() {
    const row = this.modeRow;
    if (!row?.conversation || this.turnsCarried < 2) return [];
    return this.turns.filter((turn) => turn.mode === this.mode).map((turn) => turn.sent()).filter((sent) => sent !== null)
      .slice(-(this.turnsCarried - 1));
  }

  html() {
    const row = this.modeRow;
    const id = `${this.cell.hostId}:${this.cell.port}`;
    const close = escapeHtml(t("close"));
    const head = `<div class="talk-head"><strong class="talk-name">🎙 ${escapeHtml(t("talkTitle", { name: this.cell.name || id }))}</strong>`
      + `<span class="talk-port">:${escapeHtml(this.cell.port)}</span>`
      + `<button type="button" class="talk-close" data-talk-close="1" data-t="talk-close" title="${close}" aria-label="${close}">✕</button></div>`;
    const tabs = this.modes.length > 1
      ? `<div class="talk-modes" role="group">${this.modes.map((m) => `<button type="button" class="talk-mode" data-talk-mode="${escapeHtml(m.id)}"`
        + ` data-t="talk-mode" data-t-id="${escapeHtml(m.id)}" aria-pressed="${m.id === this.mode}"${this.busy || this.recorder.recording ? " disabled" : ""}>`
        + `${escapeHtml(t(m.labelKey))}</button>`).join("")}</div>`
      : `<div class="talk-modes"><span class="talk-mode-one" data-t="talk-mode" data-t-id="${escapeHtml(this.mode)}">${escapeHtml(row ? t(row.labelKey) : "")}</span></div>`;
    return `<div class="talk-backdrop" data-talk-close="1" aria-hidden="true"></div>`
      + `<div class="talk-window" role="dialog" aria-modal="true" aria-label="${escapeHtml(t("talkTitle", { name: this.cell.name || id }))}"`
      + ` data-t="talk-window" data-t-id="${escapeHtml(id)}" data-t-state="${this.state}">`
      + `${head}${tabs}${this.settingsHtml(row)}${this.sampleHtml()}<div class="talk-turns" data-t="talk-turns">${this.turnsHtml()}</div>`
      + `${this.notice ? `<p class="talk-notice" role="alert" data-t="talk-notice">${escapeHtml(this.notice)}</p>` : ""}`
      + `${this.inputHtml(row)}</div>`;
  }

  /** What the window is doing, for its testers: recording, waiting, or ready. */
  get state() { return this.recorder.recording ? "recording" : this.busy ? "waiting" : "ready"; }

  settingsHtml(row) {
    if (!row) return "";
    const voice = this.voiceHtml(row);
    if (!row.conversation) return voice ? `<div class="talk-settings">${voice}</div>` : "";
    const memory = this.turnsCarried < 2 ? t("talkNoMemory") : t("talkMemory", { n: String(this.turnsCarried) });
    return `<div class="talk-settings">${voice}<p class="talk-memory" data-t="talk-memory">${escapeHtml(memory)}</p>`
      + `<details class="talk-system"><summary>${escapeHtml(t("talkSystem"))}</summary>`
      + `<textarea rows="3" data-talk-system data-t="talk-system" title="${escapeHtml(t("talkSystemTip"))}">${escapeHtml(this.system)}</textarea></details></div>`;
  }

  /** The voice to speak in: the runner's list; or the cell's, said as it is asked, failed or empty. A sample in use is
   *  the voice: the list stays, shut. */
  voiceHtml(row) {
    const option = (v) => `<option value="${escapeHtml(v)}"${v === this.voice ? " selected" : ""}>${escapeHtml(v)}</option>`;
    const field = (options) => `<label class="talk-field">${escapeHtml(t("talkVoice"))} <select data-talk-voice data-t="talk-voice"`
      + `${this.sample ? " disabled" : ""}>${options}</select></label>`;
    const own = this.cell.spec?.voices?.[row.id] || [];
    if (own.length || !this.cell.spec?.asksVoices) return own.length ? field(own.map(option).join("")) : "";
    const said = (key, state, words = {}) => `<p class="talk-voices${state === "failed" ? " talk-error" : ""}" data-t="talk-voices"`
      + ` data-t-state="${state}">${escapeHtml(t(key, words))}</p>`;
    if (!this.asked) return said("talkVoicesAsking", "asking");
    if (this.asked.error) return said("talkVoicesFailed", "failed", { error: this.asked.error });
    const { voices, stored } = this.asked;
    if (!voices.length && !stored.length) return this.takesSample ? said("talkVoicesNone", "none") : "";
    const group = (key, names) => (names.length ? `<optgroup label="${escapeHtml(t(key))}">${names.map(option).join("")}</optgroup>` : "");
    return field(group("talkVoicesModel", voices) + group("talkVoicesKept", stored.map((v) => v.name)));
  }

  /** The sample of a voice the text is read in, and keeping it on the cell under a name: for a cell that can. */
  sampleHtml() {
    if (!this.takesSample) return "";
    const sampling = this.recorder.recording && this.recordingFor === "sample";
    const state = sampling ? "recording" : this.sample ? "recorded" : "none";
    const record = `<button type="button" class="talk-go${sampling ? " recording" : ""}" data-talk-sample-record="1" data-t="talk-sample-record"`
      + ` aria-pressed="${sampling}"${this.busy || (this.recorder.recording && !sampling) ? " disabled" : ""}>`
      + `${escapeHtml(sampling ? `■ ${t("stop")}` : t("talkSampleRecord"))}</button>`;
    const seconds = sampling ? `<span class="talk-rec" data-talk-seconds>${escapeHtml(t("talkRecording", { seconds: this.recorder.seconds.toFixed(1) }))}</span>` : "";
    const got = this.sample
      ? `<audio controls preload="metadata" src="data:audio/wav;base64,${escapeHtml(this.sample.audio)}"></audio>`
        + `<span class="talk-len">${escapeHtml(t("talkSeconds", { seconds: this.sample.seconds.toFixed(1) }))}</span>`
        + `<button type="button" class="talk-clear" data-talk-sample-forget="1" data-t="talk-sample-forget"${this.busy ? " disabled" : ""}>`
        + `${escapeHtml(t("talkSampleForget"))}</button>` : "";
    const use = this.sample ? `<p class="talk-memory" data-t="talk-sample-use" data-t-state="${this.consent ? "used" : "consent"}">`
      + `${escapeHtml(t(this.consent ? "talkSampleInUse" : "talkSampleNeedsConsent"))}</p>` : "";
    return `<div class="talk-sample" data-t="talk-sample" data-t-state="${state}"><strong class="talk-sample-title">${escapeHtml(t("talkSampleTitle"))}</strong>`
      + `<div class="talk-sample-row">${record}${seconds}${got}</div>`
      + `<label class="talk-field talk-wide">${escapeHtml(t("talkSampleWords"))}<textarea rows="2" data-talk-sample-text data-t="talk-sample-text"`
      + ` placeholder="${escapeHtml(t("talkSampleWordsPlaceholder"))}">${escapeHtml(this.sampleText)}</textarea></label>`
      + `<label class="talk-consent"><input type="checkbox" data-talk-consent data-t="talk-consent"${this.consent ? " checked" : ""}> `
      + `${escapeHtml(t("talkSampleConsent"))}</label>${use}`
      + `<div class="talk-sample-row"><label class="talk-field">${escapeHtml(t("talkKeepAs"))} <input type="text" data-talk-keep-name`
      + ` data-t="talk-keep-name" value="${escapeHtml(this.keepName)}" maxlength="64" pattern="${escapeHtml(this.cell.spec?.voiceName || "")}"`
      + ` title="${escapeHtml(t("talkKeepNameTip"))}" spellcheck="false" autocomplete="off"></label>`
      + `<button type="button" class="talk-go" data-talk-keep="1" data-t="talk-keep"${this.canKeep ? "" : " disabled"}>${escapeHtml(t("save"))}</button></div></div>`;
  }

  turnsHtml() {
    if (!this.turns.length) return `<p class="talk-empty">${escapeHtml(t(this.modeRow?.takes === "text" ? "talkHintText" : "talkHintVoice"))}</p>`;
    return this.turns.map((turn, i) => {
      const who = turn.role === "user" ? t("talkYou") : (this.cell.name || this.cell.runner);
      // The length is read up front: the data is in the page already, and a player that has not read it shows
      // 0:00 / 0:00 — an empty recording, to the eye (found live, 2026-10-21).
      const voice = turn.audio
        ? `<audio controls preload="metadata" src="data:${escapeHtml(turn.audioType || "audio/wav")};base64,${escapeHtml(turn.audio)}"></audio>` : "";
      const length = turn.role === "user" && turn.seconds ? `<span class="talk-len">${escapeHtml(t("talkSeconds", { seconds: turn.seconds.toFixed(1) }))}</span>` : "";
      const words = turn.text ? `<div class="talk-text">${escapeHtml(turn.text)}</div>` : "";
      const nothing = turn.role === "assistant" && !turn.error && !turn.text && !turn.audio
        ? `<div class="talk-text muted">${escapeHtml(t("talkEmptyAnswer"))}</div>` : "";
      const error = turn.error ? `<div class="talk-error">${escapeHtml(turn.error)}</div>` : "";
      return `<div class="talk-turn ${turn.role}" data-t="talk-turn" data-t-id="${i}" data-t-state="${turn.error ? "failed" : turn.role}">`
        + `<div class="talk-who">${escapeHtml(who)}${length}</div>${words}${nothing}${voice}${error}${this.timingHtml(turn)}</div>`;
    }).join("");
  }

  /** An answer's time, in seconds: until the cell's answer began, in all, and until its voice was heard. */
  timingHtml(turn) {
    if (turn.role !== "assistant" || !turn.ms) return "";
    const s = (ms) => (Number(ms) / 1000).toFixed(1);
    const parts = [t("talkTiming", { first: s(turn.ms.first), total: s(turn.ms.total) })];
    if (turn.sound !== null) parts.push(t("talkTimingSound", { sound: s(turn.sound) }));
    return `<div class="talk-timing" data-t="talk-timing">${escapeHtml(parts.join(" · "))}</div>`;
  }

  inputHtml(row) {
    const clear = `<button type="button" class="talk-clear" data-talk-clear="1" data-t="talk-clear"${this.turns.length && !this.busy ? "" : " disabled"}>${escapeHtml(t("talkClear"))}</button>`;
    if (!row) return `<div class="talk-input">${clear}</div>`;
    if (row.takes === "text") {
      // While a sample is recorded nothing is said: it would go without the sample being made.
      return `<div class="talk-input"><textarea rows="2" data-talk-text data-t="talk-text" placeholder="${escapeHtml(t("talkTextPlaceholder"))}"${this.busy ? " disabled" : ""}>`
        + `${escapeHtml(this.draft)}</textarea><button type="button" class="talk-go" data-talk-say="1" data-t="talk-say"${this.busy || this.recorder.recording ? " disabled" : ""}>`
        + `${escapeHtml(this.busy ? t("talkWaiting") : t("talkSay"))}</button>${clear}</div>`;
    }
    const recording = this.recorder.recording;
    const label = this.busy ? t("talkWaiting") : recording ? t("talkStopSend") : t("talkRecord");
    const seconds = recording ? `<span class="talk-rec" data-talk-seconds>${escapeHtml(t("talkRecording", { seconds: this.recorder.seconds.toFixed(1) }))}</span>` : "";
    return `<div class="talk-input"><button type="button" class="talk-go${recording ? " recording" : ""}" data-talk-record="1" data-t="talk-record"`
      + ` aria-pressed="${recording}"${this.busy ? " disabled" : ""}>${escapeHtml(label)}</button>${seconds}${clear}</div>`;
  }

  mount() {
    if (!this.doc?.createElement) return;
    this.root = this.doc.createElement("div");
    this.root.className = "talk-overlay";
    this.root.addEventListener("click", (e) => this.onClick(e));
    this.root.addEventListener("change", (e) => this.onChange(e));
    this.root.addEventListener("input", (e) => this.onInput(e));
    this.doc.body.appendChild(this.root);
    this.doc.addEventListener("keydown", this.onKey);
    this.redraw();
    this.loadVoices();
  }

  /** Ask the cell its voices, of a runner whose cell says them; the list is drawn as asked, failed or said. The voice
   *  picked stays when the cell still has it (named in its own spelling), else the first of the list is picked. */
  async loadVoices() {
    if (!this.cell.spec?.asksVoices) return null;
    this.asked = null;
    this.redraw();
    let got;
    try {
      got = await this.call(`/api/cell-talk/voices?hostId=${encodeURIComponent(this.cell.hostId)}&port=${encodeURIComponent(this.cell.port)}`);
    } catch (err) {
      got = { error: String(err?.message || err) };
    }
    if (TalkWindow.current !== this) return null;
    this.asked = got.error ? { error: String(got.error) } : { voices: [...(got.voices || [])], stored: [...(got.stored || [])] };
    const list = this.voicesOf(this.mode);
    this.voice = list.find((v) => v.toLowerCase() === this.voice.toLowerCase()) || list[0] || "";
    this.redraw();
    return this.asked;
  }

  redraw() {
    if (this.root) this.root.innerHTML = this.html();
  }

  onClick(e) {
    const el = e.target?.closest?.("[data-talk-close],[data-talk-mode],[data-talk-record],[data-talk-say],[data-talk-clear],"
      + "[data-talk-sample-record],[data-talk-sample-forget],[data-talk-keep]");
    if (!el) return;
    if (el.dataset.talkClose) this.close();
    else if (el.dataset.talkMode) this.pick(el.dataset.talkMode);
    else if (el.dataset.talkRecord) this.toggleRecord();
    else if (el.dataset.talkSay) this.say(this.draft);
    else if (el.dataset.talkClear) this.clear();
    else if (el.dataset.talkSampleRecord) this.toggleSample();
    else if (el.dataset.talkSampleForget) this.forgetSample();
    else if (el.dataset.talkKeep) this.keepVoice();
  }

  onChange(e) {
    const d = e.target?.dataset || {};
    if (d.talkVoice !== undefined) this.voice = String(e.target.value || "");
    if (d.talkConsent !== undefined) {
      this.consent = e.target.checked === true;
      this.redraw();
    }
  }

  // Typing redraws nothing: the field keeps its focus and its caret. The one thing a name changes is whether it can
  // be kept: that button is set as it is typed.
  onInput(e) {
    const d = e.target?.dataset || {};
    if (d.talkSystem !== undefined) this.system = String(e.target.value);
    if (d.talkText !== undefined) this.draft = String(e.target.value);
    if (d.talkSampleText !== undefined) this.sampleText = String(e.target.value);
    if (d.talkKeepName !== undefined) {
      this.keepName = String(e.target.value).trim();
      const keep = this.root?.querySelector?.("[data-talk-keep]");
      if (keep) keep.disabled = !this.canKeep;
    }
  }

  pick(mode) {
    if (this.busy || this.recorder.recording || !this.modes.some((m) => m.id === mode)) return false;
    this.mode = mode;
    this.voice = this.voicesOf(mode)[0] || "";
    this.notice = "";
    this.redraw();
    return true;
  }

  clear() {
    if (this.busy) return false;
    this.turns = [];
    this.notice = "";
    this.redraw();
    return true;
  }

  async toggleRecord() {
    if (this.busy) return null;
    if (this.recorder.recording) return this.recordingFor === "talk" ? this.stopAndSend() : null;
    return this.listen("talk");
  }

  /** The microphone on, for `what` ("talk" or "sample"); why it is not, said in the window. */
  async listen(what) {
    this.notice = "";
    try {
      await this.recorder.start();
    } catch (err) {
      this.notice = err instanceof TalkError ? t(err.key, { error: err.detail }) : String(err?.message || err);
      this.redraw();
      return null;
    }
    this.recordingFor = what;
    this.redraw();
    this.ticker = setInterval(() => this.tick(), 250);
    return true;
  }

  /** While recording: the seconds, and the stop at the longest recording. */
  tick() {
    if (!this.recorder.recording) return;
    if (this.recorder.seconds >= WavRecorder.MAX_SECONDS) {
      if (this.recordingFor === "sample") this.stopSample();
      else this.stopAndSend();
      return;
    }
    const counter = this.root?.querySelector?.("[data-talk-seconds]");
    if (counter) counter.textContent = t("talkRecording", { seconds: this.recorder.seconds.toFixed(1) });
  }

  /** The recording as it stops: the microphone let go, the ticker gone. */
  stopRecording() {
    clearInterval(this.ticker);
    this.ticker = null;
    this.recordingFor = "";
    return this.recorder.stop();
  }

  async stopAndSend() {
    const { wav, seconds } = this.stopRecording();
    const audio = WavFile.base64(wav);
    return this.send(new TalkTurn({ role: "user", audio, audioType: "audio/wav", seconds, mode: this.mode }), { audio });
  }

  async toggleSample() {
    if (this.busy || !this.takesSample) return null;
    if (this.recorder.recording) return this.recordingFor === "sample" ? this.stopSample() : null;
    return this.listen("sample");
  }

  stopSample() {
    const { wav, seconds } = this.stopRecording();
    this.sample = { audio: WavFile.base64(wav), seconds };
    this.redraw();
    return this.sample;
  }

  forgetSample() {
    if (this.busy || this.recorder.recording) return false;
    this.sample = null;
    this.notice = "";
    this.redraw();
    return true;
  }

  /** A text read out — in the sample's voice when there is a sample, and only with the operator's word for it: a
   *  sample that cannot be used is said, not passed over for another voice. */
  async say(text) {
    const words = String(text || "").trim();
    if (!words || this.busy || this.recorder.recording) return null;
    const sampled = this.sample && this.takesSample;
    if (sampled && !this.consent) {
      this.notice = t("talkSampleNeedsConsent");
      this.redraw();
      return null;
    }
    this.draft = "";
    const sample = sampled ? { sample: this.sample.audio, sampleText: this.sampleText.trim(), consent: true } : {};
    return this.send(new TalkTurn({ role: "user", text: words, mode: this.mode }), { text: words, ...sample });
  }

  /** Keep the sample on the cell under the name typed: one of the cell's voices from then on, for this window and for
   *  any client of the cell's port (Open WebUI names it as its voice). The list is asked again, the new voice picked. */
  async keepVoice() {
    if (!this.canKeep) return null;
    const name = this.keepName;
    this.busy = true;
    this.notice = "";
    this.redraw();
    let got;
    try {
      got = await this.call("/api/cell-talk/voice", { method: "POST", body: JSON.stringify({
        hostId: this.cell.hostId, port: Number(this.cell.port), name, sample: this.sample.audio, sampleText: this.sampleText.trim(), consent: true }) });
    } catch (err) {
      got = { error: String(err?.message || err) };
    }
    if (TalkWindow.current !== this) return null;
    this.busy = false;
    if (got.error) {
      this.notice = t("talkKeepFailed", { error: String(got.error) });
      this.redraw();
      return got;
    }
    this.sample = null;
    this.sampleText = "";
    this.keepName = "";
    this.voice = name;
    await this.loadVoices();
    this.notice = t("talkKept", { name });
    this.redraw();
    return got;
  }

  /** Ask the cell through the controller; the answer — or the refusal, or why it could not be asked — is the next
   *  message of the talk. An answer for a window closed meanwhile lands nowhere. */
  async send(turn, what) {
    const row = this.modeRow;
    const history = this.history();
    this.turns.push(turn);
    this.busy = true;
    this.notice = "";
    this.redraw();
    const asked = this.clock();
    const body = { hostId: this.cell.hostId, port: Number(this.cell.port), mode: this.mode, ...what, history,
                   ...(row?.conversation ? { system: this.system } : {}), ...(this.voice ? { voice: this.voice } : {}) };
    let answer;
    try {
      const got = await this.call("/api/cell-talk", { method: "POST", body: JSON.stringify(body) });
      answer = new TalkTurn({ role: "assistant", mode: this.mode, text: got.text, audio: got.audio, audioType: got.audioType, ms: got.ms,
                              error: got.error ? t("talkCellRefused", { status: String(got.status), error: got.error }) : "" });
    } catch (err) {
      answer = new TalkTurn({ role: "assistant", mode: this.mode, error: t("talkFailed", { error: String(err?.message || err) }) });
    }
    if (TalkWindow.current !== this) return null;
    this.turns.push(answer);
    this.busy = false;
    this.redraw();
    if (answer.audio) {
      try {
        await this.play(`data:${answer.audioType || "audio/wav"};base64,${answer.audio}`, () => {
          answer.sound = this.clock() - asked;
          this.redraw();
        });
      } catch {
        // A browser that would not play by itself leaves the answer's own player: one press away.
      }
    }
    return answer;
  }

  close() {
    clearInterval(this.ticker);
    this.ticker = null;
    this.recordingFor = "";
    this.recorder.release();
    this.doc?.removeEventListener?.("keydown", this.onKey);
    this.root?.remove?.();
    this.root = null;
    if (TalkWindow.current === this) TalkWindow.current = null;
  }
}
