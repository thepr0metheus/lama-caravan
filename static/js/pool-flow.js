// Which of Routing's cables carry a request now (the owner, 2026-10-14: "keep how an active connection is shown,
// dashes or a drop — and carry it to Routing too"). The main board lights a cable by the monitor's rows
// (topologyItemsActivity, topology-activity.js): a request is "active" while it is served, and "recent" for 8 s after it
// ended. Routing's chain is longer — a client, its set, a pool, a row, a model — and a request names its own way down
// it: the port it came in by (a client's, or a pool's own), and the pool and the row that serve it (`cloudPoolId` and
// `poolStepId`, caravan/proxy/handler.py). The board's cables are named by those: client:<port>, set:<set>/<pool>,
// row:<pool>/<row> (pool-board.js, `data-pb-cable-key`). A rule of its own, with no page in it, so a value says what it reads.
export class PoolFlow {
  // How long a finished request still lights its way: the same 8 s the main board's cables keep (topologyItemsActivity).
  static RECENT_MS = 8000;

  // The cables lit by the monitor's `agents` ({<port>: {port, active: [...], recent: [...]}}) on a board that draws these
  // `clients` (each with its `port` and `set`) and `pools`, at `now` (ms). `active` is the cables a request runs through;
  // `recent` those one ran through a moment ago and none now. `signature` says whether the picture changed since the last one.
  static of(board, agents, now = Date.now()) {
    const { clients, pools } = board || {};
    const setOf = new Map();
    for (const client of clients || []) if (client?.set) setOf.set(Number(client.port), String(client.set));
    const poolIds = new Set((pools || []).map((pool) => String(pool.id)));
    const active = new Set();
    const recent = new Set();
    for (const row of Object.values(agents || {})) {
      for (const [items, keys, running] of [[row?.active, active, true], [row?.recent, recent, false]]) {
        for (const item of items || []) {
          // A queued request is not served yet; a finished one lights its way for RECENT_MS only — and one with no
          // finishing time has no age to measure, so it lights nothing: a way nobody knows the age of is not news.
          if (running ? item?.phase === "queued" : !(Number(item?.finishedAt || 0) * 1000 > now - PoolFlow.RECENT_MS)) continue;
          PoolFlow.way(item, Number(item?.port ?? row?.port), setOf, poolIds).forEach((key) => keys.add(key));
        }
      }
    }
    for (const key of active) recent.delete(key);
    return { active, recent, signature: `${[...active].sort().join("|")}~${[...recent].sort().join("|")}` };
  }

  // The cables one request goes through: its client's own (when the client has a set), the client's set to the pool that
  // serves it, and the pool's row that serves it. A request not served by a pool yet (no pool named on it) lights the
  // client's cable only; a pool the board does not draw lights nothing of it.
  static way(item, port, setOf, pools) {
    const keys = [];
    const set = setOf.get(port);
    if (set) keys.push(`client:${port}`);
    const pool = String(item?.cloudPoolId || "");
    if (!pool || !pools.has(pool)) return keys;
    if (set) keys.push(`set:${set}/${pool}`);
    const row = String(item?.poolStepId ?? "");
    if (row) keys.push(`row:${pool}/${row}`);
    return keys;
  }
}
