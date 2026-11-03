#!/usr/bin/env python3
"""Value snapshot: static/js/voice-live.js — the board's live window: a talk both ways at once with a cell over its own
WebSocket, through the controller (scripts/test_rust_admin_conformance.py keeps that side's answers).

MiniCPM-o talks only over its WebSocket (llama.cpp-omni's `/backend`): the first message is `session.init`; the voice
goes in as base64 float32 at 16 kHz — in full duplex a second at a time, silence too — and comes back float32 at 24 kHz
about a second at a time; `listen` says the model listens again, `session.closed` why the talk ended. A busy cell
closes without a word.

The runners' rows come from the program's own table (contract/controller.json) — this snapshot keeps no copy. Pinned by value, each
claim with a positive and a negative: the samples' base64 both ways and their rate changed; the microphone as a stream
(why it refuses before asking, the chunks it hands on, what it lets go); the voice played back to back; which cells the
card offers the window to; the protocol's messages both ways; the window — the cell asked first, the talk opened, the
models loading, full duplex (a second at a time, silence while muted, the model's lines and voice), turn by turn (an
utterance sent whole, the answer's first sound timed), and each way a talk ends said by why: the cell's reason, a busy
cell, a door that drops WebSocket, a cell that does not answer, the operator hanging up.

Words are read from static/js/i18n/en.js programmatically.

Run: python3 scripts/test_js_voice_live.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_args, node_search_paths, probe_args  # noqa: E402
from _contract import Contract  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


PROBE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const root = process.env.JS_ROOT;
const REG = JSON.parse(process.env.LIVE_REGISTRY);
globalThis.__stubReturns = { "llama-edit.runnerRegistry": () => REG };
const st = await import(pathToFileURL(root + "/state.js").href);
st.setState({ runners: REG, talkModes: [] });
const L = await import(pathToFileURL(root + "/voice-live.js").href);
const { PcmCodec, MicStream, VoiceQueue, LiveCell, MiniCpmOmniTalk, LiveWindow, LIVE_PROTOCOLS } = L;
const out = {};
const r3 = (xs) => Array.from(xs).map((x) => Math.round(x * 1000) / 1000);
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

// ── the samples ──
{
  const f = Float32Array.from([0, 1, -0.5, 0.25]);
  const b64 = PcmCodec.toBase64(f);
  out.b64 = b64 === Buffer.from(f.buffer).toString("base64");
  out.back = Array.from(PcmCodec.fromBase64(b64));
  out.cut = Array.from(PcmCodec.fromBase64(Buffer.from([0, 0, 128, 63, 1]).toString("base64")));
  out.down = r3(PcmCodec.resample(Float32Array.from([0, 1, 2, 3, 4, 5]), 48000, 16000));
  out.up = r3(PcmCodec.resample(Float32Array.from([0, 1]), 16000, 24000));
  out.same = Array.from(PcmCodec.resample(Float32Array.from([0.5, 0.25]), 16000, 16000));
  const big = new Float32Array(20000).map((_, i) => Math.sin(i / 10));
  out.bigB64 = PcmCodec.toBase64(big) === Buffer.from(big.buffer).toString("base64");
}

// ── the microphone ──
{
  const media = (fn) => ({ getUserMedia: fn });
  out.refuse = [new MicStream({ secure: false, media: media(async () => ({})), Context: function () {} }).refusal(),
    new MicStream({ secure: true, media: undefined, Context: function () {} }).refusal(),
    new MicStream({ secure: true, media: media(async () => ({})), Context: function () {} }).refusal()];
  const log = [];
  let asked = null;
  const stream = { getTracks: () => [{ stop: () => log.push("track stopped") }] };
  let node = null;
  class Ctx {
    constructor() { this.sampleRate = 48000; log.push("context"); }
    async resume() { log.push("resumed"); }
    createMediaStreamSource(s) { log.push(s === stream ? "source" : "other source"); return { connect: () => log.push("source→node"), disconnect: () => log.push("source off") }; }
    createScriptProcessor(size, inn, outn) { log.push(`processor ${size} ${inn} ${outn}`); node = { connect: () => log.push("node→out"), disconnect: () => log.push("node off") }; return node; }
    get destination() { return "out"; }
    close() { log.push("context closed"); }
  }
  const mic = new MicStream({ secure: true, media: media(async (c) => { asked = c; return stream; }), Context: Ctx });
  const chunks = [];
  await mic.start((c) => chunks.push(Array.from(c)), { rate: 16000, chunk: 4 });
  out.asked = asked;
  out.open = mic.open;
  node.onaudioprocess({ inputBuffer: { getChannelData: () => Float32Array.from([0, 0, 0, 3, 3, 3, 6, 6, 6, 9, 9, 9, 12, 12, 12, 15, 15, 15]) } });
  out.chunks1 = chunks.map(r3);
  out.pending1 = r3(mic.pending);
  node.onaudioprocess({ inputBuffer: { getChannelData: () => Float32Array.from([18, 18, 18, 21, 21, 21]) } });
  out.chunks2 = chunks.map(r3);
  mic.stop();
  out.stopped = [mic.open, mic.pending.length];
  out.micLog = log;
  const denied = new MicStream({ secure: true, media: media(async () => { const e = new Error("no"); e.name = "NotAllowedError"; throw e; }), Context: Ctx });
  try { await denied.start(() => {}); out.denied = null; } catch (e) { out.denied = [e.key, denied.open]; }
  const plain = new MicStream({ secure: false, media: media(async () => { out.plainAsked = true; return stream; }), Context: Ctx });
  try { await plain.start(() => {}); out.plain = null; } catch (e) { out.plain = [e.key, !!out.plainAsked]; }
}

// ── the voice played back to back ──
{
  const starts = [];
  let stopped = 0;
  class Ctx {
    constructor() { this.currentTime = 10; this.made = true; }
    async resume() { out.voiceResumed = true; }
    createBuffer(ch, n, rate) { return { duration: n / rate, copyToChannel: (s) => { this.copied = Array.from(s); } }; }
    createBufferSource() { const src = { connect: () => {}, start: (at) => starts.push(at), stop: () => { stopped += 1; } }; return src; }
    get destination() { return "out"; }
    close() { out.voiceClosed = true; }
  }
  const q = new VoiceQueue({ Context: Ctx });
  out.aheadBefore = q.ahead;
  q.wake();
  q.push(new Float32Array(24000), 24000);
  q.push(new Float32Array(12000), 24000);
  out.starts = starts.map((x) => Math.round(x * 1000) / 1000);
  out.ahead = Math.round(q.ahead * 1000) / 1000;
  q.push(new Float32Array(0), 24000);
  out.startsAfterEmpty = starts.length;
  q.stop();
  out.voiceStop = [stopped, q.until];
  q.close();
  const none = new VoiceQueue({ Context: undefined });
  none.push(new Float32Array(10), 24000);
  out.noContext = none.context;
}

// ── which cells the card offers the window to ──
{
  const btn = (h) => { const b = String(h).match(/<button[^>]*>/); if (!b) return null;
    const a = (n) => (b[0].match(new RegExp(" " + n + '="([^"]*)"')) || [])[1] ?? null;
    return { t: a("data-t"), id: a("data-t-id"), host: a("data-cell-live"), port: a("data-node-cell-port"), runner: a("data-cell-live-runner"),
             name: a("data-cell-live-name"), disabled: / disabled/.test(b[0]), title: a("title") }; };
  const mini = new LiveCell({ hostId: "m1", port: 22024, name: "MiniCPM-o", runner: "minicpm-omni" });
  out.btnRunning = btn(mini.buttonHtml(true));
  out.btnStopped = btn(mini.buttonHtml(false));
  out.btnOther = new LiveCell({ hostId: "m1", port: 22027, runner: "qwen3-tts" }).buttonHtml(true);
  out.spec = [mini.spec, new LiveCell({ runner: "qwen3-tts" }).spec];
  out.urls = [mini.url({ protocol: "https:", host: "board.example" }), mini.url({ protocol: "http:", host: "10.0.0.5:7990" }),
    new LiveCell({ hostId: "a b&c", port: 1 }).url({ protocol: "https:", host: "x" })];
  const back = LiveCell.fromButton({ dataset: { cellLive: "m1", nodeCellPort: "22024", cellLiveName: "MiniCPM-o", cellLiveRunner: "minicpm-omni" } });
  out.fromButton = [back.hostId, back.port, back.name, back.runner];
}

// ── the protocol ──
{
  const p = new MiniCpmOmniTalk();
  out.consts = [MiniCpmOmniTalk.RATE_IN, MiniCpmOmniTalk.RATE_OUT, MiniCpmOmniTalk.CHUNK, MiniCpmOmniTalk.MODES, Object.keys(LIVE_PROTOCOLS)];
  out.init = [JSON.parse(p.init("full_duplex")), JSON.parse(p.init("turn_based"))];
  const second = JSON.parse(p.second(Float32Array.from([0.5, -0.5])));
  out.second = [second.type, Object.keys(second.input), Array.from(PcmCodec.fromBase64(second.input.audio))];
  const utt = JSON.parse(p.utterance(Float32Array.from([0.25])));
  out.utterance = [utt.type, utt.input.streaming, utt.input.tts, utt.input.messages.length, utt.input.messages[0].role,
    utt.input.messages[0].content.map((c) => c.type), Array.from(PcmCodec.fromBase64(utt.input.messages[0].content[0].data))];
  const audio = p.read(JSON.stringify({ type: "response.output.delta", kind: "audio", audio: PcmCodec.toBase64(Float32Array.from([0.125, -1])) }));
  out.read = [
    p.read(JSON.stringify({ type: "session.created", session_id: "abc", mode: "full_duplex" })),
    p.read(JSON.stringify({ type: "response.output.delta", kind: "text", text: "Hel" })),
    [audio.kind, Array.from(audio.samples), audio.rate],
    p.read(JSON.stringify({ type: "response.output.delta", kind: "listen" })),
    p.read(JSON.stringify({ type: "response.done", text: "Hello", reason: "turn_end" })),
    p.read(JSON.stringify({ type: "session.closed", reason: "prefill_failed" })),
    p.read(JSON.stringify({ type: "response.output.delta", kind: "video" })),
    p.read(JSON.stringify({ type: "metrics.tick" })),
    p.read("not json"),
  ];
}

// ── the window ──
class FakeSocket {
  static made = [];
  constructor(url) { this.url = url; this.sent = []; this.closed = null; FakeSocket.made.push(this); }
  send(data) { this.sent.push(JSON.parse(data)); }
  close(code) { this.closed = code; }
}
class FakeMic {
  constructor() { this.starts = []; this.stops = 0; this.onChunk = null; this.pending = new Float32Array(0); }
  async start(onChunk, opts) { this.starts.push(opts); this.onChunk = onChunk; }
  stop() { this.stops += 1; this.onChunk = null; }
}
class FakeVoice {
  constructor() { this.pushed = []; this.stops = 0; this.wakes = 0; this.closes = 0; }
  wake() { this.wakes += 1; }
  push(samples, rate) { this.pushed.push([samples.length, rate]); }
  stop() { this.stops += 1; }
  close() { this.closes += 1; }
}
const mini = new LiveCell({ hostId: "m1", port: 22024, name: "MiniCPM-o", runner: "minicpm-omni" });
const healthy = async (url) => { out.askedUrl = url; return { ok: true, runner: "minicpm-omni", protocol: "minicpm-omni", health: { status: 200, error: "" } }; };
const msg = (o) => ({ data: JSON.stringify(o) });
const made = (deps = {}) => {
  FakeSocket.made = [];
  let now = 1000;
  const win = new LiveWindow(mini, { call: healthy, Socket: FakeSocket, mic: new FakeMic(), voice: new FakeVoice(), clock: () => now,
    doc: null, location: { protocol: "https:", host: "board.example" }, ...deps });
  win.tick = (ms) => { now += ms; };
  LiveWindow.current = win;
  return win;
};
const status = (w) => (w.statusText() || "");
{
  const w = made();
  out.d0 = [w.phase, w.state, w.mode, w.modes];
  await w.start();
  const s = FakeSocket.made[0];
  out.d1 = [out.askedUrl, s?.url, w.phase, w.voice.wakes];
  s.onopen();
  out.d2 = [w.phase, s.sent[0], status(w)];
  await w.heard(s, msg({ type: "session.created", session_id: "abc" }).data);
  out.d3 = [w.phase, w.state, w.mic.starts, status(w)];
  w.mic.onChunk(Float32Array.from([0.5, -0.5]));
  out.d4 = [s.sent.length, s.sent[1].type, Array.from(PcmCodec.fromBase64(s.sent[1].input.audio))];
  w.toggleMute();
  w.mic.onChunk(Float32Array.from([0.5, -0.5]));
  out.d5 = [w.state, Array.from(PcmCodec.fromBase64(s.sent[2].input.audio))];
  w.toggleMute();
  await w.heard(s, msg({ type: "response.output.delta", kind: "text", text: "Hel" }).data);
  await w.heard(s, msg({ type: "response.output.delta", kind: "text", text: "lo" }).data);
  out.d6 = [w.lines.map((l) => [l.role, l.text]), status(w)];
  await w.heard(s, msg({ type: "response.output.delta", kind: "audio", audio: PcmCodec.toBase64(new Float32Array(24)) }).data);
  out.d7 = [w.voice.pushed, w.lines.length, w.lines[0].firstSound];
  await w.heard(s, msg({ type: "response.done", text: "Hello" }).data);
  await w.heard(s, msg({ type: "response.output.delta", kind: "text", text: " there" }).data);
  out.d8 = [w.lines.length, w.lines[0].text];
  await w.heard(s, msg({ type: "response.output.delta", kind: "listen" }).data);
  out.d9 = status(w);
  await w.heard(s, msg({ type: "response.output.delta", kind: "text", text: "Again" }).data);
  out.d10 = w.lines.map((l) => l.text);
  await w.heard(s, msg({ type: "session.closed", reason: "prefill_failed" }).data);
  s.onclose({ code: 1000 });
  out.d11 = [w.phase, w.state, w.notice, status(w), w.mic.stops, w.voice.stops, w.socket];
  out.d11html = /data-t-state="ended"/.test(w.html()) && /data-t="live-start"/.test(w.html()) && !/data-t="live-hangup"/.test(w.html());
}
{
  const w = made({ call: async () => ({ health: { status: 0, error: "the cell on 10.0.0.9:22024 did not answer" } }) });
  await w.start();
  out.cellDown = [w.phase, w.notice, FakeSocket.made.length];
}
{
  const w = made({ call: async () => { throw new Error("HTTP 409"); } });
  await w.start();
  out.downThrown = [w.phase, w.notice?.key, w.notice?.args?.error, FakeSocket.made.length];
}
{
  const w = made();
  await w.start();
  const s = FakeSocket.made[0];
  s.onopen();
  s.onclose({ code: 1000 });
  out.busy = [w.phase, w.notice];
}
{
  const w = made();
  await w.start();
  FakeSocket.made[0].onclose({ code: 1006 });
  out.door = [w.phase, w.notice];
}
{
  const w = made();
  await w.start();
  const s = FakeSocket.made[0];
  s.onopen();
  await w.heard(s, msg({ type: "session.created" }).data);
  s.onclose({ code: 1006 });
  out.endedLive = [w.phase, w.notice];
}
{
  const w = made();
  w.pick("turn_based");
  await w.start();
  const s = FakeSocket.made[0];
  s.onopen();
  out.t1 = s.sent[0];
  w.pick("full_duplex");
  out.t1mode = w.mode;
  await w.heard(s, msg({ type: "session.created" }).data);
  out.t2 = [w.state, w.mic.starts.length, status(w)];
  await w.toggleSpeak();
  out.t3 = [w.state, w.mic.starts, status(w)];
  w.mic.onChunk(Float32Array.from([0.25, 0.25]));
  w.mic.onChunk(Float32Array.from([0.5]));
  w.mic.pending = Float32Array.from([0.75]);
  await w.toggleSpeak();
  const sent = s.sent[1] || {};
  out.t4 = [w.state, sent.type ?? null, Array.from(PcmCodec.fromBase64(sent.input?.messages?.[0]?.content?.[0]?.data || "")), w.lines.map((l) => [l.role, l.text, l.seconds]),
    w.mic.stops, status(w)];
  await w.toggleSpeak();
  out.t4again = s.sent.length;
  w.tick(1500);
  await w.heard(s, msg({ type: "response.output.delta", kind: "text", text: "Hi" }).data);
  await w.heard(s, msg({ type: "response.output.delta", kind: "audio", audio: PcmCodec.toBase64(new Float32Array(4)) }).data);
  w.tick(500);
  await w.heard(s, msg({ type: "response.output.delta", kind: "audio", audio: PcmCodec.toBase64(new Float32Array(4)) }).data);
  out.t5 = [w.lines.map((l) => [l.role, l.text, l.firstSound]), w.state];
  await w.heard(s, msg({ type: "response.done", text: "Hi" }).data);
  out.t6 = [w.state, status(w)];
  w.hangUp();
  out.t7 = [w.phase, s.closed, w.mic.stops >= 2, w.voice.stops];
  s.onclose({ code: 1000 });
  out.t8 = [w.phase, w.notice];
}
{
  const w = made();
  await w.start();
  const old = FakeSocket.made[0];
  old.onopen();
  w.hangUp();
  await w.start();
  const fresh = FakeSocket.made[1];
  await w.heard(old, msg({ type: "session.created" }).data);
  old.onclose({ code: 1000 });
  out.stale = [w.phase, FakeSocket.made.length, fresh.sent.length, w.notice];
}
{
  const plain = new LiveWindow(new LiveCell({ hostId: "m1", port: 22027, runner: "qwen3-tts" }), { call: healthy, Socket: FakeSocket, mic: new FakeMic(), voice: new FakeVoice(), doc: null });
  FakeSocket.made = [];
  await plain.start();
  out.noProtocol = [plain.talk, plain.modes, FakeSocket.made.length, /data-t="live-start" disabled/.test(plain.html())];
}
{
  const w = made();
  out.htmlIdle = [/data-t="live-mode" data-t-id="full_duplex" aria-pressed="true"/.test(w.html()), /class="live-hint"/.test(w.html())];
  w.pick("turn_based");
  out.htmlTurns = [/class="live-hint"/.test(w.html()), w.mode];
  await w.start();
  out.htmlActive = /data-t="live-mode"[^>]*disabled/.test(w.html());
  w.pick("full_duplex");
  out.pickedWhileActive = w.mode;
}
{
  let removed = 0;
  const listeners = {};
  const doc = { createElement: () => ({ addEventListener: () => {}, remove: () => { removed += 1; }, set innerHTML(v) { this._h = v; } }),
                body: { appendChild: () => {} }, addEventListener: (k, f) => { listeners[k] = f; }, removeEventListener: (k) => { delete listeners[k]; } };
  const w = LiveWindow.open(mini, { call: healthy, Socket: FakeSocket, mic: new FakeMic(), voice: new FakeVoice(), doc });
  out.opened = [LiveWindow.current === w, typeof listeners.keydown];
  listeners.keydown({ key: "Escape" });
  out.closed = [LiveWindow.current, removed, typeof listeners.keydown, w.voice.closes];
}
console.log(JSON.stringify(out));
"""


