#!/usr/bin/env python3
"""Ячейка vLLM на машине со скаутом: одна строка запуска, выполненная по-настоящему.

Скаут запускает command-ячейку одной строкой `bash -lc`, которую строит
контроллер (render_command_cell_shell_line). У vLLM в этой строке была своя
копия подготовки venv — и она разошлась со start.sh: ставила vLLM без
закреплённой версии, а `exec`, который ставится перед командой, встал перед
всей цепочкой. bash подменялся программой `[`: на новой машине ячейка
выходила с кодом 1, ничего не поставив, на машине с venv — с кодом 0, так и
не запустив vLLM. Ни один тест эту строку не выполнял.

Теперь подготовка — те же строки, что в start.sh, собранные в одну. Строка
выполняется в bash с подставными python3/pip/vllm в пустом HOME: что
ставится, с какой версией, что запускается последним и с какими
аргументами, и что второй старт ничего не ставит.

Запуск: python3 scripts/test_vllm_shell_line.py
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.admin.launch import one_line_statements, render_command_cell_shell_line  # noqa: E402
from caravan.admin.config_builder import CONFIG_FIELDS, FIELD_HELP  # noqa: E402
from caravan.common.errors import AppError  # noqa: E402
from caravan.domain.runner import get as runner_get  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


# The stand-ins write down what they were asked to do; pip "installs" by
# creating the venv's binaries, vllm says with what it was started and exits.
FAKE_PYTHON = r"""#!/usr/bin/env bash
echo "python3 $*" >> "$HOME/calls.log"
if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then
  mkdir -p "$3/bin"
  cat > "$3/bin/pip" <<'PIP'
#!/usr/bin/env bash
echo "pip $*" >> "$HOME/calls.log"
bin="$(dirname "$0")"
for arg in "$@"; do
  case "$arg" in
    vllm==*) printf '#!/usr/bin/env bash\necho "vllm $*" >> "$HOME/calls.log"\necho "served with MAX_JOBS=$MAX_JOBS PATH0=${PATH%%%%:*}"\n' > "$bin/vllm"; chmod +x "$bin/vllm" ;;
    ninja) printf '#!/usr/bin/env bash\n' > "$bin/ninja"; chmod +x "$bin/ninja" ;;
  esac
done
PIP
  chmod +x "$3/bin/pip"
