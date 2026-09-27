"""Every place a router names one of its outputs, in one table.

A router names an output in its rules (the default; the default kept in
reserve while its output is away; audio; embeddings), in its rule lists
(schedule, by source), in failover, and in its graph, where an edge's end is
`out:<output id>`. Following an output to a new id — a cell moved to another
port, two cells swapping ports, a legacy cloud output upgraded, a model's
cables moved onto the provider's newer model — rewrites all of them; listing
what depends on a cloud model reads all of them.

Before this table four functions kept their own copy of the list, and the
copies had drifted: the legacy upgrade never looked at the reserve default,
audio or embeddings.
"""


class RouterOutputRefs:
    RULE_KEYS = ("default", "dormantDefault", "audioOutput", "embeddingsOutput")
    RULE_LISTS = ("schedule", "bySource")
    EDGE_PREFIX = "out:"

    def __init__(self, router):
        self.router = router if isinstance(router, dict) else {}

    def _rules(self):
        return self.router.get("rules") or {}

    def _edges(self):
        return [e for e in ((self.router.get("graph") or {}).get("edges") or []) if isinstance(e, dict)]

    def _list_rows(self, rules, key):
        return [r for r in (rules.get(key) or []) if isinstance(r, dict)]

    def rules_naming(self, output_id):
        """The kinds of rule that name `output_id`, in the table's order."""
        rules = self._rules()
        hits = [k for k in self.RULE_KEYS if str(rules.get(k) or "") == output_id]
        hits += [k for k in self.RULE_LISTS
                 if any(str(r.get("output") or "") == output_id for r in self._list_rows(rules, k))]
        if output_id in (rules.get("failover") or []):
            hits.append("failover")
        return hits

    def edges_touching(self, output_id):
        ref = self.EDGE_PREFIX + output_id
        return [e for e in self._edges() if ref in (str(e.get("from") or ""), str(e.get("to") or ""))]

    def rewrite(self, new_id_of):
        """Every output id `v` the router names becomes `new_id_of(v)`, in place
        (an edge keeps its id, so the roles nodes hold by edge id stay).
        Returns how many places changed."""
        rules = self._rules()
        changed = 0
        for key in self.RULE_KEYS:
            old = rules.get(key)
            if old and new_id_of(old) != old:
                rules[key] = new_id_of(old)
                changed += 1
        for key in self.RULE_LISTS:
            for row in self._list_rows(rules, key):
                old = row.get("output")
                if old and new_id_of(old) != old:
                    row["output"] = new_id_of(old)
                    changed += 1
        failover = rules.get("failover") or []
        moved = [new_id_of(o) for o in failover]
        if moved != failover:
            rules["failover"] = moved
            changed += 1
        for edge in self._edges():
            for end in ("from", "to"):
                ref = edge.get(end)
                if isinstance(ref, str) and ref.startswith(self.EDGE_PREFIX):
                    old = ref[len(self.EDGE_PREFIX):]
                    if new_id_of(old) != old:
                        edge[end] = self.EDGE_PREFIX + new_id_of(old)
                        changed += 1
        return changed
