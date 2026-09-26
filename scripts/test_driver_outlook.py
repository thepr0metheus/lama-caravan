#!/usr/bin/env python3
"""Snapshot of caravan/domain/driver_outlook.py — whether a machine's NVIDIA
card will be there after its next reboot.

Pinned by value: the facts of the morning of 2026-09-26 (a new kernel whose
only nvidia module was a DKMS build signed by the machine's unenrolled key)
say the card will be gone, the state after the fix says nothing, and every
case where the facts cannot tell stays silent rather than guessing. The
host record keeps the facts in their own shapes only.

Run: python3 scripts/test_driver_outlook.py
"""
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.domain.driver_outlook import DriverOutlook  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def same(actual, expected, msg):
    check(actual == expected, msg)
    if actual != expected:
        print(f"        got:  {actual!r}\n        want: {expected!r}")


SAMPLE = json.loads((ROOT / "scripts" / "fixtures" / "scout-report-sample.json").read_text(encoding="utf-8"))
MORNING = SAMPLE["heartbeat"]["driver"]
NEXT = "7.0.0-34-generic"
CANONICAL = "Canonical Ltd. Kernel Module Signing"


def facts(**changes):
    out = copy.deepcopy(MORNING)
    for key, value in changes.items():
        out[key] = value
    return out


def module(signer, path=f"/lib/modules/{NEXT}/kernel/nvidia-610-open/nvidia.ko"):
    return {"path": path, "version": "610.57.04", "signer": signer}


def main():
    print("утро 26 сентября и после починки:")
    same(DriverOutlook(MORNING).warnings(),
         [{"kind": "nextBootNoDriver", "reason": "untrusted-key", "kernel": NEXT,
           "package": "linux-modules-nvidia-610-open-7.0.0-34-generic"}],
         "образец скаута — то утро: новое ядро, сборка DKMS подписана ключом машины, которого прошивка не знает, — "
         "карты после перезагрузки не будет, и названо, что поставить")
    same(DriverOutlook(facts(nextModule=module(CANONICAL))).warnings(), [],
         "negative: у следующего ядра модуль, подписанный Canonical, — сказать нечего")

    print("почему карты не будет:")
    same([w["reason"] for w in DriverOutlook(facts(nextModule=None)).warnings()], ["missing"],
         "у следующего ядра модуля nvidia нет вовсе")
    same([w["reason"] for w in DriverOutlook(facts(nextModule=module(""))).warnings()], ["unsigned"],
         "модуль без подписи при включённом Secure Boot")
    same(DriverOutlook(facts(nextModule=module(""), secureBoot=False)).warnings(), [],
         "negative: Secure Boot выключен — неподписанный модуль загрузится")
    same([w["reason"] for w in DriverOutlook(facts(nextModule=None, secureBoot=False)).warnings()], ["missing"],
         "а модуля нет — нет и при выключенном Secure Boot")

    print("не может сказать — молчит:")
    same(DriverOutlook(facts(secureBoot=None)).warnings(), [],
         "negative: включён ли Secure Boot, неизвестно — утверждать нечего")
    same(DriverOutlook(facts(dkmsKey={"signer": "linux Secure Boot Module Signature key", "enrolled": True})).warnings(),
         [], "negative: ключ DKMS записан в прошивку — его сборка загрузится")
    same(DriverOutlook(facts(dkmsKey={"signer": "linux Secure Boot Module Signature key", "enrolled": None})).warnings(),
         [], "negative: записан ли ключ, неизвестно — молчит")
    same(DriverOutlook(facts(nextModule=module("Some Vendor key"))).warnings(), [],
         "negative: подписант незнакомый — не Canonical и не ключ DKMS — утверждать нечего")
    same(DriverOutlook(facts(kernelNext="7.0.0-31-generic", nextModule=None)).warnings(), [],
         "negative: следующим загрузится то же ядро — что с картой сейчас, говорит её собственная ошибка, а не прогноз")
    same(DriverOutlook(facts(kernelRunning=None)).warnings(), [],
         "negative: работающее ядро неизвестно — не сравнить, молчит")
    same(DriverOutlook(None).warnings(), [], "negative: фактов нет (скаут старше 2.19, не Linux) — ничего")

    print("драйвер обновлён, а в памяти старый:")
    same(DriverOutlook(facts(nextModule=module(CANONICAL), installed="610.57.04")).warnings(),
         [{"kind": "rebootForDriver", "loaded": "610.43.02", "installed": "610.57.04"}],
         "установлен 610.57.04, загружен 610.43.02 — новые процессы не откроют карту до перезагрузки")
    same(DriverOutlook(facts(nextModule=module(CANONICAL), loaded=None, installed="610.57.04")).warnings(), [],
         "negative: модуль не загружен — это не «разошлись версии», об этом говорит ошибка карты")
    same([w["kind"] for w in DriverOutlook(facts(installed="610.57.04")).warnings()],
         ["nextBootNoDriver", "rebootForDriver"], "обе беды сразу — обе названы")

    print("что поставить:")
    same(DriverOutlook(facts(nextModule=None, package="nvidia-driver-580")).warnings()[0]["package"],
         "linux-modules-nvidia-580-7.0.0-34-generic", "закрытый драйвер — пакет без -open")
    same(DriverOutlook(facts(nextModule=None, package=None)).warnings()[0]["package"], None,
         "negative: пакет драйвера неизвестен — имя не выдумывается")

    print("запись хоста держит факты только в их форме:")
    same(DriverOutlook.clean("x"), None, "не словарь — None")
    dirty = DriverOutlook.clean({"secureBoot": "yes", "kernelRunning": "rm -rf /", "kernelNext": " 7.0.0-35-generic ",
                                 "loaded": "610.43.02; x", "installed": "610.57.04",
                                 "nextModule": {"path": "", "signer": CANONICAL},
                                 "dkmsKey": {"signer": 5, "enrolled": "no"}, "package": "nvidia-driver-610-open; x"})
    same(dirty, {"secureBoot": None, "kernelRunning": None, "kernelNext": "7.0.0-35-generic", "loaded": None,
                 "installed": "610.57.04", "nextModule": None, "dkmsKey": {"signer": None, "enrolled": None},
                 "package": None},
         "флаг только флагом, ядро и версия только в своей форме, модуль без пути — нет модуля, пакет — только "
         "nvidia-driver-*: мусор в записи становится None, а не текстом на доске")
    same(DriverOutlook.clean({"nextModule": {"path": "/x/nvidia.ko"}})["nextModule"],
         {"path": "/x/nvidia.ko", "version": None, "signer": ""}, "модуль без подписанта — подписант пустой")

    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg)
        sys.exit(1)
    print("driver outlook OK: утро 26-го, починенное состояние и все «не могу сказать» — значениями")


if __name__ == "__main__":
    main()
