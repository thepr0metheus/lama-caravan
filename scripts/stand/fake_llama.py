"""The stand's llama-server: takes the real command line, computes nothing, and holds memory on the stand's cards.

What the caravan built is written down word for word in <stand>/launches/<port>.json, so a check reads what a start would
have run on a real machine. Where the memory goes follows llama.cpp's own rules closely enough to catch a wrong plan:
the cards CUDA_VISIBLE_DEVICES leaves, --device, --tensor-split in the order of the visible cards, layers past -ngl in RAM.
A plan that does not fit dies as llama.cpp dies, with its words and exit code 1.
"""
import json
import os
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cards import StandCards

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gguf_reader import GgufHeader  # noqa: E402


class Flags:
    """The command line by the flags this stand-in cares for; the rest is written down and passed over."""

    ALIASES = {"-m": "--model", "-c": "--ctx-size", "-np": "--parallel", "-ngl": "--n-gpu-layers", "--gpu-layers": "--n-gpu-layers",
               "-ts": "--tensor-split", "-dev": "--device", "-a": "--alias"}

    def __init__(self, argv):
        self.values = {}
        for index, word in enumerate(argv[:-1]):
            if word.startswith("-"):
                self.values[self.ALIASES.get(word, word)] = argv[index + 1]

    def get(self, name, default=""):
        return self.values.get(name, default)


class InvalidDevice(Exception):
    """--device named a card this process cannot see."""


class ModelFacts:
    """What the model's header says, as far as memory goes."""

    def __init__(self, layers, embedding, heads, heads_kv, weights_mib):
        self.layers, self.embedding, self.heads, self.heads_kv = layers, embedding, heads, heads_kv
        self.weights_mib = weights_mib

    @classmethod
    def of(cls, header, weights_mib):
        arch = header.get("general.architecture", "")

        def fact(suffix):
            return int(header.get(f"{arch}.{suffix}") or 0)

        return cls(fact("block_count"), fact("embedding_length"), fact("attention.head_count"),
                   fact("attention.head_count_kv"), weights_mib)

    def kv_mib(self, window):
        """llama.cpp's cache at F16: keys and values, one per token, in every layer, over the heads it keeps."""
        if not self.heads:
            return 0.0
        return window * self.layers * (self.embedding / self.heads * self.heads_kv) * 2 * 2 / (1024 * 1024)


