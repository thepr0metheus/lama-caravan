#!/usr/bin/env python3
"""Value snapshot: on Routing only a chosen path makes the rest of the board step back (1.3.676).

The owner, 2026-10-27, with the pointer on a card of Routing: "let us after all NOT hide the other blocks (make them
transparent) when I only point at a block; hide them only when I chose a block". From 1.3.503 the pointer over a card lit its
path and dimmed everything else, so a pointer crossing the board made the whole of it blink. pool-board.js marks the board
`tracing` while a path is lit, pointed at or pinned, and `traced` as well while it is pinned by a click (`lightPath`, `pin`;
test_js_pool_board.py pins both); what steps back is the stylesheets' to say. The browser is not in CI, so this reads
static/css/pool-board.css and static/css/cables.css and names a stylesheet in which

  - something steps back while a path is only pointed at: a rule under `.pb.tracing` with no `.traced` (or `.path-alone`) in the
    same compound makes what it styles clear (`opacity` below 1, or one that cannot be read as a number), filtered (`filter`),
    hidden (`visibility: hidden`) or gone (`display: none`); a `:not(.traced)` does not count as `.traced`;
  - a pinned path leaves the rest as it is: what is not on it — a card, a model, a row of «Напрямую», the rows of a lit card that
    are not on the path, a cable and its drops — needs a rule under `.pb.tracing.traced` that takes its opacity below 1. Under
    `.traced` alone it would not do: while a cable is carried the pin stays (`traced`) and the path goes dark (`tracing` and
    `on-path` are taken off), and such a rule would dim every card of the board under the carried cable;
  - a path that is pointed at is not lit: its cards need their frame (`box-shadow`) and its dots their fill (`background`) —
    pointing still shows where a card leads; it only takes nothing away.

Run: python3 scripts/test_path_dim_css.py
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _css_rules import CssRules  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STYLES = [ROOT / "static" / "css" / name for name in ("pool-board.css", "cables.css")]

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


class PathDimming:
    """What a lit path of Routing does to the rest of the board, read from the stylesheets' text."""

    # What steps back behind a pinned path: each by what the rule under `.pb.tracing.traced` styles.
    BEHIND = (
        ".pb-card[data-pb-node]:not(.on-path)",
        ".pb-model[data-pb-node]:not(.on-path)",
        ".pb-direct-row[data-pb-node]:not(.on-path)",
        ".pb-card[data-pb-node].on-path [data-pb-node]:not(.on-path)",
        ".pb-cables g:not(.on-path) .pb-cable",
        ".pb-cables g:not(.on-path) .cable-flow",
    )
    # What lights on a path that is only pointed at: what the rule under `.pb.tracing` styles, and the property it must set.
    LIT = ((".pb-card[data-pb-node].on-path", "box-shadow"), ("[data-pb-node].on-path > .pb-dot:not(.open)", "background"))
    PINNED = {"traced", "path-alone"}

    @staticmethod
    def board(selector):
        """The classes of the compound that carries `.tracing` — the board's own — or None for a rule that is not about a lit path.
        What stands inside `:not(...)` is left out: `.pb.tracing:not(.traced)` is a path that is only pointed at."""
        for compound in re.split(r"[\s>+~]+", selector):
            names = set(re.findall(r"\.([\w-]+)", re.sub(r":not\([^()]*\)", "", compound)))
            if "tracing" in names:
                return names
        return None

    @staticmethod
    def opacity(value):
        """An opacity as a number from 0 to 1 (`.38`, `38%`); None for one that cannot be read (`var(--x)`, `calc(...)`)."""
        text = (value or "").strip()
        try:
            return float(text[:-1]) / 100 if text.endswith("%") else float(text)
        except ValueError:
            return None

    @classmethod
    def steps_back(cls, declarations):
        """What in these declarations makes an element step back — clear, filtered, hidden or gone; empty when nothing does."""
        found = []
        if "opacity" in declarations:
            value = cls.opacity(declarations["opacity"])
            if value is None or value < 1:
                found.append(f"opacity: {declarations['opacity']}")
        if declarations.get("filter", "none") != "none":
            found.append(f"filter: {declarations['filter']}")
        if declarations.get("visibility") == "hidden":
            found.append("visibility: hidden")
        if declarations.get("display") == "none":
            found.append("display: none")
        return found

    @staticmethod
    def declared(rules, selector):
        """Every declaration of every rule whose selector is exactly this one, the later one over the earlier."""
        merged = {}
        for sel, decl in rules:
            if sel == selector:
                merged.update(decl)
        return merged

    @classmethod
    def problems(cls, css):
        rules = CssRules.rules(css)
        bad = []
        for selector, declarations in rules:
            names = cls.board(selector)
            if names is None or names & cls.PINNED:
                continue
            what = cls.steps_back(declarations)
            if what:
                bad.append(f"{selector} makes what it styles step back while a path is only pointed at ({', '.join(what)}): "
                           "only a pinned path does (.pb.tracing.traced)")
        for subject in cls.BEHIND:
            selector = f".pb.tracing.traced {subject}"
            value = cls.opacity(cls.declared(rules, selector).get("opacity"))
            if value is None or value >= 1:
                bad.append(f"behind a pinned path {subject} does not step back: {selector} needs an opacity below 1")
        for subject, prop in cls.LIT:
            selector = f".pb.tracing {subject}"
            if prop not in cls.declared(rules, selector):
                bad.append(f"a path that is pointed at does not light {subject}: {selector} needs its {prop}")
        return bad


