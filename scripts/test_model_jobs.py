#!/usr/bin/env python3
"""Value snapshot: what a model DOES, as opposed to what launches it.

The rule lives twice — caravan/common/model_jobs.py and
static/js/model-jobs.js — because the picker decides in the browser and the
board decides on the server. Both copies are run here against ONE table of
cases: diverging twins would be exactly the defect this rule was split into
its own file to prevent.

What's pinned. That a `.gguf` is an LLM or a recognizer by its OWN metadata and
not by its extension; that seamless is speech-translate and NOT asr (it returns
the target language only, never a transcript, so a consumer picking it up as a
recognizer would get a translation labelled as a transcription); that a cell's
live `kinds` outranks the runner table, which is the only way a TTS cell run as
a typed command can be named as one; and that an unnameable job answers with
NOTHING rather than falling back to "llm" — the silence this rule exists to end.

Run: python3 scripts/test_model_jobs.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _node import find_node  # noqa: E402
from caravan.common.model_jobs import (  # noqa: E402
    JOBS, jobs_for_artifact, jobs_for_cell, jobs_from_kinds,
)

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


# (name, kind, sttVariant, arch, family, expected jobs, what the pin is for)
ARTIFACTS = [
    ("embed_gguf", "model", "", "", "embedding", ["embed"],
     "positive: эмбеддинговая модель — ОТДЕЛЬНАЯ работа: она отдаёт векторы, а чат с той же ячейки llama.cpp не поднимет; первая версия правила звала её «LLM», и живая Qwen3-Embedding ходила по доске с 💬"),
    ("chat_gguf_family_blank", "model", "", "", "", ["llm"],
     "negative: семейство не названо — обычная языковая модель, а не эмбеддинги по догадке"),
    ("chat_gguf", "model", "", "", "qwen", ["llm"],
     "обычный gguf — LLM; и это СКАЗАНО, а не выведено из того, что про него молчат"),
    ("asr_gguf", "model", "gigaam-rnnt", "", "asr", ["asr"],
     "тот же .gguf, но с речевыми метаданными — распознавание; расширение их не различает"),
    ("asr_gguf_whitespace_variant", "model", "   ", "", "", ["llm"],
     "boundary: пробельный stt.variant — это НЕ речевые веса, а пустое поле"),
    ("safetensors_chat", "st", "", "qwen3", "", ["llm"],
     "safetensors под vLLM — тоже LLM"),
    ("safetensors_seamless", "st", "", "seamless_m4t_v2", "", ["speech-translate"],
     "positive: seamless — речь → перевод, ОТДЕЛЬНАЯ работа от распознавания: транскрипта он не отдаёт"),
    ("whisper_size", "whisper", "", "", "", ["asr"],
     "whisper — распознавание, хотя «модель» тут это размер"),
    ("moonshine_lang", "moonshine", "", "", "", ["asr", "tts"],
     "moonshine делает ДВЕ работы — и распознаёт, и синтезирует: одна строка ≠ одна работа"),
    ("nllb_repo", "translate", "", "", "", ["translate"],
     "NLLB — перевод текста в текст"),
    ("unknown_kind", "sherpa", "", "", "", [],
     "negative: неизвестный вид — НИЧЕГО, а не «llm» по умолчанию; выдуманная работа хуже названной"),
    ("empty_kind", "", "", "", "", [],
     "negative: пустой вид — тоже ничего"),
]

# (name, runnerId, kinds, expected jobs, what the pin is for)
CELLS = [
    ("llama_cell", "llama-server", [], ["llm"],
     "раннер без живого отчёта — работа из таблицы раннеров"),
    ("vllm_cell", "vllm", [], ["llm"], "vLLM — тоже LLM"),
    ("whisper_cell_dotted_kind", "whisper", ["stt.whisper"], ["asr"],
     "positive: «stt.whisper» читается по первому сегменту — движок в слове, а работа всё равно понятна"),
    ("transcribe_cell_bare_kind", "transcribe", ["asr"], ["asr"],
     "…и голое «asr» из другой ячейки значит ТО ЖЕ САМОЕ — два написания одной работы"),
    ("moonshine_cell_two_jobs", "moonshine", ["asr", "tts"], ["asr", "tts"],
     "две работы разом — обе и названы"),
    ("seamless_cell", "seamless", ["speech-translate"], ["speech-translate"],
     "positive: seamless говорит про себя правду — речь → перевод"),
    ("custom_tts_cell_named_by_itself", "custom", ["tts"], ["tts"],
     "positive: TTS живёт командной ячейкой, и назвать её работой может ТОЛЬКО её собственный отчёт"),
    ("custom_cell_silent", "custom", [], [],
     "negative: командная ячейка молчит — работы не выдумываем: команду печатал человек, раннер про неё не знает"),
    ("live_kinds_outrank_the_table", "whisper", ["tts"], ["tts"],
     "живой отчёт ПЕРЕВЕШИВАЕТ таблицу: ячейка знает про себя больше, чем ожидание от раннера"),
    ("unknown_kinds_fall_back_to_runner", "whisper", ["sorcery"], ["asr"],
     "boundary: непонятное слово в kinds — не отчёт; падаем на таблицу раннера, а не показываем пусто"),
    ("unknown_runner_silent", "sherpa", [], [],
     "negative: неизвестный раннер без отчёта — молчание, а не догадка"),
    ("kinds_order_is_the_vocabulary", "custom", ["tts", "asr"], ["asr", "tts"],
     "порядок чипов задан словарём, а не порядком в отчёте: две ячейки с теми же работами рисуются одинаково"),
]


#: What each cell server declares about itself, by value. The guard next door
#: (check_cell_kinds.py) can only see that a word is IN the vocabulary — whether
#: it is the RIGHT word is a claim about the cell's behaviour, and that belongs
#: in a snapshot. Seamless spent its whole life saying "asr" while its own
#: docstring said it never produces a transcript; nothing could have caught that
#: except pinning what it says.
DECLARED = {
    "moonshine_server.py": ["asr", "tts"],
    "seamless_server.py": ["speech-translate"],
    "transcribe_server.py": ["asr"],
    "translate_server.py": ["translate"],
    "tts_server.py": ["tts", "tts.*"],
    "whisper_server.py": ["asr", "stt.whisper"],
}


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
    print("правило на сервере — артефакты пикера:")
    py_art = {}
    for name, kind, variant, arch, family, want, msg in ARTIFACTS:
        got = list(jobs_for_artifact(kind, variant, arch, family))
        py_art[name] = got
        check(got == want, f"{msg} (got {got})")

    print("правило на сервере — работающие ячейки:")
    py_cell = {}
    for name, runner, kinds, want, msg in CELLS:
        got = list(jobs_for_cell(runner, kinds))
        py_cell[name] = got
        check(got == want, f"{msg} (got {got})")

    check(jobs_from_kinds(None) == () and jobs_from_kinds([]) == (),
          "negative: kinds отсутствуют или пусты — пустой ответ, а не падение")
    check(jobs_from_kinds(["STT.Whisper", " ASR "]) == ("asr",),
          "регистр и пробелы в kinds не мешают: одна работа, одно слово")
    check(tuple(JOBS) == ("llm", "embed", "asr", "tts", "translate", "speech-translate"),
          "словарь — ровно шесть работ, и его порядок и есть порядок чипов")

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
        'const out = { art: {}, cell: {} };\n'
        'for (const [n, k, v, a, fam] of arts) out.art[n] = m.jobsForArtifact(k, v, a, fam);\n'
        'for (const [n, r, k] of cells) out.cell[n] = m.jobsForCell(r, k);\n'
        'out.__jobs = m.JOBS;\n'
        'out.__empty = [m.jobsFromKinds(null), m.jobsFromKinds([])];\n'
        'out.__case = m.jobsFromKinds(["STT.Whisper", " ASR "]);\n'
        'console.log(JSON.stringify(out));\n'
    )
    try:
        env = {**os.environ, "JS_FILE": str(ROOT / "static" / "js" / "model-jobs.js")}
        run = subprocess.run([node, str(probe)], capture_output=True, text=True,
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
    diverged = ([n for n in py_art if js["art"].get(n) != py_art[n]]
                + [n for n in py_cell if js["cell"].get(n) != py_cell[n]])
    check(not diverged,
          f"обе копии правила отвечают ОДИНАКОВО на всей таблице (разошлись: {diverged})")
    check(js["__jobs"] == list(JOBS), f"словарь совпадает в обеих копиях (got {js['__jobs']})")
    check(js["__empty"] == [[], []], "js: пустые kinds — пустой ответ")
    check(js["__case"] == ["asr"], f"js: регистр и пробелы так же (got {js['__case']})")
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
