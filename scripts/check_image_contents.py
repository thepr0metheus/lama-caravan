#!/usr/bin/env python3
"""Guard: the image carries every part of the repo the running controller reads.

The Docker image is built from an explicit COPY list. A folder the code reads
at run time and the list leaves out is no error at build time: the image
builds, starts and answers /health, and then the one feature that needs the
folder fails. `cells/` was missing that way: a scout asking the containerised
controller for its cell servers got an empty list and a 500 (found 2026-10-07).

What the code reads is asked from the code, not listed here by hand: the two
entry points, the caravan package, `caravan.admin.paths.STATIC_DIR` and
`caravan.admin.cell_assets.CELLS_DIR`. Each must be carried by a COPY line of
the Dockerfile and must not be dropped by .dockerignore. Every COPY source
must exist, or the build fails on the machine that builds it, not here.

Run: python3 scripts/check_image_contents.py
"""
import fnmatch
import shlex
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def runtime_homes():
    """The repo parts the running code reads, as repo-relative paths (folders end with /)."""
    from caravan.admin import cell_assets, paths
    homes = ["app.py", "agent-proxies.py", "caravan/"]
    for folder in (Path(paths.STATIC_DIR), Path(cell_assets.CELLS_DIR)):
        homes.append(folder.resolve().relative_to(ROOT).as_posix() + "/")
    return homes


def copied_sources(dockerfile):
    """Every source of every COPY line, with flags (--chown=…) left out."""
    sources = []
    for line in dockerfile.read_text(encoding="utf-8").splitlines():
        if not line.strip().upper().startswith("COPY "):
            continue
        words = shlex.split(line.split("#", 1)[0])
        args = [word for word in words[1:] if not word.startswith("--")]
        sources.extend(args[:-1])
    return sources


def ignored_patterns(dockerignore):
    if not dockerignore.exists():
        return []
    return [line.strip() for line in dockerignore.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith(("#", "!"))]


def is_carried(home, sources):
    for source in sources:
        clean = source.rstrip("/")
        if clean in (".", "./"):
            return True
        if home.rstrip("/") == clean or home.startswith(clean + "/"):
            return True
    return False


def dropped_by(home, patterns):
    name = home.rstrip("/")
    for pattern in patterns:
        bare = pattern.rstrip("/")
        if fnmatch.fnmatch(name, bare) or fnmatch.fnmatch(name, bare + "/*") or name.startswith(bare + "/"):
            return pattern
    return ""


def main():
    dockerfile = ROOT / "Dockerfile"
    if not dockerfile.exists():
        print("image contents: FAILED\n  - Dockerfile не найден — гвард смотрит не туда")
        return 1
    homes = runtime_homes()
    sources = copied_sources(dockerfile)
    patterns = ignored_patterns(ROOT / ".dockerignore")
    problems = []
    for home in homes:
        if not is_carried(home, sources):
            problems.append(f"{home}: код читает его при работе, а COPY в Dockerfile его не несёт")
        pattern = dropped_by(home, patterns)
        if pattern:
            problems.append(f"{home}: .dockerignore выбрасывает его правилом «{pattern}»")
    for source in sources:
        if not (ROOT / source).exists():
            problems.append(f"COPY {source}: такого в репозитории нет — сборка упадёт")
    if problems:
        print("image contents: FAILED")
        for problem in problems:
            print("  - " + problem)
        return 1
    print(f"image contents OK: {len(homes)} частей, которые читает код, все в образе ({', '.join(homes)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
