#!/usr/bin/env python3
"""LFM2.5-Audio cell: Liquid AI's 1.5B audio model, and it SPEAKS.

The llama.cpp and vLLM cells of this caravan answer in text, and llama.cpp cannot make this model's voice at
all: its audio output lives in Liquid's own PyTorch package (`liquid-audio`), not in the mainline runner. This
cell runs that package on the GPU behind the HTTP shapes the caravan already speaks. Run with the package's own
venv (run_lfm_audio.sh makes it and starts this file).

    GET  /health                -> 200 while ready, 503 {"status": "loading"} before
    POST /v1/audio/speech       -> OpenAI text-to-speech: {"input", "voice", "response_format": "wav"|"pcm"}
                                   -> audio bytes, 24 kHz mono (pcm: 16-bit little-endian). The voice is one of
                                   us_male, us_female, uk_male, uk_female; any other name (OpenAI's "alloy") is
                                   the default, us_female.
    POST /v1/chat/completions   -> a spoken answer: {"messages": [{"role": "user", "content": "text" |
                                   [{"type": "input_audio", "input_audio": {"data": <base64 wav>, "format": "wav"}}]}]}
                                   -> message.content (the words) and message.audio.data (base64 wav of the voice).
                                   ONE turn: the model answers the last user message; system messages and earlier
                                   turns are ignored (the only prompt it takes for speech-to-speech is its own).
    POST /asr                   -> a wav as the raw body -> {"text"}

English only: Liquid lists other languages as "in progress". Modes are the model's own system prompts
("Perform TTS. Use the US female voice.", "Respond with interleaved text and audio.", "Perform ASR.").

The cell declares only what it serves the way the caravan's consumers expect: `tts`. The chat and ASR routes
are documented above, not advertised: a consumer that chose this cell as a chat model or as a recognizer by
its `kinds` would send what those kinds mean (a history, a multipart upload) and get a one-turn answer.

Usage: lfm_audio_server.py [port] [model-dir]    (model-dir: the folder that holds model.safetensors and
audio_detokenizer/; default $LFM_MODEL_DIR, else the models library's copy)
"""
# Deferred so no annotation is evaluated at import: the macOS client runs stock Python 3.9, where a PEP-604
# union in a def is a TypeError that stops the module loading.
from __future__ import annotations

import base64
import io
import json
import os
import re
import sys
import threading
import time
import wave

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cell_base import CellServer   # noqa: E402

SAMPLE_RATE = 24_000
#: The model's end-of-audio code: a frame that holds it is dropped, not decoded.
END_OF_AUDIO = 2048
VOICES = {f"{a}_{b}": f"Perform TTS. Use the {a.upper()} {b} voice." for a in ("us", "uk") for b in ("male", "female")}
DEFAULT_VOICE = "us_female"
#: The only system prompt the model answers speech-to-speech with (Liquid's issue #17: a persona is ignored).
SPEECH_PROMPT = "Respond with interleaved text and audio."
ASR_PROMPT = "Perform ASR."
DEFAULT_MODEL_DIR = "/mnt/lama-caravan-models/LFM2.5-Audio-1.5B/LiquidAI/SAFETENSORS"
#: A text longer than this is spoken in pieces of whole sentences: the model's text-to-speech degrades on a long run.
PIECE_CHARS = 240
MAX_NEW_TOKENS = 4096


def log(msg):
    print(msg, flush=True)


class BadRequest(Exception):
    """The caller's request cannot be answered as written: 400 with the reason, never a guess."""


def split_text(text, limit=PIECE_CHARS):
    """The text as pieces of whole sentences, each at most `limit` characters unless one sentence is longer."""
    pieces, current = [], ""
    for part in re.split(r"(?<=[.!?])\s+", str(text).strip()):
        if current and len(current) + len(part) + 1 > limit:
            pieces.append(current)
            current = part
        else:
            current = f"{current} {part}".strip()
    return pieces + ([current] if current else [])


def voice_of(name):
    """The voice a request names, as one of ours; an unknown name is the default voice."""
    key = str(name or "").lower().replace("-", "_").replace(" ", "_")
    return key if key in VOICES else DEFAULT_VOICE


