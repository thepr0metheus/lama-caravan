#!/usr/bin/env python3
"""Value snapshot: when a deploy restarts the proxy, and how it knows what the proxy runs.

The decision (scripts/proxy_restart.py) is pinned row by row: every reason to
restart — not running, no record, a record that is not the running process's,
a commit this repository lacks, a changed proxy file — and every reason to
keep it — nothing the proxy runs changed, only the release number did. Around
it, by value too: the facts as deploy.sh gathers them, the start record the
proxy writes and reads back (caravan/proxy/started.py), the one rule for a
checkout's commit (caravan/common/checkout.py), the diff on a real git
repository, and — end to end — a real proxy process writing its record.

Run: python3 scripts/test_proxy_restart.py
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from proxy_restart import ProxyFacts, ProxyRestart, changed_files  # noqa: E402
from caravan.common.checkout import CheckoutCommit  # noqa: E402
from caravan.proxy.started import StartRecord  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def git(repo, *args):
    run = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                         cwd=repo, capture_output=True, text=True, check=True)
    return run.stdout.strip()


def commit_files(repo, files, message):
    for rel, text in files.items():
        path = Path(repo) / rel
        if text is None:
            path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


A = "a" * 40
RUNNING = ProxyFacts("active", 4242, A, 4242)

COVERS = [
    ("agent-proxies.py", True, "the launcher"),
    ("caravan/proxy/handler.py", True, "the proxy package"),
    ("caravan/common/checkout.py", True, "the shared package the proxy imports"),
    ("caravan/proxyx/a.py", False, "a neighbour whose name only begins the same"),
    ("caravan/commonly.py", False, "the same trap on the other package"),
    ("caravan/__init__.py", False, "the release number — kept out on purpose"),
    ("caravan/admin/routes.py", False, "the board"),
    ("static/js/topology-dnd.js", False, "the page"),
    ("agent-proxies.py.bak", False, "a file named like the launcher"),
]

# (facts, changed, action, what the reason says)
VERDICTS = [
    (ProxyFacts("inactive", 0, A, 4242), [], "restart", "the proxy is not running (inactive)"),
    (ProxyFacts("", 0, "", 0), [], "restart", "the proxy is not running (no answer)"),
    (ProxyFacts("active", 4242, "", 4242), [], "restart", "does not say which commit it runs"),
    (ProxyFacts("active", 4242, A, 1111), [], "restart", "record pid 1111, running pid 4242"),
    (ProxyFacts("active", 0, A, 0), [], "restart", "is not the running process's"),
    (RUNNING, None, "restart", "the running commit aaaaaaaa is not in this repository"),
    (RUNNING, ["caravan/admin/routes.py", "static/js/a.js", "docs/b.md"], "keep",
     "no proxy code changed since aaaaaaaa"),
    (RUNNING, ["caravan/__init__.py", "CHANGELOG.md"], "keep", "no proxy code changed since aaaaaaaa"),
    (RUNNING, [], "keep", "no proxy code changed since aaaaaaaa"),
    (RUNNING, ["caravan/proxy/handler.py"], "restart",
     "proxy code changed since aaaaaaaa: caravan/proxy/handler.py"),
    (RUNNING, ["caravan/common/x.py", "caravan/proxy/a.py", "docs/c.md", "agent-proxies.py", "caravan/proxy/b.py"],
     "restart", "caravan/common/x.py, caravan/proxy/a.py, agent-proxies.py and 1 more"),
    (RUNNING, ["caravan/proxyx/a.py"], "keep", "no proxy code changed"),
]


def test_decision():
    print("ProxyRestart.covers — what counts as the proxy's code:")
    for path, expected, why in COVERS:
        got = ProxyRestart.covers(path)
        check(got is expected, f"{path!r} → {expected}: {why} (got {got})")
    print("ProxyRestart.verdict — restart or keep, and why:")
    for facts, changed, action, says in VERDICTS:
        got_action, why = ProxyRestart(facts, changed).verdict()
        check(got_action == action and says in why,
              f"{facts.active or '-'}/{facts.main_pid}/{facts.commit[:4] or '-'}/{facts.pid} {changed!r} "
              f"→ {action}: …{says}… (got {got_action}: {why})")
    print("ProxyRestart.verify — the proxy after the deploy:")
    facts = ProxyFacts("active", 4242, "abcdef1234567890", 4242)
    for new, state, says in (("abcdef12", "ok", "runs abcdef12 (pid 4242)"),
                             ("abcdef1", "ok", "runs abcdef12"),
                             ("", "ok", "runs abcdef12"),
                             ("bbbbbbbb", "mismatch", "runs abcdef12, not bbbbbbbb")):
        got, what = ProxyRestart(facts, []).verify(new)
        check(got == state and says in what, f"verify({new!r}) → {state}: …{says}… (got {got}: {what})")
    got, what = ProxyRestart(ProxyFacts("failed", 0, "abc", 4242), []).verify("abc")
    check(got == "mismatch" and "not running (failed)" in what, f"a dead proxy is a mismatch (got {got}: {what})")
    got, what = ProxyRestart(ProxyFacts("active", 5000, "abc", 4242), []).verify("abc")
    check(got == "mismatch" and "record pid 4242, running pid 5000" in what,
          f"a record left by an earlier process is a mismatch (got {got}: {what})")


def test_facts():
    print("ProxyFacts.parse — the three lines deploy.sh gathers:")
    facts = ProxyFacts.parse(' active \n 4242 \n{"sourceCommit": "abc", "pid": 4242}\n')
    check((facts.active, facts.main_pid, facts.commit, facts.pid) == ("active", 4242, "abc", 4242),
          f"all three, whitespace trimmed (got {vars(facts)})")
    for text, why in (("", "nothing at all"), ("active\nnot-a-number\nnot json", "rubbish"),
                      ("active\n4242\n[1, 2]", "a record that is not an object")):
        facts = ProxyFacts.parse(text)
        check(facts.commit == "" and facts.pid == 0, f"{why}: no commit, no pid — unknown, not zero-as-a-fact "
                                                       f"(got {vars(facts)})")
    check(ProxyFacts.parse("active\n0\n{}").main_pid == 0, "MainPID 0 — systemd's own word for no process")


def test_start_record():
    print("StartRecord — what the proxy writes about itself, and reads back:")
    with tempfile.TemporaryDirectory(prefix="caravan-start-") as tmp:
        state = Path(tmp) / "agent-proxy-state.json"
        state.write_text(json.dumps({"sourceCommit": "abc", "pid": 77, "routes": []}), encoding="utf-8")
        record = StartRecord.read(state)
        check((record.commit, record.pid) == ("abc", 77), f"read from the state file (got {vars(record)})")
        for body, why in (("{not json", "not JSON"), ("[1]", "not an object"),
                          (json.dumps({"sourceCommit": "abc", "pid": "x"}), "a pid that is not a number")):
            state.write_text(body, encoding="utf-8")
            record = StartRecord.read(state)
            check(record.pid == 0 and (record.commit in ("", "abc")), f"{why}: unknown stays unknown "
                                                                     f"(got {vars(record)})")
        record = StartRecord.read(Path(tmp) / "missing.json")
        check((record.commit, record.pid) == ("", 0), "no state file — an empty record, not an error")
    record = StartRecord.at_start(ROOT)
    head = git(ROOT, "rev-parse", "HEAD")
    check(record.commit == head and record.pid == os.getpid(),
          f"at start: this checkout's full commit and this pid (got {record.commit[:12]} {record.pid})")
    check(set(record.as_state()) == {"sourceCommit", "pid"} and json.loads(record.as_json()) == record.as_state(),
          "two fields in the state file, nothing else")


def test_checkout_commit():
    print("CheckoutCommit — one rule for a checkout's commit:")
    saved = {k: os.environ.get(k) for k in ("CARAVAN_GIT_HEAD", "GIT_CEILING_DIRECTORIES")}
    try:
        with tempfile.TemporaryDirectory(prefix="caravan-checkout-") as tmp:
            os.environ["GIT_CEILING_DIRECTORIES"] = str(Path(tmp).resolve())
            repo, bare = Path(tmp) / "repo", Path(tmp) / "plain"
            repo.mkdir()
            bare.mkdir()
            git(repo, "init", "-q")
            head = commit_files(repo, {"a.txt": "a"}, "one")
            os.environ.pop("CARAVAN_GIT_HEAD", None)
            got = CheckoutCommit(repo)
            check((got.commit, got.from_git, got.baked, got.error) == (head, True, False, ""),
                  f"a git checkout: its HEAD, from git (got {vars(got)})")
            short = CheckoutCommit(repo, short=True).commit
            check(0 < len(short) < 40 and head.startswith(short), f"short: a prefix of the full one (got {short})")
            got = CheckoutCommit(bare)
            check(got.commit == "" and not got.from_git and not got.baked and got.error,
                  f"no git, nothing baked — no commit, and git's complaint kept (got {vars(got)})")
            os.environ["CARAVAN_GIT_HEAD"] = "cafe123"
            got = CheckoutCommit(bare)
            check((got.commit, got.from_git, got.baked) == ("cafe123", False, True),
                  f"no git, an image build's commit — that one, said to be baked (got {vars(got)})")
            got = CheckoutCommit(repo)
            check((got.commit, got.from_git, got.baked) == (head, True, False),
                  f"git and a baked value — git wins (got {vars(got)})")
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_diff_and_cli():
    print("changed_files and the command line, on a real repository:")
    with tempfile.TemporaryDirectory(prefix="caravan-diff-") as tmp:
        repo = Path(tmp)
        git(repo, "init", "-q")
        one = commit_files(repo, {"agent-proxies.py": "x", "caravan/proxy/a.py": "a",
                                  "caravan/admin/b.py": "b", "caravan/__init__.py": "v1"}, "one")
        two = commit_files(repo, {"caravan/admin/b.py": "b2", "caravan/__init__.py": "v2"}, "two")
        three = commit_files(repo, {"caravan/proxy/a.py": None, "caravan/admin/a.py": "a"}, "three: moved")
        check(changed_files(one, two, repo) == ["caravan/__init__.py", "caravan/admin/b.py"],
              f"the board and the release number (got {changed_files(one, two, repo)})")
        moved = changed_files(two, three, repo) or []
        check("caravan/proxy/a.py" in moved,
              f"a file moved out of the proxy counts on the side it left (got {moved})")
        check(changed_files("deadbeef" * 5, two, repo) is None, "a commit the repository lacks — None, not []")
        check(changed_files("", two, repo) is None, "no running commit — None")

        def cli(mode, facts, *args):
            run = subprocess.run([sys.executable, str(ROOT / "scripts" / "proxy_restart.py"), mode, *args,
                                  "--repo", str(repo)], input=facts, capture_output=True, text=True)
            return run.returncode, run.stdout.strip()

        record = lambda commit: f"active\n4242\n{json.dumps({'sourceCommit': commit, 'pid': 4242})}\n"
        code, out = cli("decide", record(one), "--new", two)
        check(code == 0 and out == f"keep: no proxy code changed since {one[:8]}", f"decide: keep (got {code} {out!r})")
        code, out = cli("decide", record(two), "--new", three)
        check(code == 0 and out == f"restart: proxy code changed since {two[:8]}: caravan/proxy/a.py",
              f"decide: restart, with the file named (got {code} {out!r})")
        code, out = cli("decide", record(two))
        check(code == 2, f"decide without --new — refused, not guessed (got {code})")
        code, out = cli("verify", record(three), "--new", three[:8])
        check(code == 0 and out.startswith("ok: the proxy runs"), f"verify ok → exit 0 (got {code} {out!r})")
        code, out = cli("verify", record(two), "--new", three)
        check(code == 1 and out.startswith("mismatch:"), f"verify mismatch → exit 1 (got {code} {out!r})")


def test_proxy_writes_its_record():
    print("end to end — a real proxy process says which code it runs:")
    with tempfile.TemporaryDirectory(prefix="caravan-proxy-start-") as tmp:
        tmp = Path(tmp)
        config, state = tmp / "agent-proxies.json", tmp / "agent-proxy-state.json"
        # No routes: the process binds no port at all, so nothing on this machine is touched.
        config.write_text(json.dumps({"routes": [], "routers": []}), encoding="utf-8")
        env = {**os.environ, "CARAVAN_DATA_DIR": str(tmp / "data"), "AGENT_PROXY_CONFIG_FILE": str(config),
               "AGENT_PROXY_STATE_FILE": str(state), "PYTHONDONTWRITEBYTECODE": "1"}
        proc = subprocess.Popen([sys.executable, str(ROOT / "agent-proxies.py")], cwd=ROOT, env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        try:
            record = StartRecord()
            deadline = time.time() + 15
            while time.time() < deadline and not record.commit:
                time.sleep(0.2)
                record = StartRecord.read(state)
            head = git(ROOT, "rev-parse", "HEAD")
            check(record.commit == head and record.pid == proc.pid,
                  f"the state file names this checkout's commit and the process's pid "
                  f"(got {record.commit[:12] or '-'} {record.pid}, expected {head[:12]} {proc.pid})")
            facts = f"active\n{proc.pid}\n{record.as_json()}\n"
            state_, what = ProxyRestart(ProxyFacts.parse(facts), []).verify(head[:8])
            check(state_ == "ok", f"and the deploy's verify accepts it (got {state_}: {what})")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


def main():
    test_decision()
    test_facts()
    test_start_record()
    test_checkout_commit()
    test_diff_and_cli()
    test_proxy_writes_its_record()
    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg)
        return 1
    print("all proxy-restart snapshots hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
