"""Persistent admin panel state (admin.json) — now an AdminStore behind a facade.

`admin_state` is the store's own dict, not a copy: seventeen modules import this
name and mutate it in place, and that identity is the contract. Never rebind it
— see caravan/store/base.py for what the rebinding costs.

The module-level names stay because the callers are still written in terms of
them; each one is a one-line delegation, and they move to the store's methods a
caller at a time.
"""
from caravan.admin.paths import ADMIN_STATE_FILE
from caravan.store.admin import AdminStore
from caravan.store.topology import TopologyStore

store = AdminStore(ADMIN_STATE_FILE)

#: The topology section with its addressing. `topology_store()` below still
#: hands out the raw dict — forty callers read sections straight off it — while
#: the ones that build a slot key go through this object instead.
topology = TopologyStore(store)

#: The live document. THE SAME OBJECT the store holds — mutating this mutates
#: the store, which is exactly what every caller expects.
admin_state = store.data


def load_admin_state():
    """The file's contents, RAW: no defaults seeded, no migration.

    Deliberately not the store's own data. Its one caller is the settings
    import, which wants what the just-restored file says so it can refill the
    live document with it.
    """
    return store.read()


def save_admin_state():
    store.save()


def topology_store():
    """The raw topology section, as it has always been returned."""
    return store.topology()
