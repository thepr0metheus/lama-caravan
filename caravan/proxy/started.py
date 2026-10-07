"""What the running proxy says about itself: the commit it started from, and its pid.

The proxy writes this once, when it starts, into its state file; a deploy
reads it on the controller (scripts/deploy.sh, scripts/proxy_restart.py) to
decide whether the code the proxy runs has changed. The checkout's head is
not that answer: a deploy with --no-restart moves the checkout and leaves the
proxy where it was, and the next deploy would compare the wrong two commits.
The pid lets the reader tell this process's record from a dead one's.
"""
import json
import os

from caravan.common.checkout import CheckoutCommit
from caravan.proxy.paths import PROJECT_ROOT, STATE_FILE


class StartRecord:
    """`commit` — "" when unknown; `pid` — 0 when unknown. Never a guess."""

    def __init__(self, commit="", pid=0):
        self.commit = str(commit or "")
        try:
            self.pid = max(0, int(pid or 0))
        except (TypeError, ValueError):
            self.pid = 0

    @classmethod
    def at_start(cls, root=PROJECT_ROOT):
        """This process, now: the commit of the checkout it was started from."""
        return cls(CheckoutCommit(root).commit, os.getpid())

    @classmethod
    def read(cls, state_file=STATE_FILE):
        """What the state file says, or an empty record when it says nothing readable."""
        try:
            payload = json.loads(state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        if not isinstance(payload, dict):
            return cls()
        return cls(payload.get("sourceCommit"), payload.get("pid"))

    def as_state(self):
        """The two fields as the state file carries them."""
        return {"sourceCommit": self.commit, "pid": self.pid}

    def as_json(self):
        return json.dumps(self.as_state())
