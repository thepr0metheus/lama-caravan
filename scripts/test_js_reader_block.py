#!/usr/bin/env python3
"""Snapshot of static/js/reader-block.js — the reader block on Routing's Pools column (docs/vision-describe.md, 2026-11-06).

The block is the half of the reader rule that a person sees: one row for the whole board, the name the operator named, and
the answer the rule gave for that name. It was written as a page that could decide what a name means, and that is the defect:
`qwen3-vl-8b-instruct` says vision in its name and `text` in its facts, so a block that read the state off the name would draw
"reads" for a board whose reader cannot take the picture, while the entry refused the same request with `media_reader_cannot`.
The block reads the word the board gives for its reader (`top.reader`, from `Reader::word()` through
rust/crates/admin/src/cloud/pool_state.rs) and says nothing else; scripts/check_media_reader_board.py holds its words to the
arms of `word()`, and this test runs the same table the guard reads.

The module is loaded FOR REAL; its two neighbours are stubs, and `t` is stubbed to answer with the key it is given, so the words
below are the table's keys rather than the sentences of a language — which is what the table holds, and a translation is held by
scripts/check_messages_i18n.py. What is pinned: the words and their keys (both ways, with the negative case — a word the table
has no key for is said as the program says it); what the row says for each answer, and the absence said in words instead of as
an empty field; the cable key, said without a pool, and whether a cable is drawn; the dots — an output, and the named absence of
an input; the block's own state (names or none) and that it is drawn whatever the pools are; the flow's way, lit only by what a
request names, never by a cable being drawn.

Run: python3 scripts/test_js_reader_block.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _contract import Contract  # noqa: E402
from _js_pins import run  # noqa: E402

TABLE = Contract.table("media_reader_board")

PREAMBLE = r'''
import { pathToFileURL } from "node:url";
// `t` answers with the key: the table holds which word of the rule each key says, not the words of a language.
globalThis.__stubReturns = {
  "i18n.t": (key) => key,
  "utils.escapeHtml": (x) => String(x ?? ""),
};
const { ReaderBlock } = await import(pathToFileURL(process.env.JS_ROOT + "/reader-block.js").href);
const { PoolFlow } = await import(pathToFileURL(process.env.JS_ROOT + "/pool-flow.js").href);
function reset() {}
'''


def pins():
    answer_cases = TABLE["answers"]
    row_cases = TABLE["row"]
    key_cases = TABLE["key"]
    dot_cases = TABLE["dot"]
    block_cases = TABLE["block"]
    flow_cases = TABLE["flow"]
    out = []

    out.append(("answers", '',
        "[%s]" % ",".join(f"ReaderBlock.label({json.dumps(c['answer'])})" for c in answer_cases),
        json.dumps([c.get("key") or c["answer"] for c in answer_cases]),
        "каждый ответ правила имеет своё слово в блоке, и только то, что правило отвечает; "
        "negative: `itself` — слово, которого здесь нет, потому что строка борда не называет пула, и оно сказано "
        "как его говорит программа; negative: слово, которого у таблицы нет, — не выдумано блоком"))

    out.append(("row", '',
        "[%s]" % ",".join(
            f"(() => {{ const f = ReaderBlock.rowFacts({json.dumps({'name': c['reader'], 'answer': c['answer']})}); "
            f"return [f.named, f.shown, f.answer, f.state]; }})()" for c in row_cases),
        json.dumps([[c["says"]["named"], c["says"]["shown"], c["says"]["answer"], c["says"]["state"]] for c in row_cases]),
        "строка говорит два факта: имя, которое назвал оператор, и ответ правила; отсутствие имени сказано словами, "
        "а не пустым полем; состояние — слово правила, прочитанное с борда, никогда не выведенное из имени; "
        "negative: имя, которое выглядит как читатель (qwen3-vl-8b-instruct, ответы — `cannot take` и `unknown`), "
        "не меняет ответа; negative: слово, которого у таблицы нет, не превращается в «ничего»"))

    out.append(("key", '',
        "[%s]" % ",".join(
            f"[ReaderBlock.key(), ReaderBlock.wiredKeys({json.dumps({'name': c['reader']})}).includes(ReaderBlock.key())]"
            for c in key_cases),
        json.dumps([[c["key"], c["wired"]] for c in key_cases]),
        "ключ каната — префикс блока, сказанный один раз, без пула: один борд — один читатель; канат рисуется только "
        "там, где имя названо; negative: ключ без имени есть, каната нет — отсутствие решения оператора не является "
        "канатом в никуда"))

    out.append(("dot", '',
        "[%s]" % ",".join(
            f"ReaderBlock.dotHtml().includes({json.dumps(c['hook'])})" for c in dot_cases),
        json.dumps([c["present"] for c in dot_cases]),
        "у строки есть точка, от которой тянут канат, и нет входной — отсутствие названо: в строку читателя канат не тянется, "
        "читатель — проводка, а не путь запроса"))

    out.append(("block", '',
        "[%s]" % ",".join(
            f"[ReaderBlock.state({json.dumps({'name': c['reader']})}), ReaderBlock.html({json.dumps({'name': c['reader']})}) !== \"\"]"
            for c in block_cases),
        json.dumps([[c["state"], c["drawn"]] for c in block_cases]),
        "состояние блока — факт об имени (named/quiet), не ответ правила и не факт о пулах; negative: имени нет — "
        "блок всё равно рисуется, потому что борд, у которого читателя нет, должен сказать, какое именно отсутствие он видит"))

    out.append(("flow", '',
        "[%s]" % ",".join(
            f"PoolFlow.way({json.dumps(c['item'])}, {json.dumps(c['item']['port'])}, new Set({json.dumps(c['pools'])}))"
            for c in flow_cases),
        json.dumps([c["keys"] for c in flow_cases]),
        "строку читателя зажигает только то, что запрос назвал читателя (`readerName`, пишет прокси, когда читатель прочёл "
        "картинки для строки, которая отвечает); negative: канат нарисован — запрос не шёл по нему, ничего не горит; модель, "
        "названная напрямую, тоже бывает прочитана — горят «Напрямую» и канат читателя; собственный запрос читателя (`readerFor`) "
        "зажигает только канат читателя, не канат клиента; без клиента зажигать некому"))

    return out


def main() -> int:
    return run("js reader block", ".probe_js_reader_block.tmp.mjs", PREAMBLE, pins(), stubs="i18n,utils")


if __name__ == "__main__":
    sys.exit(main())
