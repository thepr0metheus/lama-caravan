"""Proxy daemon entry point: stop-request watcher + per-route listeners."""
import threading
import time

from caravan.proxy.listeners import listener_watcher, reconcile_listeners
from caravan.proxy.paths import STATE_FILE
from caravan.proxy.queue_admission import stop_request_watcher


def main():
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    watcher = threading.Thread(target=stop_request_watcher, daemon=True)
    watcher.start()
    # Bind the current config's ports, then keep the listen set in sync as the
    # Kanban graph adds/removes clients — no proxy restart needed.
    reconcile_listeners()
    threading.Thread(target=listener_watcher, daemon=True).start()
    while True:
        time.sleep(3600)
