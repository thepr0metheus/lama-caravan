// The model behind each local row of Routing's Servers panel and of its Models column, and what the row says of it
// (2026-10-04: the operator's points 2, 6 and 7 after a look at the live Routing).
//
// A row said only the traffic: one grey dot, "idle", for a cell that serves and for one that is not running at all — 24 of the
// 30 rows on the live Routing were stopped and looked exactly like the 6 that ran (absence drawn as normality), and the cables
// into two stopped cells looked live. And the stopped cells nothing leads to filled two screens of the panel.
//
// Since 2026-11-07 (Papyrus caravan-scout-port-lease, step 3) a cell is no output of its own: it holds a port only while it runs,
// and a request reaches it through its machine's model (`mm:`), of which it is a copy. So a local row is a model of a machine's
// entry or of an engine, found on the machine its output names (`hostId`): a machine's model in its scout's list of them, an
// engine's by its engine. The state is the scout's or the engine's own word. A model the board does not have, or a word these
// tables do not know, is "unknown": never stopped, never idle.
import { JOB_MARKS } from "./model-jobs.js";

export class OutputCells {
  // An engine's state (rust/crates/admin/src/domain/engine.rs) → the row's words. A model of a running engine is served: the
  // engine loads it on the first request.
  static ENGINE = { ok: "running", stopped: "stopped", auth: "failed", unreachable: "failed" };
  // A model of a machine's entry (its scout, 1.3.506): the scout's own words, the same four.
  static MACHINE = { running: "running", starting: "starting", failed: "failed", stopped: "stopped" };
  // The word a row says beside its name (i18n keys). A running row says none — its dot speaks.
  static WORDS = { stopped: "stopped", starting: "starting", stopping: "rtCellStopping", failed: "failed", unknown: "unknown" };

  constructor(topology, router = {}) {
    this.nodes = topology?.nodes || [];
    this.router = router || {};
  }

  // The queue a local output's requests stand in, as the proxy names it on each request
  // (rust/crates/rules/src/router_outputs.rs, MachineOutput::group): "host:port/model" for a model of a machine's entry — its
  // port serves every model of the machine, each with places of its own (1.3.506) — and "host:port" for an output of any other
  // kind, an engine's.
  static upstream(out) {
    const base = `${out?.upstreamHost || ""}:${out?.upstreamPort || ""}`;
    return String(out?.upstreamType || "") === "machine" ? `${base}/${out.upstreamModel || ""}` : base;
  }

  // The machine an output names (`hostId`, an engine's model and a machine's alike); null when the board has none of that id.
  nodeAt(out) {
    const id = String(out?.hostId || "");
    return id ? this.nodes.find((n) => String(n.id) === id) || null : null;
  }

  // A model of a machine's entry as its scout last said it: {id, state, slots, busy, copies}; null
  // when its scout does not say (an older scout) or no longer lists it.
  modelOf(out) {
    if (String(out?.upstreamType || "") !== "machine") return null;
    const models = this.nodeAt(out)?.entryModels;
    return Array.isArray(models) ? models.find((m) => String(m?.id) === String(out.upstreamModel || "")) || null : null;
  }

  // How many cells serve a machine's model: its copies; 0 for any other output.
  copies(out) {
    return (this.modelOf(out)?.copies || []).length;
  }

  // running | stopped | starting | stopping | failed | unknown for a local output, "" for a
  // cloud one — no machine of the fleet serves it, and its own card says how it is.
  state(out) {
    const type = String(out?.upstreamType || "");
    if (type === "cloud") return "";
    if (type === "engine") {
      const engine = (this.nodeAt(out)?.engines || []).find((e) => String(e?.kind || "") === String(out.engine || ""));
      return OutputCells.ENGINE[String(engine?.state || "")] || "unknown";
    }
    if (type === "machine") return OutputCells.MACHINE[String(this.modelOf(out)?.state || "")] || "unknown";
    // An output of no kind the board draws (the controller's out-of-the-box one): nothing says what stands behind it.
    return "unknown";
  }

  // What a row calls its model: a machine's model by its name, an engine's by the label the controller gave it ("qwen3:8b ·
  // Ollama", else its model and engine), any other output by its label — "" when nothing names it, never a guess. No port: a
  // machine's entry and an engine serve many models on one, and a cell holds one only while it runs.
  name(out) {
    const type = String(out?.upstreamType || "");
    if (type === "machine") return String(out.upstreamModel || out.label || "");
    if (type === "engine") return String(out.label || [out.upstreamModel, out.engine].filter(Boolean).join(" · "));
    return String(out?.label || "");
  }

  // What the model does, as job names — the list the cell card's job chips draw. The controller says it on a machine's model's
  // output, from its copies (rust/crates/admin/src/fleet/machine_models.rs); an output that says none — an engine's — does
  // none that can be named.
  jobs(out) {
    return Array.isArray(out?.jobs) ? out.jobs : [];
  }

  // The same, as marks.
  marks(out) {
    return this.jobs(out).map((job) => JOB_MARKS[job] || "").join("");
  }

  // The outputs something of this router leads to: a cable, the default, the fleet-wide audio
  // and embeddings outputs and the older rule lists. A stopped model among them stays in sight —
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

  // One machine's rows for its group: the ones kept in sight, and the stopped models nothing leads
  // to, folded under one row while there are two or more of them — a row that hides one row
  // saves nothing. The order of each part is the order given.
  split(outs) {
    const reached = this.reached();
    const quiet = outs.filter((o) => this.state(o) === "stopped" && !reached.has(String(o.id)));
    if (quiet.length < 2) return { shown: outs, quiet: [] };
    return { shown: outs.filter((o) => !quiet.includes(o)), quiet };
  }
}
