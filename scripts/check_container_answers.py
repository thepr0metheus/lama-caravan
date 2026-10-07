#!/usr/bin/env python3
"""Guard: every program the controller runs on its machine has a container decision.

In a container the controller does not see its machine. A command that needs
the machine — systemctl, sudo, nvidia-smi, ps — either fails somewhere inside
or, worse, answers as if the machine had nothing to report. Most of them went
to the machine's scout (caravan/admin/machine_scout.py: power, the GPU driver,
the cards and their reading, processes and snapshots); what is still run here
is named with its decision:

  MACHINE  — needs the machine. The module that runs it must ask first: it
             reads IS_CONTAINER, so a container gets a reason instead of a
             failure;
  WORKS    — fine in a container, with the reason written down.

A program the code runs and this table does not name fails the guard: a new
command needs a decision before it ships. "Runs a program" means a call of
run, run_in or a subprocess function whose first argument is a list starting
with a literal name. A MACHINE program in a module that never asks fails it
too — and there any list that starts with its name counts, because a command
is often built first and run later (`cmd = ["bash", script]`). An import of
IS_CONTAINER is not asking; only a read of it is. The guard also fails when it
finds nothing — then it is looking in the wrong place.

Run: python3 scripts/check_container_answers.py
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

MACHINE = "MACHINE"
DECISIONS = {
    "systemctl": MACHINE,
    "journalctl": MACHINE,
    "sudo": MACHINE,
    "mokutil": MACHINE,
    "nvidia-smi": MACHINE,
    "ps": MACHINE,
    "timeout": MACHINE,        # the btop snapshot of the monitor panel
    "bash": MACHINE,           # the llama.cpp build script; top in the monitor panel
    "dpkg-query": MACHINE,
    "apt-cache": MACHINE,
    "uname": MACHINE,
    "git": "WORKS: the image has no .git; the app's commit falls back to the one baked "
           "into the image (caravan/common/checkout.py), and llama.cpp's checkout is asked "
           "only by status.py, which answers for a container itself",
    "dd": "WORKS: coreutils is in every image; the verifying read of a model move reads "
          "the model folders the container itself has mounted",
    "sysctl": "WORKS: macOS only, the memory reading of a Mac; a Linux container reads /proc/meminfo",
    "vm_stat": "WORKS: macOS only, the memory reading of a Mac; a Linux container reads /proc/meminfo",
}
RUNNERS = {"run", "run_in", "Popen", "check_output", "check_call", "call"}
MUST_SEE = ("caravan/admin/monitoring.py", "caravan/admin/systemd_ctl.py")


def program_of(call):
    """The literal program name a run(...)-style call starts, or ""."""
    func = call.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
    if name not in RUNNERS or not call.args:
        return ""
    first = call.args[0]
    if isinstance(first, (ast.List, ast.Tuple)) and first.elts:
        head = first.elts[0]
        if isinstance(head, ast.Constant) and isinstance(head.value, str):
            return head.value
    return ""


def asks_first(tree):
    """Whether the module reads IS_CONTAINER — an import alone is not asking."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "IS_CONTAINER" and isinstance(node.ctx, ast.Load):
            return True
    return False


def built_machine_command(node):
    """A list or tuple that starts with a MACHINE program's name — a command built to run later.

    At least two elements: a command carries its arguments, while a lone name is
    data — `kind in ("nvidia-smi",)` or a query's default `["nvidia-smi"]`.
    """
    if isinstance(node, (ast.List, ast.Tuple)) and len(node.elts) >= 2:
        head = node.elts[0]
        if isinstance(head, ast.Constant) and DECISIONS.get(head.value) == MACHINE:
            return head.value
    return ""


def scan():
    """{module: {program: [line, ...]}} over caravan/."""
    found = {}
    for path in sorted(ROOT.glob("caravan/**/*.py")):
        rel = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        for node in ast.walk(tree):
            program = program_of(node) if isinstance(node, ast.Call) else built_machine_command(node)
            if program:
                found.setdefault(rel, {"tree": tree, "programs": {}})["programs"].setdefault(program, []).append(node.lineno)
    return found


def main():
    found = scan()
    problems = [f"не найден запуск программ в {must} — гвард смотрит не туда" for must in MUST_SEE if must not in found]
    machine_modules = 0
    for rel, entry in found.items():
        needs_asking = False
        for program, lines in sorted(entry["programs"].items()):
            decision = DECISIONS.get(program)
            if decision is None:
                problems.append(f"{rel}:{lines[0]}: программа «{program}» без решения для контейнера — "
                                f"впишите её в DECISIONS этого гварда")
            elif decision == MACHINE:
                needs_asking = True
        if needs_asking:
            machine_modules += 1
            if not asks_first(entry["tree"]):
                programs = ", ".join(sorted(p for p in entry["programs"] if DECISIONS.get(p) == MACHINE))
                problems.append(f"{rel}: запускает на машине {programs} и не спрашивает, не в контейнере ли он "
                                f"(IS_CONTAINER)")
    if problems:
        print("container answers: FAILED")
        for problem in problems:
            print("  - " + problem)
        return 1
    programs = sorted({p for entry in found.values() for p in entry["programs"]})
    print(f"container answers OK: {len(programs)} программ в {len(found)} модулях, "
          f"у каждой решение; {machine_modules} модулей с машинными командами спрашивают про контейнер")
    return 0


if __name__ == "__main__":
    sys.exit(main())