def main():
    node = find_node()
    if not node:
        print(f"js voice-live: node not found (looked in {', '.join(node_search_paths())})")
        return 1
    en = json.loads(subprocess.run(
        node_args(node, "--input-type=module", "-e",
                  f"const m = await import({json.dumps((ROOT / 'static/js/i18n/en.js').as_uri())}); console.log(JSON.stringify(m.default));"),
        capture_output=True, text=True, check=True, timeout=60).stdout)
    reg = Contract.table("controller")["runners"]
    harness = ROOT / "scripts" / "_js_harness.mjs"
    probe_path = ROOT / "scripts" / ".probe_js_voice_live.tmp.mjs"
    probe_path.write_text(PROBE)
    try:
        env = {**os.environ, "JS_ROOT": str(ROOT / "static" / "js"), "JS_STUBS": "llama-edit,form",
               "LIVE_REGISTRY": json.dumps(reg), "LANG": "en_US.UTF-8", "TZ": "UTC"}
        run = subprocess.run(probe_args(node, harness, probe_path), capture_output=True, text=True, env=env, cwd=ROOT, timeout=120)
    finally:
        probe_path.unlink(missing_ok=True)
    if run.returncode != 0:
        print(run.stdout)
        print(run.stderr)
        print(f"js voice-live FAILED: node exited {run.returncode}")
        return 1
    o = json.loads(run.stdout.strip().splitlines()[-1])

    def w(key, **args):
        text = en[key]
        for k, v in args.items():
            text = text.replace("{" + k + "}", str(v))
        return text

    print("the samples:")
    check(o["b64"] is True and o["back"] == [0, 1, -0.5, 0.25],
          "float32 little-endian in base64, as the server reads it, and back the same")
    check(o["cut"] == [1.0], f"negative: a cut last sample is dropped, not read as a number ({o['cut']})")
    check(o["down"] == [0, 3] and o["up"] == [0, 0.667, 1] and o["same"] == [0.5, 0.25],
          f"down from the microphone's 48 kHz and up to a card's rate, by straight lines; the same rate the same ({o['down']}, {o['up']})")
    check(o["bigB64"] is True, "base64 of 80 000 bytes, built in chunks, equals the whole")

    print("the microphone as a stream:")
    check(o["refuse"] == ["talkMicNotSecure", "talkMicMissing", ""], f"why it cannot have the microphone, before asking: {o['refuse']}")
    check(o["asked"] == {"audio": {"channelCount": 1, "echoCancellation": True, "noiseSuppression": True}} and o["open"] is True,
          "one channel, the browser's echo cancelling and noise suppression")
    check(o["chunks1"] == [[0, 3, 6, 9]] and o["pending1"] == [12, 15],
          f"chunks of the size asked, at the rate asked, as they fill; the rest waits ({o['chunks1']}, {o['pending1']})")
    check(o["chunks2"] == [[0, 3, 6, 9], [12, 15, 18, 21]], f"the rest goes with the next ({o['chunks2']})")
    check(o["stopped"] == [False, 0] and "track stopped" in o["micLog"] and "context closed" in o["micLog"]
          and "node off" in o["micLog"] and "resumed" in o["micLog"]
          and o["micLog"].index("resumed") < o["micLog"].index("processor 4096 1 1"),
          f"stopped: the microphone let go, nothing pending; its context resumed before it hears ({o['micLog']})")
    check(o["denied"] == ["talkMicDenied", False] and o["plain"] == ["talkMicNotSecure", False],
          "negative: refused by the browser, or on a plain page without even asking")

    print("the voice played back to back:")
    check(o["aheadBefore"] == 0 and o["voiceResumed"] is True and o["starts"] == [10.05, 11.05] and o["ahead"] == 1.55,
          f"woken in the click; each second starts where the last ends ({o['starts']}, ahead {o['ahead']})")
    check(o["startsAfterEmpty"] == 2, "negative: nothing is scheduled for no samples")
    check(o["voiceStop"] == [2, 0] and o["voiceClosed"] is True and o["noContext"] is None,
          "stopped: what plays and what waits; a page with no audio plays nothing and fails nothing")

    print("which cells the card offers the window to:")
    check(o["btnRunning"] == {"t": "cell-live", "id": "m1:22024", "host": "m1", "port": "22024", "runner": "minicpm-omni",
                              "name": "MiniCPM-o", "disabled": False, "title": w("liveOpenTitle")},
          f"a running MiniCPM-o cell: 📞, naming its machine, port and runner ({o['btnRunning']})")
    check(o["btnStopped"]["disabled"] is True and o["btnStopped"]["title"] == w("liveOpenStopped") and o["btnStopped"]["t"] is None,
          "negative: stopped, the button is shut and says why, with nothing to press")
    check(o["btnOther"] == "" and o["spec"] == [{"protocol": "minicpm-omni"}, None],
          "negative: a cell whose runner does not talk live gets none — the registry's word, no list here")
    check(o["urls"] == ["wss://board.example/api/cell-live?hostId=m1&port=22024", "ws://10.0.0.5:7990/api/cell-live?hostId=m1&port=22024",
                        "wss://x/api/cell-live?hostId=a%20b%26c&port=1"],
          f"the board's own address as a WebSocket — wss behind https — the cell named, never its path ({o['urls']})")
    check(o["fromButton"] == ["m1", "22024", "MiniCPM-o", "minicpm-omni"], "the cell the button names")

    print("MiniCPM-o's messages:")
    check(o["consts"] == [16000, 24000, 16000, ["full_duplex", "turn_based"], ["minicpm-omni"]],
          "16 kHz in, 24 kHz out, a second at a time; both modes, full duplex first")
    check(o["init"] == [{"type": "session.init", "payload": {"mode": "full_duplex", "use_tts": True}},
                        {"type": "session.init", "payload": {"mode": "turn_based", "use_tts": True}}],
          "the first message: the mode, and speech on")
    check(o["second"] == ["input.append", ["audio"], [0.5, -0.5]], "a second of full duplex: its samples in `audio`, nothing else")
    check(o["utterance"] == ["input.append", True, {"enabled": True}, 1, "user", ["audio"], [0.25]],
          "an utterance turn by turn: one user message of audio, streamed back, with speech")
    check(o["read"] == [{"kind": "created", "session": "abc"}, {"kind": "text", "text": "Hel"}, ["audio", [0.125, -1], 24000],
                        {"kind": "listen"}, {"kind": "done", "text": "Hello"}, {"kind": "closed", "reason": "prefill_failed"},
                        {"kind": "unknown", "type": "response.output.delta"}, {"kind": "unknown", "type": "metrics.tick"},
                        {"kind": "unreadable"}],
          f"what the server says, read; negative: a kind or a type it does not know is unknown, not guessed ({o['read']})")

    print("the window, full duplex:")
    check(o["d0"] == ["idle", "idle", "full_duplex", ["full_duplex", "turn_based"]], "closed at first, full duplex picked")
    check(o["d1"] == ["/api/cell-live?hostId=m1&port=22024", "wss://board.example/api/cell-live?hostId=m1&port=22024", "connecting", 1],
          "the cell asked first, then the talk opened through the board; the player woken in the click")
    check(o["d2"] == ["loading", {"type": "session.init", "payload": {"mode": "full_duplex", "use_tts": True}}, w("liveLoading")],
          "open: the first message sent, and the window says the models load")
    check(o["d3"] == ["live", "live", [{"rate": 16000, "chunk": 16000}], w("liveListening")],
          f"the talk begun: the microphone a second at a time at 16 kHz, the model listening ({o['d3']})")
    check(o["d4"] == [2, "input.append", [0.5, -0.5]], "each second goes as it fills")
    check(o["d5"] == ["muted", [0, 0]], "negative: muted, a second of silence goes in its place — the model speaks on only while seconds come")
    check(o["d6"] == [[["assistant", "Hello"]], w("liveSpeaking")], "the model's words grow into one line while it speaks")
    check(o["d7"] == [[[24, 24000]], 1, None], "its voice played at 24 kHz, in the order it came; nothing timed — nothing was sent to time from")
    check(o["d8"] == [1, "Hello there"], "negative: a step said done does not end the line — the model speaks on into it")
    check(o["d9"] == w("liveListening") and o["d10"] == ["Hello there", "Again"], "after it listened, its next words are a new line")
    check(o["d11"] == ["ended", "ended", {"key": "liveClosedBy", "args": {"reason": "prefill_failed"}}, w("liveClosedBy", reason="prefill_failed"),
                       1, 1, None] and o["d11html"] is True,
          f"the cell ended it: its reason said; the microphone and the voice stopped; Start again ({o['d11']})")

    print("each way a talk ends, said by why:")
    check(o["cellDown"] == ["failed", {"key": "liveCellDown", "args": {"error": "the cell on 10.0.0.9:22024 did not answer"}}, 0],
          "the cell does not answer its health: said, and no talk dialled")
    check(o["downThrown"] == ["failed", "liveCellDown", "HTTP 409", 0], "negative: the controller's own refusal is said the same way")
    check(o["busy"] == ["failed", {"key": "liveBusy", "args": {}}], "closed without a word while the models load: a busy cell, or the last talk still closing")
    check(o["door"] == ["failed", {"key": "liveDoorNoWs", "args": {"error": "WebSocket 1006"}}],
          "the cell answers but the talk never opens: the door drops WebSocket — the operator's to turn on")
    check(o["endedLive"] == ["ended", {"key": "liveEnded", "args": {}}], "a talk broken off after it began: over, not failed")

    print("the window, turn by turn:")
    check(o["t1"] == {"type": "session.init", "payload": {"mode": "turn_based", "use_tts": True}} and o["t1mode"] == "turn_based",
          "the mode picked goes in the first message; negative: it is not changed while the talk is on")
    check(o["t2"] == ["ready", 0, w("liveReady")], "begun: the microphone stays off until the operator speaks")
    check(o["t3"] == ["recording", [{"rate": 16000, "chunk": 1600}], w("liveRecording")], "Speak: recording, in tenths of a second")
    check(o["t4"] == ["waiting", "input.append", [0.25, 0.25, 0.5, 0.75], [["user", "", 4 / 16000]], 1, w("liveWaiting")],
          f"Send: the whole utterance in one message, the microphone's last part-chunk with it; its line; waiting ({o['t4']})")
    check(o["t4again"] == 2, "negative: nothing more is sent while the answer is awaited")
    check(o["t5"] == [[["user", "", None], ["assistant", "Hi", 1.5]], "waiting"],
          f"the answer's words and voice in a line of its own, its first sound timed from the send ({o['t5']})")
    check(o["t6"] == ["ready", w("liveReady")], "done: ready for the next turn")
    check(o["t7"] == ["ended", 1000, True, 1] and o["t8"] == ["ended", None],
          "hung up: the socket closed as a normal end, the microphone and the voice stopped; its late close says nothing")

    print("one talk at a time:")
    check(o["stale"] == ["connecting", 2, 0, None],
          f"negative: the old socket's words and its close change nothing of the new talk ({o['stale']})")
    check(o["noProtocol"] == [None, [], 0, True], "negative: a cell whose runner talks no protocol here is not dialled, and Start is shut")
    check(o["htmlIdle"] == [True, True] and o["htmlTurns"] == [False, "turn_based"],
          "the headphones hint for full duplex only — through speakers the model hears itself")
    check(o["htmlActive"] is True and o["pickedWhileActive"] == "turn_based", "the modes are shut while a talk is on")
    check(o["opened"] == [True, "function"] and o["closed"] == [None, 1, "undefined", 1],
          "Escape closes it: off the page, the key let go, the player closed")
    print()
    if _fail:
        print(f"js voice-live: {len(_fail)} FAILED")
        return 1
    print("js voice-live OK: the live window by value, MiniCPM-o's talk both ways")
    return 0


if __name__ == "__main__":
    sys.exit(main())
