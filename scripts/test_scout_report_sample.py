#!/usr/bin/env python3
"""The scout's report sample is what the controller reads — every field of it.

A field one side renamed used to be lost without a word: the scout's
`version` became `scoutVersion` and the host record kept neither, and the
llama.cpp update status rode only one of the two reports, so "building…"
blinked on the board as the pull and the beat replaced each other.

The sample is the scout's: caravan-scout docs/report-sample.json, the
heartbeat and /api/state of an imagined machine, built from the scout's real
report code. This repo keeps a byte-identical copy in scripts/fixtures/.
Checked here:
1. every field the scout sends changes the host record — or is named below
   as not read, with the reason;
2. the pull (/api/state) and the heartbeat make the same host record;
3. the copy is the scout's file — when a checkout of the scout sits next to
   this one to compare with (a laptop with both repos). CI has only this
   repo and says the comparison was skipped.

Run: python3 scripts/test_scout_report_sample.py
"""
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import caravan.admin.fleet_clients as fc  # noqa: E402

SAMPLE_PATH = ROOT / "scripts" / "fixtures" / "scout-report-sample.json"
SCOUT_SAMPLE = ROOT.parent / "caravan-scout" / "docs" / "report-sample.json"

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


# What the scout sends and the host record does not keep — each on purpose.
NOT_READ = {
    "time": "the scout's clock; the record keeps the controller's own lastSeen",
    "llamaNode": "the one-cell view older controllers read — the same as llamaNodes[0], which is kept",
    "cpu.load1": "the raw load average; the board shows loadPct",
    "llamaNodes[].adopted": "whether the scout started the process or found it again after a restart",
    "llamaNodes[].startedAt": "the start of a download or a process; the board counts from uptimeSec",
    "llamaNodes[].gpuLayers": "bookkeeping of the scout's — the controller built the arguments",
    "llamaNodes[].ctxSize": "what was asked; the window kept is ctxMax, what the server says it runs",
}


class SampleReading:
    """Which fields of a report reach the host record, found by taking each
    away — and, for a plain value, by changing it — and seeing whether the
    record changes. Taking away alone is blind to a field whose value is its
    own default: an empty mmprojPath removed is still an empty mmprojPath."""

    TIMESTAMPS = ("firstSeen", "lastSeen")

    def __init__(self, payload):
        self.payload = payload

    @classmethod
    def record(cls, payload):
        rec = fc.host_from_report(copy.deepcopy(payload))
        return {k: v for k, v in rec.items() if k not in cls.TIMESTAMPS}

    def paths(self):
        """(path shown, where to delete) for every field, down to the fields of
        each GPU, cell, host and CPU entry."""
        out = []
        for key, value in self.payload.items():
            out.append((key, (key,)))
            if isinstance(value, dict):
                for sub in value:
                    out.append((f"{key}.{sub}", (key, sub)))
                    if isinstance(value[sub], dict):
                        for leaf in value[sub]:
                            out.append((f"{key}.{sub}.{leaf}", (key, sub, leaf)))
            elif isinstance(value, list):
                for i, item in enumerate(value):
                    if isinstance(item, dict):
                        for sub in item:
                            out.append((f"{key}[].{sub}", (key, i, sub)))
        return out

    @staticmethod
    def other(value):
        """A different value of the same kind, or None for a container."""
        if isinstance(value, bool):
            return not value
        if isinstance(value, (int, float)):
            return value + 1
        if isinstance(value, str):
            return value + "~"
        return None

    def reads(self, where, base):
        """True when the record depends on the field at `where`."""
        probes = []
        for change in ("delete", "alter"):
            probe = copy.deepcopy(self.payload)
            node = probe
            for step in where[:-1]:
                node = node[step]
            if change == "delete":
                del node[where[-1]]
            else:
                other = self.other(node[where[-1]])
                if other is None:
                    continue
                node[where[-1]] = other
            probes.append(probe)
        for probe in probes:
            try:
                if self.record(probe) != base:
                    return True
            except Exception:  # noqa: BLE001 — no record without it: the field is required, so read
                return True
        return False

    def unread(self):
        """Fields no entry of which the record depends on (a field of a list
        of cells counts as read when it is read for any cell)."""
        base = self.record(self.payload)
        read, seen = set(), []
        for shown, where in self.paths():
            if shown not in seen:
                seen.append(shown)
            if self.reads(where, base):
                read.add(shown)
        return [shown for shown in seen if shown not in read]


