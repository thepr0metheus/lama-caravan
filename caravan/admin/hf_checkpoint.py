"""A safetensors repository on the models disk: where the page put its files, and how each one stands against the hub.

The /hf page downloads a safetensors repository as ONE artifact: the files the
listing's `safetensors` part names (hf.py — not the README, not the pictures,
not the weights a second time as .bin or .pt). They land under
<model>/<author>/<FORMAT>/, each file keeping its folder of the repository:
GR00T's experiment_cfg/conf.yaml lies in .../BF16/experiment_cfg/. The verify
of such a repository used to look for *.gguf only, and said "nothing of this
repo is on disk" about a folder that was whole (found 2026-10-13 on
nvidia/Cosmos-Reason2-2B).

Two choices here look odd and are not.

* The folder is found by CONTENT, not by the FORMAT label the listing gives
  today. The label is chosen at download time from the repository's name and
  its config.json, and it does not hold still: a gated repository's config.json
  cannot be read without a token whose owner accepted the terms (hf.py sends the
  operator's, and until 1.3.524 did not for this file), so its label then is
  "SAFETENSORS" while its copy may sit under BF16 (placed by hand, or fetched
  when the dtype rule was another). A check that looked in today's folder alone
  would call a copy that is there absent. So every folder under
  <model>/<author>/ that holds a file of the plan is a copy, and each answers on
  its own. A GGUF quant folder holds no file of the plan and is never taken for one.
* A copy is judged as a whole. Once a folder holds one file of the plan, every
  other file of the plan is expected there, and a missing one is NAMED. A
  repository whose checkpoint folder is not there at all is not "14 files
  missing": it was never downloaded, and nothing is said about it.
"""
import os
import stat
from pathlib import Path

from caravan.admin.hub_hash import HubHash
from caravan.common.errors import AppError
from caravan.common.model_artifacts import hidden


class CheckpointLayout:
    """Where the page lays a safetensors repository out under the models directory.

    This is the twin of `HfDownloads.checkpointDir` and `checkpointFileDir` in
    static/js/hf-downloads.js, where the plan is made and sent to the server as
    each file's `destDir`: the check has to look where the page put the files.
    A rule that lives twice is held by one table of cases run against both
    (scripts/test_hf_checkpoint_layout.py); the copy that drifts turns it red.
    """

    #: The folder of a repository id that names no author, as the page spells it.
    NO_AUTHOR = "unknown"

    @classmethod
    def repo_folder(cls, repo_id):
        """<model>/<author>: the folder the format folders of one repository sit in."""
        author = repo_id.split("/")[0] if "/" in repo_id else cls.NO_AUTHOR
        return f"{repo_id.split('/')[-1]}/{author}"

    @staticmethod
    def file_dirs(path):
        """The folders of a path in the repository, below the checkpoint's folder.
        A "." or ".." step is dropped, so a path cannot leave the folder it lands in."""
        return [part for part in str(path or "").split("/")[:-1] if part and part not in (".", "..")]

    @classmethod
    def file_path(cls, path, name):
        """Where a file lies below the checkpoint's folder: its repository folders, then its name."""
        return "/".join(cls.file_dirs(path) + [name])


