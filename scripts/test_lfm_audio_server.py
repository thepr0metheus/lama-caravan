#!/usr/bin/env python3
"""Value snapshot: the LFM2.5-Audio cell (cells/lfm_audio_server.py) and the launchers of the voice cells
(caravan/admin/cell_assets.py).

The cell speaks: text to speech, a spoken answer to a spoken question, speech to text. The model needs torch and
Liquid's package, so the model side is a stand-in here (`voice`), and what is pinned is everything around it:
the shapes the caravan's consumers speak (OpenAI text-to-speech, OpenAI chat with input_audio), what a bad
request is told, which voice a name means, how a long text is cut, and what the cell declares about itself.

Pinned, each claim with the answer that would pass it wrongly:
  * the audio that comes back is a real wav (24 kHz, mono, 16 bit), or raw PCM when asked;
  * a name that is no voice of ours is the default voice, and the cell does not fail on OpenAI's "alloy";
  * a bad request is a 400 that says what is wrong, never a 200 with an empty body, never a 500;
  * the chat answer is ONE turn: the last user message; earlier turns and a system message do not reach the model;
  * the cell advertises `tts` and no more: a chat history or a multipart upload (what `llm` and `asr` consumers send)
    would meet a one-turn answer;
  * the board's stale-source check for a custom command follows the LAUNCHER the command names, so an LFM cell
    is not called stale for not being the TTS server.

Run: python3 scripts/test_lfm_audio_server.py
"""
import base64
import io
import json
import os
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "cells"))
sys.path.insert(0, str(ROOT))
os.environ.setdefault("CARAVAN_DATA_DIR", "/tmp/caravan-lfm-audio-test")

import lfm_audio_server as lfm  # noqa: E402
from caravan.admin import cell_assets  # noqa: E402
from caravan.admin.topology import _cell_meta  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


PCM = b"\x01\x00\xff\x7f" * 300          # 600 samples of 2 bytes: 25 ms of what the stand-in "said"


class Voice:
    """The stand-in for the model: remembers what it was asked."""

    def __init__(self):
        self.asked = []

    def tts(self, text, voice, temperature=0.8, top_k=64, max_new_tokens=1024):
        self.asked.append(("tts", text, voice, temperature, top_k, max_new_tokens))
        return PCM

    def speak(self, parts, temperature=1.0, top_k=4, max_new_tokens=1024):
        self.asked.append(("speak", parts, temperature, top_k, max_new_tokens))
        return "Two plus two equals four.", PCM

    def asr(self, raw):
        self.asked.append(("asr", len(raw)))
        return "what is two plus two"

    def vram_gib(self):
        return 2.8


def cell():
    c = lfm.LfmAudioCell(["8031", "/lib/LFM2.5-Audio-1.5B/LiquidAI/SAFETENSORS"])
    c.voice = Voice()
    return c


def post(c, path, doc):
    body = doc if isinstance(doc, bytes) else json.dumps(doc).encode()
    code, out, ctype = c.handle(body, {}, path)
    return code, out, ctype


def wav_facts(raw):
    with wave.open(io.BytesIO(raw)) as w:
        return w.getframerate(), w.getnchannels(), w.getsampwidth() * 8, w.getnframes()