def load_sample():
    return json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))


def test_every_field_is_read():
    print("каждое поле отчёта скаута доходит до записи машины:")
    sample = load_sample()
    unread = SampleReading(sample["heartbeat"]).unread()
    ancestors_ignored = [p for p in unread if p.split(".")[0].split("[")[0] in NOT_READ
                         and p.split(".")[0].split("[")[0] != p]
    unexplained = [p for p in unread if p not in NOT_READ and p not in ancestors_ignored]
    check(unexplained == [], f"поля, которые скаут шлёт, а запись машины не держит, — только из списка "
                             f"с причинами (лишние: {unexplained})")
    stale = [p for p in NOT_READ if p not in unread]
    check(stale == [], f"список «не читается» не врёт: каждое поле в нём действительно не читается (лишние: {stale})")
    rec = SampleReading.record(sample["heartbeat"])
    check(rec.get("scoutVersion") == "X.Y.Z" and rec.get("llamaUpdate", {}).get("tag") == "b9947",
          "версия скаута и статус обновления llama.cpp — в записи, под теми же именами")
    downloading = [n for n in rec.get("llamaNodes", []) if n.get("phase") == "downloading"]
    check(downloading and downloading[0].get("downloadingFile") == "other-q8.gguf",
          "defect-history: имя скачиваемого файла доходит до карточки; запись его теряла, и у ячейки клиента "
          "всю загрузку было написано просто «downloading…»")


def test_a_rename_is_caught():
    print("переименованное поле краснит проверку:")
    sample = load_sample()
    renamed = copy.deepcopy(sample["heartbeat"])
    renamed["version"] = renamed.pop("scoutVersion")
    unread = SampleReading(renamed).unread()
    check("version" in unread and SampleReading.record(renamed).get("scoutVersion") == "",
          "negative: скаут назвал версию «version» — поле не читается, а в записи версии нет")
    renamed = copy.deepcopy(sample["heartbeat"])
    for node in renamed["llamaNodes"]:
        if "genTps" in node:
            node["tokensPerSec"] = node.pop("genTps")
    check("llamaNodes[].tokensPerSec" in SampleReading(renamed).unread(),
          "negative: поле ячейки переименовано — тоже видно")


def test_pull_and_beat_agree():
    print("опрос /api/state и пульс дают одну запись:")
    sample = load_sample()
    agent_url = sample["heartbeat"]["agentUrl"]
    from_beat = SampleReading.record(sample["heartbeat"])
    from_pull = SampleReading.record(fc.scout_payload_from_state(sample["state"], agent_url))
    differ = sorted(k for k in set(from_beat) | set(from_pull) if from_beat.get(k) != from_pull.get(k))
    check(differ == [], f"запись после опроса та же, что после пульса — ничто не мигает (разные поля: {differ})")
    trimmed = copy.deepcopy(sample["state"])
    trimmed.pop("llamaUpdate")
    check(SampleReading.record(fc.scout_payload_from_state(trimmed, agent_url)).get("llamaUpdate") == {},
          "negative: /api/state без статуса обновления — запись без него: так «building…» и мигало")


def test_the_copy_is_the_scouts():
    print("копия образца — файл самого скаута:")
    if not SCOUT_SAMPLE.exists():
        print("  --  сверка пропущена: рядом нет клона caravan-scout (так в CI); на машине с обоими "
              "репозиториями она обязательна")
        return
    check(SAMPLE_PATH.read_bytes() == SCOUT_SAMPLE.read_bytes(),
          "scripts/fixtures/scout-report-sample.json совпадает с caravan-scout/docs/report-sample.json байт в байт "
          "(разошлось — скопировать файл скаута сюда)")


for fn in (test_every_field_is_read, test_a_rename_is_caught, test_pull_and_beat_agree, test_the_copy_is_the_scouts):
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 — a crash is a red pin; the rest still runs
        check(False, f"{fn.__name__} упал: {exc!r}")

if _fail:
    print(f"\nFAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("\nscout report sample OK")
