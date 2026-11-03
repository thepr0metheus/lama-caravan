#!/usr/bin/env python3
"""Guard: every place the controller runs a program on its machine has a container decision.

In a container the controller does not see its machine. A command that needs the machine — systemctl, nvidia-smi, ps — either fails somewhere inside or, worse, answers as
if the machine had nothing to report. Most of them went to the machine's scout; what is still run here is named with its decision, by the file that runs it. A file the
code runs a program from, and this table does not name, fails the guard: a new command needs a decision before it ships. So does a file named here that runs nothing, for
then the table has fallen behind.

Run: python3 scripts/check_container_answers.py
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _rust_source import RustSource  # noqa: E402

DECISIONS = {
    "common/checkout.rs": "git: fine in a container: the image has no .git, and the commit falls back to the one the release was built from",
    "monitoring/machine.rs": "sysctl, vm_stat: macOS only, the memory reading of a Mac; a Linux container reads /proc/meminfo",
    "proxies/service.rs": "the proxy, its child; systemctl only outside a container: `paths.is_container` is asked first",
    "status.rs": "git over the checkout it asks of, for a controller that has one: it answers for a container itself",
    "status/llama_build.rs": "a llama.cpp build on this machine: asked of a controller outside a container only",
    "models/moves/mover/copy.rs": "dd: coreutils is in the image; the verifying read of a model move reads the folders the container has mounted",
    "models/store_probe.rs": "this very program, as the child that probes a store",
}
RUNS = re.compile(r"commands\.run\(|Command::new\(")


def main():
    running = {}
    for rel, lines in RustSource.files("admin/src"):
        short = rel.removeprefix("rust/crates/admin/src/")
        hits = [number for number, line in enumerate(lines, 1) if RUNS.search(line)]
        if hits:
            running[short] = hits
    problems = [f"{rel}:{hits[0]}: запускает программу, а решения для контейнера нет — впишите файл в DECISIONS этого гварда"
                for rel, hits in sorted(running.items()) if rel not in DECISIONS]
    problems += [f"{rel}: в DECISIONS, а программ не запускает — таблица отстала от кода" for rel in sorted(set(DECISIONS) - set(running))]
    if problems:
        print("container answers: FAILED")
        for problem in problems:
            print("  - " + problem)
        return 1
    print(f"container answers OK: {len(running)} файлов запускают программы, у каждого решение")
    return 0


if __name__ == "__main__":
    sys.exit(main())
