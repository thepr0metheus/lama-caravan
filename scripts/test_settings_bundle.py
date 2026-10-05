#!/usr/bin/env python3
"""The settings file: what it carries, what it refuses to carry, and what it
must not destroy on the way back in.

The dangerous half is the import. A bundle exported without secrets says
"__redacted__" where an API key was, and writing that through would replace a
working key with a literal string — the cell keeps running and starts failing
authentication later, which is the slowest way to find out. So the test that
matters most here is the one asserting a redacted bundle LEAVES the local keys
alone.

The copy an import takes of what it replaces has to land somewhere the process
can write and that outlives it. In the container the repo directory is the image
and the app runs as a user that cannot write there: the copy was kept beside the
code, so every import in the container died with "Permission denied: /app/var"
(2026-09-30). Where the copy goes is checked at the bottom, in processes of their
own — the paths are fixed when the modules are imported.

And every import keeps its own copy. The copy was named by the second and swapped
in over a name that was there, so two imports inside one second — a script, an
agent exploring the panel — left the second's copy and lost the first's: the copy
of the ORIGINAL settings, the one that makes the restore possible (found
2026-09-30 by running two imports back to back in a container). The names go to
the microsecond now and a taken name is never written over; that is the last
section here.
"""
import contextlib
import errno
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_TMP = Path(tempfile.mkdtemp(prefix="caravan-settings-test-"))
os.environ["CARAVAN_DATA_DIR"] = str(_TMP)
os.environ["LLAMA_START_SCRIPT"] = str(_TMP / "start-server.sh")
os.environ["CARAVAN_SETTINGS_BACKUPS"] = str(_TMP / "settings-backups")

from caravan.admin import settings_bundle as sb   # noqa: E402
from caravan.common.errors import AppError        # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}{'' if cond else '  ' + detail}")


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) if not isinstance(data, str) else data,
                    encoding="utf-8")


LOCATION_SNIPPET = """
import json
from caravan.admin import paths, routes, settings_bundle as sb
print(json.dumps({"paths": str(paths.SETTINGS_BACKUP_DIR), "bundle": str(sb.SETTINGS_BACKUP_DIR),
                  "routes": str(routes.SETTINGS_BACKUP_DIR)}))
"""

IMPORT_SNIPPET = """
import json, os, stat
from pathlib import Path
os.umask(0o022)                      # the usual one: a file made without care is 0644
from caravan.admin import routes, settings_bundle as sb
res = sb.apply_bundle(sb.export_bundle())
class Answer:
    def send_json(self, doc): self.doc = doc
answer = Answer()
routes.GET_ROUTES["/api/settings/backups"](answer, None)
copy = Path(res["backup"])
print(json.dumps({"copy": res["backup"], "listed": answer.doc,
                  "fileMode": stat.S_IMODE(copy.stat().st_mode), "dirMode": stat.S_IMODE(copy.parent.stat().st_mode)}))
"""


def in_a_process(snippet, env_extra, drop=("CARAVAN_DATA_DIR", "CARAVAN_SETTINGS_BACKUPS", "LLAMA_START_SCRIPT")):
    """The snippet run in a process started with exactly this environment: the
    paths are read when the modules are imported, so this file's own process —
    which set them at the top — cannot answer for any other combination."""
    env = {k: v for k, v in os.environ.items() if k not in drop}
    env.update(env_extra, PYTHONPATH=str(ROOT))
    out = subprocess.run([sys.executable, "-c", snippet], env=env, cwd=ROOT, capture_output=True, text=True)
    if out.returncode != 0:
        return {"error": out.stderr.strip()[-300:]}
    return json.loads(out.stdout.strip().splitlines()[-1])


