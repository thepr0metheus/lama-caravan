"""Proxy daemon entry point: stop-request watcher + per-route listeners."""
import threading
import time

from caravan.common.container_preflight import ContainerPreflight
from caravan.proxy.listeners import listener_watcher, reconcile_listeners
from caravan.proxy.output_probe import start_probe_thread
from caravan.proxy.paths import STATE_FILE
from caravan.proxy.queue_admission import stop_request_watcher
from caravan.proxy.runtime import state
from caravan.proxy.started import StartRecord


def main():
    # The router's schedule rules read the clock: in a container the zone must
    # be stated (caravan/common/container_preflight.py). The address is the
    # controller's business, not the proxy's.
    ContainerPreflight().enforce("agent-proxies", address=False)
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Which code this process runs, said before the first state write: a
    # deploy asks the proxy instead of assuming (caravan/proxy/started.py).
    state.update(StartRecord.at_start().as_state())
    watcher = threading.Thread(target=stop_request_watcher, daemon=True)
    watcher.start()
    # Bind the current config's ports, then keep the listen set in sync as the
    # Kanban graph adds/removes clients — no proxy restart needed.
    reconcile_listeners()
    threading.Thread(target=listener_watcher, daemon=True).start()
    # Backup exits are asked whether they are alive while idle, so a dead main
    # is skipped before the next request pays for finding out.
    start_probe_thread()
    while True:
        time.sleep(3600)
