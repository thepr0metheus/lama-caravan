#!/usr/bin/env python3
"""Value snapshot: the models directory the controller LISTS and SERVES from.

The cell editor's picker (list_models) has always read the CONFIGURED models
directory: LLAMA_MODELS_DIR in the saved config, else the default the paths
module derives (the data volume's models/ in a container). GET /api/models
(list_gguf_models) and GET /api/models/download (serve_model_file — what scouts
fetch a model from) read LLAMA_HOME/models instead: the same place only while the
config says so. Wherever it does not — a container above all — the list was empty
and every download was a 404 for a file the picker had just offered.

What is pinned, by value: both read the configured directory, and not
LLAMA_HOME/models; the picker's rows can all be downloaded (the property that was
broken); a missing configured directory is said, not papered over with the other
one; the listing's skip rules and its rows; the statuses of a download (400 no
path, 403 outside the directory, 404 no such file, 200 with the exact bytes).

Run: python3 scripts/test_models_dir_served.py
"""
import io
import sys
import tempfile
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.admin import config_builder, models  # noqa: E402

_fail = []
MiB = 1048576


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


class Handler:
    """The part of the request handler serve_model_file talks to."""

    def __init__(self):
        self.status, self.headers, self.wfile = None, {}, io.BytesIO()
        self.close_connection, self.errors = False, []

    def send_response(self, code):
        self.status = code

    def send_header(self, key, value):
        self.headers[key] = value

    def end_headers(self):
        pass

    def log_error(self, fmt, *args):
        self.errors.append(fmt % args)


def served(rel):
    handler = Handler()
    models.serve_model_file(handler, "path=" + urllib.parse.quote(rel) if rel is not None else "")
    return handler