def where_the_copy_goes():
    data = Path(tempfile.mkdtemp(prefix="caravan-settings-where-"))
    elsewhere = data / "elsewhere"
    repo_copy_dir = ROOT / "var" / "settings-backups"

    # In a container: CARAVAN_DATA_DIR only. On the volume, by all three names.
    got = in_a_process(LOCATION_SNIPPET, {"CARAVAN_DATA_DIR": str(data)})
    want = str(data / "settings-backups")
    check("with a data directory the copy's directory is on the volume",
          got.get("paths") == want, str(got))
    check("the settings module reads that same directory",
          got.get("bundle") == want, str(got))
    check("the backups listing reads that same directory",
          got.get("routes") == want, str(got))

    # The per-file variable still wins, as it does for every other mutable path.
    got = in_a_process(LOCATION_SNIPPET, {"CARAVAN_DATA_DIR": str(data), "CARAVAN_SETTINGS_BACKUPS": str(elsewhere)})
    check("CARAVAN_SETTINGS_BACKUPS wins over the data directory",
          got.get("paths") == got.get("bundle") == got.get("routes") == str(elsewhere), str(got))

    # A native install has no data directory and keeps what it always had.
    got = in_a_process(LOCATION_SNIPPET, {})
    native = str(repo_copy_dir)
    check("as-is: without a data directory it stays var/settings-backups in the repo",
          got.get("paths") == got.get("bundle") == got.get("routes") == native, str(got))

    # An import in the container's shape, end to end: the copy lands on the
    # volume and the listing finds it. The start script is pointed into the
    # temporary directory so nothing of the operator's is rewritten, and the
    # repo's own var/ is watched: a copy of the settings, secrets included,
    # must not appear there.
    watched = set(repo_copy_dir.glob("*")) if repo_copy_dir.exists() else set()
    existed = repo_copy_dir.exists()
    try:
        got = in_a_process(IMPORT_SNIPPET, {"CARAVAN_DATA_DIR": str(data),
                                            "LLAMA_START_SCRIPT": str(data / "start-server.sh")})
    finally:
        strays = (set(repo_copy_dir.glob("*")) if repo_copy_dir.exists() else set()) - watched
        for extra in strays:
            extra.unlink()
        if not existed and repo_copy_dir.exists() and not any(repo_copy_dir.iterdir()):
            repo_copy_dir.rmdir()
    volume = sorted((data / "settings-backups").glob("*-before-import.json"))
    check("an import with only a data directory leaves its copy on the volume",
          len(volume) == 1, f"{[p.name for p in volume]} {got}")
    check("negative: and nothing in the repo directory",
          not strays, str(sorted(p.name for p in strays)))
    check("the import's answer names that copy",
          bool(volume) and got.get("copy") == str(volume[0]), f"{got.get('copy')} vs {volume}")
    listed = [row.get("name") for row in (got.get("listed") or {}).get("backups", [])]
    check("the listing shows the copy the import took",
          listed == [p.name for p in volume], f"{listed} {got}")

    # The copy holds every secret and the accounts database — it has to, or it
    # could not put them back — so it is for its owner alone. Under the usual
    # umask a file made without care is 0644 and its directory 0755; the copies
    # made on the controller before this were 0664 in a 0775 directory.
    check("the copy is readable and writable by its owner only",
          got.get("fileMode") == 0o600, oct(got.get("fileMode") or 0))
    check("the directory made for it is closed to everyone else",
          (got.get("dirMode") or 0o777) & 0o077 == 0, oct(got.get("dirMode") or 0))
    shutil.rmtree(data, ignore_errors=True)


TWICE_SNIPPET = """
import json
from datetime import datetime
from pathlib import Path
from caravan.admin import routes, settings_bundle as sb
FIXED = datetime(2026, 9, 30, 16, 10, 8, 500000)
class Frozen(datetime):
    @classmethod
    def now(cls, tz=None):
        return FIXED
sb.datetime = Frozen                     # two imports at one instant: what the old name could not hold
admin = Path(sb._files()["admin-state"])
admin.parent.mkdir(parents=True, exist_ok=True)
admin.write_text(json.dumps({"marker": "original"}))
def bundle_with(marker):
    b = sb.export_bundle()
    b["files"]["admin-state"] = {"kind": "json", "content": {"marker": marker}}
    return b
first = sb.apply_bundle(bundle_with("after-first"))
second = sb.apply_bundle(bundle_with("after-second"))
def marker_in(path):
    return json.loads(Path(path).read_text())["files"]["admin-state"]["content"]["marker"]
class Answer:
    def send_json(self, doc): self.doc = doc
answer = Answer()
routes.GET_ROUTES["/api/settings/backups"](answer, None)
print(json.dumps({"first": first["backup"], "second": second["backup"],
                  "markers": [marker_in(first["backup"]), marker_in(second["backup"])],
                  "files": sorted(p.name for p in Path(sb.SETTINGS_BACKUP_DIR).iterdir()),
                  "listed": [row["name"] for row in answer.doc["backups"]]}))
"""

