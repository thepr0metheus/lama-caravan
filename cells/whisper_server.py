#!/usr/bin/env python3
"""OpenAI-compatible faster-whisper server for a voice app's --asr-endpoint.

Serves POST /v1/audio/transcriptions (multipart wav -> {"text": ...}) on your GPU.

The skeleton — argv, the port, the loading thread, /health with its required
fields, and the rule that a failure never answers success — lives in
cell_base.CellServer. What stays here is what makes this cell whisper: the
download-with-progress hook, the multipart parsing, and the transcription.

Setup (on the GPU box):
    python3 -m venv ~/wsr && ~/wsr/bin/pip install faster-whisper \\
        nvidia-cudnn-cu12 nvidia-cublas-cu12
    bash run_whisper.sh 8000 large-v3     # sets LD_LIBRARY_PATH for CTranslate2
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cell_base import CellServer   # noqa: E402


class WhisperCell(CellServer):
    default_port = 8000
    engine = "faster-whisper"
    # "asr" is the job, "stt.whisper" the engine behind it. Both, because a
    # consumer choosing by job must not have to know engines, and one that
    # already matches on "stt.whisper" keeps working.
    kinds = ["asr", "stt.whisper"]

    @property
    def model_name(self):
        return self.args[0] if self.args else "large-v3"

    def load(self):
        from faster_whisper import WhisperModel
        model_ref = self._download_with_progress() or self.model_name
        self.state["phase"] = "loading"
        self.log(f"whisper: loading '{self.model_name}' on CUDA …")
        self.model = WhisperModel(model_ref, device="cuda", compute_type="float16")
        self.state["downloaded"] = self.state["total"] or self.state["downloaded"]

    def _download_with_progress(self):
        """Fetch the model files first, updating self.state with byte progress so the
        admin UI can show a percentage. Best-effort: on any problem we return None
        and let WhisperModel download on load (just without the percentage)."""
        try:
            from faster_whisper.utils import _MODELS
            import huggingface_hub
            from huggingface_hub.utils import tqdm as _hf_tqdm
        except Exception as exc:  # noqa: BLE001
            self.log(f"whisper: progress hook unavailable ({exc})")
            return None
        repo = _MODELS.get(self.model_name, self.model_name) if isinstance(_MODELS, dict) else self.model_name
        try:
            info = huggingface_hub.HfApi().model_info(repo, files_metadata=True)
            self.state["total"] = sum(int(getattr(f, "size", 0) or 0) for f in (info.siblings or []))
        except Exception:  # noqa: BLE001
            self.state["total"] = 0
    
        # `state` is bound here, not read off `self`: inside this class `self` is
        # the progress bar, not the cell. Written as self.state it raised
        # AttributeError on every chunk, straight into the except below, and the
        # board drew a 3 GB download sitting at 0% for its whole duration — a
        # stalled download and a working one look identical that way.
        state = self.state

        class _T(_hf_tqdm):  # sum bytes across all downloaded files
            def update(self, n=1):
                try:
                    state["downloaded"] += int(n or 0)
                except Exception:  # noqa: BLE001
                    pass
                return super().update(n)
    
        self.state["phase"] = "downloading"
        self.log(f"whisper: downloading '{self.model_name}' ({self.state['total'] / 1e9:.1f} GB) …")
        return huggingface_hub.snapshot_download(repo, tqdm_class=_T)

    def handle(self, body, headers, path):
        wav = _extract_file(body, headers.get("Content-Type", ""))
        lang = _field(body, "language")
        task = _field(body, "task")           # "translate" -> whisper any->en
        # WHEN each word was said. A live transcriber re-runs this on a growing
        # buffer and, once a sentence has settled, wants to drop the audio it
        # already covered — which it can only do if it knows where that sentence
        # ended in TIME. Without it the buffer keeps growing and every request
        # re-transcribes the whole thing from the top: a 30 s phrase costs
        # thirty ever-longer passes instead of thirty short ones.
        #
        # Off unless asked. Word timestamps cost an extra alignment pass, and
        # the answer for everyone who does not ask stays byte-for-byte what it
        # was — this endpoint has LAN clients that predate the field.
        fmt = (_field(body, "response_format") or "json").strip().lower()
        grans = [g.strip().lower() for g in _fields(body, "timestamp_granularities[]")
                 + _fields(body, "timestamp_granularities")]
        want_words = "word" in grans
        # Segments are needed by every format that carries timing, not just the
        # verbose one — srt and vtt ARE segment lists, just written differently.
        want_segs = fmt in ("verbose_json", "srt", "vtt") or want_words
        translating = task == "translate"
        text = ""
        failure = ""                          # set when transcription raised
        detected = ""                         # what whisper decided it heard
        out_segs, out_words, duration = [], [], 0.0
        if wav:
            path = tempfile.mktemp(suffix=".wav")
            try:
                with open(path, "wb") as f:
                    f.write(wav)
                segs, info = self.model.transcribe(
                    path, language=(lang or None), beam_size=1, vad_filter=False,
                    word_timestamps=want_words,
                    task=("translate" if translating else "transcribe"))
                # `segs` is a GENERATOR — whisper does the work as it is walked,
                # so everything must be collected in this single pass.
                parts = []
                for s in segs:
                    parts.append(s.text.strip())
                    if want_segs:
                        out_segs.append({"id": len(out_segs),
                                         "start": round(float(s.start), 3),
                                         "end": round(float(s.end), 3),
                                         "text": s.text})
                    for w in (getattr(s, "words", None) or []):
                        out_words.append({"word": w.word,
                                          "start": round(float(w.start), 3),
                                          "end": round(float(w.end), 3)})
                text = " ".join(parts).strip()
                # report the auto-detected language: on a short clip whisper's
                # guess is often wrong, and a client that knows which languages
                # are actually in play can only correct it if it's told
                detected = str(getattr(info, "language", "") or "")
                duration = float(getattr(info, "duration", 0.0) or 0.0)
            except Exception as e:  # noqa: BLE001
                sys.stderr.write(f"transcribe error: {e}\n")
                failure = f"{type(e).__name__}: {e}"
            finally:
                try:
                    os.remove(path)
                except OSError:
                    pass
        # A transcription that FAILED is not a transcription of silence. The
        # error was logged and then execution fell through to the normal
        # response, so a caller got 200 with {"text": ""} — indistinguishable
        # from a clip with nothing in it, and the reason (here: the GPU was
        # full) reached nobody. Observed live 2026-08-18: whisper answered
        # empty for twenty minutes while the log filled with CUDA OOM.
        if failure:
            return 500, json.dumps({"error": failure}).encode(), "application/json; charset=utf-8"
        # Answer in the shape that was ASKED for. Returning JSON to a client that
        # requested srt is the same class of wrong as returning nothing: it looks
        # like an answer and is not the one requested.
        if fmt == "text":
            return 200, (text + "\n").encode(), "text/plain; charset=utf-8"
        if fmt in ("srt", "vtt"):
            lines = ["WEBVTT", ""] if fmt == "vtt" else []
            for i, s in enumerate(out_segs, 1):
                if fmt == "srt":
                    lines.append(str(i))
                lines.append(f"{_ts(s['start'], fmt == 'srt')} --> {_ts(s['end'], fmt == 'srt')}")
                lines.append(s["text"].strip())
                lines.append("")
            ctype = "text/vtt; charset=utf-8" if fmt == "vtt" else "application/x-subrip; charset=utf-8"
            return 200, "\n".join(lines).encode(), ctype
        payload = {"text": text, "language": detected}
        if fmt == "verbose_json":
            payload.update({"task": "translate" if translating else "transcribe",
                            "duration": round(duration, 3),
                            "segments": out_segs})
            # Top level, where the OpenAI schema puts it, and only when asked —
            # an empty list would read as "no words found" rather than "not
            # requested", and a caller cannot tell those apart.
            if want_words:
                payload["words"] = out_words
        return 200, json.dumps(payload).encode(), "application/json"


def _boundary(ctype):
    for part in ctype.split(";"):
        part = part.strip()
        if part.startswith("boundary="):
            return part[len("boundary="):].strip('"')
    return None


def _extract_file(body, ctype):
    b = _boundary(ctype)
    if not b:
        return None
    sep = b"--" + b.encode()
    for part in body.split(sep):
        head, _, rest = part.partition(b"\r\n\r\n")
        if b"filename=" in head and rest:
            return rest.rsplit(b"\r\n", 1)[0]
    return None


def _fields(body, name):
    """EVERY value sent under this field name, in order.

    Repeated names are normal in this API — `timestamp_granularities[]` is sent
    once per granularity, so a client asking for both segment and word sends two
    parts. Reading only the first would silently drop whichever came second.
    """
    key = ('name="%s"' % name).encode()
    out, at = [], 0
    while True:
        i = body.find(key, at)
        if i < 0:
            return out
        s = body.find(b"\r\n\r\n", i)
        if s < 0:
            return out
        s += 4
        e = body.find(b"\r\n", s)
        if e > s:
            out.append(body[s:e].decode(errors="replace"))
        at = e if e > i else i + len(key)


def _field(body, name):
    vals = _fields(body, name)
    return vals[0] if vals else None


def _ts(seconds, comma=False):
    """HH:MM:SS,mmm — the timestamp shape SRT and WebVTT want."""
    ms = int(round(float(seconds) * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return "%02d:%02d:%02d%s%03d" % (h, m, s, "," if comma else ".", ms)


if __name__ == "__main__":
    WhisperCell().serve()
