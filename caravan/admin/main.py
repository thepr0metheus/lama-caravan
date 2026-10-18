"""Admin server entry point: background threads + ThreadingHTTPServer."""
import os
import threading
from http.server import ThreadingHTTPServer

from caravan.admin.cell_schedule import start_scheduler_thread
from caravan.admin.monitoring import monitor_sampler_loop
from caravan.admin.gpu_driver import start_watch_thread as start_driver_watch
from caravan.admin.queue_thresholds import QUEUE_THRESHOLDS
from caravan.admin.paths import DATA_DIR, HOST, IS_CONTAINER, PORT, PROJECT_ROOT, validate_port_ranges
from caravan.admin.proxies_config import read_agent_proxy_payload, write_agent_proxy_payload
from caravan.admin.router_dsl import recompute_cloud_fallback_eligibility
from caravan.admin.routes import Handler
from caravan.common.container_preflight import ContainerPreflight
from caravan.admin.data_tree import DataTree


class _Server(ThreadingHTTPServer):
    """The admin listener, with an accept queue that fits one page load.

    socketserver's default `request_queue_size` is 5 — five connections may wait
    to be accepted, and the kernel drops the rest. Answering HTTP/1.0, this
    server gets ONE CONNECTION PER REQUEST, and a board load is ~46 static
    modules plus its API calls; a second browser doubles that into a queue five
    deep. Measured on the controller: `ss -ltn` showed Send-Q 5 while
    net.core.somaxconn was 4096, and TcpExtListenOverflows stood at 4166.

    An overflow is not a refusal you can see. With tcp_abort_on_overflow=0 the
    kernel silently drops the SYN, the client retries at 1s, 3s, 7s… and the
    page sits there — a 74-second load was measured from outside, and /health,
    being one cheap request, answered green throughout. That is why this went
    unnoticed: nothing logs it on our side.

    128 is generous for a handful of operators and still far under somaxconn,
    which is the real ceiling (listen(2) silently clamps to it).
    """
    request_queue_size = 128
    daemon_threads = True


