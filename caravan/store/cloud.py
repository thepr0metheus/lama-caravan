"""Two documents with opposite jobs: what the cloud accounts ARE, and their keys.

`cloud-providers.json` is configuration — accounts and the blocks that point at
them — read on every topology build. `provider-secrets.json` holds the API keys,
lives at mode 0600, and nothing that reaches a browser may carry its contents:
the account list says whether a credential exists and shows four characters of
it, never the key.

BOTH are cached on the file's own (mtime, size), and that is load-bearing rather
than tidy. Reading them was treated as free: the credential summary reads the
accounts once per lookup and the block list calls that once per block, so 502
blocks meant ~500 re-parses of a 99 KB file for ONE request — ~100 MB of parsing,
profiled at 287 ms of a 732 ms build. Every parse holds the GIL, so eight tabs
polling did not run eight builds in parallel; they queued behind each other's
parsing. That is what an outside measurement saw as time-to-first-byte rising
from 750 ms to 4.5 s while the bytes themselves still arrived in 30 ms.

The other half of that trade is invalidation. The key is (mtime, size), not a
timer and not forever: an operator who rotates a key through the UI, or edits the
file by hand, is served the new one on the very next call. A cache that missed
that would have the caravan authenticating with a key its owner had revoked.
"""
import json

from caravan.common.fsio import atomic_write_text
from caravan.store.base import keep_unreadable


class CachedJsonStore:
    """A JSON document re-read only when the file itself changes.

    Not a subclass of store.base.Store: that one loads once and holds a document
    the process mutates in place. These two are read-through — the proxy writes
    secrets, the panel writes accounts, and each must see the other's work — so
    what is kept is a parse, keyed by the file generation that produced it.
    """

    def __init__(self, path):
        self.path = path
        #: One generation only. The key changes on every save, so an unbounded
        #: dict would grow an entry per edit for the life of the process.
        self._cache = {}

    def _key(self):
        try:
            st = self.path.stat()
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def _cached(self, key, value):
        if key is not None:
            self._cache.clear()
            self._cache[key] = value
        return value

    def read(self, parse=None):
        """The parsed document, or **None** when there is nothing usable.

        None rather than a caller-supplied empty value: an empty dict shared
        across calls is a mutable default that any caller can corrupt for every
        other one, and a sentinel that gets normalised on the way in ("empty if
        empty is not None else {}") turns the very case it exists for back into
        the thing it was distinguishing from. The caller says what absence means
        for its own document — they do not agree: one wants
        {"accounts": [], "blocks": []}, the other wants {}.

        `parse` gets the raw object and returns what to store; it runs only on a
        cache miss, so a caller may do real work there.
        """
        if not self.path.exists():
            return None
        key = self._key()
        if key is not None:
            hit = self._cache.get(key)
            if hit is not None:
                return hit
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            # A file we cannot parse is not a reason to fail the page that asked.
            # It IS a reason not to cache: the next call re-reads, so a file
            # being written right now is picked up as soon as it is whole.
            #
            # And a reason to keep a copy. These two documents are the cloud
            # accounts and their API KEYS; unreadable, they read as "no accounts,
            # no keys", and the operator's next edit writes that emptiness over
            # the file. ProxyStore made this choice in the same phase and this
            # store did not — the asymmetry was the bug, not the policy.
            keep_unreadable(self.path)
            return None
        return self._cached(key, parse(raw) if parse else raw)

    def write(self, payload, chmod=None):
        atomic_write_text(self.path,
                          json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                          **({"chmod": chmod, "mkdir": True} if chmod else {}))
