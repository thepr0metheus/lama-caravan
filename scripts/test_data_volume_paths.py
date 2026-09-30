#!/usr/bin/env python3
"""What a container keeps on its volume, and where a native install keeps it.

In the Docker image the repo directory is root's and the app runs as another
user, and its home is the container's own: whatever the app writes has to be on
/data. Every mutable path therefore goes through `_default` in
caravan/admin/paths.py, which puts it under CARAVAN_DATA_DIR when there is one.
Two were missed, and found on 2026-09-30 by running the image:

  * the controller's own config — the models directory and the defaults a new
    cell starts from — lives in start-server.sh, by default under ~/llama.cpp.
    In the container that directory is not there, so saving the config was a 500
    ("No such file or directory"), and a directory made for it would have gone
    with the container;
  * the cache of Artificial Analysis scores was written to PROJECT_ROOT/logs,
    which in the container is the image. The save was swallowed as a best-effort
    cache: nothing failed, and every restart fetched the scores again.

The paths are fixed when the modules are imported, so each case runs in a
process of its own, started with exactly the environment it names. Native
installs — no data directory — keep what they had, and each pin says so.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {detail}")


NAMES = """
import json
from caravan.admin import benchmarks, config_builder, launch, paths, settings_bundle
print(json.dumps({"start": str(paths.START_SCRIPT), "launch": str(launch.START_SCRIPT),
                  "builder": str(config_builder.START_SCRIPT),
                  "bundle": str(settings_bundle._files()["controller-config"]),
                  "aa": str(paths.AA_SCORES_CACHE_PATH), "aaUsed": str(benchmarks._AA_MAP_PATH),
                  "llamaHome": str(paths.LLAMA_HOME), "root": str(paths.PROJECT_ROOT)}))
"""

# A save and a read of the config, and a save of the scores cache, as the running
# controller does them — each in a process of its own, so one failing cannot hide
# the other. `main()` makes the volume's folders before anything writes; these do
# what it does.
USE_CONFIG = """
import json, stat
from caravan.admin import config_builder, launch, paths
(paths.DATA_DIR / "config").mkdir(parents=True, exist_ok=True)
launch.save_config({"MODEL_FILE": "m/dummy.gguf", "PORT": "8080", "CTX_SIZE": "4096",
                    "LLAMA_MODELS_DIR": str(paths.DATA_DIR / "models")})
read = config_builder.parse_config()
print(json.dumps({"script": str(paths.START_SCRIPT), "exists": paths.START_SCRIPT.exists(),
                  "mode": stat.S_IMODE(paths.START_SCRIPT.stat().st_mode),
                  "readBack": {k: read.get(k) for k in ("MODEL_FILE", "PORT", "CTX_SIZE")}}))