class CheckpointFile:
    """One file of the checkpoint's plan, held against what one folder has of it.

    The answer for it is a row: a `state`, the kind of `hash` the hub gave, both
    sizes, and the digests when a hash was compared. The states are each a
    different thing to do about it, so none stands in for another.
    """

    #: The bytes match the hub's hash.
    SAME = "same"
    #: The size is right and the hash is not: another build under the same name.
    DIFFERS = "differs"
    #: The size is not the hub's. Not read: a file of another size cannot be the same one.
    WRONG_SIZE = "wrong-size"
    #: The plan names it and the folder does not have it.
    MISSING = "missing"
    #: The size is right and the hub gave no hash to hold the bytes against (a
    #: gated repository hides it): NOT verified by hash, and the row says so.
    SIZE_ONLY = "size-only"
    #: The file is there and could not be read.
    UNREADABLE = "unreadable"
    STATES = (SAME, DIFFERS, WRONG_SIZE, MISSING, SIZE_ONLY, UNREADABLE)

    def __init__(self, repo_path, expected_size, hub_hash, local):
        #: The file's path in the repository: the key it answers under.
        self.repo_path = repo_path
        self.expected_size = int(expected_size or 0)
        self.hub_hash = hub_hash
        #: {path, size, mtime}, {path, error} when it could not even be looked at, or None.
        self.local = local

    def _row(self, state, **more):
        row = {"state": state, "hash": self.hub_hash.kind, "expectedSize": self.expected_size}
        if self.local and "size" in self.local:
            row["size"] = self.local["size"]
        row.update(more)
        return row

    def settled(self):
        """The row when no byte needs reading, or None when the hash has to be computed."""
        if self.local is None:
            return self._row(self.MISSING)
        if "error" in self.local:
            return self.unreadable(self.local["error"])
        if self.local["size"] != self.expected_size:
            return self._row(self.WRONG_SIZE)
        if not self.hub_hash.usable:
            return self._row(self.SIZE_ONLY)
        return None

    def judged(self, actual):
        """The row once the file's digest (of the kind the hub gave) is known."""
        key = "sha256" if self.hub_hash.kind == HubHash.SHA256 else "gitSha1"
        same = actual == self.hub_hash.value
        return self._row(self.SAME if same else self.DIFFERS, **{key: actual, "expected": self.hub_hash.value})

    def unreadable(self, error):
        return self._row(self.UNREADABLE, error=str(error))


class CheckpointCopy:
    """A folder on the models disk that holds part or all of the checkpoint's plan."""

    def __init__(self, folder, files):
        #: Below the models directory: <model>/<author>/<label>.
        self.folder = folder
        self.files = files


class CheckpointResult:
    """What a verify job knows of one copy, as its rows come in."""

    def __init__(self, copy):
        self.folder = copy.folder
        self.planned = len(copy.files)
        self.rows = {}

    def summary(self):
        """How many rows stand in each state, and how many are still to come: a
        copy that is half read does not read as one that is whole."""
        counts = {"files": self.planned, "pending": self.planned - len(self.rows)}
        counts.update({state: 0 for state in CheckpointFile.STATES})
        for row in self.rows.values():
            counts[row["state"]] += 1
        return counts

    def snapshot(self):
        return {"folder": self.folder, "files": dict(self.rows), "summary": self.summary()}


class CheckpointFinder:
    """Finds the copies of a repository's checkpoint on the models disk.

    Only looks and stats: nothing is read. Hashing is the job's, started on a button.
    """

    def __init__(self, models_dir):
        self.models_dir = Path(models_dir)

    def copies(self, repo_id, checkpoint):
        """The folders under <model>/<author>/ holding any file of `checkpoint`, the
        `safetensors` part of hf_list_files ({format, files}); [] when there is no
        such plan or no folder holds a file of it. A folder that cannot be read is
        a refusal, not an empty answer: "nothing on disk" would be a guess."""
        plan = (checkpoint or {}).get("files") or []
        if not plan:
            return []
        base = CheckpointLayout.repo_folder(repo_id)
        try:
            with os.scandir(self.models_dir / base) as entries:
                labels = sorted(e.name for e in entries if e.is_dir() and not hidden(e.name))
        except (FileNotFoundError, NotADirectoryError):
            return []
        except OSError as exc:
            raise AppError(f"cannot read {base}: {exc}", 500)
        found = []
        for label in labels:
            files = [self._file(self.models_dir / base / label, entry) for entry in plan]
            if any(f.local is not None for f in files):
                found.append(CheckpointCopy(f"{base}/{label}", files))
        return found

    @staticmethod
    def _file(folder, entry):
        path = folder / CheckpointLayout.file_path(entry.get("path"), entry.get("name"))
        try:
            st = path.stat()
        except (FileNotFoundError, NotADirectoryError):
            local = None
        except OSError as exc:
            local = {"path": str(path), "error": str(exc)}
        else:
            # A folder where the file should be is not the file.
            local = ({"path": str(path), "size": st.st_size, "mtime": int(st.st_mtime)}
                     if stat.S_ISREG(st.st_mode) else None)
        return CheckpointFile(entry.get("path"), entry.get("size"), HubHash.from_entry(entry), local)
