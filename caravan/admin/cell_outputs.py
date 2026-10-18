"""A machine's cell, named by its port, followed wherever the caravan names it.

A cell is named by its output id, `srv:<port>`, in three places: the routers' outputs, rules and
graph edges (agent-proxies.json, caravan/admin/output_refs.py), the pools' rows
(cloud-providers.json `pools[].steps[].output`) and the models' schedules (`schedules`, keyed
`out:srv:<port>`, caravan/common/model_schedules.py). A port move or a swap follows the cell in all
of them at once (`move`, `swap`). Until 1.3.499 it followed the routers only: a pool's row kept the
old port — after a move it named a port with no cell, and after a swap the other cell, so the pool
sent its requests to a model the operator never cabled to it (found 2026-10-12).

A cell deleted takes its rows' cables and its schedule with it (`drop`): a new cell takes the
smallest free port, and a row still naming that port would serve the new cell's model without a
word — the reason a deleted pool takes its clients' cables (caravan/admin/pools.py). A move onto a
port a row or a schedule still names — what a cell deleted before 1.3.499 left behind — takes those
names away first, for the same reason. The routers keep what they always kept on a delete: their
graph is drawn nowhere since 1.3.486 and decides only for the agent ports of the old kind, whose
walk a delete must not change unseen.

Not followed, and why: an engine's model (`eng:<id>`) is named by its machine, engine and model,
not by a port; the proxy's health verdicts by output id live 300 s in memory, and a move and a swap
are offered on stopped cells only, whose verdicts say "dead" either way.
"""
from caravan.common.model_schedules import ModelKey, ModelSchedules


class CellOutputs:
    """The names of a cell — `srv:<port>` — following it when its port changes, and leaving with it."""

    def __init__(self, load=None, save=None, routers_move=None, routers_swap=None, log=print):
        # cloud.py and proxies_config.py import Routing's modules at the top; taken here.
        from caravan.admin.cloud import load_cloud_data, save_cloud_data
        from caravan.admin.proxies_config import remap_router_output_refs, swap_router_output_refs
        self.load, self.save = load or load_cloud_data, save or save_cloud_data
        self.routers_move = routers_move or remap_router_output_refs
        self.routers_swap = routers_swap or swap_router_output_refs
        self.log = log

    @staticmethod
    def output(port):
        return f"srv:{int(port)}"

    @staticmethod
    def _rows(data, rename):
        """Every pool's row cabled to a cell, named anew by `rename(output)` — another output, the
        same one, or None, which takes the row's cable away and leaves the row open in its place
        (PoolDesk.connect_row with no target). Answers the names of the pools it changed."""
        from caravan.admin.pools import PoolDesk
        changed = []
        for pool in data.get("pools") or []:
            if not isinstance(pool, dict) or not isinstance(pool.get("steps"), list):
                continue
            touched = False
            for index, step in enumerate(pool["steps"]):
                if not isinstance(step, dict) or not step.get("output"):
                    continue
                named = rename(str(step["output"]))
                if named == step["output"]:
                    continue
                pool["steps"][index] = {**step, "output": named} if named else PoolDesk._untargeted(step)
                touched = True
            if touched:
                changed.append(str(pool.get("name") or pool.get("id") or ""))
        return changed

    def _cloud(self, rename, change_schedules):
        """One reading and one writing of cloud-providers.json: the rows named anew and the
        schedules changed together, so the proxy never reads one without the other."""
        data = self.load()
        pools = self._rows(data, rename)
        schedules = ModelSchedules(data)
        changed = change_schedules(schedules)
        if pools or changed:
            data["schedules"] = schedules.stored()
            self.save(data)
        return pools, bool(changed)

    def _follow(self, what, routers, rename, change_schedules):
        """Each file followed on its own: one that cannot be written is named — in the answer and the
        log — and the others still follow. The cell has moved already; taking the move back would
        leave its saved config on one port and its cables on another."""
        said = {"routers": False, "pools": [], "schedule": False, "notFollowed": []}
        try:
            said["routers"] = bool(routers())
        except Exception as exc:  # noqa: BLE001 — named below, not swallowed
            said["notFollowed"].append(f"routers: {exc}")
        try:
            said["pools"], said["schedule"] = self._cloud(rename, change_schedules)
        except Exception as exc:  # noqa: BLE001 — named below, not swallowed
            said["notFollowed"].append(f"pools and schedules: {exc}")
        for failure in said["notFollowed"]:
            self.log(f"[cell-outputs] {what}: did not follow — {failure}", flush=True)
        return said

    def move(self, old_port, new_port):
        """The cell moved from `old_port` to `new_port`: every name of it follows. Answers
        `{routers, pools: [names], schedule, notFollowed: [what could not]}`."""
        old, new = self.output(old_port), self.output(new_port)

        def rename(output):
            # A name the destination still carries is a deleted cell's: it goes, rather than
            # landing on the cell that moved in.
            return None if output == new else (new if output == old else output)

        def schedules(kept):
            stale = kept.forget(ModelKey.output(new))
            return kept.follow(old, new) or stale
        return self._follow(f"{old} → {new}", lambda: self.routers_move(old, new), rename, schedules)

    def swap(self, port_a, port_b):
        """Two cells swapped their ports: each one's names go with it, in one pass."""
        a, b = self.output(port_a), self.output(port_b)

        def rename(output):
            return b if output == a else (a if output == b else output)
        return self._follow(f"{a} ↔ {b}", lambda: self.routers_swap(a, b), rename, lambda kept: kept.swap(a, b))

    def drop(self, port):
        """The cell at `port` was deleted: its rows lose their cable, its schedule goes. The routers
        keep their names of it (the module's docstring says why)."""
        gone = self.output(port)
        return self._follow(f"{gone} deleted", lambda: False, lambda output: None if output == gone else output,
                            lambda kept: kept.forget(ModelKey.output(gone)))
