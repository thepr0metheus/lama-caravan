#!/usr/bin/env python3
"""Value snapshot: static/js/voice-talk.js — the board's voice window.

The owner, 2026-10-21: run the voice models from the board and talk to them somewhere, "as I talk to a new text model
in Open WebUI". The page records the microphone into a wav itself and the controller asks the cell
(scripts/test_rust_admin_conformance.py keeps that side's answers).

The runners' rows and the modes come from the program's own tables (contract/controller.json) — this snapshot
keeps no copy of them. Pinned by value, each claim with a positive and a negative: the wav bytes (header, samples,
clipping, the rate brought down, base64 in chunks); the recorder (why it refuses before asking, what it asks the
browser for, what a refusal of the browser becomes, the wav it hands over, the microphone let go); which cells the
card offers the window to and with what (the cell by its id: it holds a port only while it runs, and neither the button nor
the window draws or sends one); the window — its modes, voices, system prompt and memory note by the runner,
what one exchange sends and shows, what the talk so far carries, a refusal and a failure as messages, an answer that
comes back to a closed window, the way out. For a cell that keeps voices (Qwen3-TTS, 1.3.608): its list asked, said
while asked, failed or empty; a sample recorded, used only on the operator's word, kept on the cell under a name.

Words are read from static/js/i18n/en.js programmatically.

Run: python3 scripts/test_js_voice_talk.py
"""
import html
import json
import re
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
const REG = JSON.parse(process.env.TALK_REGISTRY);
const MODES = JSON.parse(process.env.TALK_MODES);
// A runner with two chats, the snapshot's own: no runner of the registry has two yet, and the talk so far is a mode's own.
REG.push({ id: "two-chats", talk: { modes: ["spoken-chat", "heard-chat"], system: "", voices: {}, turns: 8 } });
globalThis.__stubReturns = { "llama-edit.runnerRegistry": () => REG };
const st = await import(pathToFileURL(root + "/state.js").href);
st.setState({ runners: REG, talkModes: MODES });
const V = await import(pathToFileURL(root + "/voice-talk.js").href);
const { WavFile, WavRecorder, TalkError, TalkCell, TalkWindow, TalkTurn } = V;
const out = {};
const bytes = (u8) => Array.from(u8);

// ── the wav ──
{
  const wav = WavFile.encode(Float32Array.from([0, 1, -1, 0.5, 2, -2]), 16000);
  const dv = new DataView(wav.buffer);
  const tag = (at) => String.fromCharCode(...wav.slice(at, at + 4));
  out.wavHeader = [tag(0), dv.getUint32(4, true), tag(8), tag(12), dv.getUint32(16, true), dv.getUint16(20, true),
    dv.getUint16(22, true), dv.getUint32(24, true), dv.getUint32(28, true), dv.getUint16(32, true), dv.getUint16(34, true),
    tag(36), dv.getUint32(40, true), wav.length];
  out.wavSamples = [0, 1, 2, 3, 4, 5].map((i) => dv.getInt16(44 + i * 2, true));
  out.down = Array.from(WavFile.downsample(Float32Array.from([1, 2, 3, 4, 5, 6, 7]), 48000, 16000));
  out.same = Array.from(WavFile.downsample(Float32Array.from([1, 2, 3]), 16000, 16000));
  out.up = Array.from(WavFile.downsample(Float32Array.from([1, 2]), 16000, 48000));
  const big = new Uint8Array(70000).map((_, i) => (i * 7) & 255);
  out.b64 = WavFile.base64(big) === Buffer.from(big).toString("base64");
}

// ── the recorder ──
{
  const media = (fn) => ({ getUserMedia: fn });
  out.refuse = [new WavRecorder({ secure: false, media: media(async () => ({})), Context: function () {} }).refusal(),
    new WavRecorder({ secure: true, media: undefined, Context: function () {} }).refusal(),
    new WavRecorder({ secure: true, media: media(async () => ({})), Context: undefined }).refusal(),
    new WavRecorder({ secure: true, media: media(async () => ({})), Context: function () {} }).refusal()];
  const log = [];
  let asked = null;
  const track = { stop: () => log.push("track stopped") };
  const stream = { getTracks: () => [track] };
  let node = null;
  class Ctx {
    constructor() { this.sampleRate = 48000; log.push("context"); }
    createMediaStreamSource(s) { log.push(s === stream ? "source of the stream" : "source of something"); return { connect: () => log.push("source→node"), disconnect: () => log.push("source off") }; }
    createScriptProcessor(size, inn, outn) { log.push(`processor ${size} ${inn} ${outn}`); node = { connect: () => log.push("node→out"), disconnect: () => log.push("node off") }; return node; }
    get destination() { return "out"; }
    close() { log.push("context closed"); }
  }
  const rec = new WavRecorder({ secure: true, media: media(async (c) => { asked = c; return stream; }), Context: Ctx });
  out.before = rec.recording;
  await rec.start();
  out.asked = asked;
  out.during = rec.recording;
  node.onaudioprocess({ inputBuffer: { getChannelData: () => Float32Array.from([0.3, 0.3, 0.3, -0.6, -0.6, -0.6]) } });
  node.onaudioprocess({ inputBuffer: { getChannelData: () => Float32Array.from([1, 1, 1]) } });
  out.seconds = rec.seconds;
  const { wav, seconds } = rec.stop();
  const dv = new DataView(wav.buffer);
  out.stopped = [rec.recording, seconds, dv.getUint32(24, true), (wav.length - 44) / 2,
    [0, 1, 2].map((i) => dv.getInt16(44 + i * 2, true)), rec.chunks.length];
  out.recLog = [...log];
  const denied = new WavRecorder({ secure: true, media: media(async () => { const e = new Error("no"); e.name = "NotAllowedError"; throw e; }), Context: Ctx });
  try { await denied.start(); out.denied = null; } catch (e) { out.denied = [e instanceof TalkError, e.key, denied.recording]; }
  const broken = new WavRecorder({ secure: true, media: media(async () => { throw new Error("device busy"); }), Context: Ctx });
  try { await broken.start(); out.broken = null; } catch (e) { out.broken = [e.key, e.detail]; }
  const plain = new WavRecorder({ secure: false, media: media(async () => { out.plainAsked = true; return stream; }), Context: Ctx });
  try { await plain.start(); out.plain = null; } catch (e) { out.plain = [e.key, !!out.plainAsked]; }
}