CLOCK_SNIPPET = """
import json, tempfile, time
from pathlib import Path
from caravan.admin import settings_bundle as sb
before = time.strftime("%Y%m%d-%H%M%S")
path = sb.CopyBeforeImport(Path(tempfile.mkdtemp())).write("x")
after = time.strftime("%Y%m%d-%H%M%S")
print(json.dumps({"before": before, "name": path.name, "after": after}))
"""


@contextlib.contextmanager
def patching(obj, **attrs):
    """Attributes of `obj` set for the length of a block, then put back."""
    saved = {k: getattr(obj, k) for k in attrs}
    try:
        for k, v in attrs.items():
            setattr(obj, k, v)
        yield
    finally:
        for k, v in saved.items():
            setattr(obj, k, v)


def attempt(fn, *args, **kwargs):
    """What a call gave, or the exception it raised, as a value: a change that makes
    the call fail turns a pin red by its name instead of ending the whole run."""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001
        return exc


def names_in(directory):
    return sorted(p.name for p in Path(directory).iterdir())


def copies_that_land_together():
    at = datetime(2026, 9, 30, 16, 10, 8, 123456)
    base = Path(tempfile.mkdtemp(prefix="caravan-settings-copies-"))

    # ── two copies at one instant ──────────────────────────────────────────
    here = base / "same-instant"
    copy = sb.CopyBeforeImport(here, clock=lambda: at)
    got = [attempt(copy.write, text) for text in ("first", "second", "third")]
    names = [p.name for p in got if isinstance(p, Path)]
    check("a copy is named by its moment, to the microsecond",
          names[:1] == ["20260930-161008-123456-before-import.json"], str(got))
    check("a second copy at the same instant takes the next microsecond, not the first one's name",
          names == ["20260930-161008-123456-before-import.json", "20260930-161008-123457-before-import.json",
                    "20260930-161008-123458-before-import.json"], str(got))
    check("every copy keeps its own content — the first is not the second's",
          [p.read_text() for p in got if isinstance(p, Path)] == ["first", "second", "third"], str(got))
    check("negative: three files and nothing else in the directory — no temp file is left",
          names_in(here) == sorted(names) and len(names) == 3, str(names_in(here)))

    # ── the names sort in the order the copies were taken ──────────────────
    ordered = base / "ordered"
    ordered.mkdir()
    for old in ("20260823-160537-before-import.json", "20260930-161007-before-import.json"):
        (ordered / old).write_text("an older copy")          # as they were named before: to the second
    seen = []
    for stamp in (at, at, datetime(2026, 9, 30, 16, 10, 9, 5)):
        seen.append(attempt(sb.CopyBeforeImport(ordered, clock=lambda stamp=stamp: stamp).write, "x"))
    listing = sorted(p.name for p in ordered.glob("*.json"))[::-1]       # what the backups listing does
    check("the newest copy is listed first, the copies from before this among them by their second",
          listing == ["20260930-161009-000005-before-import.json", "20260930-161008-123457-before-import.json",
                      "20260930-161008-123456-before-import.json", "20260930-161007-before-import.json",
                      "20260823-160537-before-import.json"], str(listing))
    edge = base / "edge"
    last = datetime(2026, 9, 30, 16, 10, 8, 999999)
    pair = [attempt(sb.CopyBeforeImport(edge, clock=lambda: last).write, t) for t in ("a", "b")]
    check("boundary: the microsecond after 999999 is the next second's first, and sorts after it",
          [p.name for p in pair if isinstance(p, Path)] == ["20260930-161008-999999-before-import.json",
                                                            "20260930-161009-000000-before-import.json"], str(pair))

    # ── all at once ────────────────────────────────────────────────────────
    crowd = base / "crowd"
    shared = sb.CopyBeforeImport(crowd, clock=lambda: at)
    barrier, results = threading.Barrier(12), {}

    def worker(i):
        barrier.wait()
        results[i] = attempt(shared.write, f"copy {i}")
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    paths = [r for r in results.values() if isinstance(r, Path)]
    check("twelve imports at the same instant, in twelve threads, take twelve names",
          len(paths) == 12 and len({p.name for p in paths}) == 12, str(results)[:300])
    check("and not one of them lost its content to another",
          sorted(p.read_text() for p in paths) == sorted(f"copy {i}" for i in range(12)))
    check("negative: twelve files in the directory and no temp file left", len(names_in(crowd)) == 12, str(names_in(crowd)))

    # ── a free name is not searched for for ever ───────────────────────────
    full = base / "full"
    full.mkdir()
    for micro in (123456, 123457, 123458):
        (full / f"20260930-161008-{micro}-before-import.json").write_text("taken")
    limited = sb.CopyBeforeImport(full, clock=lambda: at)
    limited.ATTEMPTS = 3
    refused = attempt(limited.write, "x")
    check("boundary: three names taken and three tries — a refusal that says why, status 500",
          isinstance(refused, AppError) and refused.status == 500 and "no free name" in str(refused), str(refused))
    limited.ATTEMPTS = 4
    check("boundary: one try more finds the free name, and the taken ones are as they were",
          getattr(attempt(limited.write, "y"), "name", None) == "20260930-161008-123459-before-import.json"
          and (full / "20260930-161008-123456-before-import.json").read_text() == "taken")

    # ── private from the first byte, and whole when it appears ─────────────
    private = base / "private"
    old_umask = os.umask(0)                     # a file made without care would be 0666 here
    forbidden = lambda *a, **k: (_ for _ in ()).throw(AssertionError("chmod is a window: the file is private from its first byte"))
    try:
        with patching(os, chmod=forbidden):
            made = attempt(sb.CopyBeforeImport(private, clock=lambda: at).write, "secret")
    finally:
        os.umask(old_umask)
    check("under umask 0 and with no chmod to lean on, the copy is 0600 and its new directory 0700",
          isinstance(made, Path) and stat.S_IMODE(made.stat().st_mode) == 0o600
          and stat.S_IMODE(private.stat().st_mode) == 0o700, str(made))
    calls = []
    real_fsync, real_link = os.fsync, os.link

    def fsync(fd):
        calls.append("fsync")
        return real_fsync(fd)

    def link(src, dst, **kw):
        calls.append("link")
        return real_link(src, dst, **kw)
    with patching(os, fsync=fsync, link=link):
        attempt(sb.CopyBeforeImport(base / "ordered-calls", clock=lambda: at).write, "x")
    check("the content is on disk before the name appears: sync, then link", calls == ["fsync", "link"], str(calls))

    # ── where links are not allowed ────────────────────────────────────────
    nolinks = base / "no-links"

    def refuse_link(src, dst, **kw):
        raise OSError(errno.EPERM, "Operation not permitted")
    with patching(os, link=refuse_link):
        copy = sb.CopyBeforeImport(nolinks, clock=lambda: at)
        pair = [attempt(copy.write, t) for t in ("one", "two")]
    check("without hard links the name is still taken exclusively: the second copy takes the next one",
          [getattr(p, "name", p) for p in pair] == ["20260930-161008-123456-before-import.json",
                                                    "20260930-161008-123457-before-import.json"], str(pair))
    check("and neither overwrote the other, both 0600, no temp file left",
          [p.read_text() for p in pair if isinstance(p, Path)] == ["one", "two"]
          and all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in pair if isinstance(p, Path))
          and len(names_in(nolinks)) == 2, str(names_in(nolinks)))

    # ── the real thing: two imports, one instant, one answer each ──────────
    data = Path(tempfile.mkdtemp(prefix="caravan-settings-twice-"))
    got = in_a_process(TWICE_SNIPPET, {"CARAVAN_DATA_DIR": str(data), "LLAMA_START_SCRIPT": str(data / "start-server.sh")})
    first, second = "20260930-161008-500000-before-import.json", "20260930-161008-500001-before-import.json"
    check("two imports in the same instant leave two copies, each named in its own import's answer",
          [Path(got.get("first", "")).name, Path(got.get("second", "")).name] == [first, second]
          and got.get("files") == [first, second], str(got))
    check("the first copy holds the ORIGINAL settings, the second what the first import wrote",
          got.get("markers") == ["original", "after-first"], str(got))
    check("the listing shows both, the newest first", got.get("listed") == [second, first], str(got))
    shutil.rmtree(data, ignore_errors=True)

    # ── the stamp is the machine's local time, as it always was ────────────
    got = in_a_process(CLOCK_SNIPPET, {"TZ": "Asia/Tbilisi", "CARAVAN_DATA_DIR": str(base / "clock")})
    name = got.get("name", "")
    check("the copy's name is the local time to the microsecond, not UTC",
          re.fullmatch(r"\d{8}-\d{6}-\d{6}-before-import\.json", name) is not None
          and got.get("before", "z") <= name[:15] <= got.get("after", ""), str(got))
    shutil.rmtree(base, ignore_errors=True)


