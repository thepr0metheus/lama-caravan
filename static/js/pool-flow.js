// Which of Routing's cables carry a request now (the owner, 2026-10-14: "keep how an active connection is shown,
// dashes or a drop — and carry it to Routing too"). The main board lights a cable by the monitor's rows
// (topologyItemsActivity, topology-activity.js): a request is "active" while it is served, and "recent" for 8 s after it
// ended. Routing's chain since 1.3.675 (the owner, 2026-10-27, option В2): a client, the pool it named, a row, a model — or, for a
// model a client calls straight, the client, its «Напрямую» row and the model. A request names its own way: the port it came in
// by (its client's), and the pool and the row that serve it (`cloudPoolId` and `poolStepId`, rust/crates/proxy/src/exchange/mod.rs) — a model
// called straight is its pool of one row, `live:…` (rust/crates/rules/src/entry_models.rs, LiveModels). The board's cables are named by
// those: client:<port>/<pool>, row:<pool>/<row>, direct:<pool> (pool-board.js, `data-pb-cable-key`). A rule of its own, with no
// page in it, so a value says what it reads.
export class PoolFlow {
  // How long a finished request still lights its way: the same 8 s the main board's cables keep (topologyItemsActivity).
  static RECENT_MS = 8000;

  // The cables lit by the monitor's `agents` ({<port>: {port, active: [...], recent: [...]}}) on a board that draws these `pools`,
  // at `now` (ms). `active` is the cables a request runs through; `recent` those one ran through a moment ago and none now; `direct`
  // the models called straight, by their pool of one row — [{port, active}], each client once, active when one of its requests
  // runs. `signature` says whether the picture changed since the last one.
  static of(board, agents, now = Date.now()) {
    const poolIds = new Set((board?.pools || []).map((pool) => String(pool.id)));
    const active = new Set();
    const recent = new Set();
    const direct = new Map();
    for (const row of Object.values(agents || {})) {
      for (const [items, keys, running] of [[row?.active, active, true], [row?.recent, recent, false]]) {
        for (const item of items || []) {
          // A queued request is not served yet; a finished one lights its way for RECENT_MS only — and one with no
          // finishing time has no age to measure, so it lights nothing: a way nobody knows the age of is not news.
          if (running ? item?.phase === "queued" : !(Number(item?.finishedAt || 0) * 1000 > now - PoolFlow.RECENT_MS)) continue;
          const port = Number(item?.port ?? row?.port);
          PoolFlow.way(item, port, poolIds).forEach((key) => keys.add(key));
          const pool = String(item?.cloudPoolId || "");
          if (!pool.startsWith("live:") || !port) continue;
          if (!direct.has(pool)) direct.set(pool, []);
          const ways = direct.get(pool);
          const was = ways.find((way) => way.port === port);
          if (was) was.active = was.active || running; else ways.push({ port, active: running });
        }
      }
    }
    for (const key of active) recent.delete(key);
    return { active, recent, direct, signature: `${[...active].sort().join("|")}~${[...recent].sort().join("|")}` };
  }

  // The cables one request goes through: its client's to the pool that serves it — or to its «Напрямую» row, for a model called
  // straight — and the pool's row that serves it, or the «Напрямую» row's on to its model. A request not served by a pool yet
  // lights nothing: where it goes is not known yet; a pool the board does not draw lights nothing either.
  static way(item, port, pools) {
    const pool = String(item?.cloudPoolId || "");
    if (!pool || !port) return [];
    if (pool.startsWith("live:")) return [`client:${port}/${pool}`, `direct:${pool}`];
    if (!pools.has(pool)) return [];
    const keys = [`client:${port}/${pool}`];
    const row = String(item?.poolStepId ?? "");
    if (row) keys.push(`row:${pool}/${row}`);
    return keys;
  }
}