def main():
    print("what the cell says about itself:")
    c = cell()
    check(c.engine == "lfm-audio" and c.kinds == ["tts", "tts.lfm-audio"],
          f"it advertises text-to-speech and nothing else (got {c.engine} {c.kinds})")
    check(c.model_name == "LFM2.5-Audio-1.5B", f"its model is named by the library's model folder (got {c.model_name!r})")
    c.state.update(ready=True, phase="ok")
    code, health = c.health()
    check(code == 200 and health["voices"] == ["us_male", "us_female", "uk_male", "uk_female"] and health["sampleRate"] == 24000
          and health["vramGiB"] == 2.8 and health["engine"] == "lfm-audio",
          f"/health, ready: the voices, the rate and the VRAM it holds (got {health})")
    c.state.update(ready=False, phase="loading")
    check(c.health()[0] == 503, "/health, loading: 503 — a port that answers is not a model that is ready")

    print("text to speech:")
    c = cell()
    code, out, ctype = post(c, "/v1/audio/speech", {"input": " Hello there. ", "voice": "uk-female"})
    check(code == 200 and ctype == "audio/wav" and wav_facts(out) == (24000, 1, 16, 600),
          f"a wav of 24 kHz, mono, 16 bit, with the samples the model made (got {code} {ctype} {wav_facts(out) if code == 200 else out})")
    check(c.voice.asked == [("tts", "Hello there.", "uk_female", 0.8, 64, 1024)], f"the text is trimmed and the voice named as ours (got {c.voice.asked})")
    code, out, ctype = post(c, "/v1/audio/speech", {"input": "Hi", "response_format": "pcm"})
    check(code == 200 and ctype == "audio/pcm" and out == PCM, "pcm: the samples as they are, no header")
    check(post(c, "/v1/audio/speech", {"input": "Hi", "voice": "alloy"})[0] == 200 and c.voice.asked[-1][2] == "us_female",
          "negative: OpenAI's voice name (alloy) is no failure: it is the default voice")
    for voice, want in (("US Male", "us_male"), ("uk_male", "uk_male"), ("", "us_female"), (None, "us_female"), ("US-FEMALE", "us_female")):
        check(lfm.voice_of(voice) == want, f"voice {voice!r} -> {want}")
    for doc, why in (({"input": ""}, "an empty input"), ({"input": "   "}, "a blank input"), ({}, "no input"),
                     ({"input": "Hi", "response_format": "mp3"}, "a format we do not make"),
                     ({"input": "Hi", "top_k": "many"}, "a number that is no number"), (b"not json", "a body that is no JSON"),
                     (b"[1, 2]", "a JSON body that is no object")):
        code, out, ctype = post(c, "/v1/audio/speech", doc)
        check(code == 400 and ctype == "application/json" and out.get("error"), f"negative: {why} is a 400 with its reason (got {code} {out})")
    post(c, "/v1/audio/speech", {"input": "Hi", "temperature": 9, "top_k": 0, "max_new_tokens": 10 ** 9})
    check(c.voice.asked[-1][3:] == (2.0, 1, lfm.MAX_NEW_TOKENS), f"temperature, top_k and length are held to their limits (got {c.voice.asked[-1][3:]})")

    print("a long text is cut at the end of a sentence:")
    pieces = lfm.split_text("One. Two! Three? " + "Word " * 60 + "end. Last one.")
    check(pieces[0] == "One. Two! Three?" or pieces[0].startswith("One. Two! Three?"), f"the first piece keeps whole sentences (got {pieces[0][:40]!r})")
    check(pieces == ["One. Two! Three?", ("Word " * 60 + "end.").strip(), "Last one."],
          f"whole sentences gather up to the limit, one longer sentence stands alone, the last words are kept (got {[p[:20] for p in pieces]})")
    check(lfm.split_text("A. B. C.", limit=5) == ["A. B.", "C."] and lfm.split_text("A. B. C.", limit=100) == ["A. B. C."]
          and lfm.split_text("A. B.", limit=4) == ["A.", "B."] and lfm.split_text("A. B.", limit=5) == ["A. B."],
          "the limit is the piece's length in characters, the space between two sentences counted")
    check(lfm.split_text("") == [] and lfm.split_text("  ") == [] and lfm.split_text("Hello") == ["Hello"], "an empty text is no piece; a short one is one")
    one_long = "A" * 500
    check(lfm.split_text(one_long) == [one_long], "negative: one sentence longer than the limit is not cut inside the sentence")

    print("a spoken answer:")
    c = cell()
    wav = base64.b64encode(b"RIFF....WAVE").decode()
    code, out, ctype = post(c, "/v1/chat/completions", {"messages": [
        {"role": "system", "content": "be a pirate"}, {"role": "user", "content": "first"}, {"role": "assistant", "content": "x"},
        {"role": "user", "content": [{"type": "text", "text": "listen"}, {"type": "input_audio", "input_audio": {"data": wav, "format": "wav"}}]}]})
    message = out["choices"][0]["message"] if code == 200 else {}
    check(code == 200 and message.get("content") == "Two plus two equals four." and message["audio"]["transcript"] == "Two plus two equals four."
          and message["audio"]["format"] == "wav" and wav_facts(base64.b64decode(message["audio"]["data"])) == (24000, 1, 16, 600),
          f"the words, and the voice as a base64 wav of 24 kHz (got {code} {list(message)})")
    check(c.voice.asked[-1][1] == [("text", "listen"), ("audio", b"RIFF....WAVE")],
          f"ONE turn: only the last user message reaches the model, the system and earlier turns do not (got {c.voice.asked[-1][1]})")
    check(c.voice.asked[-1][2:] == (1.0, 4, 1024), f"the model's own sampling for speech: temperature 1.0, top_k 4, 1024 tokens (got {c.voice.asked[-1][2:]})")
    code, out, _ = post(c, "/v1/chat/completions", {"modalities": ["text"], "messages": [{"role": "user", "content": "hi"}]})
    check(code == 200 and "audio" not in out["choices"][0]["message"], "negative: modalities text only: the words, and no audio")
    for doc, why in (({"messages": []}, "no messages"), ({"messages": [{"role": "system", "content": "x"}]}, "no user message"),
                     ({"messages": [{"role": "user", "content": []}]}, "an empty user message"),
                     ({"messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {}}]}]}, "a part we cannot hear"),
                     ({"messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}, {"type": "image_url", "image_url": {}}]}]},
                      "a part we cannot hear among parts we can (it must not be dropped in silence)"),
                     ({"messages": [{"role": "user", "content": [{"type": "input_audio", "input_audio": {}}]}]}, "audio with no data"),
                     ({"messages": [{"role": "user", "content": 5}]}, "a user message that is a number")):
        code, out, _ = post(c, "/v1/chat/completions", doc)
        check(code == 400 and out.get("error"), f"negative: {why} is a 400 with its reason (got {code} {out})")

    print("speech to text, and the routes:")
    code, out, _ = post(c, "/asr", b"RIFF1234")
    check(code == 200 and out == {"text": "what is two plus two"}, f"/asr: the words of the wav (got {code} {out})")
    check(post(c, "/asr", b"")[0] == 400, "negative: /asr with an empty body is a 400")
    code, out, _ = post(c, "/v1/nothing", {})
    check(code == 404 and "/v1/nothing" in out["error"], "an unknown route is a 404 that names it")

    print("the launchers of the voice cells, and the stale-source check:")
    check(cell_assets.group_for_command("bash ~/run_lfm_audio.sh $PORT") == "lfm-audio"
          and cell_assets.group_for_command("bash ~/run_personaplex.sh $PORT /mnt/m") == "personaplex"
          and cell_assets.group_for_command("bash ~/run_vllm_omni.sh $PORT qwen3-omni /mnt/m") in ("step-audio2", "qwen3-omni")
          and cell_assets.group_for_command("bash ~/run_minicpm_omni.sh $PORT /mnt/m") == "minicpm-omni"
          and cell_assets.group_for_command("bash ~/run_tts.sh $PORT xtts") == "custom",
          "a command names its launcher, and the launcher names its group of files (the two vLLM-Omni runners share one launcher)")
    check(cell_assets.group_for_command("python3 srv.py") == "" and cell_assets.group_for_command("") == ""
          and cell_assets.group_for_command("bash ~/run_nothing_of_ours.sh") == "",
          "negative: a command with no launcher of ours, an empty one, and a launcher nobody ships name no group")
    check(cell_assets.RUNNER_ASSETS["lfm-audio"] == ("run_lfm_audio.sh", "cell_base.py", "lfm_audio_server.py")
          and cell_assets.RUNNER_ASSETS["personaplex"] == ("run_personaplex.sh",)
          and cell_assets.RUNNER_ASSETS["step-audio2"] == cell_assets.RUNNER_ASSETS["qwen3-omni"] == ("run_vllm_omni.sh",)
          and cell_assets.RUNNER_ASSETS["minicpm-omni"] == ("run_minicpm_omni.sh",)
          and all(name in cell_assets.CELL_ASSETS for group in ("lfm-audio", "personaplex", "step-audio2", "qwen3-omni", "minicpm-omni")
                  for name in cell_assets.RUNNER_ASSETS[group]),
          "what each launcher needs is in the allowlist the fleet may fetch")
    stamp = cell_assets.server_stamp("lfm-audio")
    command = "bash ~/run_lfm_audio.sh $PORT /mnt/m"
    check(len(stamp) == 12 and stamp != cell_assets.server_stamp("custom"), "LFM's files have a stamp of their own, not the TTS server's")
    check(cell_assets.cell_source_state("custom", stamp, command) == "current", "the cell that runs the files we ship is current, though its runner id is custom")
    check(cell_assets.cell_source_state("custom", stamp) == "stale",
          "negative: with no command the old rule holds (the runner id's files), so the same cell would read as stale — the defect this fixes")
    check(cell_assets.cell_source_state("custom", "0123456789ab", command) == "stale", "negative: another stamp is stale")
    check(cell_assets.cell_source_state("custom", "", command) == "unknown", "negative: a cell that reports nothing is unknown, not stale")
    check(cell_assets.cell_source_state("custom", "", "bash ~/run_personaplex.sh $PORT /mnt/m") == "unknown",
          "PersonaPlex serves itself and reports no stamp: unknown, never stale")
    check(cell_assets.cell_source_state("custom", "", "bash ~/run_vllm_omni.sh $PORT step-audio2 /mnt/m") == "unknown",
          "vLLM-Omni serves itself and reports no stamp: unknown, never stale")
    check(cell_assets.cell_source_state("custom", "", "bash ~/run_minicpm_omni.sh $PORT /mnt/m") == "unknown",
          "llama.cpp-omni serves itself and reports no stamp: unknown, never stale")

    print("the board's verdict on a cell follows its launcher:")
    healthy = {"status": "ok", "meta": {"source": stamp}}
    lfm_cfg = {"CELL_KIND": "command", "COMMAND": command}
    check(_cell_meta(healthy, lfm_cfg, True).get("sourceState") == "current",
          "the LFM cell that runs the files we ship is current on the board")
    check(_cell_meta(healthy, {"CELL_KIND": "command", "COMMAND": "bash ~/run_tts.sh $PORT xtts"}, True).get("sourceState") == "stale",
          "negative: the same stamp under a TTS command is stale: the verdict is per launcher")
    check(_cell_meta(healthy, {"CELL_KIND": "command"}, True).get("sourceState") == "stale",
          "negative: a command cell saved with no COMMAND falls back to the runner id's files")
    check("sourceState" not in _cell_meta(healthy, lfm_cfg, False), "negative: a cell that is no command cell gets no verdict")
    check("sourceState" not in _cell_meta({"status": "loading", "meta": {"source": stamp}}, lfm_cfg, True),
          "negative: a cell that is still loading gets no verdict")
    check("sourceState" not in _cell_meta(None, lfm_cfg, True), "negative: a cell that did not answer gets no verdict")

    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg)
        sys.exit(1)
    print("lfm audio server snapshots hold")


if __name__ == "__main__":
    main()
