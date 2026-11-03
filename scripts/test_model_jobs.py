#!/usr/bin/env python3
"""Value snapshot: what a model DOES, as opposed to what launches it, as the browser decides it (static/js/model-jobs.js).

The picker decides in the browser and the board in the program (rust/crates/admin/tests/contract.rs): both are held to ONE table of cases, contract/model_jobs.json.
Diverging twins would be exactly the defect this rule was split into its own file to prevent.

What's pinned. That a `.gguf` is an LLM or a recognizer by its OWN metadata and not by its extension; that seamless is speech-translate and NOT asr (it returns the target
language only, never a transcript, so a consumer picking it up as a recognizer would get a translation labelled as a transcription); that a cell's live `kinds` outranks the
runner table, which is the only way a TTS cell run as a typed command can be named as one; and that an unnameable job answers with NOTHING rather than falling back to
"llm" — the silence this rule exists to end.

Run: python3 scripts/test_model_jobs.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _contract import Contract  # noqa: E402
from _node import find_node, node_args  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


TABLE = Contract.table("model_jobs")
JOBS = TABLE["jobs"]
# (name, kind, sttVariant, arch, family, expected jobs, what the pin is for)
ARTIFACTS = [(r["name"], r["kind"], r["sttVariant"], r["arch"], r["family"], r["jobs"], r["why"]) for r in TABLE["artifacts"]]
# (name, runnerId, kinds, expected jobs, what the pin is for)
CELLS = [(r["name"], r["runner"], r["kinds"], r["jobs"], r["why"]) for r in TABLE["cells"]]


#: What each cell server declares about itself, by value. The guard next door
#: (check_cell_kinds.py) can only see that a word is IN the vocabulary — whether
#: it is the RIGHT word is a claim about the cell's behaviour, and that belongs
#: in a snapshot. Seamless spent its whole life saying "asr" while its own
#: docstring said it never produces a transcript; nothing could have caught that
#: except pinning what it says.
DECLARED = {
    # The engine cell's job follows its model (llm, or embed for a vector
    # model) — both pinned by value in test_engine_cell_server.py; what a
    # reader of the source sees is the common case, llm.
    "engine_cell_server.py": ["llm"],
    "gr00t_server.py": ["robot-policy", "robot-policy.gr00t"],
    # Speaks (text to speech) and also answers a spoken question and transcribes; only what a consumer may count on is
    # declared (tts), the other two routes are documented in the server and not advertised.
    "lfm_audio_server.py": ["tts", "tts.lfm-audio"],
    "moonshine_server.py": ["asr", "tts"],
    "seamless_server.py": ["speech-translate"],
    "transcribe_server.py": ["asr"],
    "translate_server.py": ["translate"],
    "tts_server.py": ["tts", "tts.*"],
    "whisper_server.py": ["asr", "stt.whisper"],
}


# A cell's record — its settings and what it says of itself — as the board draws its chips (cellJobs):
# (name, settings, what the cell said, expected runner, expected jobs, what the pin is for)
RECORDS = [(r["name"], r["config"], r["meta"], r["runner"], r["jobs"], r["why"]) for r in TABLE["records"]]


def test_cells_say_what_they_do():
    """Each cell server's own `kinds`, pinned by value."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from check_cell_kinds import declared_kinds
    cells = ROOT / "cells"
    seen = {}
    for path in sorted(cells.glob("*_server.py")):
        seen[path.name] = declared_kinds(path)
    check(seen == DECLARED,
          f"каждая ячейка объявляет РОВНО свою работу (got {seen})")
    check(seen.get("seamless_server.py") == ["speech-translate"],
          "seamless НЕ распознаватель: транскрипта он не отдаёт, и говорит об этом сам")
    check("tts" in (seen.get("tts_server.py") or []),
          "у синтезатора есть ГОЛОЕ «tts» — иначе его найдёт только тот, кто уже знает движок")
    check(all(any("." not in k for k in v) for v in seen.values()),
          "у каждой ячейки есть голое слово работы")


