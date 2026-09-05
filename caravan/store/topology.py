"""The topology section: which cells exist, on which host, under which key.

A slot is stored under `"<hostId>:<port>"`, and that string is the whole
invariant. The controller answers to two spellings of its id — the machine name
it used to have and the role sentinel it has now — and a port arrives as text
from one caller and a number from another. A lookup that builds the key
differently from the write does not fail; it addresses a slot that is not there,
and the cell reads as having no config. That is why the key is built in ONE
place and every accessor here goes through it.

Fifty-two call sites reach into this document. The ones with an invariant are
the ones that build a slot key, so those are the ones with methods here; the
rest still take the raw section and will move as they are touched.
"""
from caravan.admin.paths import canonical_host_id


class TopologyStore:
    """A view onto the admin document's `topology` section.

    Holds no data of its own: it reads through to the AdminStore, so a caller
    holding this object and a caller holding the raw dict see the same thing.
    Saving is still the AdminStore's job — a view that wrote on its own would
    give the process two places that persist, and no way to order them.
    """

    def __init__(self, admin):
        self._admin = admin

    @property
    def data(self):
        """The section itself, seeded. What `topology_store()` has always returned."""
        return self._admin.topology()

    # ── addressing ───────────────────────────────────────────────────────────
    @staticmethod
    def slot_key(host_id, port):
        """The one spelling of a slot's key.

        Canonicalised here, at the single choke point every slot lookup and
        write goes through: a stale frontend still says the old machine name
        while a fresh one says the sentinel, and both must land on the same
        stored record.
        """
        return f"{canonical_host_id(host_id)}:{int(port)}"

    def _section(self, name):
        """A dict under `name`, guaranteed to BE a dict.

        setdefault alone is not enough: it only fills an ABSENT key, so a
        document where the value is null — hand-edited, or written by a version
        that stored something else there — hands the caller a None that fails
        three frames away from the cause. The old call sites wrote
        `.get(name) or {}`, which quietly worked around it every single time
        without ever repairing it. This repairs it once.
        """
        value = self.data.get(name)
        if not isinstance(value, dict):
            value = {}
            self.data[name] = value
        return value

    # ── slots ────────────────────────────────────────────────────────────────
    def slots(self):
        return self._section("serverSlots")

    def slot(self, host_id, port):
        """The slot for this host and port, or {} — never a KeyError.

        Empty rather than None because every caller immediately reads a field
        off it, and `(x or {}).get(...)` at forty call sites is forty chances
        to forget the `or {}`.
        """
        return self.slots().get(self.slot_key(host_id, port)) or {}

    def find_slot(self, host_id, port):
        """The slot, or None when there is none.

        The other half of `slot()`. A caller that RENDERS a cell wants `{}` and
        an empty card; a caller that is about to change something wants to
        refuse — "no server slot controller:22029" is an answer an operator can
        act on, where a silent write into an empty dict is a change that goes
        nowhere and reports success.
        """
        return self.slots().get(self.slot_key(host_id, port))

    def has_slot(self, host_id, port):
        return self.slot_key(host_id, port) in self.slots()

    def put_slot(self, host_id, port, slot):
        """Store a slot under its canonical key, and answer with that key."""
        key = self.slot_key(host_id, port)
        self.slots()[key] = slot
        return key

    def drop_slot(self, host_id, port):
        """Remove a slot; answer with what was there, or None."""
        return self.slots().pop(self.slot_key(host_id, port), None)

    # ── the other sections, by name rather than by string literal ────────────
    def clients(self):
        return self._section("clients")

    def assignments(self):
        return self._section("assignments")

    def aliases(self):
        return self._section("clientAliases")

    def deleted_agents(self):
        return self._section("deletedAgents")

    def power_schedules(self):
        return self._section("hostPowerSchedules")
