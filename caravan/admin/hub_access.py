"""Why the hub shut the door on a download, and the page where a person opens it.

A gated repository (nvidia/personaplex-7b-v1, 2026-10-15) lists its files to anyone and
refuses the files themselves — HTTP 403 — until the owner of the token has accepted its
terms on its page. The job ended with `HTTP Error 403: Forbidden` after a pause and a
second try, and nothing said which page to go to: the operator found it by asking.

Two things are said here, once. The hub's refusal is a WALL: 401 and 403 are the same
answer every time, so a job does not wait and ask again (downloads.py). And a wall at a
GATED repository has an address: the repository's own page, where the terms are accepted.
That address goes to the job as `access`, and the /hf page opens it.

A wall at a repository that is not gated (a private one, a token the hub no longer knows)
names no page to go to. It stays what it was, an error row with the hub's words.
"""
import json
import urllib.error
import urllib.parse
import urllib.request


class HubAccess:
    """The hub's refusal of one repository's file, and what to do about it."""

    #: The statuses that answer the same way every time: no login, no terms.
    WALLS = (401, 403)
    SITE = "https://huggingface.co/"

    def __init__(self, repo, status, token_set):
        self.repo = repo
        self.status = status
        self.token_set = bool(token_set)

    @classmethod
    def is_wall(cls, exc):
        """True for the hub's refusal itself, and for nothing a retry could change."""
        return isinstance(exc, urllib.error.HTTPError) and exc.code in cls.WALLS

    @classmethod
    def page(cls, repo):
        """The repository's page: where its terms are read and accepted."""
        return cls.SITE + urllib.parse.quote(repo, safe="/")

    @staticmethod
    def gate_of(repo, token, timeout=8):
        """What the repository's record says about its gate: "auto", "manual" or False for an
        open one; None when the record could not be read (the hub did not answer): unknown is
        not "open"."""
        headers = {"User-Agent": "lama-caravan/1.0"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        url = HubAccess.SITE + "api/models/" + urllib.parse.quote(repo, safe="/")
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
                record = json.loads(r.read().decode("utf-8"))
        except Exception:
            return None
        gate = record.get("gated") if isinstance(record, dict) else None
        return gate if gate in ("auto", "manual") else (False if gate is False else None)

    @classmethod
    def after(cls, exc, repo, token):
        """What a failed download says about the gate: an HubAccess when the hub's wall
        stands at a gated repository, else None. Reads the repository's record once."""
        if not cls.is_wall(exc):
            return None
        gate = cls.gate_of(repo, token)
        return cls(repo, exc.code, token) if gate in ("auto", "manual") else None

    def as_dict(self):
        """The job's `access`: the page to open, and whether a token is saved at all."""
        return {"kind": "gated", "url": self.page(self.repo), "repo": self.repo,
                "status": self.status, "tokenSet": self.token_set}
