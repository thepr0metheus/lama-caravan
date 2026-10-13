// The words a pool's deletion says about what still points at the pool
// ("Delete pool", pools.js). Read from GET /api/pools/refs.
import { t } from "./i18n.js";

export class CloudRefWords {
  static lines(refs = {}) {
    const lines = [];
    const label = (x) => (x.label ? ` · ${x.label}` : "");
    (refs.routes || []).forEach((r) => lines.push(t("refAgentRoute", { port: String(r.port) }) + label(r)));
    (refs.fallbacks || []).forEach((r) => lines.push(t("refCloudFallback", { port: String(r.port) }) + label(r)));
    (refs.queueRoles || []).forEach((q) => lines.push(t("refQueueRole", { role: q.role })));
    (refs.rescueRoles || []).forEach((q) => lines.push(t("refRescueRole", { role: q.role })));
    (refs.rules || []).forEach((r) => lines.push(t("refRule", { rule: r.rule })));
    if ((refs.edges || []).length) lines.push(t("refCables", { n: String(refs.edges.length) }));
    return lines;
  }

  // The line under a deletion's question: what leads there, or that nothing does.
  static detail(lines) {
    return lines.length ? `${t("refsUsedBy")}\n${lines.map((l) => `• ${l}`).join("\n")}` : t("refsNone");
  }
}
