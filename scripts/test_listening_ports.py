#!/usr/bin/env python3
"""Snapshot of ListeningPorts (caravan/admin/listening_ports.py) and of the scan
that reads it, by value, on a /proc tree written by hand.

The table is the kernel's own format: hex ports, state 0A for LISTEN, the inode
in the tenth column; a socket's owner is the process whose fd links to that
inode. On Linux one more case reads the real /proc: a socket this test opens
must come back as this test's own process. Elsewhere that case is skipped and
says so.

Run: python3 scripts/test_listening_ports.py
"""
import os
import socket
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(tempfile.mkdtemp(prefix="caravan-listen-"))
os.environ["CARAVAN_DATA_DIR"] = str(DATA)
os.environ["HOME"] = str(DATA)
sys.path.insert(0, str(ROOT))

import caravan.admin.port_exclusions as pe  # noqa: E402
from caravan.admin.listening_ports import ListeningPorts  # noqa: E402
from caravan.admin.systemd_ctl import listening_pid  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


HEADER = "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode"
BASE = pe.SERVER_CELL_BASE_PORT
OUTSIDE = pe.SCAN_UPPER + 5


def row(index, port, state, inode, v6=False):
    local = ("0" * 32 if v6 else "00000000") + f":{port:04X}"
    return (f"   {index}: {local} {'0' * (32 if v6 else 8)}:0000 {state} 00000000:00000000 00:00000000 "
            f"00000000  1000        0 {inode} 1 0000000000000000 100 0 0 10 0")


def fake_proc(with_tables=True):
    proc = Path(tempfile.mkdtemp(prefix="caravan-proc-"))
    (proc / "net").mkdir()
    if with_tables:
        (proc / "net" / "tcp").write_text("\n".join([
            HEADER,
            row(0, BASE, "0A", "1111"),            # a cell's llama-server, ours to see
            row(1, BASE + 1, "01", "4444"),        # an established connection, not a listener
            row(2, OUTSIDE, "0A", "6666"),          # a listener above the scanned range
        ]) + "\n")
        (proc / "net" / "tcp6").write_text("\n".join([
            HEADER,
            row(0, BASE + 2, "0A", "5555", v6=True),   # somebody else's: no fd of ours links to it
            row(1, BASE + 3, "0A", "3333", v6=True),   # a python process of ours
        ]) + "\n")
    for pid, comm, links in ((1234, "llama-server", {"3": "socket:[1111]", "4": "/dev/null"}),
                             (99, "python3", {"7": "socket:[3333]"})):
        (proc / str(pid) / "fd").mkdir(parents=True)
        (proc / str(pid) / "comm").write_text(comm + "\n")
        for fd, target in links.items():
            os.symlink(target, proc / str(pid) / "fd" / fd)
    (proc / "self").mkdir()
    return proc


def test_table():
    print("таблица ядра:")
    ports = ListeningPorts(fake_proc())
    check(ports.known, "таблица прочитана")
    check(ports.ports() == [BASE, BASE + 2, BASE + 3, OUTSIDE],
          f"слушающие порты из tcp и tcp6, без установленного соединения (получено {ports.ports()})")
    check(ports.owner(BASE) == (1234, "llama-server"), f"свой процесс назван (получено {ports.owner(BASE)})")
    check(ports.owner(BASE + 3) == (99, "python3"), f"и в tcp6 тоже (получено {ports.owner(BASE + 3)})")
    check(ports.owner(BASE + 2) == (0, "?"), f"чужой сокет: занят, хозяин неизвестен (получено {ports.owner(BASE + 2)})")
    check(ports.owner(BASE + 1) == (0, ""), f"порт без слушателя свободен (получено {ports.owner(BASE + 1)})")
    check(ports.busy(OUTSIDE) and not ports.busy(BASE + 1), "занят / свободен")
    proc = fake_proc()
    check([listening_pid(port, proc) for port in (BASE, BASE + 1, BASE + 2)] == [(1234, "llama-server"), (0, ""), (0, "?")],
          "listening_pid отвечает по той же таблице: свой / свободен / чужой")


def test_no_table():
    print("машина без таблицы:")
    ports = ListeningPorts(fake_proc(with_tables=False))
    check(not ports.known, "known = False: «не знаю», а не «свободно»")
    check(ports.ports() == [] and ports.owner(BASE) == (0, ""), "портов нет, владельца нет")


def test_scan():
    print("скан диапазона ячеек:")
    found = pe.scan_foreign_listeners(listening=ListeningPorts(fake_proc()))
    controller = found["hosts"][0]
    check(controller["ok"] is True, "машина контроллера просканирована")
    check(controller["ports"] == [{"port": BASE, "proc": "llama-server", "pid": 1234},
                                  {"port": BASE + 2, "proc": "?", "pid": 0},
                                  {"port": BASE + 3, "proc": "python3", "pid": 99}],
          f"чужие слушатели диапазона, порт выше диапазона — нет (получено {controller['ports']})")
    blind = pe.scan_foreign_listeners(listening=ListeningPorts(fake_proc(with_tables=False)))["hosts"][0]
    check(blind["ok"] is False and blind["ports"] == [] and "no table" in blind.get("error", ""),
          f"без таблицы — «не просканировано» с причиной, а не «чисто» (получено {blind})")


def test_real_proc():
    print("настоящий /proc:")
    if not Path("/proc/net/tcp").exists():
        print("  --  пропущено: на этой машине нет /proc/net/tcp")
        return
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    comm = Path("/proc/self/comm").read_text().strip()
    try:
        check(listening_pid(port) == (os.getpid(), comm),
              f"свой слушающий сокет найден со своим pid (получено {listening_pid(port)})")
    finally:
        server.close()
    check(listening_pid(port) == (0, ""), "закрытый — свободен")


for fn in (test_table, test_no_table, test_scan, test_real_proc):
    fn()

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("all listening-ports snapshots hold")
