"""The stand's nvidia-smi: answers the queries the scout makes, from StandCards.

Only what is asked gets an answer. A query field nobody taught it is refused with the exit code a real nvidia-smi gives for
a bad field: an answer invented here would be read by the scout as a fact about a card.
"""
import sys

from cards import StandCards


class StandSmi:
    def __init__(self, cards, out=None):
        self.cards = cards
        self.out = out or sys.stdout

    def gpu_field(self, field, card, claims):
        used = self.cards.used_mib(card["index"], claims)
        table = {
            "index": card["index"],
            "name": card["name"],
            "uuid": card["uuid"],
            "memory.total": card["mib"],
            "memory.used": used,
            "memory.free": card["mib"] - used,
            "utilization.gpu": 0,
            "temperature.gpu": 41,
            "power.draw": "31.50",
            "driver_version": StandCards.DRIVER,
            "pcie.link.gen.max": card["pcie_gen"],
            "pcie.link.width.current": card["pcie_width"],
        }
        return table[field]

    def query_gpu(self, fields):
        claims = self.cards.claims()
        for card in StandCards.CARDS:
            print(", ".join(str(self.gpu_field(field, card, claims)) for field in fields), file=self.out)

    def query_apps(self, fields):
        uuid_of = {str(card["index"]): card["uuid"] for card in StandCards.CARDS}
        for row in self.cards.claims():
            for index, mib in row["shares"].items():
                values = {"gpu_uuid": uuid_of[index], "pid": row["pid"], "process_name": row["name"], "used_memory": mib}
                print(", ".join(str(values[field]) for field in fields), file=self.out)

    def run(self, argv) -> int:
        for arg in argv:
            try:
                if arg.startswith("--query-gpu="):
                    self.query_gpu(arg.split("=", 1)[1].split(","))
                    return 0
                if arg.startswith("--query-compute-apps="):
                    self.query_apps(arg.split("=", 1)[1].split(","))
                    return 0
            except KeyError as exc:
                print(f"Field {exc} is not a valid field to query.", file=sys.stderr)
                return 2
        print(f"Stand cards: {len(StandCards.CARDS)} (no driver, no hardware)", file=self.out)
        return 0


def main():
    sys.exit(StandSmi(StandCards.from_env()).run(sys.argv[1:]))
