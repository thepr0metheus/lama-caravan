#!/usr/bin/env python3
"""Value snapshot: what the hub says about the bytes of one file (caravan/admin/hub_hash.py).

A tree listing gives every file an `oid`, and the word means three things. In an
LFS entry it is the sha256 of the content; in an ordinary git entry it is the
git blob id, a sha1; in a gated repository whose terms the token has not
accepted it is 64 asterisks (nvidia/Cosmos-Reason2-2B, 2026-10-13: the real
mask is pinned below). Read as a hash, the mask made every file "differ".

Every claim is pinned with its opposite: a mask is hidden and not a hash; a
hidden hash is not "none"; junk that is not a mask is not called hidden; the
git id of an LFS POINTER (the entry's own `oid`, which LFS entries carry too)
is never taken for the content's hash; a sha256-length value is not a sha1.

Run: python3 scripts/test_hub_hash.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.admin.hub_hash import HubHash  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


SHA256 = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
SHA1 = "3b18e512dba79e4c8300dd08aeb37f8e728b8dad"
POINTER_ID = "0bb57c08c47f" + "a" * 28  # the git blob id the hub gives an LFS entry's own `oid`
MASK = "*" * 64  # as the hub sent it for nvidia/Cosmos-Reason2-2B without the terms accepted


def read(item):
    h = HubHash.from_tree_item(item)
    return h.kind, h.value


def main():
    print("a tree entry:")
    check(read({"oid": POINTER_ID, "lfs": {"oid": SHA256, "size": 9, "pointerSize": 135}}) == ("sha256", SHA256),
          "an LFS entry: the sha256 is `lfs.oid`")
    check(read({"oid": POINTER_ID, "lfs": {"oid": SHA256.upper(), "size": 9}}) == ("sha256", SHA256),
          "an upper-case sha256 is the same hash, spelled as everywhere else (lower case)")
    check(read({"oid": SHA1}) == ("git-sha1", SHA1), "an ordinary entry: the git blob id is its `oid`")
    check(read({"oid": POINTER_ID, "lfs": {"oid": MASK, "size": 4877470304, "pointerSize": 135}}) == ("hidden", ""),
          "the hub's mask (64 asterisks) is HIDDEN: no hash, and the kind says why")
    check(read({"oid": POINTER_ID, "lfs": {"oid": MASK}})[0] != "git-sha1",
          "negative: a masked LFS entry's own `oid` (the pointer's blob id) is not the content's hash")
    check(read({"oid": SHA1, "lfs": {"size": 9}}) == ("none", ""),
          "negative: an LFS entry with no `lfs.oid` is NONE, whatever its own `oid` says")
    check(read({"oid": SHA1, "lfs": {"oid": "", "size": 9}}) == ("none", ""), "negative: an empty `lfs.oid` is NONE, not hidden")
    check(read({"oid": POINTER_ID, "lfs": {"oid": "unavailable"}}) == ("none", ""),
          "negative: junk that is not a mask is not called hidden — only what the hub does is named")
    check(read({"oid": POINTER_ID, "lfs": {"oid": SHA256[:63]}}) == ("none", ""),
          "negative: a sha256 one digit short is not a hash")
    check(read({}) == ("none", "") and read({"oid": ""}) == ("none", ""), "an entry with nothing — NONE")
    check(read({"oid": SHA256}) == ("none", ""),
          "negative: a plain entry whose `oid` is 64 digits is not a git sha1 — it cannot be held against one")
    check(read({"oid": "*" * 40}) == ("none", ""), "negative: a mask in a plain entry is no git id")
    check(read({"oid": None, "lfs": {"oid": None}}) == ("none", ""), "null values — NONE, no exception")

    print("the listing's words for it:")
    check(HubHash("sha256", SHA256).fields() == {"oid": SHA256, "gitOid": "", "hashHidden": False},
          "a sha256: `oid` as it always was, the others empty")
    check(HubHash("git-sha1", SHA1).fields() == {"oid": "", "gitOid": SHA1, "hashHidden": False},
          "a git id: `oid` stays empty — it was always \"its LFS sha256\"")
    check(HubHash("hidden").fields() == {"oid": "", "gitOid": "", "hashHidden": True},
          "hidden: `oid` empty — never the mask — and `hashHidden` says why")
    check(HubHash("none").fields() == {"oid": "", "gitOid": "", "hashHidden": False}, "none: all empty, not hidden")
    for kind, value in (("sha256", SHA256), ("git-sha1", SHA1), ("hidden", ""), ("none", "")):
        h = HubHash(kind, value)
        back = HubHash.from_entry(h.fields())
        check((back.kind, back.value) == (kind, value), f"{kind}: what a listing carries reads back as the same")
    check(HubHash.from_entry({"oid": MASK}).kind == "none",
          "negative: a mask that reached `oid` is no hash — it can never be compared")
    check(HubHash.from_entry({"oid": MASK, "hashHidden": True}).kind == "hidden", "…and `hashHidden` still says why")
    check(HubHash.from_entry({"oid": SHA256, "gitOid": SHA1, "hashHidden": True}).kind == "sha256",
          "a usable sha256 wins over the rest")
    check(HubHash.from_entry({"oid": "", "hashHidden": "yes"}).kind == "none",
          "negative: `hashHidden` is a flag that is true or is not: any other value is no claim")
    check(HubHash.from_entry({}).kind == "none", "an old-shaped entry with nothing — NONE")

    print("usable:")
    check([HubHash(k, v).usable for k, v in (("sha256", SHA256), ("git-sha1", SHA1), ("hidden", ""), ("none", ""))]
          == [True, True, False, False], "only the two kinds with a value can be held against a file")

    print("a kind needs its value:")
    for args in (("sha256", ""), ("git-sha1", ""), ("hidden", SHA256), ("none", SHA1), ("md5", "")):
        try:
            HubHash(*args)
            check(False, f"HubHash{args!r} should refuse")
        except ValueError:
            check(True, f"HubHash{args!r} is refused")

    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg)
        sys.exit(1)
    print("hub-hash snapshots hold")


if __name__ == "__main__":
    main()