def main():
    print("ячейки о себе:")
    test_cells_say_what_they_do()
    print("двойник в браузере:")
    node = find_node()
    if not node:
        check(False, "node не найден — двойник не проверен")
        return _verdict()
    probe = ROOT / "scripts" / ".probe_jobs.tmp.mjs"
    probe.write_text(
        'import { pathToFileURL } from "node:url";\n'
        'const m = await import(pathToFileURL(process.env.JS_FILE).href);\n'
        f"const arts = {json.dumps([[n, k, v, a, fam] for n, k, v, a, fam, _w, _m in ARTIFACTS])};\n"
        f"const cells = {json.dumps([[n, r, k] for n, r, k, _w, _m in CELLS])};\n"
        f"const records = {json.dumps([[n, c, meta] for n, c, meta, _r, _w, _m in RECORDS])};\n"
        'const out = { art: {}, cell: {}, rec: {} };\n'
        'for (const [n, k, v, a, fam] of arts) out.art[n] = m.jobsForArtifact(k, v, a, fam);\n'
        'for (const [n, r, k] of cells) out.cell[n] = m.jobsForCell(r, k);\n'
        'for (const [n, c, meta] of records) out.rec[n] = [m.cellRunnerId(c), m.cellJobs(m.cellRunnerId(c), meta, c)];\n'
        'out.__jobs = m.JOBS;\n'
        'out.__marks = m.JOBS.map((j) => m.JOB_MARKS[j] || "");\n'
        'out.__labels = m.JOBS.map((j) => m.JOB_LABELS[j] || "");\n'
        'out.__extraMarks = Object.keys(m.JOB_MARKS).filter((k) => !m.JOBS.includes(k));\n'
        'out.__empty = [m.jobsFromKinds(null), m.jobsFromKinds([])];\n'
        'out.__case = m.jobsFromKinds(["STT.Whisper", " ASR "]);\n'
        'out.__engine = [m.jobsFromKinds(["embedding"]), m.jobsFromKinds(["vlm"]), m.jobsFromKinds(["llm"])];\n'
        'console.log(JSON.stringify(out));\n'
    )
    try:
        env = {**os.environ, "JS_FILE": str(ROOT / "static" / "js" / "model-jobs.js")}
        run = subprocess.run(node_args(node, probe), capture_output=True, text=True,
                             env=env, cwd=ROOT, timeout=60)
    finally:
        probe.unlink(missing_ok=True)
    if run.returncode != 0:
        print(run.stdout, run.stderr)
        check(False, f"node вышел с кодом {run.returncode}")
        return _verdict()

    js = json.loads(run.stdout.strip().splitlines()[-1])
    for name, _k, _v, _a, _f, want, msg in ARTIFACTS:
        check(js["art"].get(name) == want, f"js: {msg} (got {js['art'].get(name)})")
    for name, _r, _k, want, msg in CELLS:
        check(js["cell"].get(name) == want, f"js: {msg} (got {js['cell'].get(name)})")
    for name, _c, _meta, runner, want, msg in RECORDS:
        check(js["rec"].get(name) == [runner, want], f"js: {msg} (got {js['rec'].get(name)})")
    check(js["__jobs"] == list(JOBS), f"словарь совпадает в обеих копиях (got {js['__jobs']})")
    # Marks and labels live BESIDE the vocabulary, in one place, because both the
    # picker row and the cell card draw them. They each kept a private copy for a
    # day — written differently, emoji in one and \u escapes in the other — which
    # is how two copies of one fact stop looking like copies.
    check(all(js["__marks"]), f"у КАЖДОЙ работы есть значок — иначе чип нарисуется пустым (got {js['__marks']})")
    check(all(js["__labels"]), f"и подпись у каждой (got {js['__labels']})")
    check(len(set(js["__marks"])) == len(js["__marks"]),
          f"значки не повторяются: две работы под одним значком неразличимы (got {js['__marks']})")
    check(js["__extraMarks"] == [],
          f"negative: значка без работы нет — осиротевшая запись пережила бы удаление работы (got {js['__extraMarks']})")
    check(js["__empty"] == [[], []], "js: пустые kinds — пустой ответ")
    check(js["__case"] == ["asr"], f"js: регистр и пробелы так же (got {js['__case']})")
    check(js["__engine"] == [["embed"], ["llm"], ["llm"]], f"js: слова движков — так же (got {js['__engine']})")
    return _verdict()


def _verdict():
    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg)
        sys.exit(1)
    print("model-jobs snapshots hold")


if __name__ == "__main__":
    main()
