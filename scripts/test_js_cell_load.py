#!/usr/bin/env python3
"""Snapshot of static/js/cell-load.js — the two rows a starting cell's card
shows while the controller measures its load (load_progress.py).

Pinned by value. The line beside the bar: read of total, speed and time left
only once they are known; "no data for N s" when the load stands; the setup
wording between files and after the last; "starting" before any. The bar's
share, never past 100 nor made up from a zero total. The files row: one step
per file in reading order — ✓ done, ▸ reading with its bytes, ○ waiting with
its size — 📚 only for a file read from a library; a role or a state the card
does not know is shown as sent ("?"), not guessed. The hover: every file's name,
size and where it is read from. The hooks: cell-load with the cell and the
stage, cell-load-file with the role and the state. A stall trades the spinner
for ⚠; the card's own tail goes at the end of the first row; names are escaped.

Run: python3 scripts/test_js_cell_load.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _js_pins import run  # noqa: E402

STUBS = ("dialogs,dialog-llamas,polling,canvas,topology-dnd,topology-render,charts,cables,cloud,history,favorites,"
         "config-locator,system-panels,onboarding,onboarding-tours,usage-stats,system-page,memory,command-preview,"
         "llama-edit,remote-cells,topology-nodes,topology-modals,routers,topology-activity,topology-proxies,model-meta,form")

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const L = await import(pathToFileURL(process.env.JS_ROOT + "/cell-load.js").href);
const GB = 2 ** 30, MB = 2 ** 20;
const LIB = "lama-caravan-models";
const FILES = () => [
  { role: "model", name: "m-Q4_K_M.gguf", size: 10 * GB, read: 2 * GB, state: "reading", library: LIB },
  { role: "mmproj", name: "mmproj-BF16.gguf", size: 1 * GB, read: 0, state: "waiting", library: LIB }];
const P = (over = {}) => ({ stage: "reading", read: 2 * GB, total: 11 * GB, speed: 112 * MB, left: 80, files: FILES(), ...over });
const reset = () => {};
"""