def put(root, rel, size, fill=b"x"):
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((fill * size)[:size])
    return path


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    home, configured = tmp / "home", tmp / "configured"
    # The directory the config names: a model, its projector, a vocab file, a stub, a space in a name.
    put(configured, "Qwen/unsloth/Q4_K_M/qwen-Q4_K_M.gguf", 3 * MiB, b"q")
    put(configured, "Qwen/unsloth/Q4_K_M/mmproj-F16.gguf", 2 * MiB)
    put(configured, "projectors/vision-projector.gguf", 2 * MiB)
    put(configured, "vocabs/ggml-vocab-llama.gguf", 2 * MiB)
    put(configured, "stubs/tiny.gguf", 1023)
    put(configured, "stubs/small.gguf", 500000)
    put(configured, "stubs/mid.gguf", 2883584)           # 2.75 MiB
    put(configured, "My Model/Q8_0/my model-Q8_0.gguf", 4 * MiB, b"m")
    put(configured, "notes/readme.txt", 5000)
    # The directory the OLD code read: a file that exists only there.
    put(home / "models", "stale/only-here.gguf", 3 * MiB, b"s")

    config = {"LLAMA_MODELS_DIR": str(configured)}
    saved = models.LLAMA_HOME, models.parse_config, config_builder.DEFAULT_MODELS_DIR
    models.LLAMA_HOME = home
    models.parse_config = lambda: dict(config)
    try:
        print("the listing reads the configured directory:")
        listing = models.list_gguf_models()
        paths = [row["path"] for row in listing.get("models", [])]
        check(listing.get("ok") is True and listing.get("modelsDir") == str(configured),
              f"ok, and modelsDir names the configured directory, not LLAMA_HOME/models (got {listing.get('modelsDir')!r})")
        check(paths == sorted(paths) and set(paths) == {
            "Qwen/unsloth/Q4_K_M/qwen-Q4_K_M.gguf", "My Model/Q8_0/my model-Q8_0.gguf", "stubs/small.gguf", "stubs/mid.gguf"},
            f"the models of the configured directory — and only them (got {paths})")
        check("stale/only-here.gguf" not in paths, "negative: a file that exists only under LLAMA_HOME/models is not listed")
        by_path = {row["path"]: row for row in listing.get("models", [])}
        check(by_path.get("Qwen/unsloth/Q4_K_M/qwen-Q4_K_M.gguf") == {
            "path": "Qwen/unsloth/Q4_K_M/qwen-Q4_K_M.gguf", "name": "qwen-Q4_K_M.gguf", "sizeMiB": 3, "dir": "Qwen/unsloth/Q4_K_M"},
            f"a row: path relative to the directory, the file's name, MiB, the folder it sits in (got {by_path.get('Qwen/unsloth/Q4_K_M/qwen-Q4_K_M.gguf')})")
        check(by_path.get("stubs/small.gguf", {}).get("sizeMiB") == 0,
              "as-is: a file of half a MiB is listed with sizeMiB 0 (rounded), not dropped; only a file under 1 KiB is")
        check(by_path.get("stubs/mid.gguf", {}).get("sizeMiB") == 3, "sizes are rounded to the nearest MiB (2.75 → 3), not cut")
        check("stubs/tiny.gguf" not in paths, "negative: a file under 1 KiB is skipped")
        check(not any(part in p.lower() for p in paths for part in ("mmproj", "projector", "vocab")),
              "negative: projectors and vocab files are not models of their own")
        check(all(not p.endswith(".txt") for p in paths), "negative: only .gguf files")

        print("a download reads the same directory:")
        rel = "Qwen/unsloth/Q4_K_M/qwen-Q4_K_M.gguf"
        got = served(rel)
        check(got.status == 200 and got.wfile.getvalue() == b"q" * (3 * MiB),
              f"200 and the exact bytes of the file in the configured directory (status {got.status})")
        check(got.headers.get("Content-Length") == str(3 * MiB) and got.headers.get("Content-Type") == "application/octet-stream"
              and got.headers.get("Content-Disposition") == 'attachment; filename="qwen-Q4_K_M.gguf"',
              f"length, type and file name are told (got {got.headers})")
        check(got.close_connection is False and got.errors == [], "a complete copy leaves the connection alone")
        check(served("stale/only-here.gguf").status == 404,
              "negative: a file that exists only under LLAMA_HOME/models is a 404, not a download")
        check(served("Qwen/unsloth/Q4_K_M/not-there.gguf").status == 404, "negative: no such file in the configured directory — 404")
        check(served("Qwen/unsloth").status == 404, "negative: a directory is no file — 404")

        print("every row the list offers can be downloaded:")
        for row in listing.get("models", []):
            got = served(row["path"])
            on_disk = (configured / row["path"]).stat().st_size if (configured / row["path"]).is_file() else -1
            check(got.status == 200 and len(got.wfile.getvalue()) == on_disk,
                  f"{row['path']}: 200 and every byte of the file (got {got.status}, {len(got.wfile.getvalue())} of {on_disk})")
        check(served("My Model/Q8_0/my model-Q8_0.gguf").wfile.getvalue() == b"m" * (4 * MiB),
              "a name with spaces: the percent-encoded path is read back to the same file")

        print("what a download refuses:")
        empty = served(None)
        check(empty.status == 400 and empty.headers.get("Content-Length") == "0", "no path — 400, with an empty body that says so")
        check(served("   ").status == 400, "a blank path is no path — 400")
        outside = served("../home/models/stale/only-here.gguf")
        check(outside.status == 403 and outside.wfile.getvalue() == b"",
              "a path that leaves the directory — 403, though the file it names exists")
        check(served("/etc/hosts").status == 403, "an absolute path is outside the directory — 403")
        link = configured / "linked.gguf"
        link.symlink_to(home / "models" / "stale" / "only-here.gguf")
        check(served("linked.gguf").status == 403,
              "as-is: a symlink that leads out of the directory is 403 — a library is read by a scout from its own mount")

        print("the listing says so when the configured directory is missing:")
        config["LLAMA_MODELS_DIR"] = str(tmp / "nowhere")
        (home / "models" / "other").mkdir(parents=True, exist_ok=True)
        gone = models.list_gguf_models()
        check(gone == {"ok": False, "error": f"models dir not found: {tmp / 'nowhere'}", "models": []},
              f"ok false, the error names the directory that was asked for, no models (got {gone})")
        check(served("stale/only-here.gguf").status == 404,
              "and a download does not fall back to the other directory either — 404")

        print("without a configured directory the default one is used (a container):")
        default = tmp / "data" / "models"
        put(default, "Gemma/Q4/gemma-Q4.gguf", 2 * MiB, b"g")
        config.clear()
        config_builder.DEFAULT_MODELS_DIR = default
        fresh = models.list_gguf_models()
        check(fresh.get("ok") is True and fresh.get("modelsDir") == str(default)
              and [r["path"] for r in fresh.get("models", [])] == ["Gemma/Q4/gemma-Q4.gguf"],
              f"the default models directory is listed (got {fresh})")
        check(served("Gemma/Q4/gemma-Q4.gguf").wfile.getvalue() == b"g" * (2 * MiB), "and served from")
        check(served("stale/only-here.gguf").status == 404, "negative: LLAMA_HOME/models is no part of it")
    finally:
        models.LLAMA_HOME, models.parse_config, config_builder.DEFAULT_MODELS_DIR = saved

if _fail:
    print(f"\nFAILED ({len(_fail)}):")
    for message in _fail:
        print("  -", message)
    sys.exit(1)
print("\nmodels dir served OK: the list and the download read the configured directory, and agree with each other")
