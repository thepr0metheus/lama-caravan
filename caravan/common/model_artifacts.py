"""Which folders are models in their own right.

A model is not always one file. A whisper cache is a directory of blobs with a
tree of links over it; a checkpoint is a directory of shards. The manager, the
mover and the library walk all have to agree on where such a folder starts —
otherwise the page offers to move half of one.

The rule lives here alone because two different walks ask it: model_gc walks
the models disk, and model_stores walks a library inside a child process that
imports nothing at all. That child gets these lines as text (the module's own
source), so both walks answer from the same ones.

Nothing here opens a file. A library sits on a NAS, where every read costs a
round trip; a name and a place are enough to tell a model folder apart.
"""
import os


def artifact_kind(rel, names):
    """The kind of model a directory is by itself — "whisper", "safetensors",
    or "" for an ordinary folder. `rel` is its path from the store's root and
    `names` the file names directly inside it."""
    # The store's own root is a store, not a model: a stray .safetensors lying
    # at the top would otherwise make the whole library one giant item.
    parts = [p for p in str(rel).replace(os.sep, "/").strip("/").split("/") if p and p != "."]
    if not parts:
        return ""
    if len(parts) == 2 and parts[0] == "whisper" and parts[1].startswith("models--"):
        return "whisper"
    if any(str(n).endswith(".safetensors") for n in names):
        return "safetensors"
    return ""


def artifact_dirs(root, walk=os.walk):
    """Every model folder under `root`, outermost first, as (relpath, kind).

    Outermost only: a whisper cache holds snapshot directories full of
    .safetensors links, and each of those matches the rule on its own. Naming
    them too would put a part of a model beside the model — two items for one
    thing, either of which a move could carry off alone."""
    found = []
    for base, dirs, names in walk(root):
        dirs[:] = sorted(d for d in dirs if not hidden(d))
        rel = relative(base, root)
        kind = artifact_kind(rel, [n for n in names if not hidden(n)])
        if kind:
            found.append((rel, kind))
            # Everything below belongs to this folder, and it travels whole.
            dirs[:] = []
    return found


def folder_weight(root, walk=os.walk, lstat=os.lstat):
    """What a folder weighs and when it last changed — as a copy of it would
    weigh, so links count for nothing. A whisper cache keeps every blob twice,
    once in blobs/ and once as a link under snapshots/; following those links
    would report the cache at double its size, and the page would blame the
    NAS for space nothing is using."""
    size = 0
    mtime = 0
    for base, dirs, names in walk(root):
        dirs[:] = [d for d in dirs if not hidden(d)]
        for name in names:
            if hidden(name):
                continue
            try:
                st = lstat(os.path.join(base, name))
            except OSError:
                continue
            if (st.st_mode & 0o170000) != 0o100000:  # regular files only
                continue
            size += st.st_size
            mtime = max(mtime, int(st.st_mtime))
    return size, mtime


def hidden(name):
    """Names no walk here looks into: dotfiles, Synology's #recycle and @eaDir,
    and macOS's "._name" shadows on a share."""
    return str(name)[:1] in (".", "#", "@")


def relative(base, root):
    """A path under the store's root, in the one spelling every store speaks:
    forward slashes, and "" for the root itself."""
    if os.path.normpath(base) == os.path.normpath(root):
        return ""
    return os.path.relpath(base, root).replace(os.sep, "/")