GOOD = """/* the path */
.pb [data-pb-node] { transition: opacity .12s ease, box-shadow .12s ease; }
.pb.tracing .pb-card[data-pb-node].on-path { box-shadow: 0 0 0 2px x; }
.pb.traced .pb-card[data-pb-node].on-path { box-shadow: 0 0 0 2px y; }
.pb.tracing .pb-model[data-pb-node].on-path { background: z; }
.pb.tracing .pb-cables g.on-path .pb-cable { stroke: a; stroke-width: 1.5; }
.pb.tracing.traced .pb-card[data-pb-node]:not(.on-path), .pb.tracing.traced .pb-model[data-pb-node]:not(.on-path),
.pb.tracing.traced .pb-direct-row[data-pb-node]:not(.on-path) { opacity: .38; }
.pb.tracing.traced .pb-card[data-pb-node].on-path [data-pb-node]:not(.on-path) { opacity: .45; }
.pb.tracing.traced .pb-cables g:not(.on-path) .pb-cable { opacity: .14; }
.pb.path-alone .pb-cables g:not(.on-path) { display: none; }
.pb.tracing [data-pb-node].on-path > .pb-dot:not(.open) { border-color: a; background: a; }
.pb.tracing.traced .pb-cables g:not(.on-path) .cable-flow { opacity: 0.14; }
@media (prefers-reduced-motion: reduce) { .pb [data-pb-node] { transition: none; } }
"""


def test_the_rule():
    print("отступает только у выбранного пути — на своих образцах:")
    check(PathDimming.problems(GOOD) == [], "наведение только зажигает путь, закреплённый путь уводит остальное назад — без замечаний")
    check(PathDimming.problems(GOOD + ".pb.tracing .pb-card[data-pb-node].on-path { opacity: 1; }\n.pb.tracing .pb-model { opacity: 100%; }") == [],
          "непрозрачность 1 (и 100%) на наведении — ничего не отступает, без замечаний")
    old = GOOD + ".pb.tracing .pb-card[data-pb-node]:not(.on-path), .pb.tracing .pb-model[data-pb-node]:not(.on-path) { opacity: .38; }"
    got = PathDimming.problems(old)
    check(len(got) == 2 and all("only pointed at" in line and "opacity: .38" in line for line in got),
          "negative: правило 1.3.675 — наведение притушивает чужие карточки и модели — названо дважды, по селектору на каждую")
    got = PathDimming.problems(GOOD + ".pb.tracing .pb-cables g:not(.on-path) .cable-flow { opacity: 0.14; }")
    check(len(got) == 1 and ".cable-flow" in got[0], "negative: на наведении тускнеют капли чужих канатов (cables.css до 1.3.676) — названо")
    for decl, word in (("display: none", "display: none"), ("visibility: hidden", "visibility: hidden"), ("filter: grayscale(1)", "filter: grayscale(1)")):
        got = PathDimming.problems(GOOD + f".pb.tracing .pb-cables g:not(.on-path) {{ {decl}; }}")
        check(len(got) == 1 and word in got[0], f"negative: на наведении чужое не тускнеет, а {word} — тоже отступает — названо")
    got = PathDimming.problems(GOOD + ".pb.tracing:not(.traced) .pb-card[data-pb-node]:not(.on-path) { opacity: .5; }")
    check(len(got) == 1 and ":not(.traced)" in got[0], "negative: «:not(.traced)» — это и есть наведение, а не закреплённый путь — названо")
    got = PathDimming.problems(GOOD + ".pb.tracing .pb-model[data-pb-node]:not(.on-path) { opacity: var(--pb-dim); }")
    check(len(got) == 1 and "var(--pb-dim)" in got[0], "negative: непрозрачность, которую не прочесть числом, — не угадана, а названа")
    got = PathDimming.problems(GOOD.replace("{ opacity: .38; }", "{ opacity: 1; }"))
    check(len(got) == 3 and all("does not step back" in line for line in got),
          "negative: закреплённый путь не уводит назад чужие карточки, модели и строки «Напрямую» — названо трижды")
    got = PathDimming.problems(GOOD.replace(".pb.tracing.traced .pb-cables g:not(.on-path) .cable-flow { opacity: 0.14; }\n", ""))
    check(len(got) == 1 and ".cable-flow" in got[0], "negative: за закреплённым путём капли чужих канатов не тускнеют — названо")
    pinned_only = GOOD.replace(".pb.tracing.traced .pb-card[data-pb-node].on-path [data-pb-node]", ".pb.traced .pb-card[data-pb-node].on-path [data-pb-node]")
    got = PathDimming.problems(pinned_only)
    check(len(got) == 1 and "pb.tracing.traced .pb-card[data-pb-node].on-path [data-pb-node]:not(.on-path)" in got[0],
          "negative: правило под одним «.traced» — с канатом в руке путь гаснет, а оно притушило бы всю доску — названо")
    got = PathDimming.problems(GOOD.replace(".pb.tracing .pb-card[data-pb-node].on-path { box-shadow: 0 0 0 2px x; }\n", ""))
    check(len(got) == 1 and "does not light" in got[0] and "box-shadow" in got[0], "negative: наведённый путь не обводит свои карточки — названо")
    got = PathDimming.problems(GOOD.replace("border-color: a; background: a;", "border-color: a;"))
    check(len(got) == 1 and "pb-dot" in got[0], "negative: точки наведённого пути не залиты — названо")


def test_the_board():
    print("доска (static/css/pool-board.css, static/css/cables.css):")
    bad = PathDimming.problems("\n".join(path.read_text(encoding="utf-8") for path in STYLES))
    check(bad == [], "наведение зажигает путь и ничего не уводит назад; закреплённый путь уводит назад остальное" + (f" — {'; '.join(bad)}" if bad else ""))


for fn in (test_the_rule, test_the_board):
    fn()

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("path dim css snapshot holds")