// ── which cells the card offers the window to ──
{
  const btn = (h) => { const b = String(h).match(/<button[^>]*>/); if (!b) return null;
    const a = (n) => (b[0].match(new RegExp(" " + n + '="([^"]*)"')) || [])[1] ?? null;
    return { t: a("data-t"), id: a("data-t-id"), cell: a("data-cell-talk"), port: a("data-node-cell-port"), runner: a("data-cell-talk-runner"),
             hears: a("data-cell-talk-hears"), name: a("data-cell-talk-name"), title: a("title"), disabled: /\sdisabled[\s>]/.test(b[0]) }; };
  const cell = (runner, hears = null) => new TalkCell({ cellId: "c22022", name: "LFM <one>", runner, hears });
  out.modesOf = {
    lfm: cell("lfm-audio").modes().map((m) => m.id),
    qwen: cell("qwen3-omni").modes().map((m) => m.id),
    whisper: cell("whisper").modes().map((m) => m.id),
    seamless: cell("seamless").modes().map((m) => m.id),
    llamaHears: cell("llama-server", true).modes().map((m) => m.id),
    llamaDeaf: cell("llama-server", false).modes().map((m) => m.id),
    llamaUnsaid: cell("llama-server", null).modes().map((m) => m.id),
    custom: cell("custom").modes().map((m) => m.id),
    personaplex: cell("personaplex").modes().map((m) => m.id),
    vllm: cell("vllm").modes().map((m) => m.id),
  };
  out.voiced = MODES.map((m) => [m.id, TalkCell.voiced(m)]);
  out.btn = {
    running: btn(cell("lfm-audio").buttonHtml(true)),
    stopped: btn(cell("lfm-audio").buttonHtml(false)),
    llamaHears: btn(cell("llama-server", true).buttonHtml(true)),
    llamaDeaf: cell("llama-server", false).buttonHtml(true),
    llamaStopped: cell("llama-server", null).buttonHtml(false),
    custom: cell("custom").buttonHtml(true),
    customStopped: cell("custom").buttonHtml(false),
    vllm: cell("vllm").buttonHtml(true),
    vllmStopped: cell("vllm").buttonHtml(false),
  };
  const fake = { dataset: { cellTalk: "c22022", cellTalkName: "x", cellTalkRunner: "llama-server", cellTalkHears: "true" } };
  const back = TalkCell.fromButton(fake);
  out.fromButton = [back.cellId, back.name, back.runner, back.hears,
    TalkCell.fromButton({ dataset: { ...fake.dataset, cellTalkHears: "" } }).hears];
  // A button of the old shape (the machine in data-cell-talk, the port beside it): no port is read off it, and no field holds one.
  const old = TalkCell.fromButton({ dataset: { cellTalk: "m1", nodeCellPort: "22022", cellTalkRunner: "lfm-audio" } });
  out.fromOld = [old.cellId, "port" in old, "hostId" in old];
  // A cell the card gives no name: the window is titled by its id, never by a port.
  const nameless = new TalkCell({ cellId: "c22022", runner: "lfm-audio" });
  out.title = [nameless.title, new TalkCell({ cellId: "c22022", name: "LFM", runner: "lfm-audio" }).title];
}

