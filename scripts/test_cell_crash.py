#!/usr/bin/env python3
"""Value snapshot: the words a cell writes, read one way (CellWords).

A cell tells why it would not start, where its start is, and what killed it
only in its own lines — llama.cpp's, vLLM's, the driver's, a launch
script's. Its scout carries them to the board: a crash note (the reason and
the last lines) and the lines written while the port did not listen yet.
The controller reads them with one vocabulary, whoever carried them. Until
step 6.9 it read the journal of its own cells with the same words; those
cells moved to its machine's scout, and the journal parse went with them.

What is pinned is the vocabulary as values: every word of every table gives
its own kind (no entry swallowed by an earlier one — one is, as-is, below),
the order that decides a line naming two kinds, and what comes back when no
word says anything. How a crash note reaches the card is pinned in
test_topology_remote_cells.py.

Run: python3 scripts/test_cell_crash.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.admin.cell_words import CellWords  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def every_word(table, read):
    """[(kind, word, what reading the word alone gives)] for a table."""
    return [(kind, word, read(word)) for kind, words in table for word in words]


def test_failure_kind():
    print("почему ячейка не стартовала (failure_kind):")
    check([kind for kind, _ in CellWords.FAILURE] == ["exec", "oom", "model", "port"],
          "виды по порядку: exec, oom, model, port — порядок и есть правило")
    wrong = [(k, w, got) for k, w, got in every_word(CellWords.FAILURE, CellWords.failure_kind) if got != k]
    check(wrong == [], f"каждое слово таблицы даёт свой вид — ни одно не съедено более ранним (got {wrong})")
    guards = [CellWords.failure_kind(w) for w in (
        "Model not found: /home/x/models/M/m.gguf", "MMProj not found: /home/x/models/M/p.gguf",
        "Spec draft not found: /mnt/lib/M/d.gguf", "Library not mounted: NAS (/mnt/lib)")]
    check(guards == ["model"] * 4,
          f"слова скрипта запуска — «нет модели», «нет проектора», «нет черновика», «библиотека не смонтирована» — "
          f"это «модель», а не необъяснимый крэш (got {guards})")
    check(CellWords.failure_kind("cudaMalloc failed: out of memory\nllama_model_load: error loading model") == "oom",
          "нехватка памяти важнее «модели»: такой лог всегда заканчивается и «error loading model»")
    check(CellWords.failure_kind("bind: Address already in use") == "port"
          and CellWords.failure_kind("status=203/EXEC") == "exec",
          "регистр не важен: «Address already in use» — порт, «203/EXEC» — не нашёлся исполняемый файл")
    check(CellWords.failure_kind("gguf_init_from_file: failed to open /m/x.gguf: Permission denied") == "exec",
          "as-is: «Permission denied» — всегда exec, даже про файл модели: exec стоит первым")
    check([CellWords.failure_kind(w) for w in ("Segmentation fault (core dumped)", "", None)] == ["crash"] * 3,
          "negative: незнакомые слова, пусто, None — «crash», а не выдуманная причина")


def test_crash_kind():
    print("чем ячейка УПАЛА (crash_kind):")
    check([kind for kind, _ in CellWords.CRASH] == ["gpu-hang", "gpu-oom", "assert", "killed"],
          "виды по порядку: gpu-hang, gpu-oom, assert, killed")
    wrong = [(k, w, got) for k, w, got in every_word(CellWords.CRASH, CellWords.crash_kind) if got != k]
    check(wrong == [("killed", "out of memory: killed process", "gpu-oom")],
          f"as-is: одно слово таблицы съедено — OOM-киллер ядра («Out of memory: Killed process») читается как "
          f"нехватка памяти КАРТЫ: gpu-oom стоит раньше (got {wrong})")
    check(CellWords.crash_kind("CUDA error: the launch timed out and was terminated") == "gpu-hang",
          "Xid 8 с карты (прод 2026-09-06) — зависание карты")
    check(CellWords.crash_kind("NVRM: Xid 31, out of memory") == "gpu-hang",
          "зависание важнее нехватки: строка с Xid и «out of memory» — gpu-hang")
    check(CellWords.crash_kind("cudaMalloc failed: out of memory") == "gpu-oom",
          "нехватка памяти карты отличается от зависания")
    check(CellWords.crash_kind("GGML_ASSERT(n > 0) failed") == "assert", "проверка llama.cpp — assert")
    check([CellWords.crash_kind(w) for w in ("died of SIGKILL", "died of SIGSEGV", "died of SIGABRT")]
          == ["killed", "crash", "crash"],
          "скаут 2.6 называет сигнал: SIGKILL — «убита», SIGSEGV/SIGABRT — «крэш»; negative: «died» само по себе не вид")
    check([CellWords.crash_kind(w) for w in ("exited (code 1)", "", None)] == ["crash"] * 3,
          "negative: незнакомые слова, пусто, None — «crash»")


def test_progress_note():
    print("где сейчас старт (progress_note):")
    check([label for label, _ in CellWords.PROGRESS] == [
        "starting API", "capturing CUDA graphs", "compiling kernels", "loading weights",
        "downloading model", "provisioning venv", "warming up"],
          "стадии — от поздней к ранней")
    wrong = [(k, w, got) for k, w, got in every_word(CellWords.PROGRESS, CellWords.progress_note) if got != k]
    check(wrong == [], f"каждое слово таблицы даёт свою стадию (got {wrong})")
    check(CellWords.progress_note("Loading safetensors checkpoint shards\nstarting vLLM API server") == "starting API",
          "решает ПОСЛЕДНЯЯ строка, где стадия названа: заметка идёт за стартом")
    check(CellWords.progress_note("starting vLLM API server\nLoading safetensors checkpoint shards") == "loading weights",
          "negative: не самая поздняя стадия из всех строк, а последняя строка")
    check(CellWords.progress_note("loading weights\nnothing to see\n\n") == "loading weights",
          "строки без слов пропускаются — берётся последняя, где слово есть")
    check(CellWords.progress_note("torch.compile took 12 s, capturing CUDA graph 3/67") == "capturing CUDA graphs",
          "строка с двумя стадиями — более поздняя по таблице")
    check([CellWords.progress_note(w) for w in ("nothing here", "", None)] == ["", "", ""],
          "negative: нет слов, пусто, None — пустая заметка, а не выдуманная стадия")


test_failure_kind()
test_crash_kind()
test_progress_note()

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("all cell-words snapshots hold")