fi
"""


def run(line, home, env_extra=None):
    fake = home / "fakebin"
    fake.mkdir(exist_ok=True)
    (fake / "python3").write_text(FAKE_PYTHON)
    (fake / "python3").chmod(0o755)
    env = {"HOME": str(home), "PATH": f"{fake}:/usr/bin:/bin", **(env_extra or {})}
    done = subprocess.run(["bash", "-c", line], capture_output=True, text=True, env=env, timeout=60)
    calls = (home / "calls.log").read_text().splitlines() if (home / "calls.log").exists() else []
    (home / "calls.log").unlink(missing_ok=True)
    return done.returncode, done.stdout + done.stderr, calls


def section_first_start():
    print("первый старт на машине без venv:")
    line = render_command_cell_shell_line({"RUNNER": "vllm", "VLLM_MODEL": "org/some-model", "PORT": "22012"})
    with tempfile.TemporaryDirectory() as t:
        home = Path(t)
        code, out, calls = run(line, home)
        check("[caravan] provisioning vLLM venv at" in out,
              "журнал говорит, что идёт подготовка venv — первый старт длится минуты")
        check(calls[:3] == [f"python3 -m venv {home}/vllm-venv", "pip install --quiet --upgrade pip",
                            "pip install --quiet vllm==0.30.0"],
              f"venv создан, pip обновлён, vLLM поставлен ЗАКРЕПЛЁННОЙ версией 0.30.0 (got {calls[:3]})")
        check("pip install --quiet ninja" in calls, "ninja поставлен — без него torch-inductor не компилирует")
        check(code == 0 and calls[-1] == "vllm serve org/some-model --host 0.0.0.0 --port 22012 --served-model-name some-model",
              f"последним запущен сам vLLM, с портом ячейки; negative (defect-history): раньше bash подменялся `[` "
              f"и до vLLM дело не доходило (код {code}, последний вызов {calls[-1:]})")
        check("MAX_JOBS=4" in out and f"PATH0={home}/vllm-venv/bin" in out,
              "vLLM видит окружение подготовки: MAX_JOBS=4 и venv первым в PATH")
        code, out, calls = run(line, home)
        check("provisioning" not in out and not any(c.startswith(("python3", "pip install --quiet vllm")) for c in calls)
              and calls == ["vllm serve org/some-model --host 0.0.0.0 --port 22012 --served-model-name some-model"],
              f"второй старт: venv есть — ничего не ставится, сразу vLLM (got {calls})")


def prepared_venv(home, flashinfer="", cubin=""):
    """A venv that is already there: stand-in pip (it writes down what it is asked and, asked to
    uninstall flashinfer-cubin, takes its dist-info away), vllm and ninja, and the dist-info folders
    of flashinfer-python and flashinfer-cubin at the versions given ("" — not installed)."""
    venv = home / "vllm-venv"
    (venv / "bin").mkdir(parents=True)
    site = venv / "lib" / "python3.12" / "site-packages"
    site.mkdir(parents=True)
    (venv / "bin" / "pip").write_text(
        '#!/usr/bin/env bash\necho "pip $*" >> "$HOME/calls.log"\n'
        'if [ "$1" = "uninstall" ]; then rm -rf "$(dirname "$0")"/../lib/python3*/site-packages/flashinfer_cubin-*.dist-info; fi\n')
    (venv / "bin" / "vllm").write_text('#!/usr/bin/env bash\necho "vllm $*" >> "$HOME/calls.log"\n')
    (venv / "bin" / "ninja").write_text("#!/usr/bin/env bash\n")
    for tool in ("pip", "vllm", "ninja"):
        (venv / "bin" / tool).chmod(0o755)
    if flashinfer:
        (site / f"flashinfer_python-{flashinfer}.dist-info").mkdir()
    if cubin:
        (site / f"flashinfer_cubin-{cubin}.dist-info").mkdir()
    return venv


def section_flashinfer_pair():
    print("пара flashinfer в venv:")
    line = render_command_cell_shell_line({"RUNNER": "vllm", "VLLM_MODEL": "org/some-model", "PORT": "22012"})
    serve = "vllm serve org/some-model --host 0.0.0.0 --port 22012 --served-model-name some-model"
    uninstall = "pip uninstall --quiet -y flashinfer-cubin"
    cases = (
        ("0.6.18.post1", "0.6.12", True, "defect-history 2026-10-05: cubin старой версии остался рядом с flashinfer 0.6.18.post1 — FlashInfer не стартует, «version does not match»"),
        ("0.6.13", "0.6.12", True, "любое расхождение версий, не только эта пара"),
        ("0.6.18.post1", "0.6.18.post1", False, "negative: версии равны — cubin на месте, его никто не трогает"),
        ("0.6.18.post1", "", False, "negative: cubin не стоит — снимать нечего"),
        ("", "0.6.12", False, "negative: flashinfer не стоит, а cubin есть — это не наш случай, ничего не снимается"),
        ("", "", False, "negative: ни того ни другого (venv без FlashInfer) — запуск как был"),
    )
    for flashinfer, cubin, removed, why in cases:
        with tempfile.TemporaryDirectory() as t:
            home = Path(t)
            venv = prepared_venv(home, flashinfer, cubin)
            code, out, calls = run(line, home)
            left = sorted(p.name for p in (venv / "lib" / "python3.12" / "site-packages").glob("flashinfer_cubin-*"))
            check(code == 0 and calls[-1] == serve, f"flashinfer {flashinfer or '—'} / cubin {cubin or '—'}: vLLM запущен последним, код {code} ({calls[-1:]})")
            check((uninstall in calls) is removed, why + f" (вызовы: {calls})")
            if removed:
                check("flashinfer-cubin 0.6" in out and "removing it" in out and left == [],
                      f"журнал называет обе версии и что cubin снят; папки cubin больше нет (осталось {left})")
                code, out, calls = run(line, home)
                check(uninstall not in calls and "removing it" not in out and calls[-1] == serve,
                      "второй старт: расхождения больше нет — ничего не снимается")
            else:
                check("removing it" not in out, "негатив: в журнале нет слов о снятии")


def section_trust_remote_code_and_env():
    print("--trust-remote-code и ENV у vLLM:")
    base = {"RUNNER": "vllm", "VLLM_MODEL": "org/some-model", "PORT": "22012"}
    tail = "--served-model-name some-model"
    for yes in ("1", "true", "on", " YES "):
        line = render_command_cell_shell_line({**base, "TRUST_REMOTE_CODE": yes})
        check(line.endswith(f"{tail} --trust-remote-code"), f"TRUST_REMOTE_CODE={yes!r}: флаг в конце команды (MiniCPM-o, Nemotron Omni без него не стартуют)")
    for no in ("", "0", "false", "off", "synthetic-trust_remote_code"):
        line = render_command_cell_shell_line({**base, "TRUST_REMOTE_CODE": no})
        check("--trust-remote-code" not in line and line.endswith(tail),
              f"negative: TRUST_REMOTE_CODE={no!r}: флага нет — он запускает код авторов модели, без слова оператора не ставится")
    check("--trust-remote-code" not in render_command_cell_shell_line(base), "negative: поля нет совсем — флага нет")
    # The cell's ENV is exported for a vLLM cell, before the venv is touched: what a flag of the form cannot say,
    # a variable can (HF_HOME, VLLM_ATTENTION_BACKEND, FLASHINFER_DISABLE_VERSION_CHECK).
    line = render_command_cell_shell_line({**base, "ENV": "FLASHINFER_DISABLE_VERSION_CHECK=1\nHF_HOME=/data/hf"})
    check('export FLASHINFER_DISABLE_VERSION_CHECK="1"; export HF_HOME="/data/hf"' in line
          and line.index("export HF_HOME") < line.index("provisioning vLLM venv"),
          "ENV ячейки vLLM уходит в строку запуска: каждая пара — export, до подготовки venv")
    with tempfile.TemporaryDirectory() as t:
        home = Path(t)
        venv = prepared_venv(home)
        (venv / "bin" / "vllm").write_text('#!/usr/bin/env bash\necho "vllm sees FLASHINFER_DISABLE_VERSION_CHECK=$FLASHINFER_DISABLE_VERSION_CHECK HF_HOME=$HF_HOME"\n')
        code, out, _calls = run(line, home)
        check(code == 0 and "vllm sees FLASHINFER_DISABLE_VERSION_CHECK=1 HF_HOME=/data/hf" in out,
              f"и сам vLLM видит эти переменные в своём окружении (код {code}, вывод {out.strip()!r})")
    check("export FLASHINFER" not in render_command_cell_shell_line(base), "negative: без ENV — ни одного лишнего export")


def refused(config):
    """(status, message) when the line is refused, None when it is built."""
    try:
        render_command_cell_shell_line(config)
    except AppError as err:
        return err.status, str(err)
    return None


def section_recipe_flags():
    print("флаги из рецепта модели — --max-num-seqs, --kv-cache-dtype, --reasoning-parser:")
    base = {"RUNNER": "vllm", "VLLM_MODEL": "org/some-model", "PORT": "22012"}
    tail = "--served-model-name some-model"
    # Nemotron 3 Nano Omni needed all three and went through a custom command, because the vLLM tab had no field for them.
    recipe = {**base, "MAX_NUM_SEQS": " 8 ", "KV_CACHE_DTYPE": " FP8 ", "REASONING_PARSER": " nano_v3 ", "TRUST_REMOTE_CODE": "1"}
    line = render_command_cell_shell_line(recipe)
    check(line.endswith(f"{tail} --max-num-seqs 8 --kv-cache-dtype fp8 --reasoning-parser nano_v3 --trust-remote-code"),
          "все три и TRUST_REMOTE_CODE: флаги по порядку, значения без пробелов, тип KV — строчными; --trust-remote-code по-прежнему последний")
    for field, value, flag in (("MAX_NUM_SEQS", "16", "--max-num-seqs 16"), ("KV_CACHE_DTYPE", "fp8_e5m2", "--kv-cache-dtype fp8_e5m2"),
                               ("REASONING_PARSER", "deepseek_r1", "--reasoning-parser deepseek_r1"),
                               ("REASONING_PARSER", "qwen3.5", "--reasoning-parser qwen3.5")):
        line = render_command_cell_shell_line({**base, field: value})
        check(line.endswith(f"{tail} {flag}") and line.count("--max-num-seqs") + line.count("--kv-cache-dtype") + line.count("--reasoning-parser") == 1,
              f"{field}={value!r}: один флаг, и только он")
    for field, value in (("MAX_NUM_SEQS", ""), ("MAX_NUM_SEQS", "   "), ("KV_CACHE_DTYPE", ""), ("KV_CACHE_DTYPE", "auto"),
                         ("KV_CACHE_DTYPE", " AUTO "), ("REASONING_PARSER", ""), ("REASONING_PARSER", "  ")):
        line = render_command_cell_shell_line({**base, field: value})
        check(line.endswith(tail), f"negative: {field}={value!r}: флага нет (пусто — слово vLLM; auto — тип модели)")
    line = render_command_cell_shell_line(base)
    check(line.endswith(tail), "negative: полей нет совсем — строка как была")
    # The value goes into a shell line: its shape is checked, and a value of another shape is refused by the field's name,
    # not replaced by the default (a cell started with other flags than the form shows is the wrong cell).
    for field, value, what in (
            ("MAX_NUM_SEQS", "0", "ноль — не число последовательностей"), ("MAX_NUM_SEQS", "-1", "отрицательное"),
            ("MAX_NUM_SEQS", "1.5", "дробное"), ("MAX_NUM_SEQS", "eight", "слово"), ("MAX_NUM_SEQS", "08", "с нулём впереди"),
            ("MAX_NUM_SEQS", "1234567", "семь знаков — не число последовательностей"),
            ("MAX_NUM_SEQS", "8; rm -rf ~", "оболочка"), ("KV_CACHE_DTYPE", "fp8 --foo", "второй флаг"),
            ("KV_CACHE_DTYPE", "fp8;reboot", "оболочка"), ("KV_CACHE_DTYPE", "fp-8", "дефис — не имя типа"),
            ("KV_CACHE_DTYPE", "x" * 41, "длиннее 40"), ("REASONING_PARSER", "a b", "пробел"),
            ("REASONING_PARSER", "x; reboot", "оболочка"), ("REASONING_PARSER", "$(id)", "подстановка"),
            ("REASONING_PARSER", "p" * 65, "длиннее 64")):
        got = refused({**base, field: value})
        check(got is not None and got[0] == 400 and got[1].startswith(f"{field} must be "),
              f"negative: {field}={value[:20]!r} ({what}): отказ 400, в нём имя поля (got {got})")
    check(refused({**base, "MAX_NUM_SEQS": "999999", "KV_CACHE_DTYPE": "x" * 40, "REASONING_PARSER": "p" * 64}) is None,
          "boundary: шесть знаков, 40 и 64 — ровно на пределе, строка строится")
    # The runner itself, handed padded values (the line above comes through a config that is trimmed on the way in):
    # a value is trimmed here too, not refused for its spaces.
    padded = runner_get("vllm").command({**base, "MAX_NUM_SEQS": " 8 ", "KV_CACHE_DTYPE": " FP8 ", "REASONING_PARSER": " nano_v3 "})
    check(padded.endswith(f"{tail} --max-num-seqs 8 --kv-cache-dtype fp8 --reasoning-parser nano_v3"),
          f"VllmRunner.command сам срезает пробелы у значений ({padded[-70:]!r})")
    # The form's words are the server's words: the same help in FIELD_HELP and in the dictionary the form reads.
    en = (ROOT / "static" / "js" / "i18n" / "en.js").read_text(encoding="utf-8")
    for field in ("MAX_NUM_SEQS", "KV_CACHE_DTYPE", "REASONING_PARSER"):
        in_dictionary = re.search(r'^    ' + field + r': (".*"),$', en, re.M)
        check(field in CONFIG_FIELDS and in_dictionary is not None and json.loads(in_dictionary.group(1)) == FIELD_HELP.get(field),
              f"{field}: поле конфига, и подсказка у сервера слово в слово та, что читает форма (en.js)")
    # The line runs, and vLLM is started with exactly these arguments.
    with tempfile.TemporaryDirectory() as t:
        home = Path(t)
        prepared_venv(home)
        code, out, calls = run(render_command_cell_shell_line(recipe), home)
        check(code == 0 and calls[-1] == f"vllm serve org/some-model --host 0.0.0.0 --port 22012 {tail} --max-num-seqs 8"
              " --kv-cache-dtype fp8 --reasoning-parser nano_v3 --trust-remote-code",
              f"строка выполнена в bash: vLLM получил те же аргументы (код {code}, последний вызов {calls[-1:]})")


def section_the_version():
    print("версия задаётся переменной:")
    line = render_command_cell_shell_line({"RUNNER": "vllm", "VLLM_MODEL": "org/some-model", "PORT": "22012"})
    with tempfile.TemporaryDirectory() as t:
        code, out, calls = run(line, Path(t), {"VLLM_VERSION": "0.25.1"})
    check("pip install --quiet vllm==0.25.1" in calls, "VLLM_VERSION в окружении ячейки ставит свою версию, как в start.sh")


def section_one_line():
    print("строки скрипта одной строкой:")
    got = one_line_statements(["if [ ! -x X ]; then", "  echo a", "  b", "fi", "", "for f in 1 2; do", "echo $f",
                               "done", "c"])
    check(got == ["if [ ! -x X ]; then echo a", "b", "fi", "for f in 1 2; do echo $f", "done", "c"],
          f"после then/do — пробел, а не «;» (then; — синтаксическая ошибка); пустые строки выпадают (got {got})")
    check(one_line_statements(["x=then", "git undo", "echo next"]) == ["x=then", "git undo", "echo next"],
          "negative: строка, лишь кончающаяся на then/do (x=then, undo), блока не открывает — следующая идёт через «;»")
    for runner, cfg in (("whisper", {"RUNNER": "whisper", "PORT": "22024"}),
                        ("custom", {"RUNNER": "custom", "CELL_KIND": "command", "COMMAND": "python srv.py", "PORT": "22030"})):
        line = render_command_cell_shell_line(cfg)
        check(line.count("exec ") == 1 and "; exec " in line,
              f"negative: у {runner} подготовки нет — строка как была, один exec перед командой")


def main():
    if not (Path("/bin/bash").exists() or Path("/usr/bin/bash").exists()):
        print("vllm shell line: SKIPPED — нет bash")
        return 0
    section_first_start()
    section_flashinfer_pair()
    section_trust_remote_code_and_env()
    section_recipe_flags()
    section_the_version()
    section_one_line()
    if _fail:
        print(f"\nFAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m)
        return 1
    print("\nvllm shell line OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
