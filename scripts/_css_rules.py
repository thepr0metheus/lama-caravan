"""A stylesheet read by value, for the snapshots that guard one layout rule (test_routing_dock_css.py, test_board_heads.py).

A browser is not in CI, so what a stylesheet says about a box is read from the text: each rule's selectors with its
declarations, comments left out. The reading is deliberately plain: a rule inside @media is read like any other (a
guard that sees a margin there errs on the safe side), and a value it cannot read as pixels is None, never a guess.
A claim about one width and not another (test_pages_fit_phone_css.py, test_routing_cards_css.py) sets the @media blocks
apart first (`split`), and a claim about one width of a container (the machine page's rack) its @container blocks.
"""
import re


class CssRules:
    RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
    PX = re.compile(r"(-?[\d.]+)(?:px)?")

    @classmethod
    def split(cls, css, at="media"):
        """(the stylesheet at rest, without its blocks of `at`, @media or @container; [(query, the block's text)]), comments
        left out, each query on one line: a rule read inside a block must not pass for the rule at rest."""
        block = re.compile(r"@" + re.escape(at) + r"\s*([^{]*)\{((?:[^{}]*\{[^{}]*\})*[^{}]*)\}")
        text = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        blocks = [(" ".join(m.group(1).split()), m.group(2)) for m in block.finditer(text)]
        return block.sub("", text), blocks

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
    def specificity(cls, selector):
        """(ids, classes, types) of one selector, as the cascade weighs it: attributes and pseudo-classes count as classes,
        a pseudo-element as a type, `:not(x)` and `:is(x)` as their argument, `:where(...)` as nothing."""
        s = re.sub(r":where\([^()]*\)", "", selector)
        inner = re.findall(r":(?:not|is)\(([^()]*)\)", s)
        s = re.sub(r":(?:not|is)\([^()]*\)", "", s)
        attrs = re.findall(r"\[[^\]]*\]", s)
        s = re.sub(r"\[[^\]]*\]", "", s)
        ids = len(re.findall(r"#[\w-]+", s))
        classes = len(re.findall(r"\.[\w-]+", s)) + len(attrs) + len(re.findall(r"(?<!:):(?!:)[\w-]+", s))
        types = len(re.findall(r"::[\w-]+", s)) + len(re.findall(r"(?:^|[\s>+~])([a-zA-Z][\w-]*)", s))
        for argument in inner:
            more = cls.specificity(argument)
            ids, classes, types = ids + more[0], classes + more[1], types + more[2]
        return (ids, classes, types)

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