PINS = [
    ("summary_reading_with_pace", "",
     r"""(() => [new L.CellLoad(P()).summary(), new L.CellLoad(P({ speed: undefined, left: undefined })).summary(),
                new L.CellLoad(P({ left: 7300 })).summary(), new L.CellLoad(P({ speed: 3 * GB })).summary()])()""",
     '["2.00 GB / 11.0 GB · 112 MB/s · ~2 min left","2.00 GB / 11.0 GB","2.00 GB / 11.0 GB · 112 MB/s · ~2 h 2 min left","2.00 GB / 11.0 GB · 3.0 GB/s · ~2 min left"]',
     "строка у полосы: прочитано из целого · скорость · осталось; первое чтение — без скорости и остатка (их ещё нет); часы и ГБ/с — той же формулировкой, что переносы"),

    ("summary_other_stages", "",
     r"""(() => [new L.CellLoad(P({ stage: "stalled", idle: 45, read: 3 * GB })).summary(), new L.CellLoad(P({ stage: "setup" })).summary(),
                new L.CellLoad(P({ stage: "starting" })).summary(), new L.CellLoad(P({ stage: "stalled", idle: 45 })).summary().includes("MB/s")])()""",
     '["3.00 GB / 11.0 GB · no data for 45 s","setting up: context, warm-up","starting",false]',
     "стоит — «нет данных N с» вместо скорости; подготовка контекста — своей фразой; до первого файла — «starting»; у стоящей загрузки скорости нет"),

    ("bar_share", "",
     r"""(() => [new L.CellLoad(P()).pct, new L.CellLoad(P({ read: 12 * GB })).pct, new L.CellLoad(P({ total: 0 })).pct, new L.CellLoad(null).pct])()""",
     '[18,100,0,0]',
     "доля полосы: округлена; не больше 100; нулевое целое или нет ответа — 0, а не деление на ноль"),

    ("steps_marks_sizes_library", "",
     r"""(() => { const c = new L.CellLoad(P({ files: [{ role: "model", name: "m.gguf", size: 10 * GB, read: 10 * GB, state: "done", library: LIB },
            { role: "draft", name: "mtp.gguf", size: 512 * MB, read: 100 * MB, state: "reading" }, { role: "mmproj", name: "p.gguf", size: GB, read: 0, state: "waiting", library: LIB }] }));
        return c.files.map((f) => c.step(f)); })()""",
     '["<span class=\\"msl-step is-done\\" data-t=\\"cell-load-file\\" data-t-id=\\"model\\" data-t-state=\\"done\\">✓ 📚 weights 10.0 GB</span>",'
     '"<span class=\\"msl-step is-reading\\" data-t=\\"cell-load-file\\" data-t-id=\\"draft\\" data-t-state=\\"reading\\">▸ draft 0.10 GB / 0.50 GB</span>",'
     '"<span class=\\"msl-step is-waiting\\" data-t=\\"cell-load-file\\" data-t-id=\\"mmproj\\" data-t-state=\\"waiting\\">○ 📚 mmproj 1.00 GB</span>"]',
     "шаги: ✓ готово с размером, ▸ читается «прочитано / размер», ○ ждёт с размером; 📚 только у файла из библиотеки; порядок — как прислан"),

    ("steps_unknown_role_and_state_as_sent", "",
     r"""(() => { const c = new L.CellLoad(P()); return [c.step({ role: "vae", name: "v.gguf", size: GB, read: 0, state: "paused" }), L.CellLoad.mark({ state: "done" })]; })()""",
     '["<span class=\\"msl-step is-paused\\" data-t=\\"cell-load-file\\" data-t-id=\\"vae\\" data-t-state=\\"paused\\">? vae 1.00 GB</span>","✓"]',
     "незнакомая роль — как прислана; незнакомое состояние — «?», а не «ждёт»: карточка не говорит того, чего контроллер не сказал"),

    ("title_names_sizes_places", "",
     r"""(() => new L.CellLoad(P({ files: [...FILES().slice(0, 1), { role: "draft", name: "d.gguf", size: 512 * MB, read: 0, state: "waiting" }] })).title())()""",
     '"▸ weights: m-Q4_K_M.gguf · 10.0 GB · read from library lama-caravan-models\\n○ draft: d.gguf · 0.50 GB · read from this disk"',
     "подсказка: по строке на файл — имя, размер и откуда читается (библиотека по имени или этот диск)"),

    ("html_two_rows_with_hooks", "",
     r"""(() => new L.CellLoad(P()).html("controller:22009"))()""",
     '"<div class=\\"node-model-row2 model-status-line msl-load\\" data-t=\\"cell-load\\" data-t-id=\\"controller:22009\\" data-t-state=\\"reading\\" title=\\"▸ weights: m-Q4_K_M.gguf · 10.0 GB · read from library lama-caravan-models\\n○ mmproj: mmproj-BF16.gguf · 1.00 GB · read from library lama-caravan-models\\">'
     '<span class=\\"topology-spinner\\" aria-hidden=\\"true\\"></span><span class=\\"msl-bar\\"><span style=\\"width:18%\\"></span></span><span class=\\"msl-text\\">2.00 GB / 11.0 GB · 112 MB/s · ~2 min left</span></div>'
     '<div class=\\"node-model-row2 msl-steps\\" title=\\"▸ weights: m-Q4_K_M.gguf · 10.0 GB · read from library lama-caravan-models\\n○ mmproj: mmproj-BF16.gguf · 1.00 GB · read from library lama-caravan-models\\">'
     '<span class=\\"msl-step is-reading\\" data-t=\\"cell-load-file\\" data-t-id=\\"model\\" data-t-state=\\"reading\\">▸ 📚 weights 2.00 GB / 10.0 GB</span>'
     '<span class=\\"msl-step is-waiting\\" data-t=\\"cell-load-file\\" data-t-id=\\"mmproj\\" data-t-state=\\"waiting\\">○ 📚 mmproj 1.00 GB</span></div>"',
     "две строки: полоса с долей и цифрами (хук cell-load с ячейкой и стадией, подсказка), под ней шаги файлов (хуки cell-load-file)"),

    ("html_stall_trades_spinner_and_tail_goes_last", "",
     r"""(() => { const h = new L.CellLoad(P({ stage: "stalled", idle: 31 })).html("controller:22009", "<i>TAIL</i>");
        const r = new L.CellLoad(P()).html("controller:22009", "<i>TAIL</i>");
        return [h.includes('msl-load msl-load-stalled"'), h.includes('data-t-state="stalled"'), h.includes('<span class="msl-stall-icon" aria-hidden="true">⚠</span><span class="msl-bar">'),
                h.includes("topology-spinner"), r.includes("msl-load-stalled"), r.includes("msl-stall-icon"), r.includes('~2 min left</span><i>TAIL</i></div><div class="node-model-row2 msl-steps"')]; })()""",
     '[true,true,true,false,false,false,true]',
     "стоит — класс и стадия stalled, ⚠ вместо спиннера (спиннер над замершими байтами врал бы); без стоя — ни класса, ни ⚠; хвост карточки — в конце первой строки"),

    ("html_escapes_what_it_did_not_write", "",
     r"""(() => { const h = new L.CellLoad(P({ files: [{ role: 'x"y', name: "<b>evil</b>.gguf", size: GB, read: 0, state: "waiting", library: '<i>lib</i>' }] })).html('h"1:22009');
        return [h.includes("<b>"), h.includes("&lt;b&gt;evil&lt;/b&gt;.gguf"), h.includes('data-t-id="h&quot;1:22009"'), h.includes('data-t-id="x&quot;y"'), h.includes("<i>lib</i>")]; })()""",
     '[false,true,true,true,false]',
     "имена файлов, библиотеки, роли и ячейки экранированы: чужая строка не становится разметкой"),
]


if __name__ == "__main__":
    sys.exit(run("js cell-load", ".probe_js_cell_load.tmp.mjs", PREAMBLE, PINS, STUBS))
