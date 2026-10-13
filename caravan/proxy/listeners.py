"""Per-route listener lifecycle: bind/unbind one ThreadingHTTPServer per
enabled route and watch agent-proxies.json for changes every ~2s.
_pending_rebind is rebound here — keep its writers in this module."""
import threading
import time
from http.server import ThreadingHTTPServer

from caravan.proxy.config import current_config, load_enabled_routes
from caravan.proxy.entry import EntryHandler
from caravan.proxy.handler import ProxyHandler
from caravan.proxy.paths import CONFIG_FILE, HOST
from caravan.proxy.state import sync_agents_state, write_state


# Live listen-socket registry: port -> ThreadingHTTPServer. Reconciled against the
# config so adding/removing a client in the Kanban graph opens/closes its port
# without restarting the proxy. _pending_rebind retries a port whose bind failed
# (e.g. transiently still in use) on the next watcher tick.
serving = {}

serving_lock = threading.Lock()

_pending_rebind = False


class _RouteServer(ThreadingHTTPServer):
    """A route's listener, with an accept queue that fits a burst of agents.

    Same reason as the admin server (caravan/admin/main.py): socketserver
    defaults `request_queue_size` to 5, and a queue that shallow drops
    connections silently — tcp_abort_on_overflow=0 turns an overflow into a
    dropped SYN and a client that retries at 1s, 3s, 7s. On a proxy port that
    reads as an agent hanging, with nothing in our logs to say why.

    It matters more here than on the board: several agents can call one route at
    once, and llama-server itself listens with a backlog of 512 — this is the
    one hop in the chain that was five deep.
    """
    request_queue_size = 128
    daemon_threads = True


def _start_listener(route):
    """Bind a listen socket for one route and serve it in a daemon thread.
    Returns the server, or None if the bind failed (e.g. the port is in use)."""
    port = route["port"]
    try:
        server = _RouteServer((HOST, port), ProxyHandler)
    except OSError as exc:
        print(f"agent-proxy: cannot bind {route['label']} on {HOST}:{port}: {exc}", flush=True)
        return None
    server.route = route
    threading.Thread(target=server.serve_forever, name=f"proxy-{port}", daemon=True).start()
    print(
        f"{route['label']} proxy listening on {HOST}:{port} -> {route['upstreamHost']}:{route['upstreamPort']}",
        flush=True,
    )
    return server

def _stop_listener(server, port):
    """Shut a listener down. Runs off the reconcile thread because shutdown()
    joins the serve_forever loop and must not run on the server's own thread."""
    try:
        server.shutdown()
        server.server_close()
    except Exception:
        pass
    print(f"agent-proxy: stopped listener on {HOST}:{port}", flush=True)

class EntryListener:
    """The entry's listener (caravan/proxy/entry.py): started, moved or stopped
    as the config's `entry` says — the board sets it, nothing restarts."""

    def __init__(self):
        self.server = None
        self.port = 0

    def reconcile(self, entry, route_ports):
        """Bring the listener in line with `entry` ({} = off). False when its
        port could not be bound, so the watcher tries again on its next tick."""
        port = int((entry or {}).get("port") or 0)
        if port and port in route_ports:
            # The board refuses this; the file can be edited by hand. A route
            # that listens there keeps its port, and the entry waits.
            print(f"agent-proxy: entry port {port} is a route's port — the entry stays closed", flush=True)
            port = 0
        if port == self.port and (self.server is not None or not port):
            return True
        if self.server is not None:
            threading.Thread(target=_stop_listener, args=(self.server, self.port), daemon=True).start()
            self.server, self.port = None, 0
        if not port:
            return True
        try:
            server = _RouteServer((HOST, port), EntryHandler)
        except OSError as exc:
            print(f"agent-proxy: cannot bind the entry on {HOST}:{port}: {exc}", flush=True)
            return False
        server.route = None
        threading.Thread(target=server.serve_forever, name="proxy-entry", daemon=True).start()
        self.server, self.port = server, port
        print(f"agent-proxy: entry listening on {HOST}:{port} — a key names the route", flush=True)
        return True


entry_listener = EntryListener()


def reconcile_listeners():
    """Open/close listen sockets to match the enabled routes, so the Kanban graph
    can add or remove a client without restarting the proxy. Routing changes for a
    port that stays are already picked up live via live_route_for_port(). A route
    whose port is closed is served by the entry only, by its key."""
    global _pending_rebind
    routes = load_enabled_routes()
    desired = {route["port"]: route for route in routes if not route.get("portClosed")}
    failed = False
    with serving_lock:
        for port in list(serving):
            if port not in desired:
                server = serving.pop(port)
                threading.Thread(target=_stop_listener, args=(server, port), daemon=True).start()
        for port, route in desired.items():
            server = serving.get(port)
            if server is None:
                server = _start_listener(route)
                if server is None:
                    failed = True
                else:
                    serving[port] = server
            else:
                server.route = route  # refresh the fallback route object
    entry_ok = entry_listener.reconcile(current_config().get("entry"), set(desired))
    _pending_rebind = failed or not entry_ok
    sync_agents_state(routes)
    write_state()

def listener_watcher():
    """Re-run reconcile_listeners whenever agent-proxies.json changes, and retry
    any port whose bind failed on the previous pass."""
    last_mtime = None
    first = True
    while True:
        try:
            mtime = CONFIG_FILE.stat().st_mtime
        except OSError:
            mtime = None
        if first or mtime != last_mtime or _pending_rebind:
            first = False
            last_mtime = mtime
            try:
                reconcile_listeners()
            except Exception as exc:
                print(f"agent-proxy: listener reconcile failed: {exc}", flush=True)
        time.sleep(2)