class Placement:
    """Which card holds how much. `free` is {card index: MiB free now}; `model` is what its header says (ModelFacts)."""

    #: llama.cpp's own margin when --fit names none.
    FIT_MARGIN_MIB = 1024

    def __init__(self, flags, env, free, model):
        self.flags, self.env, self.free, self.model = flags, env, free, model
        self.layers_on = {}     # {card index: whole layers}; what is not here lies in RAM

    def visible(self):
        """The real indexes of the cards this process may use, in the order it sees them."""
        said = self.env.get("CUDA_VISIBLE_DEVICES")
        if said is None:
            cards = sorted(self.free)
        else:
            cards = [int(word) for word in said.split(",") if word.strip().lstrip("-").isdigit() and int(word) >= 0]
        device = self.flags.get("--device").strip()
        if device.lower() == "none":
            return []
        if device:
            picked = []
            for word in device.split(","):
                number = word.strip().upper().removeprefix("CUDA")
                # llama.cpp counts the cards it can see: with one visible, CUDA1 is no device and the server does not start.
                if not number.isdigit() or int(number) >= len(cards):
                    raise InvalidDevice(word.strip())
                picked.append(cards[int(number)])
            return picked
        return cards

    def window(self):
        said = self.flags.get("--ctx-size", "0").strip()
        return int(said) if said.isdigit() else 0

    def layer_mib(self):
        """One layer's weights and its share of the KV cache."""
        model = self.model
        return (model.weights_mib + model.kv_mib(self.window())) / model.layers if model.layers else 0.0

    def margins(self, count):
        said = [int(word) for word in self.flags.get("--fit-target").split(",") if word.strip()]
        if not said:
            return [self.FIT_MARGIN_MIB] * count
        return (said + [said[-1]] * count)[:count]

    def fit(self, cards):
        """--fit on: whole layers, card after card, each card keeping its --fit-target free; the rest stays in RAM."""
        layer, left = self.layer_mib(), self.model.layers
        for card, margin in zip(cards, self.margins(len(cards))):
            count = min(left, max(0, int((self.free[card] - margin) // layer))) if layer else 0
            if count:
                self.layers_on[card] = count
                left -= count
        return {card: int(count * layer) for card, count in self.layers_on.items()}

    def asked_layers(self):
        said = self.flags.get("--n-gpu-layers", "auto").strip().lower()
        return self.model.layers if said in ("auto", "all", "max", "") else min(int(said), self.model.layers)

    def split(self, cards):
        """No --fit: the asked layers on the cards, by --tensor-split in the order of the visible cards, else by their room."""
        said = [word for word in self.flags.get("--tensor-split").split(",") if word.strip()]
        wanted = [float(word) for word in said][:len(cards)]
        if not wanted or sum(wanted) <= 0:
            cards_room = [self.free[card] for card in cards]
            wanted = cards_room if sum(cards_room) else [1] * len(cards)
        asked, layer = self.asked_layers(), self.layer_mib()
        shares = {}
        if not asked:
            return shares
        for card, value in zip(cards, wanted):
            share = value / sum(wanted)
            if share > 0:
                self.layers_on[card] = round(asked * share)
                shares[card] = int(asked * share * layer)
        return shares

    def shares(self):
        """{card index: MiB}; {} when nothing goes on a card."""
        cards = self.visible()
        if not cards or not self.model.layers:
            return {}
        return self.fit(cards) if self.flags.get("--fit") == "on" else self.split(cards)

    def short(self, shares):
        """The first card this does not fit on, with what it asks and what is free, or None."""
        for card, mib in shares.items():
            if mib > self.free[card]:
                return card, mib, self.free[card]
        return None


class FakeServer:
    LOAD_SECONDS = 2.0

    def __init__(self, argv, env, cards):
        self.argv, self.env, self.cards = list(argv), dict(env), cards
        self.flags = Flags(self.argv)
        self.port = int(self.flags.get("--port", "0"))
        self.model = Path(self.flags.get("--model"))
        self.header = GgufHeader.read(self.model, 256) if self.model.is_file() else {}
        self.ready_at = 0.0

    def fact(self, suffix, default=0):
        arch = self.header.get("general.architecture", "")
        return self.header.get(f"{arch}.{suffix}", default)

    def model_id(self):
        return self.flags.get("--alias") or self.model.stem

    def window(self):
        said = self.flags.get("--ctx-size", "0").strip()
        return int(said) if said.isdigit() and int(said) else int(self.fact("context_length", 4096))

    def write_launch(self, root, shares, layers):
        folder = Path(root) / "launches"
        folder.mkdir(parents=True, exist_ok=True)
        keep = {key: self.env[key] for key in ("CUDA_VISIBLE_DEVICES",) if key in self.env}
        (folder / f"{self.port}.json").write_text(json.dumps(
            {"pid": os.getpid(), "argv": self.argv, "env": keep, "shares": {str(k): v for k, v in shares.items()},
             "layers": {str(k): v for k, v in layers.items()}, "at": int(time.time())}, indent=1), encoding="utf-8")

    def respond(self, handler, method, path):
        path = path.split("?", 1)[0]
        if time.time() < self.ready_at and path not in ("/health", "/v1/health"):
            path = "/health"
        if path in ("/health", "/v1/health"):
            if time.time() < self.ready_at:
                return 503, {"error": {"code": 503, "message": "Loading model", "type": "unavailable_error"}}
            return 200, {"status": "ok"}
        if path == "/props":
            return 200, {"default_generation_settings": {"n_ctx": self.window()}, "total_slots": 1,
                         "model_path": str(self.model), "build_info": "stand",
                         "modalities": {"vision": False, "audio": False}}
        if path == "/slots":
            return 200, [{"id": 0, "n_ctx": self.window(), "is_processing": False}]
        if path in ("/v1/models", "/models"):
            row = {"id": self.model_id(), "object": "model", "owned_by": "stand",
                   "meta": {"n_ctx_train": int(self.fact("context_length", 0)), "size": self.model.stat().st_size}}
            return 200, {"object": "list", "data": [row]}
        if path == "/metrics":
            return 200, "llamacpp:requests_processing 0\nllamacpp:requests_deferred 0\n"
        if path == "/v1/chat/completions" and method == "POST":
            return 200, {"id": "stand", "object": "chat.completion", "model": self.model_id(),
                         "choices": [{"index": 0, "finish_reason": "stop",
                                      "message": {"role": "assistant", "content": "The stand has no model: it only holds memory."}}],
                         "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
        return 404, {"error": {"code": 404, "message": f"the stand does not answer {path}"}}

    def serve(self):
        server_self = self

        class Handler(BaseHTTPRequestHandler):
            def answer(self, method):
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    self.rfile.read(length)
                status, body = server_self.respond(self, method, self.path)
                is_text = isinstance(body, str)
                raw = body.encode() if is_text else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "text/plain" if is_text else "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):  # noqa: N802
                self.answer("GET")

            def do_POST(self):  # noqa: N802
                self.answer("POST")

            def log_message(self, *args):
                pass

        # Loopback whatever --host says: the stand runs on a laptop, on whatever network it happens to be on.
        return ThreadingHTTPServer(("127.0.0.1", self.port), Handler)

    def run(self, root) -> int:
        if not self.model.is_file():
            print(f"error: failed to open model: {self.model}", flush=True)
            return 1
        claims = self.cards.claims()
        free = {card["index"]: self.cards.free_mib(card["index"], claims) for card in StandCards.CARDS}
        placement = Placement(self.flags, self.env, free, ModelFacts.of(self.header, self.model.stat().st_size // (1024 * 1024)))
        try:
            shares = placement.shares()
        except InvalidDevice as exc:
            self.write_launch(root, {}, {})
            print(f'error while handling argument "--device": invalid device: {exc}', flush=True)
            return 1
        self.write_launch(root, shares, placement.layers_on)
        short = placement.short(shares)
        if short:
            card, asks, room = short
            print(f"ggml_backend_cuda_buffer_type_alloc_buffer: allocating {asks} MiB on device {card}: "
                  f"cudaMalloc failed: out of memory ({room} MiB free)", flush=True)
            print("llama_init_from_model: failed to load model", flush=True)
            return 1
        self.cards.claim(os.getpid(), "llama-server", shares)
        self.ready_at = time.time() + self.LOAD_SECONDS
        print(f"stand llama-server on :{self.port} holds {shares} (MiB by card)", flush=True)
        server = self.serve()

        def stop(_signum, _frame):
            self.cards.release(os.getpid())
            threading.Thread(target=server.shutdown, daemon=True).start()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        server.serve_forever()
        self.cards.release(os.getpid())
        return 0


def main():
    argv = sys.argv[1:]
    if "--version" in argv:
        print("version: 9999 (stand)")
        print("built with the caravan's stand: no engine inside")
        return
    if "--help" in argv or "-h" in argv:
        print("usage: llama-server (the caravan's stand: takes every flag, computes nothing)")
        return
    sys.exit(FakeServer(argv, os.environ, StandCards.from_env()).run(os.environ[StandCards.ROOT_VAR]))
