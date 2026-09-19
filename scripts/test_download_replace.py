#!/usr/bin/env python3
"""A download never writes over a model on disk unless it was told to.

POST /api/hf/download lands every file with os.replace, so a file that is
already on disk is gone once the new bytes arrive — and the /hf page offered a
checkbox on such files like on any other, then downloaded over the working
build without a word. The server now refuses that download, names the files
(code "exists"), and starts it only with replace:true, which the page sends
after asking.

Pinned: which destinations count as "already on disk" (a file does; a missing
one, a folder of that name and a leftover ".part" do not), and what the route
does with them — refuses and starts nothing, starts with replace:true, starts
a download of new files without being asked, and does not read "false" as yes.

Run: python3 scripts/test_download_replace.py
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_TMP = Path(tempfile.mkdtemp(prefix="caravan-replace-test-"))
os.environ["CARAVAN_DATA_DIR"] = str(_TMP / "data")
os.environ["LLAMA_ADMIN_STATE"] = str(_TMP / "data" / "admin.json")

from caravan.admin import downloads as dl   # noqa: E402
from caravan.admin import routes             # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}{'' if cond else '  ' + detail}")


MODELS = _TMP / "models"
(MODELS / "Qwen/unsloth/Q4_K_M").mkdir(parents=True)
(MODELS / "Qwen/unsloth/Q4_K_M/q4.gguf").write_bytes(b"weights")
(MODELS / "Qwen/unsloth/Q8_0").mkdir(parents=True)
(MODELS / "Qwen/unsloth/Q8_0/q8.gguf.part").write_bytes(b"half")
(MODELS / "Qwen/unsloth/folder.gguf").mkdir(parents=True)


def f(dest, name):
    return {"path": name, "name": name, "size": 7, "destDir": dest}


print("what a download would write over:")
taken = dl.replaces_on_disk([f("Qwen/unsloth/Q4_K_M", "q4.gguf"), f("Qwen/unsloth/Q8_0", "q8.gguf"),
                             f("Qwen/unsloth/Q2_K", "q2.gguf"), f("Qwen/unsloth", "folder.gguf")], str(MODELS))
check("a file on disk is named, with its path from the models directory", taken == ["Qwen/unsloth/Q4_K_M/q4.gguf"], repr(taken))
check("negative: a missing file, a leftover .part and a folder of that name are not", "Qwen/unsloth/Q8_0/q8.gguf" not in taken
      and "Qwen/unsloth/Q2_K/q2.gguf" not in taken and "Qwen/unsloth/folder.gguf" not in taken, repr(taken))
many = dl.replaces_on_disk([f("Qwen/unsloth/Q4_K_M", "q4.gguf"), f("", "root.gguf")], str(MODELS))
check("negative: nothing on disk under that name, nothing named", many == ["Qwen/unsloth/Q4_K_M/q4.gguf"], repr(many))


class _H:
    """The handler the route writes its answer to."""

    def __init__(self):
        self.sent = []

    def send_json(self, doc, *a, **kw):
        self.sent.append(doc)


started = []
routes.models_dir_from_config = lambda config: MODELS
routes.parse_config = lambda *a, **kw: {}
routes.start_hf_download = lambda repo, files, models_dir, token: started.append((repo, [x["name"] for x in files])) or "job-1"


def post(body):
    """One request, from a clean record: a check sees only the jobs ITS request
    started, never one a refused request before it let through."""
    started.clear()
    h = _H()
    routes._post_api_hf_download(h, None, body)
    return h.sent[-1]


print("the download route:")
old = [f("Qwen/unsloth/Q4_K_M", "q4.gguf"), f("Qwen/unsloth/Q4_K_M", "q4-part2.gguf")]
answer = post({"repo": "unsloth/Qwen", "files": old})
check("over a file on disk: refused with code \"exists\" and the files named", answer.get("ok") is False and answer.get("code") == "exists"
      and answer.get("files") == ["Qwen/unsloth/Q4_K_M/q4.gguf"], repr(answer))
check("negative: refused means nothing started", started == [], repr(started))
answer = post({"repo": "unsloth/Qwen", "files": old, "replace": "false"})
check("negative: replace \"false\" is not a yes", answer.get("code") == "exists" and started == [], repr(answer))
answer = post({"repo": "unsloth/Qwen", "files": old, "replace": True})
check("with replace:true the download starts", answer == {"ok": True, "jobId": "job-1"} and started == [("unsloth/Qwen", ["q4.gguf", "q4-part2.gguf"])],
      repr((answer, started)))
answer = post({"repo": "unsloth/Qwen", "files": [f("Qwen/unsloth/Q8_0", "q8.gguf")]})
check("new files start without a question — a .part is where a download resumes", answer == {"ok": True, "jobId": "job-1"}
      and started == [("unsloth/Qwen", ["q8.gguf"])], repr((answer, started)))

print()
if FAIL:
    print(f"download replace FAILED ({len(FAIL)}):")
    for name in FAIL:
        print("  - " + name)
    sys.exit(1)
print(f"download replace OK: {len(PASS)} checks")
