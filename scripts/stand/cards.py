"""The stand's graphics cards: two cards that exist only as a table and a folder of claims.

Whoever "loads" onto a card writes down what it holds, one file per process. The stand's nvidia-smi reads those files, so
the scout sees what a real machine would show: a process on a card, the memory it holds, what is left. A process that died
holds nothing: its file is dropped at the next look, as a real card frees the memory of a dead process.
"""
import json
import os
from pathlib import Path


class StandCards:
    #: The sizes of a real two-card machine, so the rack on the stand reads like the rack at home.
    CARDS = (
        {"index": 0, "name": "NVIDIA GeForce RTX 3090", "mib": 24576, "uuid": "GPU-stand-0"},
        {"index": 1, "name": "NVIDIA GeForce RTX 5090", "mib": 32760, "uuid": "GPU-stand-1"},
    )
    #: What the desktop holds of the second card: memory that is no cell's, drawn on the rack as somebody else's.
    OUTSIDE_MIB = {1: 412}
    DRIVER = "stand"
    ROOT_VAR = "CARAVAN_STAND_ROOT"

    def __init__(self, root):
        self.folder = Path(root) / "cards"

    @classmethod
    def from_env(cls, env=None):
        """The cards of the stand this process was started by. No stand named: refused. A guess would write its claims
        into somebody's working directory, and a caller that takes it for a real card is exactly what this must not be."""
        root = (env if env is not None else os.environ).get(cls.ROOT_VAR, "").strip()
        if not root:
            raise SystemExit(f"{cls.ROOT_VAR} is not set: this is the stand's stand-in, run it through scripts/stand/stand.py")
        return cls(root)

    @staticmethod
    def alive(pid) -> bool:
        try:
            os.kill(int(pid), 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def claim(self, pid, name, shares):
        """`shares`: {card index: MiB}. Replaces what this process held."""
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / f"{int(pid)}.json"
        path.write_text(json.dumps({"pid": int(pid), "name": str(name),
                                    "shares": {str(k): int(v) for k, v in shares.items()}}), encoding="utf-8")

    def release(self, pid):
        (self.folder / f"{int(pid)}.json").unlink(missing_ok=True)

    def claims(self, alive=None):
        """Every living process's claim; a dead process's file goes."""
        alive = alive or self.alive
        rows = []
        if not self.folder.is_dir():
            return rows
        for path in sorted(self.folder.glob("*.json")):
            row = json.loads(path.read_text(encoding="utf-8"))
            if alive(row["pid"]):
                rows.append(row)
            else:
                path.unlink(missing_ok=True)
        return rows

    def used_mib(self, index, claims=None) -> int:
        rows = self.claims() if claims is None else claims
        return self.OUTSIDE_MIB.get(index, 0) + sum(int(row["shares"].get(str(index), 0)) for row in rows)

    def free_mib(self, index, claims=None) -> int:
        return self.CARDS[index]["mib"] - self.used_mib(index, claims)