def main():
    proxies = Path(sb._files()["agent-proxies"])
    admin = Path(sb._files()["admin-state"])
    # Routes as agent-proxies.json really stores them: identified by PORT, with
    # no id field. The first version of this test invented an id, which made the
    # secret-merge pass against a shape that does not exist on any controller.
    write(proxies, {"routes": [{"port": 23001, "label": "a", "apiKey": "sk-live-secret"},
                               {"port": 23003, "label": "b"}]})
    write(admin, {"hfToken": "hf_secret", "topology": {"clients": {"a": {}}},
                  "monitor": {"retentionSeconds": 600}})

    # 1. A plain export carries the settings and none of the secrets.
    bundle = sb.export_bundle()
    routes = bundle["files"]["agent-proxies"]["content"]["routes"]
    check("export hides an API key", routes[0]["apiKey"] == sb.REDACTED, routes[0].get("apiKey"))
    check("export hides the HF token",
          bundle["files"]["admin-state"]["content"]["hfToken"] == sb.REDACTED)
    check("export says what it hid", len(bundle["redacted"]) == 2, str(bundle["redacted"]))
    check("export keeps the settings themselves",
          bundle["files"]["admin-state"]["content"]["topology"]["clients"] == {"a": {}})
    check("export drops sampled load",
          "monitor" not in bundle["files"]["admin-state"]["content"])
    check("export names what it excluded", "token-history.json" in (bundle.get("excluded") or {}))

    # 2. Opting in carries them.
    with_secrets = sb.export_bundle(include_secrets=True)
    check("secrets=1 carries the key",
          with_secrets["files"]["agent-proxies"]["content"]["routes"][0]["apiKey"] == "sk-live-secret")

    # 3. THE ONE THAT MATTERS: importing a redacted bundle must not wipe keys.
    #    The bundle changes a port, so this is a real restore, not a no-op.
    bundle["files"]["agent-proxies"]["content"]["routes"][1]["label"] = "b2"
    sb.apply_bundle(bundle)
    after = json.loads(proxies.read_text())
    check("import keeps the local API key", after["routes"][0]["apiKey"] == "sk-live-secret",
          after["routes"][0].get("apiKey"))
    check("import keeps the local HF token",
          json.loads(admin.read_text()).get("hfToken") == "hf_secret")
    check("import applies the non-secret change", after["routes"][1]["label"] == "b2")
    check("import keeps this machine's monitor block",
          "monitor" in json.loads(admin.read_text()))

    # 4. The restore is itself undoable.
    backups = sorted(Path(os.environ["CARAVAN_SETTINGS_BACKUPS"]).glob("*.json"))
    check("import leaves a copy of what it replaced", len(backups) == 1, str(backups))
    if backups:
        prior = json.loads(backups[0].read_text())
        check("that copy carries the secrets, so it can restore them",
              prior["files"]["agent-proxies"]["content"]["routes"][0]["apiKey"] == "sk-live-secret")

    # 5. A DELETED cell comes back. This is the thing the feature is for: an
    #    exploring agent removes a cell, and the file must put it back. Since
    #    step 6.9 every cell runs through the scout of its machine and IS its
    #    slot — it travels inside admin-state; the controller's own launch
    #    files (var/server-cells) went with its own cells.
    SLOT = {"hostId": "box-a", "port": 22222, "config": {"RUNNER": "llama-server", "MODEL_FILE": "m.gguf"}}
    state = json.loads(admin.read_text())
    state["topology"]["serverSlots"] = {"box-a:22222": SLOT}
    write(admin, state)
    snapshot = sb.export_bundle(include_secrets=True)
    check("export carries the cell as its slot",
          snapshot["files"]["admin-state"]["content"]["topology"]["serverSlots"] == {"box-a:22222": SLOT})
    check("negative: export carries no launch files of the controller's own cells",
          "server-cells" not in snapshot["files"], str(sorted(snapshot["files"])))
    state["topology"]["serverSlots"] = {}
    write(admin, state)
    sb.apply_bundle(snapshot)
    check("import brings the cell back",
          json.loads(admin.read_text())["topology"]["serverSlots"] == {"box-a:22222": SLOT})

    # 5b. A file taken while the controller still ran cells of its own carries
    #     their launch files. They have nowhere to go: said in the preview and
    #     in the answer, and nothing is written for them.
    old = json.loads(json.dumps(snapshot))
    old["files"]["server-cells"] = {"kind": "cells", "content": {
        "22001": {"cell": {"hostId": "controller", "port": 22001}, "start": "#!/bin/bash\nexec echo hello\n"}}}
    rows = [r for r in sb.preview_import(old)["changes"] if r["name"] == "server-cells"]
    check("preview names the old launch files and why they stay out",
          rows == [{"name": "server-cells", "action": "skip", "note": sb.SERVER_CELLS_GONE}], str(rows))
    check("the reason says where the cells are now",
          sb.SERVER_CELLS_GONE == "the controller runs no cells of its own since step 6.9 — its old launch "
                                  "files are not restored; the cells come back with admin-state")
    res = sb.apply_bundle(old)
    check("import reports them as not restored", res["skipped"] == ["server-cells"], str(res["skipped"]))
    check("negative: nothing is written for them",
          not (_TMP / "server-cells").exists() and not any(_TMP.rglob("start.sh")))
    check("negative: a file without them has no such row",
          not [r for r in sb.preview_import(snapshot)["changes"] if r["name"] == "server-cells"])

    # 5c. The labels the monitor gave the clients of the controller's own
    #     single server. It stopped watching that server in step 6.9 and
    #     nothing reads them: they neither leave nor come back.
    check("negative: export carries no client labels",
          "client-labels" not in snapshot["files"], str(sorted(snapshot["files"])))
    older = json.loads(json.dumps(snapshot))
    older["files"]["client-labels"] = dict(snapshot["files"]["model-catalog"], content={"10.0.0.7": "lab"})
    rows = [r for r in sb.preview_import(older)["changes"] if r["name"] == "client-labels"]
    check("preview names the old client labels and why they stay out",
          rows == [{"name": "client-labels", "action": "skip", "note": sb.CLIENT_LABELS_GONE}], str(rows))
    check("the reason says nothing reads them",
          sb.CLIENT_LABELS_GONE == "the controller no longer watches its own server's clients since step 6.9 — "
                                   "their labels are not restored; nothing reads them")
    res = sb.apply_bundle(older)
    check("import reports them as not restored", res["skipped"] == ["client-labels"], str(res["skipped"]))
    check("negative: nothing is written for them", not any(_TMP.rglob("client-labels.json")))
    both = json.loads(json.dumps(old))
    both["files"]["client-labels"] = older["files"]["client-labels"]
    check("a file with both retired sections names both, in one order",
          sb.apply_bundle(both)["skipped"] == ["server-cells", "client-labels"])

    # 6. Accounts and cloud keys: out only when asked, and restorable when they
    #    are. These are the two files that make an export dangerous to leave
    #    lying around, and also the two a wrecked controller cannot be rebuilt
    #    without — so both halves need proving.
    from caravan.admin.auth import AUTH_DB
    secrets_file = Path(sb.PROVIDER_SECRETS_FILE)
    AUTH_DB.parent.mkdir(parents=True, exist_ok=True)
    AUTH_DB.write_bytes(b"SQLite format 3\x00-pretend-accounts")
    write(secrets_file, {"openai": "sk-cloud-key"})

    plain = sb.export_bundle()
    check("a plain export carries no accounts", plain["files"]["auth-db"]["content"] is None)
    check("a plain export carries no cloud keys", plain["files"]["provider-secrets"]["content"] is None)
    check("and says why they are absent",
          "secrets" in (plain["files"]["auth-db"].get("omitted") or ""))
    check("a plain export declares no credentials", plain["containsCredentials"] == [])

    full = sb.export_bundle(include_secrets=True)
    check("secrets=1 carries the accounts database", full["files"]["auth-db"]["content"] is not None)
    check("secrets=1 declares what it carries",
          full["containsCredentials"] == ["auth-db", "provider-secrets"],
          str(full["containsCredentials"]))

    # Wreck both, then restore from the file.
    AUTH_DB.unlink()
    secrets_file.unlink()
    sb.apply_bundle(full)
    check("import restores the accounts database",
          AUTH_DB.is_file() and AUTH_DB.read_bytes().endswith(b"-pretend-accounts"))
    check("the restored accounts database is not world-readable",
          (AUTH_DB.stat().st_mode & 0o077) == 0, oct(AUTH_DB.stat().st_mode))
    check("import restores the cloud keys",
          json.loads(secrets_file.read_text())["openai"] == "sk-cloud-key")

    # And a bundle WITHOUT them must not wipe what is here.
    sb.apply_bundle(plain)
    check("a plain import leaves the accounts alone", AUTH_DB.is_file())
    check("a plain import leaves the cloud keys alone",
          json.loads(secrets_file.read_text())["openai"] == "sk-cloud-key")

    # 7. The passphrase locks ONLY the credentials, and only when asked.
    try:
        import cryptography  # noqa: F401
        have_crypto = True
    except ImportError:
        have_crypto = False
    if not have_crypto:
        print("  skip passphrase checks — no cryptography package on this host")
    else:
        AUTH_DB.write_bytes(b"SQLite format 3\x00-locked-accounts")
        write(secrets_file, {"openai": "sk-locked"})
        locked = sb.encrypt_credentials(sb.export_bundle(include_secrets=True), "hunter2")
        check("a passphrase declares itself on the file", locked.get("credentialsEncrypted") is True)
        check("the accounts database is unreadable without it",
              isinstance(locked["files"]["auth-db"]["content"], dict)
              and locked["files"]["auth-db"]["content"].get("enc") == sb.ENC_MARK)
        # The half that must NOT be locked: a restore is reached for when things
        # are already broken, and a forgotten passphrase must not take the cells
        # and the routes down with it.
        check("the cells stay readable without the passphrase",
              locked["files"]["admin-state"]["content"]["topology"]["serverSlots"] == {"box-a:22222": SLOT})
        check("the topology stays readable without the passphrase",
              locked["files"]["admin-state"]["content"]["topology"]["clients"] == {"a": {}})

        AUTH_DB.unlink()
        secrets_file.unlink()
        wiped = json.loads(admin.read_text())
        wiped["topology"]["serverSlots"] = {}
        write(admin, wiped)
        res = sb.apply_bundle(locked)          # no passphrase
        check("without the passphrase the credentials are skipped, not mangled",
              sorted(res["skipped"]) == ["auth-db", "provider-secrets"], str(res.get("skipped")))
        check("and the rest still restored",
              json.loads(admin.read_text())["topology"]["serverSlots"] == {"box-a:22222": SLOT})
        check("nothing was written where the credentials go", not AUTH_DB.exists())

        try:
            sb.apply_bundle(locked, "wrong-one")
            check("a wrong passphrase is refused", False, "it accepted it")
        except AppError as exc:
            check("a wrong passphrase is refused", "passphrase" in str(exc).lower(), str(exc))

        res = sb.apply_bundle(locked, "hunter2")
        check("the right passphrase restores the accounts database",
              AUTH_DB.is_file() and AUTH_DB.read_bytes().endswith(b"-locked-accounts"))
        check("and the cloud keys", json.loads(secrets_file.read_text())["openai"] == "sk-locked")

    # 8. Nonsense is refused rather than half-applied.
    for name, payload in (("not a bundle", {"hello": "world"}),
                          ("a future format", {"kind": "lama-caravan-settings", "format": 999,
                                               "files": {}}),
                          ("no files section", {"kind": "lama-caravan-settings",
                                                "format": sb.BUNDLE_FORMAT})):
        try:
            sb.validate_bundle(payload)
            check(f"refuses {name}", False, "accepted it")
        except AppError:
            check(f"refuses {name}", True)

    # 9. The preview reports before anything is written.
    fresh = sb.export_bundle()
    preview = sb.preview_import(fresh)
    check("preview of an unchanged bundle changes nothing",
          all(r["action"] != "replace" for r in preview["changes"]),
          str([r for r in preview["changes"] if r["action"] == "replace"]))

    # 10. Where the copy an import takes is kept.
    where_the_copy_goes()

    # 11. Imports that land in one second keep a copy each.
    copies_that_land_together()

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
