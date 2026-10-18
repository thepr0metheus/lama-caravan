#!/usr/bin/env python3
"""Guard: no script picks its own free port — they draw from scripts/_ports.py, which never gives a port twice.

Thirteen scripts carried a copy of the same eight lines (bind to port 0, read the number, close the socket, return it), and
test_proxy_forward.py asked about 60 times before any server bound: the kernel handed one port out twice and the second server died with
"Address already in use" (GitLab pipeline 30 of MR !130, 2026-10-14; the pool is scripts/_ports.py, 1.3.569). A copy that is written
again brings the race back with it.

Fails three ways: a script binds port 0 itself (on any address) and is not named below with its reason; a script defines its own
`free_port`; and a script named below that no longer binds port 0 (the list must not say what is no longer so). It does not look for
scripts/_ports.py itself: every script that imports it dies on the import without it.

Run: python3 scripts/check_test_ports.py
"""
import re
import sys
from pathlib import Path


class TestPorts:
    #: Scripts that bind port 0 on purpose, with the reason: it is not a free port they ask for.
    ALLOWED = {
        "test_cell_servers.py": "holder: another process's listener on every address, kept open on purpose",
        "test_listening_ports.py": "the socket stays open and listening: it is the thing under test",
        "test_machine_scout.py": "closed_port(): a port nobody listens on, on purpose",
    }
    #: Scripts that write the pattern down as TEXT (the guard's own regex, a breakage for the guard's self-test): they ask for no port.
    TEXT_ONLY = ("check_test_ports.py", "test_guards_fail.py")
    POOL = "_ports.py"
    #: `.bind((HOST, 0))` with any host: the copies of the eight lines said "127.0.0.1", but a test that holds a port open says "0.0.0.0".
    BIND_ZERO = re.compile(r"\.bind\(\(\s*[^,()]+,\s*0\s*\)\)")
    OWN_DEF = re.compile(r"^def free_port\(", re.M)

    def __init__(self, root):
        self.scripts = sorted((Path(root) / "scripts").glob("*.py"))

    def problems(self):
        found = []
        binding = set()
        for path in self.scripts:
            if path.name == self.POOL or path.name in self.TEXT_ONLY:
                continue
            text = path.read_text(encoding="utf-8")
            if self.BIND_ZERO.search(text):
                binding.add(path.name)
                if path.name not in self.ALLOWED:
                    found.append(f"scripts/{path.name} просит у ядра свободный порт сам (bind на порт 0): бери free_port из scripts/_ports.py — "
                                 f"он не отдаёт один порт дважды; а если порт 0 здесь нужен не как «свободный», впиши файл в ALLOWED с причиной")
            if self.OWN_DEF.search(text):
                found.append(f"scripts/{path.name} заводит свой free_port: он снова отдаст один порт дважды — нужен free_port из scripts/_ports.py")
        for name in sorted(set(self.ALLOWED) - binding):
            found.append(f"ALLOWED называет scripts/{name}, который порт 0 больше не просит: список не должен говорить того, чего уже нет")
        return found


def main():
    found = TestPorts(Path(__file__).resolve().parent.parent).problems()
    if found:
        print("test ports: FAILED")
        for line in found:
            print("  - " + line)
        return 1
    print(f"test ports OK: ни один скрипт не просит свободный порт сам; исключений с причиной — {len(TestPorts.ALLOWED)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