// ── the window ──
const facts = (html) => ({
  state: (html.match(/data-t="talk-window" data-t-id="([^"]*)" data-t-state="(\w+)"/) || []).slice(1),
  modes: [...html.matchAll(/data-t="talk-mode" data-t-id="([^"]+)" aria-pressed="(true|false)"/g)].map((x) => [x[1], x[2]]),
  one: (html.match(/class="talk-mode-one" data-t="talk-mode" data-t-id="([^"]+)">([^<]*)</) || []).slice(1),
  voices: [...html.matchAll(/<option value="([^"]+)"( selected)?>/g)].map((x) => x[1] + (x[2] ? "*" : "")),
  memory: (html.match(/data-t="talk-memory">([^<]*)</) || [])[1] ?? null,
  system: (html.match(/data-t="talk-system"[^>]*>([^<]*)<\/textarea>/) || [])[1] ?? null,
  record: (html.match(/data-t="talk-record" aria-pressed="(true|false)"(?: disabled)?>([^<]*)</) || []).slice(1),
  say: (html.match(/data-t="talk-say"(?: disabled)?>([^<]*)</) || [])[1] ?? null,
  text: html.includes('data-t="talk-text"'),
  turns: [...html.matchAll(/data-t="talk-turn" data-t-id="(\d+)" data-t-state="(\w+)"/g)].map((x) => x[2]),
  timing: [...html.matchAll(/data-t="talk-timing">([^<]*)</g)].map((x) => x[1]),
  audios: (html.match(/<audio controls/g) || []).length,
  preloads: [...html.matchAll(/<audio controls preload="(\w+)"/g)].map((x) => x[1]),
  notice: (html.match(/data-t="talk-notice">([^<]*)</) || [])[1] ?? null,
  empty: (html.match(/<p class="talk-empty">([^<]*)</) || [])[1] ?? null,
  clearOff: /data-t="talk-clear" disabled/.test(html),
});
class FakeRecorder {
  constructor(fail = null) { this.fail = fail; this.on = false; this.log = []; this.secondsNow = 0; }
  get recording() { return this.on; }
  get seconds() { return this.secondsNow; }
  async start() { this.log.push("start"); if (this.fail) throw this.fail; this.on = true; }
  stop() { this.log.push("stop"); this.on = false; return { wav: Uint8Array.from([82, 73, 70, 70]), seconds: 2.5 }; }
  release() { this.log.push("release"); this.on = false; }
}
const ticks = (...v) => { const it = v[Symbol.iterator](); return () => it.next().value; };
const doc = () => {
  const d = { listeners: [], appended: [], body: { appendChild: (el) => d.appended.push(el) },
    createElement: () => ({ className: "", innerHTML: "", addEventListener: () => {}, querySelector: () => null, remove() { this.removed = true; } }),
    addEventListener: (k, f) => d.listeners.push([k, f]), removeEventListener: (k, f) => { d.listeners = d.listeners.filter((x) => x[1] !== f); } };
  return d;
};
const ANSWER = { ok: true, mode: "spoken-chat", status: 200, text: "Two plus two is four.", audio: "UklGRg==", audioType: "audio/wav", error: "", ms: { first: 800, total: 1500 } };
// Every window's head, as drawn: the name and the ✕, and no port after the name.
const heads = [];
const headOf = (w) => { const h = w.html(); heads.push(h.slice(0, h.indexOf('<div class="talk-modes"'))); return h; };
{
  const calls = [];
  const played = [];
  const d = doc();
  const rec = new FakeRecorder();
  const qwen = new TalkCell({ cellId: "c3f9a02b1", name: "Qwen3-Omni", runner: "qwen3-omni" });
  const w = TalkWindow.open(qwen, { call: async (path, opts) => { calls.push([path, JSON.parse(opts.body)]); return ANSWER; },
    recorder: rec, clock: ticks(1000, 3400, 1000, 2000), play: async (src, onStart) => { played.push(src); onStart(); }, doc: d });
  out.qOpen = facts(headOf(w));
  out.qMounted = [d.appended.length, d.listeners.map((x) => x[0]), TalkWindow.current === w];
  out.qStart = await w.toggleRecord();
  out.qRecording = facts(w.html());
  out.qPickBusy = w.pick("spoken-chat");
  const first = await w.toggleRecord();
  out.qAfter = facts(w.html());
  out.qCall = calls[0];
  out.qPlayed = [...played];
  out.qSound = first.sound;
  w.system = "You are an English teacher.";
  w.voice = "aiden";
  await w.toggleRecord();
  await w.toggleRecord();
  out.qSecond = calls[1][1];
  out.qClear = [w.clear(), w.turns.length];
  w.close();
  out.qClosed = [TalkWindow.current, d.listeners.length, rec.log.includes("release")];
}
{
  const calls = [];
  const lfm = new TalkCell({ cellId: "c22022", name: "LFM", runner: "lfm-audio" });
  const w = TalkWindow.open(lfm, { call: async (path, opts) => { calls.push(JSON.parse(opts.body)); return ANSWER; },
    recorder: new FakeRecorder(), clock: ticks(0, 0, 0, 0, 0, 0), play: async () => {}, doc: doc() });
  out.lOpen = facts(headOf(w));
  await w.toggleRecord(); await w.toggleRecord();
  await w.toggleRecord(); await w.toggleRecord();
  out.lHistory = calls.map((c) => c.history.length);
  out.lPickBad = w.pick("transcription");
  out.lPick = w.pick("speech");
  out.lSpeech = facts(w.html());
  out.lSayEmpty = await w.say("   ");
  await w.say("Hello there.");
  out.lSayBody = calls[2];
  out.lSpeechAfter = facts(w.html());
  w.close();
  const fresh = TalkWindow.open(lfm, { call: async () => ANSWER, recorder: new FakeRecorder(), doc: doc() });
  fresh.pick("speech");
  out.lFreshSpeech = facts(fresh.html()).empty;
  fresh.close();
}
{
  const failing = new TalkCell({ cellId: "c22025", name: "whisper", runner: "whisper" });
  const replies = [
    { ok: true, mode: "transcription", status: 500, text: "", audio: "", audioType: "", error: "model is loading", ms: { first: 10, total: 12 } },
    { ok: true, mode: "transcription", status: 200, text: "", audio: "", audioType: "", error: "", ms: { first: 10, total: 12 } },
  ];
  const calls = [];
  const w = TalkWindow.open(failing, { call: async (p, o) => { calls.push(JSON.parse(o.body)); const r = replies.shift(); if (!r) throw new Error("socket hang up"); return r; },
    recorder: new FakeRecorder(), clock: ticks(0, 0, 0, 0, 0, 0), play: async () => { out.wPlayed = true; }, doc: doc() });
  out.wOpen = facts(w.html());
  await w.toggleRecord(); await w.toggleRecord();
  await w.toggleRecord(); await w.toggleRecord();
  await w.toggleRecord(); await w.toggleRecord();
  out.wAfter = facts(w.html());
  out.wTexts = w.turns.filter((t) => t.role === "assistant").map((t) => t.error);
  out.wBodies = calls.map((c) => [c.mode, "system" in c, "voice" in c, c.history.length]);
  w.close();
}
{
  const mic = new TalkCell({ cellId: "c22022", name: "LFM", runner: "lfm-audio" });
  const w = TalkWindow.open(mic, { call: async () => ANSWER, recorder: new FakeRecorder(new TalkError("talkMicNotSecure")), doc: doc() });
  out.micStart = await w.toggleRecord();
  out.mic = facts(w.html());
  w.close();
  const w2 = TalkWindow.open(mic, { call: async () => ANSWER, recorder: new FakeRecorder(new TalkError("talkMicFailed", "device busy")), doc: doc() });
  await w2.toggleRecord();
  out.mic2 = facts(w2.html()).notice;
  w2.close();
}
{
  let release;
  const slow = new Promise((r) => { release = r; });
  const cellA = new TalkCell({ cellId: "c3f9a02b1", name: "A", runner: "qwen3-omni" });
  const a = TalkWindow.open(cellA, { call: async () => slow, recorder: new FakeRecorder(), clock: ticks(0, 0, 0), play: async () => {}, doc: doc() });
  await a.toggleRecord();
  const pending = a.toggleRecord();
  out.busyClear = a.clear();
  out.busyState = facts(a.html()).state[1];
  const b = TalkWindow.open(cellA, { call: async () => ANSWER, recorder: new FakeRecorder(), doc: doc() });
  out.replaced = [TalkWindow.current === b, a.root];
  release(ANSWER);
  out.lateLanding = [await pending, a.turns.length];
  b.close();
}
{
  const calls = [];
  const two = new TalkCell({ cellId: "c22030", name: "two", runner: "two-chats", hears: true });
  const w = TalkWindow.open(two, { call: async (p, o) => { calls.push(JSON.parse(o.body)); return ANSWER; }, recorder: new FakeRecorder(),
    clock: ticks(0, 0, 0, 0, 0, 0), play: async () => {}, doc: doc() });
  await w.toggleRecord(); await w.toggleRecord();
  w.pick("heard-chat");
  await w.toggleRecord(); await w.toggleRecord();
  await w.toggleRecord(); await w.toggleRecord();
  out.twoHistory = calls.map((c) => [c.mode, c.history.length]);
  w.close();
}
// ── the window — Qwen3-TTS: the cell's own voices, a sample of a voice, a voice kept on the cell ──
const flush = () => new Promise((r) => setImmediate(r));
const sampleFacts = (html) => {
  const block = (html.split('data-t="talk-turns"')[0].split('data-t="talk-sample"')[1]) || "";
  return {
    voicesSaid: (html.match(/data-t="talk-voices" data-t-state="(\w+)">([^<]*)</) || []).slice(1),
    groups: [...html.matchAll(/<optgroup label="([^"]*)">/g)].map((x) => x[1]),
    voiceShut: /data-t="talk-voice" disabled/.test(html),
    sayShut: /data-t="talk-say" disabled/.test(html),
    present: html.includes('data-t="talk-sample"'),
    state: (html.match(/data-t="talk-sample" data-t-state="(\w+)"/) || [])[1] ?? null,
    record: (block.match(/data-t="talk-sample-record" aria-pressed="(true|false)"( disabled)?>([^<]*)</) || []).slice(1),
    sampleAudio: [...block.matchAll(/<audio controls preload="(\w+)" src="data:audio\/wav;base64,([^"]*)"/g)].map((x) => [x[1], x[2]]),
    forget: block.includes('data-t="talk-sample-forget"'),
    use: (block.match(/data-t="talk-sample-use" data-t-state="(\w+)">([^<]*)</) || []).slice(1),
    consent: (block.match(/data-t="talk-consent"( checked)?>/) || [null, null])[1] === " checked",
    keep: (block.match(/data-t="talk-keep"( disabled)?>([^<]*)</) || []).slice(1),
    pattern: (block.match(/data-t="talk-keep-name" value="[^"]*" maxlength="64" pattern="([^"]*)"/) || [])[1] ?? null,
  };
};
{
  const calls = [];
  let releaseVoices;
  const answers = {
    voices: [new Promise((r) => { releaseVoices = r; }),
             { ok: true, status: 200, voices: [], stored: [{ name: "grandpa", words: "" }, { name: "my-voice", words: "Это мой голос." }], error: "", ms: {} }],
    // Answered by the name asked, not by the order of asking: a step that sends what it must not leaves the steps
    // after it as they were.
    keep: { x: { ok: true, status: 400, name: "x", error: "name collides with a built-in voice", ms: {} },
            "my-voice": { ok: true, status: 200, name: "my-voice", error: "", ms: {} } },
  };
  const call = async (path, opts) => {
    calls.push([path, opts ? JSON.parse(opts.body) : null]);
    if (path.startsWith("/api/cell-talk/voices")) return answers.voices.shift();
    if (path === "/api/cell-talk/voice") {
      const name = JSON.parse(opts.body).name;
      return answers.keep[name] || { ok: true, status: 400, name, error: "a name the snapshot does not keep", ms: {} };
    }
    return { ok: true, mode: "speech", status: 200, text: "", audio: "UklGRg==", audioType: "audio/wav", error: "", ms: { first: 1, total: 2 } };
  };
  const rec = new FakeRecorder();
  const tts = new TalkCell({ cellId: "c5e01d7aa", name: "Qwen3-TTS", runner: "qwen3-tts" });
  const w = TalkWindow.open(tts, { call, recorder: rec, clock: ticks(0, 0, 0, 0, 0, 0, 0, 0), play: async () => {}, doc: doc() });
  out.tAsking = [sampleFacts(w.html()), facts(w.html()).voices, w.voice, calls.map((c) => c[0])];
  // A Base checkpoint: no voices of its own, one kept on it — the window offers a sample.
  releaseVoices({ ok: true, status: 200, voices: [], stored: [{ name: "grandpa", words: "" }], error: "", ms: {} });
  await flush();
  out.tListed = [sampleFacts(w.html()), facts(w.html()).voices, w.voice];
  // Each request is taken as the one its step made, not by its place among all of them.
  let before = calls.length;
  await w.say("Привет.");
  out.tPlain = calls[before];
  out.tSampleStart = await w.toggleSample();
  out.tSampling = [sampleFacts(w.html()), facts(w.html()).state[1], facts(w.html()).say];
  out.tTalkWhileSampling = [await w.toggleRecord(), await w.say("Привет."), rec.log.filter((x) => x === "stop").length, rec.recording, calls.length];
  out.tSample = await w.toggleSample();
  out.tRecorded = [sampleFacts(w.html()), w.sample, rec.recording];
  out.tNoConsent = [await w.say("Привет."), facts(w.html()).notice, calls.length];
  w.onChange({ target: { dataset: { talkConsent: "" }, checked: true } });
  w.onInput({ target: { dataset: { talkSampleText: "" }, value: " Это мой голос. " } });
  out.tConsented = sampleFacts(w.html());
  before = calls.length;
  await w.say("Привет.");
  out.tSampled = calls[before];
  const keepButton = { disabled: null };
  w.root = { querySelector: (s) => (s === "[data-talk-keep]" ? keepButton : null), innerHTML: "", remove() {} };
  w.onInput({ target: { dataset: { talkKeepName: "" }, value: "my voice" } });
  const keeps = (name) => calls.filter((c) => c[0] === "/api/cell-talk/voice" && (name === undefined || c[1].name === name));
  out.tBadName = [w.canKeep, keepButton.disabled, await w.keepVoice(), keeps().length];
  w.onInput({ target: { dataset: { talkKeepName: "" }, value: " x " } });
  out.tGoodName = [w.keepName, w.canKeep, keepButton.disabled];
  const refused = await w.keepVoice();
  out.tRefused = [refused.error, facts(w.html()).notice, !!w.sample, keeps("x")[0]];
  w.onInput({ target: { dataset: { talkKeepName: "" }, value: "my-voice" } });
  await w.keepVoice();
  const at = calls.indexOf(keeps("my-voice")[0]);
  out.tKept = [calls.slice(at).map((c) => c[0]), calls[at][1], sampleFacts(w.html()), facts(w.html()).voices, w.voice, facts(w.html()).notice,
    w.sample, w.sampleText, w.keepName];
  w.close();
}
{
  const failing = TalkWindow.open(new TalkCell({ cellId: "c5e01d7aa", name: "Qwen3-TTS", runner: "qwen3-tts" }),
    { call: async () => { throw new Error("cell c5e01d7aa did not answer"); }, recorder: new FakeRecorder(), doc: doc() });
  await flush();
  out.tFailed = [sampleFacts(failing.html()), facts(failing.html()).voices, failing.voice];
  failing.close();
  const empty = TalkWindow.open(new TalkCell({ cellId: "c5e01d7aa", name: "Qwen3-TTS", runner: "qwen3-tts" }),
    { call: async () => ({ ok: true, status: 200, voices: [], stored: [], error: "", ms: {} }), recorder: new FakeRecorder(), doc: doc() });
  await flush();
  out.tEmpty = [sampleFacts(empty.html()), facts(empty.html()).voices];
  empty.close();
  const refusedList = TalkWindow.open(new TalkCell({ cellId: "c5e01d7aa", name: "Qwen3-TTS", runner: "qwen3-tts" }),
    { call: async () => ({ ok: true, status: 404, voices: [], stored: [], error: "The model does not support Speech API", ms: {} }),
      recorder: new FakeRecorder(), doc: doc() });
  await flush();
  out.tRefusedList = sampleFacts(refusedList.html()).voicesSaid;
  refusedList.close();
  // A CustomVoice checkpoint: voices of its own, and a sample it would refuse is not offered.
  const custom = TalkWindow.open(new TalkCell({ cellId: "c0d1e2f3a", name: "Qwen3-TTS CustomVoice", runner: "qwen3-tts" }),
    { call: async () => ({ ok: true, status: 200, voices: ["aiden", "vivian"], stored: [], error: "", ms: {} }), recorder: new FakeRecorder(), doc: doc() });
  await flush();
  out.tCustom = [sampleFacts(custom.html()), facts(custom.html()).voices, custom.voice, await custom.toggleSample(), custom.sample];
  custom.close();
  const lfmCalls = [];
  const lfm = TalkWindow.open(new TalkCell({ cellId: "c22022", name: "LFM", runner: "lfm-audio" }),
    { call: async (p) => { lfmCalls.push(p); return ANSWER; }, recorder: new FakeRecorder(), doc: doc() });
  lfm.pick("speech");
  await flush();
  out.tLfm = [lfmCalls, sampleFacts(lfm.html()).present, await lfm.toggleSample(), lfm.sample];
  lfm.close();
}
{
  const t1 = new TalkTurn({ role: "assistant", text: "ok" }).sent();
  const t2 = new TalkTurn({ role: "assistant", text: "x", error: "boom" }).sent();
  const t3 = new TalkTurn({ role: "user", text: "hi", audio: "AAA=" }).sent();
  const t4 = new TalkTurn({ role: "system", text: "sneaky" }).role;
  out.sent = [t1, t2, t3, t4];
}
{
  // Opened last: a window opened closes the one before it.
  const unnamed = TalkWindow.open(new TalkCell({ cellId: "c22022", runner: "lfm-audio" }), { call: async () => ANSWER, recorder: new FakeRecorder(), doc: doc() });
  out.unnamedHead = headOf(unnamed);
  unnamed.close();
}
out.heads = heads;
console.log(JSON.stringify(out));
"""


def main():
    node = find_node()
    if not node:
        print(f"js voice-talk: node not found (looked in {', '.join(node_search_paths())})")
        return 1
    en = json.loads(subprocess.run(
        node_args(node, "--input-type=module", "-e",
                  f"const m = await import({json.dumps((ROOT / 'static/js/i18n/en.js').as_uri())}); console.log(JSON.stringify(m.default));"),
        capture_output=True, text=True, check=True, timeout=60).stdout)
    tables = Contract.table("controller")
    reg, modes = tables["runners"], tables["talkModes"]
    harness = ROOT / "scripts" / "_js_harness.mjs"
    probe_path = ROOT / "scripts" / ".probe_js_voice_talk.tmp.mjs"
    probe_path.write_text(PROBE)
    try:
        env = {**os.environ, "JS_ROOT": str(ROOT / "static" / "js"), "JS_STUBS": "llama-edit,form",
               "TALK_REGISTRY": json.dumps(reg), "TALK_MODES": json.dumps(modes), "LANG": "en_US.UTF-8", "TZ": "UTC"}
        run = subprocess.run(probe_args(node, harness, probe_path), capture_output=True, text=True, env=env, cwd=ROOT, timeout=120)
    finally:
        probe_path.unlink(missing_ok=True)
    if run.returncode != 0:
        print(run.stdout)
        print(run.stderr)
        print(f"js voice-talk FAILED: node exited {run.returncode}")
        return 1
    o = json.loads(run.stdout.strip().splitlines()[-1])
    qsys = next(r for r in reg if r["id"] == "qwen3-omni")["talk"]["system"]

    print("the wav:")
    check(o["wavHeader"] == ["RIFF", 48, "WAVE", "fmt ", 16, 1, 1, 16000, 32000, 2, 16, "data", 12, 56],
          f"a 16-bit mono wav at its rate: {o['wavHeader']}")
    check(o["wavSamples"] == [0, 32767, -32768, 16383, 32767, -32768], f"the samples, clipped to -1..1: {o['wavSamples']}")
    check(o["down"] == [2, 5], f"48 kHz to 16 kHz: each new sample the mean of three, the rest dropped: {o['down']}")
    check(o["same"] == [1, 2, 3] and o["up"] == [1, 2], "a rate that is not lower is kept as it is (negative)")
    check(o["b64"] is True, "base64 of 70 000 bytes, built in chunks, equals the whole")

    print("the recorder:")
    check(o["refuse"] == ["talkMicNotSecure", "talkMicMissing", "talkMicMissing", ""],
          f"why it cannot have the microphone, before asking: {o['refuse']}")
    check(o["before"] is False and o["during"] is True, "recording only between start and stop")
    check(o["asked"] == {"audio": {"channelCount": 1, "echoCancellation": True, "noiseSuppression": True}},
          f"one channel, the browser's echo and noise filters: {o['asked']}")
    check(abs(o["seconds"] - 9 / 48000) < 1e-9, f"seconds so far from the samples gathered: {o['seconds']}")
    check(o["stopped"][0] is False and abs(o["stopped"][1] - 9 / 48000) < 1e-9 and o["stopped"][2:] == [16000, 3, [9830, -19660, 32767], 0],
          f"the wav handed over: 16 kHz, three samples for nine at 48 kHz (truncated toward zero), the chunks dropped: {o['stopped']}")
    check(o["recLog"] == ["context", "source of the stream", "processor 4096 1 1", "source→node", "node→out",
                          "node off", "source off", "track stopped", "context closed"],
          f"the microphone is taken and let go: {o['recLog']}")
    check(o["denied"] == [True, "talkMicDenied", False], f"a microphone the browser refused: {o['denied']}")
    check(o["broken"] == ["talkMicFailed", "device busy"], f"a microphone that failed says why: {o['broken']}")
    check(o["plain"] == ["talkMicNotSecure", False], "a page of plain http does not even ask the browser")

    print("which cells the card offers the window to:")
    m = o["modesOf"]
    check(m["lfm"] == ["spoken-chat", "speech"] and m["qwen"] == ["spoken-chat"] and m["whisper"] == ["transcription"]
          and m["seamless"] == ["speech-translation"], f"the runner's modes, in its order: {m}")
    check(m["llamaHears"] == ["heard-chat"] and m["llamaDeaf"] == [] and m["llamaUnsaid"] == [],
          "llama.cpp: only a cell whose server said it hears; not said is not yes")
    check(m["custom"] == [] and m["personaplex"] == [], "a command and a duplex server: nothing (negative)")
    b = o["btn"]
    check(b["running"] == {"t": "cell-talk", "id": "c22022", "cell": "c22022", "port": None, "runner": "lfm-audio", "hears": "",
                           "name": "LFM &lt;one&gt;", "title": en["talkOpenTitle"], "disabled": False},
          f"a running cell of a talking runner: the 🎙 with its cell's id as its address and data-t-id; negative: no port beside it: {b['running']}")
    check(b["stopped"] == {"t": None, "id": None, "cell": None, "port": None, "runner": None, "hears": None, "name": None,
                           "title": en["talkOpenStopped"], "disabled": True},
          f"a stopped one: the 🎙 shut, saying why, and no hook to press: {b['stopped']}")
    check(b["llamaHears"]["hears"] == "true" and b["llamaHears"]["t"] == "cell-talk", "a llama.cpp cell that hears gets it")
    check(b["llamaDeaf"] == "" and b["llamaStopped"] == "", "a deaf or a stopped llama.cpp cell gets none (negative)")
    check(m["vllm"] == [] and b["vllm"] == "" and b["vllmStopped"] == "",
          "negative (1.3.624): a runner whose only talk is a text chat (vLLM) gets no 🎙 — its chat is the cell window's Talk tab")
    check(dict(o["voiced"]) == {"spoken-chat": True, "heard-chat": True, "text-chat": False, "speech": True,
                                  "transcription": True, "speech-translation": True},
          "this window's modes are those with a voice in them: a recording asked or a voice answered; negative: text-chat is not")
    check(b["custom"] == "" and b["customStopped"] == "", "a runner that does not talk gets none, running or not (negative)")
    check(o["fromButton"] == ["c22022", "x", "llama-server", True, None], f"the button names its cell back by its id: {o['fromButton']}")
    check(o["fromOld"] == ["m1", False, False],
          f"negative: a button of the old shape gives no port and no machine — the window keeps the cell's id alone: {o['fromOld']}")
    check(o["title"] == ["c22022", "LFM"], "a cell the card gives no name is called by its id; a named one by its name")

    print("the window — Qwen3-Omni:")
    q = o["qOpen"]
    check(q["state"] == ["c3f9a02b1", "ready"] and q["one"] == ["spoken-chat", en["talkModeSpokenChat"]] and q["modes"] == [],
          f"one mode: named, not a row of buttons: {q['state']} {q['one']}")
    check(q["voices"] == ["ethan*", "chelsie", "aiden"], f"the runner's speakers, the first picked: {q['voices']}")
    check(q["memory"] == en["talkMemory"].replace("{n}", "8"), f"what it remembers: {q['memory']}")
    check(q["system"] == qsys.replace("'", "&#39;").replace('"', "&quot;") or q["system"] == qsys,
          "the runner's system prompt filled in")
    check(q["record"] == ["false", en["talkRecord"]] and q["empty"] == en["talkHintVoice"] and q["clearOff"] is True,
          "ready to record, a hint for an empty talk, nothing to clear")
    check(o["qMounted"] == [1, ["keydown"], True], f"its own element on the page, Escape heard, the one open: {o['qMounted']}")
    check(o["qStart"] is True and o["qRecording"]["state"][1] == "recording" and o["qRecording"]["record"] == ["true", en["talkStopSend"]],
          "recording: the button stops and sends")
    check(o["qPickBusy"] is False, "no mode is picked while recording (negative)")
    call = o["qCall"]
    check(call[0] == "/api/cell-talk" and call[1] == {"cellId": "c3f9a02b1", "mode": "spoken-chat", "audio": "UklGRg==",
                                                       "history": [], "system": qsys, "voice": "ethan"},
          f"one exchange sends the recording, the system prompt and the voice to the controller: {call}")
    a = o["qAfter"]
    check(a["turns"] == ["user", "assistant"] and a["audios"] == 2, "the question and the answer, each with its voice")
    check(a["preloads"] == ["metadata", "metadata"],
          f"each player reads its length up front — not 0:00 / 0:00, which reads as an empty recording: {a['preloads']}")
    timing = en["talkTiming"].replace("{first}", "0.8").replace("{total}", "1.5") + " · " + en["talkTimingSound"].replace("{sound}", "2.4")
    check(a["timing"] == [timing], f"the answer's time — begun, in all, heard: {a['timing']}")
    check(o["qPlayed"] == ["data:audio/wav;base64,UklGRg=="] and o["qSound"] == 2400, "its voice is played, and the moment it is heard kept")
    second = o["qSecond"]
    check(second["system"] == "You are an English teacher." and second["voice"] == "aiden",
          "the system prompt and the voice as the window has them now")
    check(second["history"] == [{"role": "user", "text": "", "audio": "UklGRg=="}, {"role": "assistant", "text": "Two plus two is four."}],
          f"the talk so far goes with the next message: {second['history']}")
    check(o["qClear"] == [True, 0], "clear empties the talk")
    check(o["qClosed"] == [None, 0, True], f"closed: no window, no key listener, the microphone let go: {o['qClosed']}")

    print("the window — LFM2.5-Audio:")
    lo = o["lOpen"]
    check(lo["modes"] == [["spoken-chat", "true"], ["speech", "false"]] and lo["voices"] == [],
          f"two modes as buttons; its chat has no voices: {lo['modes']} {lo['voices']}")
    check(lo["memory"] == en["talkNoMemory"], "it says it remembers nothing")
    check(o["lHistory"] == [0, 0], "and nothing of the talk goes with the second message (negative of memory)")
    check(o["lPickBad"] is False and o["lPick"] is True, "only its own modes can be picked")
    sp = o["lSpeech"]
    check(sp["voices"] == ["us_female*", "us_male", "uk_female", "uk_male"] and sp["text"] is True
          and sp["say"] == en["talkSay"] and sp["record"] == [] and sp["memory"] is None and sp["system"] is None,
          f"speech: a text and its voices, no recording, no memory or prompt: {sp}")
    check(sp["empty"] is None and sp["turns"] == ["user", "assistant", "user", "assistant"],
          "the talk of the other mode stays on the screen after a switch (it is not sent: the history is the mode's own)")
    check(o["lFreshSpeech"] == en["talkHintText"], "an empty talk in speech has a hint of its own")
    check(o["lSayEmpty"] is None, "nothing is said for an empty text (negative)")
    check(o["lSayBody"] == {"cellId": "c22022", "mode": "speech", "text": "Hello there.", "history": [], "voice": "us_female"},
          f"speech sends the text and the voice, no system prompt: {o['lSayBody']}")

    print("the window — Qwen3-TTS: the cell's voices, a sample, a voice kept:")
    voice_name = next(r for r in reg if r["id"] == "qwen3-tts")["talk"]["voiceName"]
    sf, opts, voice, paths = o["tAsking"]
    check(sf["voicesSaid"] == ["asking", en["talkVoicesAsking"]] and opts == [] and voice == "",
          f"while the cell is asked its voices, the window says so — no empty list, no voice made up: {sf['voicesSaid']}")
    check(paths == ["/api/cell-talk/voices?cell=c5e01d7aa"], f"the window asks the controller for the cell's voices, by its id: {paths}")
    check(sf["present"] is False, "negative: no sample is offered before the cell has said whether it has voices of its own")
    sf, opts, voice = o["tListed"]
    check(sf["voicesSaid"] == [] and [html.unescape(g) for g in sf["groups"]] == [en["talkVoicesKept"]]
          and opts == ["grandpa*"] and voice == "grandpa",
          f"a cell with no voices of its own (Base): the voices kept on it, the first picked: {opts}")
    check(sf["present"] and sf["state"] == "none" and sf["record"] == ["false", None, en["talkSampleRecord"]] and sf["sampleAudio"] == []
          and not sf["forget"] and sf["use"] == [] and sf["consent"] is False and sf["keep"] == [" disabled", en["save"]],
          f"and the sample's part: nothing recorded, nothing to keep: {sf}")
    check(sf["pattern"] == voice_name, f"the name field takes the controller's rule of a voice's name: {sf['pattern']}")
    check(o["tPlain"] == ["/api/cell-talk", {"cellId": "c5e01d7aa", "mode": "speech", "text": "Привет.", "history": [], "voice": "grandpa"}],
          f"a text without a sample goes in the voice picked, with no sample's fields: {o['tPlain']}")
    sf, state, _ = o["tSampling"]
    check(o["tSampleStart"] is True and sf["state"] == "recording" and sf["record"] == ["true", None, "■ " + en["stop"]]
          and state == "recording" and sf["sayShut"] is True,
          f"recording a sample: its button stops it, the window records, nothing is said meanwhile: {sf['record']}")
    check(o["tTalkWhileSampling"] == [None, None, 0, True, 2],
          f"negative: neither the talk's record nor Say takes the sample being made: {o['tTalkWhileSampling']}")
    sf, sample, recording = o["tRecorded"]
    check(o["tSample"] == {"audio": "UklGRg==", "seconds": 2.5} and sample == o["tSample"] and recording is False,
          "the sample is kept in the window, the microphone let go")
    check(sf["state"] == "recorded" and sf["sampleAudio"] == [["metadata", "UklGRg=="]] and sf["forget"] is True and sf["voiceShut"] is True,
          f"it can be heard (its length read up front) and forgotten; the list of voices is shut — the sample is the voice: {sf['sampleAudio']}")
    check(sf["use"] == ["consent", en["talkSampleNeedsConsent"]] and sf["keep"] == [" disabled", en["save"]],
          "without the operator's word the sample is not used, and cannot be kept")
    check(o["tNoConsent"] == [None, en["talkSampleNeedsConsent"], 2],
          f"negative: a text said without consent is not sent in another voice — the window says what is missing: {o['tNoConsent']}")
    sf = o["tConsented"]
    check(sf["use"] == ["used", en["talkSampleInUse"]] and sf["consent"] is True and sf["keep"] == [" disabled", en["save"]],
          "with the tick the sample is the voice; no name yet, nothing to keep")
    check(o["tSampled"] == ["/api/cell-talk", {"cellId": "c5e01d7aa", "mode": "speech", "text": "Привет.", "sample": "UklGRg==",
                                               "sampleText": "Это мой голос.", "consent": True, "history": [], "voice": "grandpa"}],
          f"the text goes with the sample, its trimmed words and the consent: {o['tSampled']}")
    check(o["tBadName"] == [False, True, None, 0], f"negative: a name with a space cannot be kept, and is not sent: {o['tBadName']}")
    check(o["tGoodName"] == ["x", True, False], "a name of the rule, trimmed, opens the button as it is typed")
    error, notice, still, sent = o["tRefused"]
    check(error == "name collides with a built-in voice" and notice == en["talkKeepFailed"].replace("{error}", error) and still is True
          and sent == ["/api/cell-talk/voice", {"cellId": "c5e01d7aa", "name": "x", "sample": "UklGRg==",
                                               "sampleText": "Это мой голос.", "consent": True}],
          f"the cell's refusal to keep is said, and the sample stays to try again: {notice}")
    paths, body, sf, opts, voice, notice, sample, words, name = o["tKept"]
    check(paths == ["/api/cell-talk/voice", "/api/cell-talk/voices?cell=c5e01d7aa"] and body["name"] == "my-voice",
          f"kept: then the cell is asked its voices again: {paths}")
    check(opts == ["grandpa", "my-voice*"] and voice == "my-voice" and notice == en["talkKept"].replace("{name}", "my-voice"),
          f"the kept voice is in the list and picked, and the window says where else it can be named: {opts}")
    check(sf["state"] == "none" and sf["sampleAudio"] == [] and sample is None and words == "" and name == "",
          "the sample is spent: kept on the cell, not in the window")
    sf, opts, voice = o["tFailed"]
    check(sf["voicesSaid"] == ["failed", en["talkVoicesFailed"].replace("{error}", "cell c5e01d7aa did not answer")]
          and opts == [] and voice == "" and sf["present"] is True,
          f"negative: a cell that did not answer: said, not an empty list; the runner's word offers the sample: {sf['voicesSaid']}")
    check(o["tRefusedList"] == ["failed", en["talkVoicesFailed"].replace("{error}", "The model does not support Speech API")],
          "the cell's refusal of its list is said the same way")
    sf, opts = o["tEmpty"]
    check(sf["voicesSaid"] == ["none", en["talkVoicesNone"]] and opts == [] and sf["present"] is True,
          "a cell with no voices yet: said, and the sample is the way")
    sf, opts, voice, started, sample = o["tCustom"]
    check(opts == ["aiden*", "vivian"] and voice == "aiden" and [html.unescape(g) for g in sf["groups"]] == [en["talkVoicesModel"]],
          f"a cell with voices of its own (CustomVoice): its voices, the first picked: {opts}")
    check(sf["present"] is False and started is None and sample is None,
          "negative: and no sample is offered there — that checkpoint refuses one (found live, 2026-10-22)")
    check(o["tLfm"] == [[], False, None, None],
          f"negative: a runner with voices of its own asks the cell nothing and offers no sample: {o['tLfm']}")

    print("refusals and failures:")
    wo = o["wOpen"]
    check(wo["voices"] == [] and wo["memory"] is None and wo["system"] is None, "a recogniser: nothing to set")
    check(o["wTexts"] == [en["talkCellRefused"].replace("{status}", "500").replace("{error}", "model is loading"), "",
                          en["talkFailed"].replace("{error}", "socket hang up")],
          f"the cell's refusal and the controller's failure are messages of the talk: {o['wTexts']}")
    check(o["wAfter"]["turns"] == ["user", "failed", "user", "assistant", "user", "failed"],
          f"each failed answer marked: {o['wAfter']['turns']}")
    check(o["wBodies"] == [["transcription", False, False, 0]] * 3, "a recogniser gets no system prompt, voice or talk so far")
    check("wPlayed" not in o, "nothing is played when no voice came (negative)")
    check(o["micStart"] is None and o["mic"]["notice"] == en["talkMicNotSecure"] and o["mic"]["state"][1] == "ready",
          f"no microphone: the window says why and stays ready: {o['mic']['notice']}")
    check(o["mic2"] == en["talkMicFailed"].replace("{error}", "device busy"), "a failed microphone says its reason")
    check(o["busyClear"] is False and o["busyState"] == "waiting", "nothing is cleared while an answer is awaited")
    check(o["replaced"] == [True, None], "a second window closes the first")
    check(o["lateLanding"] == [None, 1], "an answer for a closed window lands nowhere")
    check(o["twoHistory"] == [["spoken-chat", 0], ["heard-chat", 0], ["heard-chat", 2]],
          f"the talk so far is the mode's own: a switch starts a talk of its own: {o['twoHistory']}")
    check(o["sent"] == [{"role": "assistant", "text": "ok"}, None, {"role": "user", "text": "hi", "audio": "AAA="}, "user"],
          f"what a message carries forward; a failed answer nothing, an unknown role is the user's: {o['sent']}")

    print("the cell by its id, no port:")
    bodies = [o["qCall"][1], o["qSecond"], o["lSayBody"], o["tPlain"][1], o["tSampled"][1], o["tRefused"][3][1], o["tKept"][1]]
    check(all("cellId" in body and "hostId" not in body and "port" not in body for body in bodies),
          "negative: no request of the window names a machine or a port — the controller knows the port the cell's run leased")
    check(len(o["heads"]) == 3 and all("talk-port" not in h and not re.search(r":\d{2,5}\b", h) for h in o["heads"]),
          "negative: no window's head draws a port after the name")
    check(f'🎙 {en["talkTitle"].replace("{name}", "c22022")}' in o["unnamedHead"],
          "a cell the card names nothing: the window is titled by its id")

    print()
    if _fail:
        print(f"js voice-talk: {len(_fail)} FAILED")
        return 1
    print("js voice-talk OK: the window records a wav, asks through the controller, and keeps the talk")
    return 0


if __name__ == "__main__":
    sys.exit(main())
