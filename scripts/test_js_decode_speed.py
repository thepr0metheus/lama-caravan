#!/usr/bin/env python3
"""Snapshot of static/js/decode-speed.js — how fast a model can answer, at best, from where its weights lie.

Pinned by value. The rule against the owner's measurements (2026-11-02, Cosmos-Reason2-2B BF16, 4.54 GiB, vLLM on the GPU machine's
RTX 3090 at PCIe 4.0 x8): all on the card 182–184 tokens/s, 3 GiB left in RAM 5.2–5.3 — the rule within a tenth of both. Two cards:
the slower one sets the pace. What it does not know it does not say: a card the table has not, a bus the scout did not say (needed only
when weights ride), a model of experts or one that did not say, no weights, no card. Card names to models, and the models sold with two
memories left out. Speeds in words.

Run: python3 scripts/test_js_decode_speed.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _js_pins import run  # noqa: E402

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const { DecodeSpeed } = await import(pathToFileURL(process.env.JS_ROOT + "/decode-speed.js").href);
const C3090 = { name: "NVIDIA GeForce RTX 3090", pcieGen: "4", pcieWidth: "8" };
const C5090 = { name: "NVIDIA GeForce RTX 5090", pcieGen: "5", pcieWidth: "8" };
const COSMOS = 4.54;
const r = (x, n = 1) => (x === null || x === undefined ? x : Math.round(x * 10 ** n) / 10 ** n);
const shown = (s) => (s ? [r(s.now), r(s.full), r(s.slower)] : null);
// The rule keeps no state between pins: nothing to put back.
function reset() {}
"""

PINS = [
    ("the_owner_s_measurements", "",
     r"""(() => { const all = DecodeSpeed.of({ cards: [C3090], weightsGiB: COSMOS, ridesGiB: 0, experts: 0 });
        const rides = DecodeSpeed.of({ cards: [C3090], weightsGiB: COSMOS, ridesGiB: 3, experts: 0 });
        return [shown(all), shown(rides), Math.abs(all.now / 183 - 1) < 0.1, Math.abs(rides.now / 5.25 - 1) < 0.1]; })()""",
     '[[192,192,1],[4.8,192,40.3],true,true]',
     "Cosmos на 3090 PCIe 4.0 x8: всё на карте 192 т/с (замер 182–184), 3 ГиБ в RAM — 4,8 (замер 5,2–5,3): правило в пределах десятой доли от обоих"),

    ("two_cards_the_slower_sets_the_pace", "",
     r"""(() => { const both = DecodeSpeed.of({ cards: [C3090, C5090], weightsGiB: 20, ridesGiB: 2, experts: 0 });
        const fast = DecodeSpeed.of({ cards: [C5090], weightsGiB: 10, ridesGiB: 2, experts: 0 });
        return [shown(both), shown(fast)]; })()""",
     '[[6.8,87.2,12.9],[13.5,166.9,12.4]]',
     "две карты делят веса поровну, темп задаёт медленная (3090: и память, и шина), а не быстрая"),

    ("what_it_does_not_know_it_does_not_say", "",
     r"""(() => { const of = (over) => DecodeSpeed.of({ cards: [C3090], weightsGiB: COSMOS, ridesGiB: 3, experts: 0, ...over });
        const busless = { name: C3090.name };
        return [of({ cards: [{ name: "NVIDIA RTX A6000", pcieGen: "4", pcieWidth: "16" }] }), of({ cards: [busless] }),
                shown(of({ cards: [busless], ridesGiB: 0 })), of({ experts: 128 }), of({ experts: null }), of({ experts: undefined }),
                of({ weightsGiB: 0 }), of({ cards: [] }), of({ cards: [{ ...C3090, pcieGen: "6" }] }), of({ cards: [{ ...C3090, pcieWidth: "x8" }] })]; })()""",
     '[null,null,[192,192,1],null,null,null,null,null,null,null]',
     "negative: карта не из таблицы, шина не сказана (нужна лишь при весах в RAM — без них оценка есть), эксперты или не сказаны, весов или карт нет, поколение или ширина не числом — оценки нет, а не догадка"),

    ("rides_no_more_than_the_card_s_share", "",
     r"""shown(DecodeSpeed.of({ cards: [C3090], weightsGiB: COSMOS, ridesGiB: 50, experts: 0 }))""",
     '[3.2,192,60.4]',
     "в RAM не больше, чем доля карты: 50 ГиБ при 4,54 весов — едут 4,54"),

    ("card_names_to_models", "",
     r"""["NVIDIA GeForce RTX 4070 Ti SUPER", "NVIDIA GeForce RTX 3090 Ti", "NVIDIA GeForce RTX 3090", "rtx 5090", "NVIDIA GeForce RTX 3060",
         "NVIDIA GeForce RTX 3080", "Tesla T4", ""].map((name) => [DecodeSpeed.modelOf(name), DecodeSpeed.memoryOf({ name })])""",
     '[["RTX 4070 Ti SUPER",672],["RTX 3090 Ti",1008],["RTX 3090",936],["RTX 5090",1792],["RTX 3060",null],["RTX 3080",null],["",null],["",null]]',
     "название карты — модель таблицы (Ti и SUPER не путаются с основной); 3060 и 3080 продавались с двумя видами памяти — их в таблице нет; не RTX — пусто"),

    ("buses", "",
     r"""[DecodeSpeed.busOf(C3090), DecodeSpeed.busOf(C5090), DecodeSpeed.busOf({ pcieGen: 3, pcieWidth: 4 }), DecodeSpeed.busOf({}), DecodeSpeed.busOf({ pcieGen: "4", pcieWidth: "0" })]""",
     '[15.752,31.504,3.94,null,null]',
     "шина: линия поколения × ширина — 3090 PCIe 4.0 x8 15,75 ГБ/с, 5090 PCIe 5.0 x8 31,5; negative: не сказана или ноль линий — null"),

    ("speeds_in_words", "",
     r"""[4.768, 9.94, 9.96, 10, 192.04, 0.05].map((x) => DecodeSpeed.said(x))""",
     '["4.8","9.9","10","10","192","0.1"]',
     "скорость словами: до 10 — с десятой, 9,96 — «10», а не «10.0»; дальше целыми"),
]


if __name__ == "__main__":
    sys.exit(run("js decode-speed", ".probe_js_decode_speed.tmp.mjs", PREAMBLE, PINS))
