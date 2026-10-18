"""The model cache of a machine as its scout reports it, and what the board asks of it (1.3.576).

A scout (2.34+) keeps in its cache the files of the last N models that ran on the machine, all their parts, and deletes the rest by
itself (the owner, 2026-10-18, when the disk of a machine was 94 % full of model copies and a start died with "No space left on
device"). Its report carries the setting and the figures (`modelCache`). The rules are the scout's (cache_keeper.py there) and so
are the refusals; this file keeps what the scout says for the board and carries the operator's word to the scout.
"""
from caravan.admin.machine_models import MachineModels
from caravan.common.errors import AppError


class ModelCacheFacts:
    """A scout's word on its model cache, cleaned for the machine's record: how many of the last models it keeps, what it holds, what
    lies in the folder that it did not download, what the disk has left.

    None when the report does not say — a scout older than 2.34 cannot — and None for a part the scout said in a form that cannot be
    read: the board then draws nothing of it. An empty cache says zeros; unknown is not zero (a disk that "has 0 bytes free" and a disk
    nobody measured are two different things on a screen)."""

    #: The folders a record keeps: the scout names its eight biggest.
    FOLDERS = 8

    @classmethod
    def clean(cls, raw):
        if not isinstance(raw, dict):
            return None
        keep = MachineModels.count(raw.get("keep"))
        if not keep:           # a cache keeps at least one model; 0 and a flag are not a setting
            return None
        return {"keep": keep, "managedBytes": MachineModels.count(raw.get("managedBytes")),
                "foreign": cls.foreign(raw.get("foreign")), "disk": cls.disk(raw.get("disk"))}

    @classmethod
    def foreign(cls, raw):
        """The files of the cache folder that the scout did not download: how many, how big, and the folders they lie in."""
        if not isinstance(raw, dict):
            return None
        files, size = MachineModels.count(raw.get("files")), MachineModels.count(raw.get("bytes"))
        if files is None or size is None:
            return None
        folders = []
        for item in raw.get("folders") if isinstance(raw.get("folders"), list) else []:
            row = item if isinstance(item, dict) else {}
            name = str(row.get("folder") or "").strip()[:200]
            count, bytes_ = MachineModels.count(row.get("files")), MachineModels.count(row.get("bytes"))
            if name and count is not None and bytes_ is not None:
                folders.append({"folder": name, "files": count, "bytes": bytes_})
            if len(folders) == cls.FOLDERS:      # a row that cannot be read does not take the place of one that can
                break
        return {"files": files, "bytes": size, "folders": folders}

    @staticmethod
    def disk(raw):
        """The cache folder's disk: its size and what is free."""
        if not isinstance(raw, dict):
            return None
        total, free = MachineModels.count(raw.get("totalBytes")), MachineModels.count(raw.get("freeBytes"))
        return {"totalBytes": total, "freeBytes": free} if total and free is not None else None


class ModelCache:
    """What the board asks of a machine's model cache: how many of the last models to keep, and the deletion of the files that its
    scout did not download.

    The scout decides — the range of the setting, what may go, and the 409 when the files changed since the operator looked — and the
    controller carries its words back unchanged (Scout.post). After an answer the machine's figures are asked again and stored, so a
    board read a moment later shows the new ones and does not wait for the next report."""

    def __init__(self, scout_of, store, save):
        self.scout_of = scout_of       # host id -> the Scout of that machine
        self.store = store             # -> the topology store (its "hosts")
        self.save = save               # writes the admin state

    @staticmethod
    def whole(raw, name):
        """A whole number the caller must give: not a flag, not text."""
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise AppError(f"{name} is required: a whole number", 400)
        return raw

    def keep(self, host_id, keep):
        """Set how many of the last started models the machine's cache keeps; its scout trims the cache to it at once."""
        keep = self.whole(keep, "keep")
        host_id = str(host_id or "").strip()
        result = self.scout_of(host_id).post("/api/llama-node/cache/keep", {"keep": keep}, timeout=60)
        return self.answer(host_id, result)

    def delete_foreign(self, host_id, expect_bytes):
        """Delete the files of the machine's cache folder that its scout did not download — only when their size is still the size the
        operator was shown (`expect_bytes`): the scout refuses with 409 otherwise, and nothing is deleted."""
        expect_bytes = self.whole(expect_bytes, "expectBytes")
        host_id = str(host_id or "").strip()
        result = self.scout_of(host_id).post("/api/llama-node/cache/delete-foreign", {"expectBytes": expect_bytes}, timeout=120)
        return self.answer(host_id, result)

    def answer(self, host_id, result):
        return {"ok": bool(result.get("ok", False)), "hostId": host_id, "result": result, "modelCache": self.refresh(host_id)}

    def refresh(self, host_id):
        """The machine's cache figures as its scout says them now, stored in its record; None when the scout would not say (the record
        keeps what its last report left)."""
        said = self.scout_of(host_id).read("/api/llama-node/cache")
        facts = ModelCacheFacts.clean(said) if said.get("ok") else None
        host = self.store()["hosts"].get(host_id)
        if facts is not None and host is not None:
            host["modelCache"] = facts
            self.save()
        return facts
