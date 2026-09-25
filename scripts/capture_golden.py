#!/usr/bin/env python3
"""Photograph what the caravan does today, so a rewrite can be checked against it.

The rewrite ahead touches every module. The risk is not that it breaks loudly —
it is that a flag stops being emitted, a field stops being carried, a default
quietly changes, and nobody notices until a cell behaves differently three weeks
later. Eighty thousand lines against six tests is not a position from which
"nothing was lost" can be claimed.

So this takes the picture first. Two kinds:

  COMMANDS — the real launch line for every cell that exists on the controller,
  generated from that cell's own saved config. A command cell also gets the
  one-line form a scout runs it with (SHELL_LINES): the same cell started on
  a machine with a scout. This is the highest-value
  snapshot in the project: it pins every flag, for every runner, for every
  configuration an operator actually arrived at. A rewrite that changes one of
  them has to say so out loud.

  SHAPES — the key structure (not the values) of the API payloads. Values move
  every second: memory, uptime, token counts. Structure is what consumers bind
  to, and a field that silently stops being produced is exactly the failure this
  codebase keeps having.

Hermetic on purpose: the configs are copied here as fixtures and the rendering
is done locally with the paths pinned, so the test runs anywhere — CI included —
and compares like with like.

    python3 scripts/capture_golden.py            # from the live controller
    python3 scripts/capture_golden.py --local    # re-render from saved fixtures
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "tests/golden"
FIXTURES = GOLDEN / "cells"
COMMANDS = GOLDEN / "commands"
SHELL_LINES = GOLDEN / "shell-lines"
HOST = os.environ.get("CARAVAN_DEPLOY_HOST", "skynet")
REMOTE = os.environ.get("CARAVAN_REMOTE_PATH", "~/projects/lama-caravan")

# The paths every rendering is pinned to. The controller's real values: a
# snapshot taken with one set of paths and checked with another would differ on
# every line for no reason at all.
# A NEUTRAL home, not the controller's. These fixtures live in the repository
# (the private one — sync-public.sh leaves tests/golden out), and no fixture
# names a fleet machine or an operator's home; a snapshot pinned to one
# machine's paths could never be checked on another either. The capture
# rewrites every real home to this one.
# Any machine's home, whatever it is: the slots of every machine are captured
# since step 6.9, and each carries its own paths. It was "the controller's own
# $HOME" — read as ~ on the machine that RAN the capture, so a capture run from
# a workstation swapped nothing and left the controller's home, and its user's
# name, in every rendered command. Hardcoding one operator's path put it in
# every file that mentions the constant.
HOMES = re.compile(r"(?:/home|/Users)/[^/\s\"']+")
HOME = "/home/caravan"
PINNED = {
    "LLAMA_HOME": f"{HOME}/llama.cpp",
    "LLAMA_MODELS_DIR": f"{HOME}/llama.cpp/models",
    "HOME": HOME,
}


def neutralize(value):
    """Every machine's home out, a neutral one in — at any depth."""
    if isinstance(value, str):
        return HOMES.sub(HOME, value)
    if isinstance(value, dict):
        return {k: neutralize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [neutralize(v) for v in value]
    return value


def pin_env():
    for key, value in PINNED.items():
        os.environ[key] = value


def fetch_cell_configs():
    """Every cell's saved config, straight off the controller: the slots in
    its admin state, by port. (Until step 6.9 they were read from the
    controller's own var/server-cells/<port>/cell.json; those cells run
    through the scout of their machine now, and every cell is its slot.)"""
    script = (
        "import json,os;"
        "p=os.environ.get('LLAMA_ADMIN_STATE') or os.path.expanduser("
        "'~/.local/state/llamacpp-easy-admin/admin.json');"
        "s=(json.load(open(p)).get('topology') or {}).get('serverSlots') or {};"
        "out={str(v.get('port')): v.get('config') or {} for v in s.values()"
        " if isinstance(v, dict) and v.get('port') and v.get('config')};"
        "print(json.dumps(out))"
    )
    raw = subprocess.run(["ssh", HOST, f"python3 -c {json.dumps(script)}"],
                         capture_output=True, text=True, check=True).stdout
    return neutralize(json.loads(raw))


def fleet_names(topology):
    """The machines and clients a topology payload names: node, client and
    host ids, and the keys of the maps kept per client. No fixture names a fleet
    machine (the golden files stay private, but the rule has no exceptions),
    and a map keyed by them (assignments, cellNotes, clientAliases…) put the
    fleet's machine names into the shapes as keys."""
    names = set()
    for section in ("nodes", "clients", "hosts"):
        for row in topology.get(section) or []:
            if isinstance(row, dict) and row.get("id"):
                names.add(str(row["id"]))
    for section in ("assignments", "clientAliases"):
        if isinstance(topology.get(section), dict):
            names.update(str(k) for k in topology[section])
    names.discard("controller")      # the sentinel, not a machine
    return names


def hidden(names):
    """A key with every fleet name in it replaced by <machine> — longest name
    first, whole names only, so "box-pc:22001" and "box" both come out right."""
    if not names:
        return lambda key: key
    pattern = re.compile(r"(?<![\w-])(" + "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
                         + r")(?![\w-])")
    return lambda key: pattern.sub("<machine>", key)


def api_shape(value, depth=0, hide=lambda key: key):
    """Keys and types, never values — and no fleet name among the keys.

    A payload's numbers change every second; its shape is the contract. Recursed
    to a fixed depth because a topology tree is deep and the interesting drift —
    a field that stopped being produced — is near the top. A map keyed by
    machines keeps one entry per placeholder: its shape, not its fleet.
    """
    if depth > 4:
        return "…"
    if isinstance(value, dict):
        return {hide(k): api_shape(v, depth + 1, hide) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [api_shape(value[0], depth + 1, hide)] if value else []
    return type(value).__name__


# The builder behind each payload, called directly rather than over HTTP. These
# endpoints require a human session — correctly, they are not machine endpoints —
# and the fleet token does not open them. Calling the builder on the controller
# is both simpler and closer to the point: what is being pinned is the shape the
# CODE produces, not what the transport layer wraps around it.
#
# The board's builder is called WITHOUT asking the scouts for fresher reports.
# That ask starts a background pull which writes the admin state file — from
# this second process, next to the live service writing the same file. A
# photograph must not touch what it photographs.
SHAPE_SOURCES = {
    "state": "from caravan.admin.status import state as f",
    "topology": "from caravan.admin.topology import topology_state; f = lambda: topology_state(refresh_hosts=False)",
    "controller-info": "from caravan.admin.status import controller_info as f",
}


def fetch_api_shapes():
    """Shapes of the payloads the UI binds to, from the builders themselves —
    all payloads first, so the fleet's names are known before any is shaped."""
    payloads, shapes = {}, {}
    for name, imp in SHAPE_SOURCES.items():
        script = (
            "import json,sys;sys.path.insert(0,'.');"
            f"{imp};print(json.dumps(f()))"
        )
        done = None
        try:
            done = subprocess.run(
                ["ssh", HOST, f"cd {REMOTE} && .venv/bin/python -c {json.dumps(script)}"],
                capture_output=True, text=True, timeout=120)
            payloads[name] = json.loads(done.stdout)
        except Exception as exc:  # noqa: BLE001
            # Recorded, not skipped: a shape that could not be taken must not
            # look like a shape that is empty.
            detail = (done.stderr.strip().splitlines()[-1] if done is not None and done.stderr
                      else str(exc))
            shapes[name] = {"__unavailable__": detail[:160]}
    hide = hidden(fleet_names(payloads.get("topology") or {}))
    for name, payload in payloads.items():
        shapes[name] = api_shape(payload, hide=hide)
    return dict(sorted(shapes.items()))



def synthetic_configs():
    """Configs that set EVERY field, one per runner.

    The 25 real cells cover 57 of 116 config fields. The other 59 appear in no
    cell, so a rewrite could rename or drop their flags and the snapshot would
    stay green — which is exactly what happened when this was tested: renaming
    --top-k and deleting --n-cpu-moe changed nothing, because nobody uses them.
    A net with holes in it is worse than a known-small net, because it reads as
    full coverage.

    So: one config per runner with every field filled, values chosen by how the
    builder consumes each field (value flag, on/off, free text). Semantically
    these are nonsense — a cell like this would never be configured by hand —
    and that does not matter. What is being pinned is the EMISSION: that each
    field still turns into the flag it turned into before.
    """
    sys.path.insert(0, str(ROOT))
    import caravan.admin.config_builder as cb

    value_fields = {f for _, f in cb._BUILDER_PAIRS}
    bool_fields = set(cb._EXTRA_FLAG_ON.values()) | set(cb._EXTRA_ONOFF_FLAGS.values())
    if hasattr(cb, "_EXTRA_PAIR_BOOL"):
        bool_fields |= {p[0] if isinstance(p, tuple) else p for p in cb._EXTRA_PAIR_BOOL.values()}

    # Fields whose value must stay real for the render to mean anything.
    anchors = {
        "HOST": "0.0.0.0", "PORT": "29999",
        "LLAMA_MODELS_DIR": PINNED["LLAMA_MODELS_DIR"],
        "MODEL_FILE": "vendor/model/Q4_K_M/synthetic-7B-Q4_K_M.gguf",
    }

    numeric_hint = ("SIZE", "PORT", "THREADS", "LAYERS", "TOKENS", "COUNT", "MAX", "MIN",
                    "RAM", "TIMEOUT", "SECONDS", "PARALLEL", "SLOTS", "BUDGET", "N_",
                    "UTILIZATION", "SPLIT", "GPU", "KEEP", "POLL", "REUSE", "PREDICT")

    def value_for(field):
        if field in anchors:
            return anchors[field]
        if field in bool_fields:
            return "1"
        if field.endswith("_FILE") or field.endswith("_DIR") or "PATH" in field:
            return f"{PINNED['HOME']}/synthetic/{field.lower()}"
        if any(h in field for h in numeric_hint):
            return "7"
        return f"synthetic-{field.lower()}"

    from caravan.admin.launch import render_launch_script
    from caravan.common.errors import AppError
    import re as _re

    out = {}
    for runner in ("llama-server", "vllm", "whisper", "moonshine",
                   "transcribe", "seamless", "translate", "custom"):
        cfg = {f: value_for(f) for f in cb.CONFIG_FIELDS}
        cfg["RUNNER"] = runner
        cfg["CELL_KIND"] = "command" if runner == "custom" else ""
        cfg["COMMAND"] = "bash $HOME/run_synthetic.sh \"$PORT\"" if runner == "custom" else ""

        # Let the validator teach us the types. Guessing them from field names
        # got FIT_CTX wrong and the whole config was refused on the first
        # complaint — which pinned an error message instead of 116 flags. The
        # renderer already knows which fields are numbers; it says so, one at a
        # time, so ask it until it stops complaining.
        blanked = []
        for _ in range(len(cb.CONFIG_FIELDS) + 5):
            try:
                render_launch_script(cfg)
                break
            except AppError as exc:
                m = _re.match(r"([A-Z_]+) must be (?:a number|an integer)", str(exc))
                if m and cfg.get(m.group(1)) != "7":
                    cfg[m.group(1)] = "7"
                    continue
                m2 = _re.match(r"([A-Z_]+)\b", str(exc))
                if m2 and m2.group(1) in cfg and cfg[m2.group(1)]:
                    # Cannot satisfy it: empty it and record that this field is
                    # therefore NOT covered, rather than leaving a refusal that
                    # covers nothing at all.
                    blanked.append(m2.group(1))
                    cfg[m2.group(1)] = ""
                    continue
                break
        if blanked:
            print(f"  синтетика {runner}: не удалось заполнить {', '.join(sorted(set(blanked)))}")
        out[f"synthetic-{runner}"] = cfg
    return out


def render_all(configs):
    """The launch script each config produces, with today's code."""
    pin_env()
    sys.path.insert(0, str(ROOT))
    from caravan.admin.launch import render_launch_script   # after pin_env
    from caravan.common.errors import AppError
    out = {}
    for port, config in sorted(configs.items()):
        try:
            out[port] = neutralize(render_launch_script(config))
        except AppError as exc:
            # A config the renderer refuses is itself behaviour worth pinning:
            # the rewrite must refuse the same ones for the same reason.
            out[port] = neutralize(f"__REFUSED__ {exc}")
    return out


def render_shell_lines(configs):
    """The one line a scout runs each command cell with, with today's code —
    the same cell as its start.sh, started on a machine with a scout."""
    pin_env()
    sys.path.insert(0, str(ROOT))
    from caravan.admin.launch import render_command_cell_shell_line   # after pin_env
    from caravan.admin.runners import uses_command_path
    from caravan.common.errors import AppError
    out = {}
    for port, config in sorted(configs.items()):
        if not uses_command_path(config):
            continue
        try:
            out[port] = neutralize(render_command_cell_shell_line(config)) + "\n"
        except AppError as exc:
            out[port] = neutralize(f"__REFUSED__ {exc}") + "\n"
    return out


def main():
    local = "--local" in sys.argv
    FIXTURES.mkdir(parents=True, exist_ok=True)
    COMMANDS.mkdir(parents=True, exist_ok=True)

    if local:
        configs = {p.stem: json.loads(p.read_text(encoding="utf-8"))
                   for p in sorted(FIXTURES.glob("*.json"))}
        print(f"  из фикстур: {len(configs)} ячеек")
    else:
        configs = fetch_cell_configs()
        print(f"  с контроллера: {len(configs)} ячеек")
        for port, config in configs.items():
            (FIXTURES / f"{port}.json").write_text(
                json.dumps(config, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        shapes = fetch_api_shapes()
        (GOLDEN / "api-shapes.json").write_text(
            json.dumps(shapes, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        print(f"  формы API: {', '.join(shapes)}")

    # Real cells pin what the operator actually uses; synthetic ones pin every
    # flag the builder can emit. Both are needed: the first catches a change to
    # a live cell, the second catches a field quietly losing its flag.
    configs.update(synthetic_configs())
    for port, config in configs.items():
        if port.startswith("synthetic-"):
            (FIXTURES / f"{port}.json").write_text(
                json.dumps(config, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")

    rendered = render_all(configs)
    for port, script in rendered.items():
        (COMMANDS / f"{port}.sh").write_text(script, encoding="utf-8")
    SHELL_LINES.mkdir(parents=True, exist_ok=True)
    lines = render_shell_lines(configs)
    for port, line in lines.items():
        (SHELL_LINES / f"{port}.txt").write_text(line, encoding="utf-8")
    runners = {}
    for port, config in configs.items():
        runners[config.get("RUNNER") or "llama-server"] = runners.get(
            config.get("RUNNER") or "llama-server", 0) + 1
    print(f"  снято команд: {len(rendered)}, строк запуска на скауте: {len(lines)}")
    print("  по раннерам: " + ", ".join(f"{k}×{v}" for k, v in sorted(runners.items())))
    print(f"\n  фикстуры: {FIXTURES.relative_to(ROOT)}")
    print(f"  эталоны:  {COMMANDS.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
