"""A model that is a folder, as a scout rebuilds it: file by file (GET /api/models/folder).

A safetensors checkpoint, a whisper or translate cache, a robot policy's checkpoint: these
models are folders, not one file. A scout takes a model through GET /api/models/download —
the one way it reaches the caravan's models, with no rights to the share they live on (the
owner, 2026-10-12) — and that route serves a file. A folder the scout could not take at all:
it refused with "a folder cannot be downloaded", and the cell did not start on any machine
but the one that held the folder already.

The listing names what the scout needs to rebuild the folder: each file with its size, taken
one by one through the download it already has, and each link inside the folder (a Hugging
Face cache's snapshots/ point at its blobs/), made again as the same link.
"""
import os
from pathlib import Path

from caravan.common.errors import AppError


class ModelFolder:
    """One folder under the models directory, listed for a scout.

    `models_dir` is the controller's models directory and `rel` the folder's path in it, as
    a cell's config names it. Nothing is read before listing() is asked.
    """

    #: Files a model folder may hold before the listing refuses: a checkpoint has tens, a
    #: Hugging Face cache hundreds. A folder of more is not a model, and walking it would
    #: hold the request.
    MAX_FILES = 5000
    #: Downloads still landing (caravan/admin/downloads.py, a scout's own .tmp): not part of
    #: the model yet, and a file that grows while it is fetched fails the fetch.
    PARTIAL = (".part", ".part.json", ".tmp")

    def __init__(self, models_dir, rel):
        self.models_dir = Path(models_dir)
        self.rel = str(rel or "").strip().strip("/")

    def root(self):
        """The folder, resolved; refused when the path is empty, leaves the models
        directory, or names no folder — the statuses the file download gives."""
        if not self.rel:
            raise AppError("path is required", 400)
        base = self.models_dir.resolve()
        root = (base / self.rel).resolve()
        try:
            root.relative_to(base)
        except ValueError:
            raise AppError("the path leaves the models directory", 403)
        if not root.is_dir():
            raise AppError(f"no model folder at {self.rel}", 404)
        return root

    def listing(self):
        """{path, files: [{path, size}], links: [{path, target}], size} — paths relative
        to the folder, sorted. A link that stays inside the folder is a link; one that
        leads elsewhere in the models directory is the file it leads to, since the
        download serves that file; one that leaves the models directory refuses the
        folder: the scout could rebuild it only with a hole."""
        root = self.root()
        base = self.models_dir.resolve()
        files, links = [], []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames.sort()
            here = Path(dirpath)
            names = sorted(filenames) + [d for d in dirnames if (here / d).is_symlink()]
            for name in names:
                path = here / name
                rel = path.relative_to(root).as_posix()
                if path.is_symlink():
                    target = os.readlink(path)
                    lands = (here / target).resolve()
                    if not os.path.isabs(target) and self._inside(lands, root):
                        links.append({"path": rel, "target": target})
                        continue
                    if not self._inside(lands, base) or not lands.is_file():
                        raise AppError(f"{self.rel}/{rel} links outside the models directory", 409)
                    files.append({"path": rel, "size": lands.stat().st_size})
                elif name.endswith(self.PARTIAL):
                    continue
                elif path.is_file():
                    files.append({"path": rel, "size": path.stat().st_size})
                if len(files) > self.MAX_FILES:
                    raise AppError(f"{self.rel} holds more than {self.MAX_FILES} files: not a model folder", 413)
            # A link to a folder is listed above and not walked into: os.walk does not follow it.
        return {"path": self.rel, "files": files, "links": links,
                "size": sum(f["size"] for f in files)}

    @staticmethod
    def _inside(path, root):
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False