def pcm_wav(pcm16):
    """16-bit mono 24 kHz little-endian samples as a wav file."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SAMPLE_RATE)
        out.writeframes(pcm16)
    return buf.getvalue()


def user_parts(content):
    """What a user message says, as [("text", str) | ("audio", wav bytes)]."""
    if isinstance(content, str):
        return [("text", content)]
    if not isinstance(content, list):
        raise BadRequest("the user message must be text or a list of parts")
    parts = []
    for part in content:
        kind = part.get("type") if isinstance(part, dict) else None
        if kind == "text":
            parts.append(("text", str(part.get("text") or "")))
        elif kind == "input_audio":
            try:
                parts.append(("audio", base64.b64decode(part["input_audio"]["data"])))
            except (KeyError, TypeError, ValueError):
                raise BadRequest("input_audio needs base64 wav data") from None
        else:
            raise BadRequest(f"unsupported content part: {kind}")
    if not parts:
        raise BadRequest("the user message is empty")
    return parts


class LfmVoice:
    """The model side: torch and liquid-audio, loaded once. Everything it returns is plain Python (PCM bytes, text)."""

    def __init__(self, model_dir):
        # Before anything imports transformers: a cell reads its weights from the library, never from the hub.
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        import torch
        from pathlib import Path
        from liquid_audio import ChatState, LFM2AudioModel, LFM2AudioProcessor
        self.torch, self.ChatState = torch, ChatState
        # A Path, not a string: a string is taken for a hub repository and triggers a download.
        path = Path(model_dir)
        self.proc = LFM2AudioProcessor.from_pretrained(path).eval()
        self.model = LFM2AudioModel.from_pretrained(path).eval()
        self.lock = threading.Lock()

    def vram_gib(self):
        return round(self.torch.cuda.memory_allocated() / 2 ** 30, 2)

    def _chat(self, system):
        chat = self.ChatState(self.proc)
        chat.new_turn("system")
        chat.add_text(system)
        chat.end_turn()
        chat.new_turn("user")
        return chat

    def _add_wav(self, chat, raw):
        import numpy as np
        import soundfile
        wav, rate = soundfile.read(io.BytesIO(raw), dtype="float32")
        if wav.ndim == 2:
            wav = wav.mean(1)
        chat.add_audio(self.torch.from_numpy(np.ascontiguousarray(wav))[None], rate)

    def _reply(self, chat):
        chat.end_turn()
        chat.new_turn("assistant")

    def _pcm(self, frames):
        import numpy as np
        frames = [f for f in frames if not (f == END_OF_AUDIO).any()]
        if not frames:
            return b""
        codes = self.torch.stack(frames, 1).unsqueeze(0)
        wave_f = self.proc.decode(codes)[0].float().cpu().numpy()
        return (np.clip(wave_f, -1, 1) * 32767).astype("<i2").tobytes()

    def _words(self, tokens):
        if not tokens:
            return ""
        return re.sub(r"<\|[^|>]*\|>", "", self.proc.text.decode(self.torch.cat(tokens))).strip()

    def tts(self, text, voice, temperature=0.8, top_k=64, max_new_tokens=1024):
        silence = b"\x00\x00" * int(0.15 * SAMPLE_RATE)
        out = []
        with self.lock, self.torch.no_grad():
            for piece in split_text(text):
                chat = self._chat(VOICES[voice])
                chat.add_text(piece)
                self._reply(chat)
                frames = [t for t in self.model.generate_sequential(
                    **chat, max_new_tokens=max_new_tokens, audio_temperature=temperature, audio_top_k=top_k)
                    if t.numel() > 1]
                out += [self._pcm(frames), silence]
        return b"".join(out[:-1])

    def speak(self, parts, temperature=1.0, top_k=4, max_new_tokens=1024):
        """Answer the user's parts in speech: (the words, PCM bytes)."""
        with self.lock, self.torch.no_grad():
            chat = self._chat(SPEECH_PROMPT)
            for kind, value in parts:
                if kind == "text":
                    chat.add_text(value)
                else:
                    self._add_wav(chat, value)
            self._reply(chat)
            text, frames = [], []
            for t in self.model.generate_interleaved(
                    **chat, max_new_tokens=max_new_tokens, audio_temperature=temperature, audio_top_k=top_k):
                (text if t.numel() == 1 else frames).append(t)
            return self._words(text), self._pcm(frames)

    def asr(self, raw):
        with self.lock, self.torch.no_grad():
            chat = self._chat(ASR_PROMPT)
            self._add_wav(chat, raw)
            self._reply(chat)
            tokens = [t for t in self.model.generate_sequential(**chat, max_new_tokens=512) if t.numel() == 1]
            return self._words(tokens)


