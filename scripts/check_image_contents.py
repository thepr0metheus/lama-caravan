#!/usr/bin/env python3
"""Guard: a release carries every part of the repo the running controller reads.

A release is the programs and the files an explicit list names (deploy/nas/release_ship.py, and the Dockerfile's COPY lines). A folder the code reads at run time and the list leaves out is no error when the
release is built: it arrives, starts and answers /health, and then the one feature that needs the folder fails. `cells/` was missing from the image that way: a scout asking
the containerised controller for its cell servers got an empty list and a 500 (found 2026-10-07).

What the code reads is asked from the code, not listed here by hand: where the program's paths find `static/`, the cell servers, and the VERSION file. Each must be in the
list. It fails when the list can no longer be read too: then it would be guarding nothing.

Run: python3 scripts/check_image_contents.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHIP = ROOT / "deploy" / "nas" / "release_ship.py"
IMAGE = ROOT / "Dockerfile"
#: (the file of the program that reads it, how it names it there, what the release must carry)
READS = (("rust/crates/admin/src/paths.rs", 'project_root.join("static")', "static"),
         ("rust/crates/admin/src/fleet/cell_assets.rs", 'join("cells")', "cells"),
         ("rust/crates/admin/src/common/checkout.rs", '"VERSION"', "VERSION"))


def main():
    problems = []
    # The public mirror leaves deploy/nas/ out: there the Dockerfile is the only way to a release.
    shipped = SHIP.read_text(encoding="utf-8") if SHIP.is_file() else None
    lists = re.findall(r'"archive", "origin/main", ((?:"[^"]+"(?:, )?)+)\]', shipped or "")
    carried = [name for listed in lists for name in re.findall(r'"([^"]+)"', listed)]
    in_image = re.findall(r'^COPY (?!--from)(\S+?)/? ', IMAGE.read_text(encoding="utf-8"), re.M)
    if not in_image:
        problems.append("Dockerfile: списка COPY не найдено — гвард смотрит мимо")
    if shipped is not None and not carried:
        problems.append(f"{SHIP.relative_to(ROOT)}: список файлов выпуска не найден — гвард смотрит не туда")
    for rel, reads, home in READS:
        if reads not in (ROOT / rel).read_text(encoding="utf-8"):
            problems.append(f"{rel} больше не читает {reads} — этот гвард отстал от кода")
        if home not in in_image:
            problems.append(f"программа читает {home}, а образ его не везёт (Dockerfile: {in_image})")
        if shipped is not None and home not in carried:
            problems.append(f"программа читает {home}, а выпуск его не везёт ({SHIP.name}: {carried})")
    if problems:
        print("image contents: FAILED")
        for problem in problems:
            print("  - " + problem)
        return 1
    print(f"image contents OK: выпуск и образ везут всё, что читает программа: {', '.join(in_image)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
