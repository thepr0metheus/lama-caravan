"""What the hub says about the bytes of one file, said once.

A tree listing names every file with an `oid`, and the word means two things.
For a file kept in LFS (weights, anything large) the entry carries an `lfs`
record and ITS `oid` is the sha256 of the content. For an ordinary git file
(config.json, a tokenizer) there is no `lfs` record and the entry's own `oid`
is the git blob id: the sha1 of "blob <size>\\0" and the content. Reading `oid`
without asking which of the two it is sets a sha256 against a sha1, or a
content hash against the hash of an LFS pointer, and calls the file different.

A third case is a gated repository whose terms the token has not accepted
(found on nvidia/Cosmos-Reason2-2B, 2026-10-13). The tree still lists the
files with their real sizes, but every LFS `oid` is 64 asterisks. Taken as a
hash, the mask made every file of such a repository "differ". It is no hash:
the file is HIDDEN, and the answer says so instead of passing or failing it.

This module only reads. Computing the same digest of a local file is
hf_verify.py's work; the four kinds below are the words both sides use.
"""
import re


class HubHash:
    """One file's hash as the hub published it: a kind, and its value when it has one."""

    #: An LFS file with the content's sha256 given.
    SHA256 = "sha256"
    #: An ordinary git file with its blob id (sha1) given.
    GIT_SHA1 = "git-sha1"
    #: An LFS file whose hash the hub masked: a gated repository, terms not accepted.
    HIDDEN = "hidden"
    #: The hub gave nothing usable and did not say why.
    NONE = "none"

    KINDS = (SHA256, GIT_SHA1, HIDDEN, NONE)

    _SHA256 = re.compile(r"[0-9a-f]{64}")
    _SHA1 = re.compile(r"[0-9a-f]{40}")
    #: What the hub puts where a hidden hash would stand: asterisks and nothing else.
    _MASK = re.compile(r"\*+")

    def __init__(self, kind=NONE, value=""):
        if kind not in self.KINDS:
            raise ValueError(f"unknown kind of hub hash: {kind!r}")
        if kind in (self.SHA256, self.GIT_SHA1) and not value:
            raise ValueError(f"a {kind} hash needs its value")
        if kind in (self.HIDDEN, self.NONE) and value:
            raise ValueError(f"a {kind} hash has no value")
        self.kind = kind
        self.value = value

    @classmethod
    def from_tree_item(cls, item):
        """The hash of one file entry of the hub's tree listing."""
        lfs = item.get("lfs")
        if isinstance(lfs, dict):
            value = str(lfs.get("oid") or "").strip().lower()
            if cls._SHA256.fullmatch(value):
                return cls(cls.SHA256, value)
            # An LFS file's `oid` that is not a sha256 is not the git blob id
            # either: that one names the pointer file, not the content.
            return cls(cls.HIDDEN) if cls._MASK.fullmatch(value) else cls(cls.NONE)
        value = str(item.get("oid") or "").strip().lower()
        return cls(cls.GIT_SHA1, value) if cls._SHA1.fullmatch(value) else cls(cls.NONE)

    @classmethod
    def from_entry(cls, entry):
        """The hash a listing entry carries (see fields()). An `oid` that is not a
        sha256 counts as no hash: a mask must never reach a comparison."""
        sha256 = str(entry.get("oid") or "").strip().lower()
        if cls._SHA256.fullmatch(sha256):
            return cls(cls.SHA256, sha256)
        git = str(entry.get("gitOid") or "").strip().lower()
        if cls._SHA1.fullmatch(git):
            return cls(cls.GIT_SHA1, git)
        return cls(cls.HIDDEN) if entry.get("hashHidden") is True else cls(cls.NONE)

    def fields(self):
        """The listing's own words for it. `oid` was always "its LFS sha256, or empty"
        and stays that; the other two say what `oid` cannot."""
        return {"oid": self.value if self.kind == self.SHA256 else "",
                "gitOid": self.value if self.kind == self.GIT_SHA1 else "",
                "hashHidden": self.kind == self.HIDDEN}

    @property
    def usable(self):
        """Whether a local file can be held against it."""
        return self.kind in (self.SHA256, self.GIT_SHA1)
