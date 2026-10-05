// The cell behind each local row of the kanban's Servers panel, and what the row says of it
// (2026-10-04: the operator's points 2, 6 and 7 after a look at the live kanban).
//
// A row said only the traffic: one grey dot, "idle", for a cell that serves and for one that
// is not running at all — 24 of the 30 rows on the live kanban were stopped and looked exactly
// like the 6 that ran (absence drawn as normality), and the cables into two stopped cells
// looked live. Its name was the output's own label, which the server makes from the model
// file: a moonshine cell read "en", and two cells of one model on one machine read the same.
// And the stopped cells nothing leads to filled two screens of the panel.
//
// The cell is found the way the panel names its machine — machineAt(the output's address) is
// the node — and then by its port; an engine's model by its machine and its engine. The state
// is the record's own word. A record the board does not have, or a word this table does not
// know, is "unknown": never stopped, never idle.
import { JOB_MARKS } from "./model-jobs.js";
import { parseModelName } from "./model-meta.js";
import { cellJobs, cellRunnerId, machineAt } from "./topology-nodes.js";

export class OutputCells {
  // A cell's phase → what its row says. Only "running" serves.
  static PHASES = {
    running: "running",
    stopped: "stopped", reserved: "stopped",
    starting: "starting", loading: "starting", warming: "starting", downloading: "starting",
    stopping: "stopping",
    error: "failed", broken: "failed",
  };
  // An engine's state (caravan/domain/engine.py) → the same words. A model of a running engine
  // is served: the engine loads it on the first request.
  static ENGINE = { ok: "running", stopped: "stopped", auth: "failed", unreachable: "failed" };
  // The word a row says beside its name (i18n keys). A running row says none — its dot speaks.
  static WORDS = { stopped: "stopped", starting: "starting", stopping: "rtCellStopping", failed: "failed", unknown: "unknown" };
  // Settings whose values never go on a row: they may carry a key or a token. A twin that
  // differs there is said to differ by the setting's name alone.
  static SECRET = /KEY|TOKEN|SECRET|PASS|AUTH|CRED|ENV|ARGS|COMMAND|CMD/i;
  // Settings that differ between any two cells by nature, so they tell no twin from another.
  static OWN = new Set(["PORT"]);

  constructor(topology, router = {}) {
    this.nodes = topology?.nodes || [];
    this.router = router || {};
  }

  // The machine an output stands on: an engine's model says its machine, a cell its address.
  nodeAt(out) {
    const key = String(out.upstreamType || "") === "engine"
      ? String(out.hostId || "") : String(machineAt(out.upstreamHost || "127.0.0.1").key);
    return this.nodes.find((n) => String(n.id) === key) || null;
  }

  // The record of the cell behind a local output; null when the board has none.
  cellOf(out) {
    return (this.nodeAt(out)?.servers || []).find((s) => Number(s.port) === Number(out.upstreamPort)) || null;
  }

  // running | stopped | starting | stopping | failed | unknown for a local output, "" for a
  // cloud one — no machine of the fleet serves it, and its own card says how it is.
  state(out) {
    const type = String(out.upstreamType || "llama");
    if (type === "cloud") return "";
    if (type === "engine") {
      const engine = (this.nodeAt(out)?.engines || []).find((e) => String(e?.kind || "") === String(out.engine || ""));
      return OutputCells.ENGINE[String(engine?.state || "")] || "unknown";
    }
    const cell = this.cellOf(out);
    return OutputCells.PHASES[String(cell?.phase || cell?.status?.phase || "")] || "unknown";
  }

  // What a row calls a cell: the server's own short phrase for what the cell runs
  // (cell_artifact_label — "moonshine en", "run_tts.sh xtts"), else the model's short name as
  // the cell card says it, else the output's label without its port.
  name(out) {
    const cell = this.cellOf(out);
    const own = String(cell?.cellLabel || "").trim() || parseModelName(cell?.model)?.label || "";
    return own || String(out.label || "").replace(/\s*:\d+\s*$/, "").trim();
  }

  // What the cell does, as marks — the list the cell card's job chips draw (cellJobs). A cell
  // whose job cannot be named has none.
  marks(out) {
    const cell = this.cellOf(out);
    if (!cell) return "";
    const cfg = cell.slotConfig || {};
    return cellJobs(cellRunnerId(cfg), cell.cellMeta, cfg).map((job) => JOB_MARKS[job] || "").join("");
  }

  // The outputs something of this kanban leads to: a cable, the default, the fleet-wide audio
  // and embeddings outputs and the older rule lists. A stopped cell among them stays in sight —
  // it is where requests go.
  reached() {
    const rules = this.router.rules || {};
    const named = [rules.default, rules.audioOutput, rules.embeddingsOutput, ...(rules.failover || []),
      ...(rules.schedule || []).map((r) => r?.output), ...(rules.bySource || []).map((r) => r?.output)];
    const ids = new Set(named.filter((id) => id).map(String));
    for (const e of (this.router.graph?.edges || [])) {
      const to = String(e?.to || "");
      if (to.startsWith("out:")) ids.add(to.slice(4));
    }
    return ids;
  }

  // One machine's rows for its group: the ones kept in sight, and the stopped cells nothing leads
  // to, folded under one row while there are two or more of them — a row that hides one row
  // saves nothing. The order of each part is the order given.
  split(outs) {
    const reached = this.reached();
    const quiet = outs.filter((o) => this.state(o) === "stopped" && !reached.has(String(o.id)));
    if (quiet.length < 2) return { shown: outs, quiet: [] };
    return { shown: outs.filter((o) => !quiet.includes(o)), quiet };
  }

  // Rows of one machine that read the same — two cells of one model — say what sets them apart:
  // each the values of the settings that differ between them ("eng" beside "rus"); a setting
  // that may hold a secret by its name alone. Twins that differ in nothing but the port say whose
  // copy they are. A twin whose settings are not known says nothing: nothing to compare is not
  // "the same". Output id → { same: port } or { differ: [[setting, value | null]], keys: [...] }.
  twins(outs) {
    const notes = new Map();
    const byName = new Map();
    for (const o of outs) {
      if (String(o.upstreamType || "llama") !== "llama") continue;
      const name = this.name(o);
      if (!byName.has(name)) byName.set(name, []);
      byName.get(name).push(o);
    }
    for (const group of byName.values()) {
      if (group.length < 2) continue;
      const cfgs = group.map((o) => this.cellOf(o)?.slotConfig);
      if (cfgs.some((c) => !c || typeof c !== "object")) continue;
      const keys = [...new Set(cfgs.flatMap((c) => Object.keys(c)))]
        .filter((k) => !OutputCells.OWN.has(k) && new Set(cfgs.map((c) => String(c[k] ?? ""))).size > 1).sort();
      group.forEach((o, i) => {
        if (!keys.length) {
          const other = group.filter((x) => x !== o).map((x) => Number(x.upstreamPort)).sort((a, b) => a - b)[0];
          notes.set(o.id, { same: other });
        } else {
          notes.set(o.id, { keys, differ: keys.map((k) => [k, OutputCells.SECRET.test(k) ? null : String(cfgs[i][k] ?? "")]) });
        }
      });
    }
    return notes;
  }
}
