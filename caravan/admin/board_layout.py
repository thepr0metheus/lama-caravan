"""The order of the board's model-server cards: machines and cloud providers in one list.

Under Model servers the board drew its machines first and its cloud providers after
them, always — two lanes, one above the other. The operator could not put the
subscription pool above a machine, or a machine between two providers (2026-10-04).
The order is the operator's, and it is kept here, in the admin document's
`topology.layout` section — seeded since the first board and empty until now — so
every browser and every account that opens the board sees the same one, and the
kanban's Servers panel follows it.

What is kept is a list of card keys, `node:<machine id>` and `cloud:<account id>`,
with a revision that grows by one on every save. The board places the cards it has
by the list and puts the ones the list does not name after them, in the order it drew
them before (the rule lives once, in static/js/server-order.js). A key whose card is
gone stays until the next save: it names nothing and costs nothing. The revision is
how a page tells a poll that left before its own save from a newer order: a reading
older than the last answer it got is not allowed to put the old order back.
"""
from caravan.admin.state import save_admin_state, topology_store
from caravan.common.errors import AppError


class ServerOrder:
    """The stored order of the Model servers cards, and the one way to change it."""

    #: The kinds of card: a machine (its node) and a cloud provider or pool (its account).
    KINDS = ("node", "cloud")
    #: Keys in one order. A fleet has a few dozen cards; a list longer than this is no board's.
    LIMIT = 500
    #: Characters in one key: a machine or account id is a short slug.
    KEY_LIMIT = 200

    def __init__(self, section=topology_store, save=save_admin_state):
        self._section = section
        self._save = save

    def _layout(self):
        """The layout section to read: an empty one when the document has none. Reading writes nothing."""
        layout = self._section().get("layout")
        return layout if isinstance(layout, dict) else {}

    def _layout_to_write(self):
        """The layout section to write into, made a section when the document holds something else."""
        topo = self._section()
        if not isinstance(topo.get("layout"), dict):
            topo["layout"] = {}
        return topo["layout"]

    @classmethod
    def is_key(cls, value):
        """Whether `value` is a card key: a kind, a colon, an id; one line, of a sane length."""
        if not isinstance(value, str) or not value or len(value) > cls.KEY_LIMIT:
            return False
        kind, sep, ident = value.partition(":")
        return bool(sep) and kind in cls.KINDS and bool(ident.strip()) and value.isprintable()

    def keys(self):
        """The stored order as the board is handed it: the well-formed keys, once each, in order.

        Only `save` writes the list, and it refuses anything else; a document edited by
        hand can still hold something else under the name. What cannot be read is no
        order at all — the board then draws its own — never a guess at one."""
        stored = self._layout().get("serverOrder")
        if not isinstance(stored, list):
            return []
        seen, keys = set(), []
        for key in stored:
            if self.is_key(key) and key not in seen:
                seen.add(key)
                keys.append(key)
        return keys

    def revision(self):
        """How many times the order was saved: 0 while it never was."""
        rev = self._layout().get("serverOrderRev")
        return rev if isinstance(rev, int) and not isinstance(rev, bool) and rev >= 0 else 0

    def layout(self):
        """What the topology payload carries under `layout`."""
        return {"serverOrder": self.keys(), "serverOrderRev": self.revision()}

    def save(self, order):
        """Store `order` whole, after checking it whole, and answer what is stored now.

        A list with one bad key is refused, not trimmed into a shorter one: the board
        sends every card it shows, and a list it did not mean would move cards the
        operator never touched. An empty list returns the board to its own order."""
        if not isinstance(order, list):
            raise AppError("order must be a list of card keys", 400)
        if len(order) > self.LIMIT:
            raise AppError(f"order holds {len(order)} keys; at most {self.LIMIT}", 400)
        seen = set()
        for at, key in enumerate(order):
            if not self.is_key(key):
                raise AppError(f"order[{at}] is not a card key (node:<machine id> or cloud:<account id>): {str(key)[:80]!r}", 400)
            if key in seen:
                raise AppError(f"order lists {key} twice", 400)
            seen.add(key)
        rev = self.revision() + 1
        layout = self._layout_to_write()
        layout["serverOrder"] = list(order)
        layout["serverOrderRev"] = rev
        self._save()
        return {"ok": True, "order": self.keys(), "rev": self.revision()}


SERVER_ORDER = ServerOrder()
