"""One address for every consumer, a key each (visumap caravan-single-entry)."""
import hmac
import re


class KeyEntry:
    """The one door the consumers share, and how a key finds its agent's route.

    Each agent had its own port, and the port was its name: a new consumer was a
    new port, a firewall rule and an address in its config. The entry is one
    port behind the DSM proxy (caravan-api.example.org). A consumer's own key —
    the one its route already carries as `apiKey` — names its route, and from
    there the request is that route's, as if it had come to the port: the same
    window, model name, priority, queue and journal. The owner chose keys only
    (2026-10-07): no key, no way in; and a migrated agent's port is closed at
    once (`portClosed`), its key still finds it here.

    The proxy and the board read the entry the same way, from here: the proxy
    to find the route, the board to refuse a key two routes would share.
    """

    PORT_MIN, PORT_MAX = 1024, 65535
    URL_RE = re.compile(r"^https?://[A-Za-z0-9.\-]+(:\d{1,5})?(/[\w\-./]*)?$")
    #: Routing's test of a client (caravan/admin/proxy_entry.py AsConsumer) carries this header
    #: and is journaled under PROBE_CLIENT: its answers are the test's, and the client's list of
    #: errors (caravan/admin/client_misses.py) leaves them out. Heard only from this machine itself.
    PROBE_HEADER = "X-Caravan-Probe"
    PROBE_CLIENT = "routing-probe"
    #: What the journal's rows from before 1.3.582 call it (the page was named after the kanban then). The journal keeps 30 days, so those rows are
    #: still read as the test's until 2026-11-18, and this line can go then.
    PROBE_CLIENT_BEFORE_1_3_582 = "kanban-probe"
    PROBE_CLIENTS = (PROBE_CLIENT, PROBE_CLIENT_BEFORE_1_3_582)

    @classmethod
    def clean(cls, raw):
        """The entry as the config keeps it: {"port": n, "publicUrl": …} or {} when off."""
        if not isinstance(raw, dict):
            return {}
        try:
            port = int(raw.get("port") or 0)
        except (TypeError, ValueError):
            return {}
        if not cls.PORT_MIN <= port <= cls.PORT_MAX:
            return {}
        url = str(raw.get("publicUrl") or "").strip()[:200]
        return {"port": port, **({"publicUrl": url} if cls.URL_RE.match(url) else {})}

    @staticmethod
    def presented_key(headers):
        """The key a request carries: `Authorization: Bearer …`, else `x-api-key`; "" for none."""
        if headers is None:
            return ""
        auth = str(headers.get("Authorization") or "")
        if auth.startswith("Bearer "):
            return auth[7:].strip()
        return str(headers.get("x-api-key") or "").strip()

    @staticmethod
    def tail(key):
        """What anything outside the controller is shown of a key: its last four characters,
        "" for none. The whole key is answered once, when it is made (caravan/admin/consumers.py)."""
        key = str(key or "")
        return key[-4:] if key else ""

    @staticmethod
    def public_route(route):
        """A route as it may leave the controller: its key replaced by `keyTail`."""
        out = {name: value for name, value in (route or {}).items() if name != "apiKey"}
        out["keyTail"] = KeyEntry.tail((route or {}).get("apiKey"))
        return out

    @staticmethod
    def same(left, right):
        """Constant-time equality of two keys, any characters (compare_digest takes bytes)."""
        return hmac.compare_digest(str(left).encode("utf-8"), str(right).encode("utf-8"))

    @classmethod
    def route_for(cls, key, routes):
        """(the enabled route this key names, why there is none): "no-key",
        "unknown-key", or "ambiguous-key" when two routes carry it."""
        if not key:
            return None, "no-key"
        found = [route for route in routes or [] if isinstance(route, dict) and route.get("enabled", True)
                 and route.get("apiKey") and cls.same(route["apiKey"], key)]
        if not found:
            return None, "unknown-key"
        if len(found) > 1:
            return None, "ambiguous-key"
        return found[0], ""

    @staticmethod
    def shared_keys(routes):
        """{key: [port, …]} for every key more than one route carries."""
        ports = {}
        for route in routes or []:
            key = str((route or {}).get("apiKey") or "").strip()
            if key:
                ports.setdefault(key, []).append(int(route.get("port") or 0))
        return {key: sorted(found) for key, found in ports.items() if len(found) > 1}
