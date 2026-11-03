"""The stand's vLLM: takes the real `vllm serve` line, computes nothing, and holds what vLLM would hold.

It stands where the caravan looks for vLLM, in its venv under the stand's HOME, and is started by the real shell line of a real
command cell. vLLM reserves its share of a card up front (--gpu-memory-utilization of the card, the smallest card's when
tensor-parallel), and dies at load when the weights leave it no room for the cache; --cpu-offload-gb takes that many GiB of the
weights of each card off it and keeps them in RAM (vllm/config/offload.py, 0.30.0).
"""
import json
import os
import signal
import sys
import threading
import time
from pathlib import Path

from cards import StandCards
from fake_llama import FakeServer, Flags


class VllmPlacement:
    #: What a card keeps for the activations and the CUDA graphs: the caravan's VllmPlacement.MARGIN_GB, as measured.
    MARGIN_MIB = 1024

    def __init__(self, flags, env, totals, weights_mib):
        self.flags, self.env, self.totals, self.weights_mib = flags, env, totals, weights_mib

    def number(self, name, default):
        said = self.flags.get(name).strip()
        return float(said) if said else default

    def cards(self):
        said = self.env.get("CUDA_VISIBLE_DEVICES")
        seen = sorted(self.totals) if said is None else [int(word) for word in said.split(",") if word.strip().isdigit()]
        return seen[:int(self.number("--tensor-parallel-size", 1))]

    def share_mib(self, cards):
        """What it reserves of each card: every tensor-parallel worker takes what the smallest card allows."""
        base = min(self.totals[card] for card in cards)
        return {card: int(self.number("--gpu-memory-utilization", 0.9) * (base if len(cards) > 1 else self.totals[card])) for card in cards}

    def offload_mib(self, cards):
        """The weights of each card that stay in RAM: no more than it has."""
        return min(self.number("--cpu-offload-gb", 0) * 1024, self.weights_mib / len(cards)) if cards else 0

    def on_card_mib(self, cards):
        return self.weights_mib / len(cards) - self.offload_mib(cards) if cards else 0

    def no_room(self, shares):
        """vLLM's words when the weights leave no room for its cache, or None."""
        for mib in shares.values():
            if self.on_card_mib(list(shares)) > mib - self.MARGIN_MIB:
                return "ValueError: No available memory for the cache blocks. Try increasing `gpu_memory_utilization` when initializing the engine."
        return None


class FakeVllm(FakeServer):
    def __init__(self, argv, env, cards):
        super().__init__(argv, env, cards)
        # `vllm serve <model> --flags`
        self.command = argv[0] if argv else ""
        self.model = Path(argv[1]) if len(argv) > 1 else Path("")
        self.header = {}

    def model_id(self):
        return self.flags.get("--served-model-name") or self.model.name

    def window(self):
        said = self.flags.get("--max-model-len", "0").strip()
        return int(said) if said.isdigit() and int(said) else 4096

    def weights_mib(self):
        if self.model.is_file():
            return self.model.stat().st_size // (1024 * 1024)
        if self.model.is_dir():
            return sum(path.stat().st_size for path in self.model.rglob("*") if path.is_file()) // (1024 * 1024)
        return 0

    def respond(self, handler, method, path):
        if path.split("?", 1)[0] in ("/v1/models", "/models") and time.time() >= self.ready_at:
            return 200, {"object": "list", "data": [{"id": self.model_id(), "object": "model", "owned_by": "stand", "max_model_len": self.window()}]}
        return super().respond(handler, method, path)

    def run(self, root):
        if self.command != "serve":
            print(f"usage: vllm serve <model> (the stand's stand-in was asked {self.command!r})", flush=True)
            return 2
        totals = {card["index"]: card["mib"] for card in StandCards.CARDS}
        placement = VllmPlacement(self.flags, self.env, totals, self.weights_mib())
        cards = placement.cards()
        shares = placement.share_mib(cards) if cards else {}
        ram_mib = int(placement.offload_mib(cards) * len(cards))
        self.write_launch(root, shares, {})
        record = Path(root) / "launches" / f"{self.port}.json"
        record.write_text(json.dumps({**json.loads(record.read_text(encoding="utf-8")), "ramMiB": ram_mib, "weightsMiB": placement.weights_mib}, indent=1), encoding="utf-8")
        words = placement.no_room(shares)
        if words:
            print(words, flush=True)
            return 1
        self.cards.claim(os.getpid(), "vllm", shares)
        self.ready_at = time.time() + self.LOAD_SECONDS
        print(f"stand vllm on :{self.port} holds {shares} (MiB by card), {ram_mib} MiB of weights in RAM", flush=True)
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
    sys.exit(FakeVllm(argv, os.environ, StandCards.from_env()).run(os.environ[StandCards.ROOT_VAR]))
