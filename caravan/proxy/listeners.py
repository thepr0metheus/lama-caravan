"""Per-route listener lifecycle: bind/unbind one ThreadingHTTPServer per
enabled route and watch agent-proxies.json for changes every ~2s.
_pending_rebind is rebound here — keep its writers in this module."""
import threading
import time
from http.server import ThreadingHTTPServer

from caravan.proxy.config import load_enabled_routes
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

def _start_listener(route):
    """Bind a listen socket for one route and serve it in a daemon thread.
    Returns the server, or None if the bind failed (e.g. the port is in use)."""
    port = route["port"]
    try:
        server = ThreadingHTTPServer((HOST, port), ProxyHandler)
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

def reconcile_listeners():
    """Open/close listen sockets to match the enabled routes, so the Kanban graph
    can add or remove a client without restarting the proxy. Routing changes for a
    port that stays are already picked up live via live_route_for_port()."""
    global _pending_rebind
    routes = load_enabled_routes()
    desired = {route["port"]: route for route in routes}
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
    _pending_rebind = failed
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
