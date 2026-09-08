#!/usr/bin/env python3
"""NLLB text translation cell: text in one language -> text in another.

WHY THIS EXISTS ALONGSIDE seamless. The seamless cell goes from speech straight
to translated text in one hop, and refuses to say what it heard. That is the
right trade when you only want the translation. When you want the source words
too — a transcript to show, a name to check — the cascade is the only way:
whisper transcribes, this cell translates, and each half can be inspected.

A dedicated MT model rather than an LLM, because the two fail differently. An
LLM reads the text it is translating as potential instructions; this one cannot
be talked out of translating. It is 600M against 12B, so it is also cheap enough
to run on text nobody is waiting for.

Serves POST /v1/translate — deliberately NOT /v1/chat/completions. Pretending to
be a chat model would invite prompts it cannot follow, and the last time a cell
here borrowed a protocol's field names it inherited their meanings too.

Usage: translate_server.py <port> <model> [src_lang] [tgt_lang]
       model: an HF repo id (facebook/nllb-200-distilled-600M) or a local dir
"""
import json
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cell_base import CellServer   # noqa: E402

MAX_NEW_TOKENS = int(os.environ.get("TRANSLATE_MAX_TOKENS", "256"))

_state = {"ready": False, "error": "", "device": "", "dtype": "", "langs": []}
_lock = threading.Lock()
_model = None
_tokenizer = None
_model_id = "facebook/nllb-200-distilled-600M"
#: The cell's default languages. Kept at module level because _resolve_lang
#: is a free function: it needs a fallback value, not an instance.
_src_lang = "eng_Latn"
_tgt_lang = "rus_Cyrl"


def log(msg):
    print(f"[translate] {msg}", flush=True)


class TranslateCell(CellServer):
    """NLLB: text in, text out, with the language pair named by the caller.

    Unlike the speech cell this one cannot detect its input — NLLB is TOLD the
    source language — so /health says `srcLangRequired` rather than leaving a
    caller to find out from output that is confidently wrong.
    """
    default_port = 8040
    engine = "nllb"
    kinds = ["translate"]
    protocol_version = "HTTP/1.1"
    json_ensure_ascii = False
    json_content_type = "application/json; charset=utf-8"

    @property
    def model_name(self):
        return _model_id

    def is_health(self, path):
        # Anything ending in /health, and the root: what this cell has always
        # answered. A fixed list would 404 a caller already using /v1/health.
        return path == "/" or path.endswith("/health")

    def ready_required(self, path):
        # A POST to a path this cell does not serve is a 404 whether or not the
        # model is up; 503 "model loading" would send the caller off to wait for
        # a load that was never going to make that path exist.
        return path.endswith("/translate") or path.endswith("/translations")

    def extra_health(self):
        return {
            "srcLang": _src_lang, "targetLang": _tgt_lang,
            # FLORES-200: language AND script. Said explicitly because a caller
            # who assumes ISO 639-3 will send `rus` and be surprised — it works
            # here, but only because short codes are resolved.
            "langs": _state.get("langs") or [],
            "codeset": "flores200",
            "acceptsShortCodes": True,
            # Unlike the speech cell, this one cannot detect its input:
            # NLLB is TOLD the source language and translates accordingly.
            "srcLangRequired": True,
            "device": _state.get("device"), "dtype": _state.get("dtype"),
            "maxNewTokens": MAX_NEW_TOKENS,
        }

    def load(self):
        global _model_id, _src_lang, _tgt_lang
        if self.args:
            _model_id = self.args[0]
        if len(self.args) > 1:
            _src_lang = self.args[1]
        if len(self.args) > 2:
            _tgt_lang = self.args[2]
        _load()
        if _state.get("error"):
            raise RuntimeError(_state["error"])

    def _lang_error(self, exc, field):
        payload = {"error": f"unsupported {field} {exc.code!r}",
                   "codeset": "flores200"}
        if exc.candidates:
            payload["error"] = (f"ambiguous {field} {exc.code!r} — "
                                f"name the script")
            payload["candidates"] = exc.candidates
        else:
            payload["accepted"] = _state.get("langs") or []
        return 400, payload, None

    def handle(self, body, headers, path):
        if not path.endswith("/translate") and not path.endswith("/translations"):
            return 404, {"error": "not found"}, None
        try:
            req = json.loads(body or b"{}")
        except Exception:  # noqa: BLE001
            return 400, {"error": "body must be JSON {text|texts, src_lang, tgt_lang}"}, None
        texts = req.get("texts")
        if texts is None:
            single = req.get("text")
            texts = [single] if isinstance(single, str) else None
        if not isinstance(texts, list) or not texts:
            return 400, {"error": "need `text` (string) or `texts` (list of strings)"}, None
        try:
            src = _resolve_lang(req.get("src_lang") or req.get("srcLang"), _src_lang)
        except LangError as exc:
            return self._lang_error(exc, "src_lang")
        try:
            tgt = _resolve_lang(req.get("tgt_lang") or req.get("tgtLang"), _tgt_lang)
        except LangError as exc:
            return self._lang_error(exc, "tgt_lang")
        done = _translate([str(t) for t in texts], src, tgt)
        payload = {"texts": done, "srcLang": src, "tgtLang": tgt}
        # `text` echoed back only when `text` was sent: a caller that asked for a
        # list gets a list, and one that asked for a string does not have to
        # unwrap one. Adding it unconditionally made a batch of 1 look singular.
        if len(done) == 1 and "texts" not in req:
            payload["text"] = done[0]
        return 200, payload, None


