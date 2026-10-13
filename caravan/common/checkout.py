"""Which commit a checkout's code is — one rule for every process that says so.

The board's /health and version chip say which commit the admin runs; the proxy
writes down the commit it started from, so that a deploy can ask it instead of
assuming. Both read the same way: `git rev-parse` of the checkout, else the
commit an image build baked into CARAVAN_GIT_HEAD (the image ships without
.git), else the commit `git archive` wrote into VERSION, else nothing — an
empty string, never a guessed number.
"""
import os
import re
from pathlib import Path

from caravan.common.procs import run_in


class CheckoutCommit:
    """The commit of the checkout at `root`, and where the answer came from.

    `commit` is "" when neither git, a baked value nor an archived VERSION
    names one. `from_git` and `baked` say where the answer came from (the build
    argument and VERSION are both the build's word, so both are `baked`);
    `error` keeps git's own complaint for a caller that shows why git did not
    answer.
    """

    BAKED_ENV = "CARAVAN_GIT_HEAD"
    #: The file `git archive` writes the archived commit into (`VERSION
    #: export-subst` in .gitattributes). The NAS gets its code only as such a
    #: copy and builds without a build argument: this is its one witness.
    VERSION_FILE = "VERSION"
    COMMIT_RE = re.compile(r"^[0-9a-f]{4,40}$")

    def __init__(self, root, short=False):
        head = run_in(["git", "rev-parse", *(["--short"] if short else []), "HEAD"], timeout=3, cwd=root)
        found = head["stdout"].strip() if head["ok"] else ""
        baked = "" if found else (os.environ.get(self.BAKED_ENV, "").strip() or self.archived(root))
        self.commit = found or baked
        self.from_git = bool(found)
        self.baked = bool(baked)
        self.error = "" if head["ok"] else str(head["stderr"] or "").strip()

    @classmethod
    def archived(cls, root):
        """The commit `git archive` wrote into VERSION, or "". A checkout's own
        VERSION still reads `$Format:%h$`, which names nothing, and anything
        but a commit's hex is not taken for one."""
        try:
            text = (Path(root) / cls.VERSION_FILE).read_text(encoding="utf-8").strip()
        except OSError:
            return ""
        return text if cls.COMMIT_RE.match(text) else ""
