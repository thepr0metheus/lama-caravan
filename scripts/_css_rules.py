"""A stylesheet read by value, for the snapshots that guard one layout rule (test_routing_dock_css.py, test_board_heads.py).

A browser is not in CI, so what a stylesheet says about a box is read from the text: each rule's selectors with its
declarations, comments left out. The reading is deliberately plain: a rule inside @media is read like any other (a
guard that sees a margin there errs on the safe side), and a value it cannot read as pixels is None, never a guess.
"""
import re


class CssRules:
    RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
    PX = re.compile(r"(-?[\d.]+)(?:px)?")

    @classmethod
    def rules(cls, css):
        """(selector, {property: value}) for each selector of each rule, comments left out, names and values in lower case."""
        found = []
        for head, body in cls.RULE.findall(re.sub(r"/\*.*?\*/", "", css, flags=re.S)):
            declarations = {}
            for part in body.split(";"):
                if ":" in part:
                    name, _, value = part.partition(":")
                    declarations[name.strip().lower()] = value.strip().lower()
            for selector in head.split(","):
                found.append((" ".join(selector.split()), declarations))
        return found

    @staticmethod
    def subject(selector):
        """The last compound of a selector, the element the rule is about: `.pb .pb-dock .pb-turn` is about `.pb-turn`."""
        masked = re.sub(r"\([^()]*\)|\[[^\]]*\]", lambda m: "_" * len(m.group(0)), selector)
        ends = [m.end() for m in re.finditer(r"[\s>+~]+", masked)]
        return selector[ends[-1]:] if ends else selector

    @classmethod
    def px(cls, value):
        """A length in px as a number (`12px`, `-28`, `0`); None for anything else (`2em`, `auto`, `calc(...)`, nothing)."""
        match = cls.PX.fullmatch((value or "").strip())
        return float(match.group(1)) if match else None

    @classmethod
    def sides(cls, value):
        """top, right, bottom, left of a shorthand like `12px -20px -28px`, in px; None for a value that is not in px."""
        parts = (value or "").split()
        if not parts or len(parts) > 4:
            return None
        if len(parts) == 1:
            parts = parts * 4
        elif len(parts) == 2:
            parts = parts * 2
        elif len(parts) == 3:
            parts = parts + [parts[1]]
        lengths = [cls.px(p) for p in parts]
        return None if None in lengths else lengths