def _load():
    global _model, _tokenizer
    try:
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        use_cuda = torch.cuda.is_available()
        dtype = torch.float16 if use_cuda else torch.float32
        _tokenizer = AutoTokenizer.from_pretrained(_model_id)
        model = AutoModelForSeq2SeqLM.from_pretrained(_model_id, dtype=dtype)
        _model = model.to("cuda" if use_cuda else "cpu").eval()
        # The languages this checkpoint has, read from the tokenizer's VOCAB.
        # NLLB codes are FLORES-200: language AND script, eng_Latn / rus_Cyrl.
        # Not from `additional_special_tokens` — NllbTokenizer does not have
        # that attribute at all in transformers 5.x, and the first version of
        # this asked for it inside a try/except, so the failure became an empty
        # list and the cell advertised zero languages while translating fine.
        try:
            vocab = _tokenizer.get_vocab()
            _state["langs"] = sorted(
                c for c in vocab
                if len(c) == 8 and c[3] == "_" and c[:3].isalpha() and c[4:].isalpha())
        except Exception as exc:  # noqa: BLE001
            _state["langs"] = []
            log(f"language list unreadable: {exc}")
        if not _state["langs"]:
            # Say it out loud: an empty list means /health advertises nothing and
            # _resolve_lang stops validating, which is a real degradation and not
            # something to discover from a puzzling 400 later.
            log("WARNING: no language codes found — requests will not be validated")
        _state["device"] = "cuda" if use_cuda else "cpu"
        _state["dtype"] = "float16" if use_cuda else "float32"
        _state["ready"] = True
        log(f"ready on {_state['device']} ({_state['dtype']}), "
             f"{len(_state['langs'])} languages, {_src_lang} -> {_tgt_lang}")
    except Exception as exc:  # noqa: BLE001
        _state["error"] = f"{type(exc).__name__}: {exc}"
        log(f"load failed: {_state['error']}")


# ISO 639-1 -> 639-3, the short codes clients actually send. Only where the
# mapping is unambiguous; anything else must be spelled out.
_ISO1_TO_3 = {
    "af": "afr", "am": "amh", "ar": "arb", "az": "azj", "be": "bel", "bg": "bul",
    "bn": "ben", "bs": "bos", "ca": "cat", "cs": "ces", "cy": "cym", "da": "dan",
    "de": "deu", "el": "ell", "en": "eng", "es": "spa", "et": "est", "eu": "eus",
    "fa": "pes", "fi": "fin", "fr": "fra", "ga": "gle", "gl": "glg", "gu": "guj",
    "he": "heb", "hi": "hin", "hr": "hrv", "hu": "hun", "hy": "hye", "id": "ind",
    "is": "isl", "it": "ita", "ja": "jpn", "ka": "kat", "kk": "kaz", "km": "khm",
    "kn": "kan", "ko": "kor", "lo": "lao", "lt": "lit", "lv": "lvs", "mk": "mkd",
    "ml": "mal", "mr": "mar", "ms": "zsm", "mt": "mlt", "my": "mya", "ne": "npi",
    "nl": "nld", "no": "nob", "pa": "pan", "pl": "pol", "pt": "por", "ro": "ron",
    "ru": "rus", "sk": "slk", "sl": "slv", "so": "som", "sq": "als", "sr": "srp",
    "sv": "swe", "sw": "swh", "ta": "tam", "te": "tel", "th": "tha", "tr": "tur",
    "uk": "ukr", "ur": "urd", "uz": "uzn", "vi": "vie", "zh": "zho", "zu": "zul",
}


class LangError(ValueError):
    """Carries the code, and the candidates when the problem is ambiguity."""

    def __init__(self, code, candidates=None):
        super().__init__(code)
        self.code = code
        self.candidates = candidates or []


def _resolve_lang(code, fallback):
    """A request's language -> a FLORES-200 code this checkpoint has.

    Short codes are accepted, but NOT guessed at when they are ambiguous: NLLB
    separates scripts, so `ace` is both ace_Arab and ace_Latn and `zho` is both
    Hans and Hant. Picking one silently would give the caller confident output
    in a writing system they did not ask for — so ambiguity is an error that
    names the candidates instead.
    """
    raw = str(code or "").strip().replace("-", "_")
    if not raw:
        return fallback
    known = _state.get("langs") or []
    index = {k.lower(): k for k in known}
    hit = index.get(raw.lower())
    if hit:
        return hit
    stem = raw.split("_")[0].lower()
    stem = _ISO1_TO_3.get(stem, stem) if len(stem) == 2 else stem
    matches = [k for k in known if k.lower().startswith(stem + "_")]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise LangError(raw, matches)
    if not known:                       # tokenizer unreadable: let the model judge
        return raw
    raise LangError(raw)


def _translate(texts, src, tgt):
    import torch
    out = []
    with _lock:
        _tokenizer.src_lang = src
        try:
            forced = _tokenizer.convert_tokens_to_ids(tgt)
        except Exception:  # noqa: BLE001
            forced = None
        for text in texts:
            if not text.strip():
                out.append("")
                continue
            batch = _tokenizer(text, return_tensors="pt", truncation=True,
                               max_length=512).to(_model.device)
            with torch.inference_mode():
                gen = _model.generate(**batch, forced_bos_token_id=forced,
                                      max_new_tokens=MAX_NEW_TOKENS)
            out.append(_tokenizer.batch_decode(gen, skip_special_tokens=True)[0].strip())
    return out


if __name__ == "__main__":
    TranslateCell().serve()