def main():
    # A container states its time zone and its address, or it does not start:
    # it can guess neither, and both would go wrong without a word.
    ContainerPreflight().enforce("lama-caravan")
    # Same directory systemd's WorkingDirectory points at; keeps every relative
    # path (var/, logs/, git commands) working when launched by hand.
    os.chdir(PROJECT_ROOT)

    # A misconfigured port range corrupts state slowly (the allocator hands out
    # the controller's own port, listeners lose ephemeral bind races); a loud
    # early death is the cheap version of that lesson.
    validate_port_ranges()

    # Single-volume layout (container/dev): make sure the tree exists before
    # any writer needs it — or stop saying why it cannot (DataTree) — and
    # supervise the proxy as a child: the image has no systemd unit to run it
    # (see caravan/admin/proxy_supervisor.py).
    if DATA_DIR:
        DataTree(DATA_DIR).prepare("lama-caravan")
    if IS_CONTAINER:
        from caravan.admin import proxy_supervisor
        proxy_supervisor.start()

    # A pool's own port is gone (1.3.487): every client comes in through the
    # entry with its own key. A file that still has one loses it first, before
    # any other writer of the routes, and the log names each port closed
    # (caravan/admin/pool_ports.py); the proxy serves none meanwhile.
    try:
        from caravan.admin.pool_ports import PoolPortsRetired
        _closed = PoolPortsRetired().migrate()
        if _closed is not None:
            print("entry: pools' own ports closed, a client comes in through the entry with its key: "
                  + ", ".join(f":{c['port']} ({c['pool'] or 'no pool'})" for c in _closed), flush=True)
    except Exception as exc:
        print(f"entry: closing the pools' own ports skipped ({exc})", flush=True)
    # One-shot: write down the context-window choice blocks used to get by
    # accident (caravan/admin/cloud.py:migrate_context_auto).
    try:
        from caravan.admin.cloud import migrate_context_auto
        _stamped = migrate_context_auto()
        if _stamped:
            print(f"cloud: contextAuto stamped on {_stamped} blocks that relied on the provider's figure", flush=True)
    except Exception as exc:
        print(f"cloud: contextAuto migration skipped ({exc})", flush=True)
    # Pools of steps (caravan/admin/pools.py): a file of the old form — model
    # blocks, pools of subscriptions — is rewritten once; the proxy reads both
    # forms meanwhile, so it does not matter that it started first.
    try:
        from caravan.admin.pools import PoolDesk
        _pooled = PoolDesk().migrate()
        if _pooled is not None:
            print(f"cloud: model blocks became pools: {', '.join(_pooled['pools']) or 'none'}; "
                  f"dropped, unused: {len(_pooled['dropped'])}", flush=True)
    except Exception as exc:
        print(f"cloud: rewriting the model blocks as pools skipped ({exc})", flush=True)
    # The steps' own levels move onto their models, once (1.3.486): the proxy
    # reads both places meanwhile (caravan/common/model_levels.py).
    try:
        from caravan.admin.pools import PoolDesk
        _rows = PoolDesk().migrate_rows()
        if _rows is not None:
            print(f"cloud: levels of {_rows['steps']} step(s) moved onto {_rows['models']} model(s)", flush=True)
    except Exception as exc:
        print(f"cloud: moving the steps' levels onto their models skipped ({exc})", flush=True)
    # Routing's right column shows the models added to it (1.3.491): the ones
    # the pools' rows name are added once, so none in use leaves it.
    try:
        from caravan.admin.pools import PoolDesk
        _added = PoolDesk().migrate_added()
        if _added is not None:
            print(f"cloud: {_added['models']} model(s) the pools' rows name added to Routing", flush=True)
    except Exception as exc:
        print(f"cloud: adding the rows' models to Routing skipped ({exc})", flush=True)
    # The main board shows each cloud provider as a block of its accounts
    # (1.3.492): the providers of the accounts are put there once.
    try:
        from caravan.admin.board_providers import ProviderDesk
        _providers = ProviderDesk().migrate()
        if _providers is not None:
            print(f"cloud: providers put on the main board: {', '.join(_providers['providers']) or 'none'}", flush=True)
    except Exception as exc:
        print(f"cloud: putting the providers on the main board skipped ({exc})", flush=True)
    # A client of the entry calls one pool (1.3.486): a client of the old form —
    # the pools it might call — gets the first of them, once, after the pools
    # above exist; the proxy reads both forms meanwhile (caravan/common/entry_models.py).
    try:
        from caravan.admin.consumers import ConsumerDesk
        _cabled = ConsumerDesk().migrate()
        if _cabled is not None:
            print("entry: clients cabled to one pool: "
                  + ", ".join(f"{c['name']} → {c['pool'] or 'none'}" for c in _cabled), flush=True)
    except Exception as exc:
        print(f"entry: cabling the clients to one pool skipped ({exc})", flush=True)
    # A client of the entry calls a set of models (1.3.497): a client cabled to one
    # pool is cabled to a set of that pool instead, once, after the move above.
    try:
        from caravan.admin.model_sets import SetDesk
        _sets = SetDesk().migrate()
        if _sets is not None:
            print("entry: clients cabled to sets: "
                  + (", ".join(f"{c['name']} → {c['set'] or 'none'}" for c in _sets["clients"]) or "none"), flush=True)
    except Exception as exc:
        print(f"entry: cabling the clients to sets skipped ({exc})", flush=True)
    # The models folder is read now, in the background, not by the first page that asks: that page waited for every
    # header (51 s for the 56 models of the NAS, 2026-10-14, the owner's red "did not finish loading"). A page that
    # asks while this runs waits for this one walk (ModelList), not for a second.
    def _read_models_folder():
        try:
            from caravan.admin.models import MODEL_LIST
            MODEL_LIST.rows()
        except Exception as exc:
            print(f"models: reading the folder at start skipped ({exc})", flush=True)
    threading.Thread(target=_read_models_folder, daemon=True).start()
    sampler = threading.Thread(target=monitor_sampler_loop, daemon=True)
    sampler.start()

    # Bootstrap ↑☁ cloud-fallback eligibility from current connections (one-shot).
    def _bootstrap_cloud_fallback():
        try:
            payload = read_agent_proxy_payload()
            routes = payload.get("routes") if isinstance(payload, dict) else None
            if isinstance(routes, list):
                before = [(r.get("cloudFallbackEligible"), r.get("cloudFallbackProviderId")) for r in routes if isinstance(r, dict)]
                recompute_cloud_fallback_eligibility(routes)
                after = [(r.get("cloudFallbackEligible"), r.get("cloudFallbackProviderId")) for r in routes if isinstance(r, dict)]
                if before != after:
                    write_agent_proxy_payload(payload)
        except Exception:
            pass
    threading.Thread(target=_bootstrap_cloud_fallback, daemon=True).start()

    # Queue thresholds: once on startup, then every 6 hours.
    threading.Thread(target=QUEUE_THRESHOLDS.compute, daemon=True).start()
    threading.Thread(target=QUEUE_THRESHOLDS.refresh_forever, daemon=True).start()
    # Driver watch: stays silent while both checkboxes are off (see gpu_driver.py).
    start_driver_watch()
    # Schedules: cell start/stop windows, the planned host shutdown, and the
    # daily model check — ONE tick per minute drives all three. The model
    # check used to have its own thread, sleeping a full day from service
    # start; across deploys it never once lived to the end of that sleep (see
    # model_watch.model_watch_tick).
    start_scheduler_thread()
    # A model move a restart interrupted continues from the point the library
    # confirmed (caravan/admin/store_moves.py). Nothing was deleted before the
    # proof, so there is nothing to repair — only to finish.
    try:
        from caravan.admin.store_moves import runner as store_moves
        store_moves().resume()
    except Exception as exc:
        print(f"store moves: resume skipped ({exc})", flush=True)

    server = _Server((HOST, PORT), Handler)
    print(f"lama-caravan listening on http://{HOST}:{PORT}")
    server.serve_forever()
