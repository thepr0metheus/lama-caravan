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
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.admin.launch import one_line_statements, render_command_cell_shell_line  # noqa: E402

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
                            "pip install --quiet vllm==0.24.0"],
              f"venv создан, pip обновлён, vLLM поставлен ЗАКРЕПЛЁННОЙ версией 0.24.0 (got {calls[:3]})")
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