"""

USE_CACHE = """
import json
from caravan.admin import benchmarks, paths
(paths.DATA_DIR / "logs").mkdir(parents=True, exist_ok=True)
benchmarks._aa_map_load()
benchmarks._aa_map_save()
print(json.dumps({"aa": str(benchmarks._AA_MAP_PATH), "aaExists": benchmarks._AA_MAP_PATH.exists()}))
"""

KEYS = ("CARAVAN_DATA_DIR", "LLAMA_START_SCRIPT", "LLAMA_HOME", "LLAMA_MODELS_DIR", "CARAVAN_CONTAINER")


def in_a_process(snippet, env_extra):
    """The snippet run in a process started with exactly this environment."""
    env = {k: v for k, v in os.environ.items() if k not in KEYS}
    env.update(env_extra, PYTHONPATH=str(ROOT))
    out = subprocess.run([sys.executable, "-c", snippet], env=env, cwd=ROOT, capture_output=True, text=True)
    if out.returncode != 0:
        return {"error": out.stderr.strip()[-400:]}
    return json.loads(out.stdout.strip().splitlines()[-1])


def main():
    base = Path(tempfile.mkdtemp(prefix="caravan-volume-paths-"))
    data, home, other = base / "data", base / "home", base / "elsewhere"
    home.mkdir()
    at_home = {"HOME": str(home)}

    # ── in a container: a data directory, and nothing else ─────────────────
    got = in_a_process(NAMES, {**at_home, "CARAVAN_DATA_DIR": str(data)})
    want = str(data / "config" / "start-server.sh")
    check("with a data directory the controller config is config/start-server.sh on the volume",
          got.get("start") == want, str(got))
    check("the launch, config and settings modules read that same file",
          got.get("launch") == got.get("builder") == got.get("bundle") == want, str(got))
    check("the scores cache is logs/aa-scores-cache.json on the volume, by both of its names",
          got.get("aa") == got.get("aaUsed") == str(data / "logs" / "aa-scores-cache.json"), str(got))
    check("negative: the llama.cpp checkout stays where LLAMA_HOME says — only the config file moved",
          got.get("llamaHome") == str(home / "llama.cpp"), str(got))

    # ── what still wins over the data directory ────────────────────────────
    got = in_a_process(NAMES, {**at_home, "CARAVAN_DATA_DIR": str(data), "LLAMA_START_SCRIPT": str(other / "s.sh")})
    check("LLAMA_START_SCRIPT wins over the data directory, in every module that reads it",
          got.get("start") == got.get("launch") == got.get("builder") == got.get("bundle") == str(other / "s.sh"), str(got))
    got = in_a_process(NAMES, {**at_home, "CARAVAN_DATA_DIR": str(data), "LLAMA_HOME": str(other)})
    check("negative: LLAMA_HOME does not pull the config file back off the volume",
          got.get("start") == want and got.get("llamaHome") == str(other), str(got))
    got = in_a_process(NAMES, {**at_home, "CARAVAN_DATA_DIR": str(data), "LLAMA_START_SCRIPT": ""})
    check("boundary: an empty LLAMA_START_SCRIPT is no setting at all — the volume's file, not a path named \"\"",
          got.get("start") == want, str(got))

    # ── a native install: no data directory, what it always had ────────────
    got = in_a_process(NAMES, at_home)
    check("as-is: without a data directory the config file is ~/llama.cpp/start-server.sh",
          got.get("start") == got.get("launch") == got.get("builder") == got.get("bundle")
          == str(home / "llama.cpp" / "start-server.sh"), str(got))
    check("as-is: and the scores cache stays in the repo's logs/",
          got.get("aa") == got.get("aaUsed") == str(Path(got.get("root", "?")) / "logs" / "aa-scores-cache.json"), str(got))
    got = in_a_process(NAMES, {**at_home, "LLAMA_HOME": str(other)})
    check("as-is: the config file follows LLAMA_HOME when there is no data directory",
          got.get("start") == str(other / "start-server.sh"), str(got))
    got = in_a_process(NAMES, {**at_home, "LLAMA_START_SCRIPT": str(other / "s.sh")})
    check("as-is: LLAMA_START_SCRIPT alone still says where it is", got.get("start") == str(other / "s.sh"), str(got))

    # ── the container's shape, end to end ──────────────────────────────────
    # A save, a read back and a cache save with a data directory and an empty
    # home: the files appear on the volume, and nothing is made under the home
    # or in the repo's logs/ (a copy of the scores there is what the old code
    # tried to write — it is watched, and removed if a failure left one).
    saved = in_a_process(USE_CONFIG, {**at_home, "CARAVAN_DATA_DIR": str(data)})
    check("saving the controller config writes the file on the volume, executable",
          saved.get("script") == want and saved.get("exists") is True and saved.get("mode") == 0o755, str(saved))
    check("and reading it back gives what was saved",
          saved.get("readBack") == {"MODEL_FILE": "m/dummy.gguf", "PORT": "8080", "CTX_SIZE": "4096"}, str(saved))
    check("negative: nothing was made under the home — no ~/llama.cpp in the container's shape",
          not (home / "llama.cpp").exists(), str(sorted(p.name for p in home.iterdir())))

    stray = ROOT / "logs" / "aa-scores-cache.json"
    before = (stray.stat().st_mtime_ns, stray.stat().st_size) if stray.exists() else None
    try:
        cached = in_a_process(USE_CACHE, {**at_home, "CARAVAN_DATA_DIR": str(data)})
    finally:
        after = (stray.stat().st_mtime_ns, stray.stat().st_size) if stray.exists() else None
        if before is None and after is not None:
            stray.unlink()
    check("the scores cache is written on the volume",
          cached.get("aa") == str(data / "logs" / "aa-scores-cache.json") and cached.get("aaExists") is True, str(cached))
    check("negative: and the repo's logs/ has no copy of the scores — it is the image there",
          after == before, f"{before} -> {after}")

    shutil.rmtree(base, ignore_errors=True)
    print(f"\n  {len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
