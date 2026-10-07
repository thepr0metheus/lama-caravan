"""Which commit a checkout's code is — one rule for every process that says so.

The board's /health and version chip say which commit the admin runs; the proxy
writes down the commit it started from, so that a deploy can ask it instead of
assuming. Both read the same way: `git rev-parse` of the checkout, else the
commit an image build baked into CARAVAN_GIT_HEAD (the image ships without
.git), else nothing — an empty string, never a guessed number.
"""
import os

from caravan.common.procs import run_in


class CheckoutCommit:
    """The commit of the checkout at `root`, and where the answer came from.

    `commit` is "" when neither git nor a baked value names one. `from_git` and
    `baked` say where the answer came from; `error` keeps git's own complaint
    for a caller that shows why git did not answer.
    """

    BAKED_ENV = "CARAVAN_GIT_HEAD"

    def __init__(self, root, short=False):
        head = run_in(["git", "rev-parse", *(["--short"] if short else []), "HEAD"], timeout=3, cwd=root)
        found = head["stdout"].strip() if head["ok"] else ""
        baked = "" if found else os.environ.get(self.BAKED_ENV, "").strip()
        self.commit = found or baked
        self.from_git = bool(found)
        self.baked = bool(baked)
        self.error = "" if head["ok"] else str(head["stderr"] or "").strip()