class LfmAudioCell(CellServer):
    """One cell: the model behind a port, speaking."""
    default_port = 8031
    engine = "lfm-audio"
    kinds = ["tts", "tts.lfm-audio"]
    work_path = ""

    def __init__(self, argv=None):
        super().__init__(argv)
        self.model_dir = (self.args[0] if self.args else os.environ.get("LFM_MODEL_DIR") or DEFAULT_MODEL_DIR)
        self.voice = None

    @property
    def model_name(self):
        """The model's folder as the library lays it out, <model>/<author>/<format>: the first of the three."""
        parts = [p for p in self.model_dir.rstrip("/").split("/") if p]
        return parts[-3] if len(parts) >= 3 else (parts[-1] if parts else "LFM2.5-Audio-1.5B")

    def load(self):
        for needed in ("model.safetensors", "audio_detokenizer"):
            if not os.path.exists(os.path.join(self.model_dir, needed)):
                raise FileNotFoundError(f"{self.model_dir}/{needed} is missing: download LiquidAI/LFM2.5-Audio-1.5B "
                                        f"(the safetensors checkpoint) on the /hf page first")
        self.voice = LfmVoice(self.model_dir)
        started = time.time()
        # Lazy parts of the model (the detokenizer, CUDA kernels) are built on the first words spoken: not by a caller.
        self.voice.tts("Ready.", DEFAULT_VOICE)
        log(f"[{self.engine}] loaded, warm-up {time.time() - started:.1f}s, VRAM {self.voice.vram_gib()} GiB")

    def extra_health(self):
        return {"voices": list(VOICES), "sampleRate": SAMPLE_RATE, "vramGiB": self.voice.vram_gib() if self.voice else 0}

    def handle(self, body, headers, path):
        if path == "/v1/audio/speech":
            return self._speech(body)
        if path == "/v1/chat/completions":
            return self._speak(body)
        if path == "/asr":
            return self._asr(body)
        return 404, {"error": f"no such route: {path}"}, "application/json"

    def _json(self, body):
        try:
            doc = json.loads(body or b"{}")
        except ValueError:
            raise BadRequest("the body is not JSON") from None
        if not isinstance(doc, dict):
            raise BadRequest("the body must be a JSON object")
        return doc

    def _number(self, doc, key, default, low, high):
        try:
            return min(max(type(default)(doc.get(key, default)), low), high)
        except (TypeError, ValueError):
            raise BadRequest(f"{key} must be a number") from None

    def _speech(self, body):
        try:
            doc = self._json(body)
            text = str(doc.get("input") or "").strip()
            if not text:
                raise BadRequest("input is empty")
            fmt = str(doc.get("response_format") or "wav").lower()
            if fmt not in ("wav", "pcm"):
                raise BadRequest("response_format must be wav or pcm")
            voice = voice_of(doc.get("voice"))
            started = time.time()
            pcm = self.voice.tts(text, voice, self._number(doc, "temperature", 0.8, 0.0, 2.0),
                                 self._number(doc, "top_k", 64, 1, 1000),
                                 self._number(doc, "max_new_tokens", 1024, 16, MAX_NEW_TOKENS))
        except BadRequest as err:
            return 400, {"error": str(err)}, "application/json"
        seconds = len(pcm) / 2 / SAMPLE_RATE
        log(f"[{self.engine}] speech {voice}: {seconds:.1f}s of audio in {time.time() - started:.1f}s")
        return (200, pcm, "audio/pcm") if fmt == "pcm" else (200, pcm_wav(pcm), "audio/wav")

    def _speak(self, body):
        try:
            doc = self._json(body)
            user = next((m for m in reversed(doc.get("messages") or []) if isinstance(m, dict) and m.get("role") == "user"), None)
            if user is None:
                raise BadRequest("need a user message")
            parts = user_parts(user.get("content"))
            started = time.time()
            words, pcm = self.voice.speak(parts, self._number(doc, "audio_temperature", 1.0, 0.0, 2.0),
                                          self._number(doc, "audio_top_k", 4, 1, 1000),
                                          self._number(doc, "max_tokens", 1024, 16, MAX_NEW_TOKENS))
        except BadRequest as err:
            return 400, {"error": str(err)}, "application/json"
        log(f"[{self.engine}] spoken answer: {len(pcm) / 2 / SAMPLE_RATE:.1f}s of audio in {time.time() - started:.1f}s")
        message = {"role": "assistant", "content": words}
        if "audio" in (doc.get("modalities") or ["text", "audio"]):
            message["audio"] = {"id": f"audio-{int(time.time() * 1000)}", "data": base64.b64encode(pcm_wav(pcm)).decode(),
                                "transcript": words, "format": "wav", "sample_rate": SAMPLE_RATE}
        answer = {"id": f"chatcmpl-{int(time.time() * 1000)}", "object": "chat.completion", "created": int(time.time()),
                  "model": self.model_name, "choices": [{"index": 0, "message": message, "finish_reason": "stop"}]}
        return 200, answer, "application/json"

    def _asr(self, body):
        if not body:
            return 400, {"error": "the body must be a wav file"}, "application/json"
        return 200, {"text": self.voice.asr(body)}, "application/json"


def main():
    LfmAudioCell().serve()


if __name__ == "__main__":
    main()
