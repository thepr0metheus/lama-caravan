"""One persisted document: loaded once, mutated in place, written atomically.

THE identity rule. A store's `data` is created at load and never rebound. Not a
style preference — seventeen modules hold a reference to the admin document, and
the settings-import path refills it with clear()/update() precisely because
rebinding would leave the rest of the process reading the settings it had just
replaced. `refill()` is that operation, named, so the next caller does not have
to rediscover why the obvious `self.data = fresh` is wrong.

A store that cannot read its file loads EMPTY rather than raising. A corrupt
admin.json must not stop the panel from starting: an operator who can open the
board can fix the file, and one who cannot open it has nothing to fix it with.
"""
import datetime
import json
import shutil

from caravan.common.fsio import atomic_write_text


def keep_unreadable(path):
    """Copy a file we cannot USE aside, once, before anything overwrites it.

    "Cannot use" is wider than "cannot parse": a document that is valid JSON but
    the wrong shape — `null`, a list, a string — is just as unusable, and the
    first branch to notice it used to return the empty default and let the next
    write replace the file. Whatever an operator could have recovered by hand
    went with it.

    Once, not once per read: a caravan that keeps failing on the same file must
    not fill the directory with copies of it. Failures here are swallowed on
    purpose — this is a net around a read, and a net that can refuse the read is
    worse than no net.

    THE COPY IS AS SENSITIVE AS THE ORIGINAL, so it is made with shutil.copy2,
    which carries the source's permission bits across. One of these documents is
    provider-secrets.json: it holds the cloud API keys and is deliberately kept
    at 0600. Path.write_bytes creates with the default umask instead — 0644 — so
    the first unreadable secrets file left every key in a world-readable sibling,
    silently, and forever, because nothing here ever cleans up.
    """
    try:
        if any(path.parent.glob(f"{path.stem}.json.unreadable-*")):
            return
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(path, path.with_name(f"{path.stem}.json.unreadable-{stamp}"))
    except Exception:  # noqa: BLE001
        pass


class Store:
    """A document on disk. Subclasses say where it lives and what it defaults to."""

    def __init__(self, path):
        self.path = path
        self.data = self.read()
        self.seed()
        self.migrate()

    # ── what a subclass says ─────────────────────────────────────────────────
    def seed(self):
        """Fill in whatever the document does not have yet. In place, and never
        over a value that is already there."""

    def migrate(self):
        """One-time repairs of an older layout. Must be idempotent: it runs on
        every start, and a store that has already been migrated has nothing left
        to match."""

    # ── the parts every store shares ─────────────────────────────────────────
    def read(self):
        """The file's contents, or {} — for a missing file AND for an unreadable
        one. See the module docstring: a corrupt document is a bad start, not a
        dead process."""
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text())
        except Exception:  # noqa: BLE001
            return {}

    def save(self):
        atomic_write_text(self.path, self.serialize(), mkdir=True)

    def serialize(self):
        """indent=2 because this file is read and hand-edited during incidents."""
        return json.dumps(self.data, indent=2)

    def refill(self, fresh):
        """Replace every value, KEEP the object. The one safe way to swap the
        contents while other modules hold a reference — which they all do."""
        self.data.clear()
        self.data.update(fresh or {})

    def reload(self):
        """Re-read the file into the same object."""
        self.refill(self.read())
        self.seed()

    # ── convenience the subclasses use for seeding ───────────────────────────
    def section(self, name, *keys):
        """A dict under `name`, guaranteed to exist and to have `keys`."""
        self.data.setdefault(name, {})
        for key in keys:
            self.data[name].setdefault(key, {})
        return self.data[name]
