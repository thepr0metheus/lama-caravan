"""What the program says in its source, for a guard that holds something else to it: a page, a cell server, a script. A guard reads the table where the program keeps it
rather than a copy; a table it cannot find is a failure, for then it has stopped looking at anything.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class RustSource:
    """One crate's or the whole workspace's files, by their code: what follows a file's `#[cfg(test)] mod` is its tests, and a line that is a comment says nothing."""

    CRATES = ROOT / "rust" / "crates"

    @classmethod
    def files(cls, *trees):
        """(path relative to the repository, its lines of code) of every .rs file under `trees`, each relative to rust/crates."""
        for tree in trees or (".",):
            for path in sorted((cls.CRATES / tree).rglob("*.rs")):
                # A file named tests.rs is all tests, as scripts/check_rust_contract.py reads it.
                if path.name != "tests.rs":
                    yield path.relative_to(ROOT).as_posix(), cls.code_lines(path.read_text(encoding="utf-8"))

    @staticmethod
    def code_lines(text):
        """The file's lines up to its tests, each with what follows a `//` taken off; a line of nothing else stays, empty, so that its number is the file's."""
        lines = text.split("\n")
        for at, line in enumerate(lines[:-1]):
            # A block of tests hides what follows it; `mod tests;` names a file of its own, and code may stand after it.
            if line.strip() == "#[cfg(test)]" and lines[at + 1].startswith("mod ") and lines[at + 1].rstrip().endswith("{"):
                lines = lines[:at]
                break
        return [re.sub(r"(^|\s)//.*$", "", line) for line in lines]

    @classmethod
    def words(cls, rel, name):
        """The strings of a constant array of the program: `const NAME: [&'static str; N] = ["a", "b"];`."""
        text = (cls.CRATES / rel).read_text(encoding="utf-8")
        found = re.search(rf"const {name}: \[[^=]+=\s*\[(.*?)\];", text, re.S)
        if not found:
            raise SystemExit(f"rust/crates/{rel} no longer has the table {name}: this guard is looking at nothing")
        return re.findall(r'"([^"]*)"', re.sub(r"(^|\s)//.*$", "", found.group(1), flags=re.M))

    @staticmethod
    def calls(lines, opening):
        """(line number, the text of each call that begins with `opening`, up to its closing parenthesis)."""
        text = "\n".join(lines)
        at = text.find(opening)
        while at != -1:
            depth, end, quoted = 0, at + len(opening) - 1, False
            while end < len(text):
                letter = text[end]
                if letter == '"' and text[end - 1] != "\\":
                    quoted = not quoted
                elif not quoted and letter == "(":
                    depth += 1
                elif not quoted and letter == ")":
                    depth -= 1
                    if depth == 0:
                        break
                end += 1
            yield text.count("\n", 0, at) + 1, text[at:end + 1]
            at = text.find(opening, end)
