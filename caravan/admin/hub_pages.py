"""A list the hub sends in pages, read to its end.

The tree of a repository comes with the details the caravan reads (`expand=true`:
each file's LFS record, its last commit) in pages of 50, and the hub names the next
page in the `Link: <url>; rel="next"` header of the answer. The caravan read the
first answer and took it for the repository. openbmb/MiniCPM-o-4_5-awq
(2026-10-15) has 75 files: the first 50 entries were the folder `assets/` (sounds,
the speech decoder's files), and the weights `model-0000x-of-00002.safetensors`
were listed after it. The checkpoint's row read "34 files · 1.4 GB" and its button
would have downloaded the extras without the model. Nothing on the page said the
list was cut.

So the rule is one: a list is read to its end, or the read is an error. A short
list that looks whole is the one answer nobody can tell from a right one.
"""
import re
import urllib.parse


class HubPagesError(Exception):
    """The list could not be read to its end; what was read is not handed back."""


class HubPages:
    """One list of the hub's API, read page by page."""

    #: The most entries one page may hold when `expand` is asked for: the hub
    #: answers 400 to `limit=1000` and 50 when no limit is given.
    PAGE_SIZE = 100
    #: A repository of 5,000 entries is more than any one the page lists. Past
    #: that the read stops with an error: a list cut short must not pass as whole.
    MAX_PAGES = 50
    #: The only address a next page may have. The request carries the operator's
    #: token: a header that sent it elsewhere would carry the token there.
    HOST = "huggingface.co"
    API_PATH = "/api/"

    _NEXT = re.compile(r'<([^>]*)>\s*;[^,]*?\brel="?next"?(?![\w-])', re.IGNORECASE)

    def __init__(self, get):
        """`get(url)` answers `(the parsed JSON, the Link header or "")`; it raises
        for whatever it cannot read."""
        self.get = get

    @classmethod
    def sized(cls, url):
        """`url` asking for the largest page, unless it names a size already."""
        parts = urllib.parse.urlsplit(url)
        query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
        if any(key == "limit" for key, _ in query):
            return url
        query.append(("limit", str(cls.PAGE_SIZE)))
        return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))

    @classmethod
    def next_url(cls, link):
        """The next page the `Link` header names; "" when it names none.

        A next page outside the hub's API is refused with an error, never followed."""
        found = cls._NEXT.search(str(link or ""))
        if not found:
            return ""
        url = found.group(1).strip()
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "https" or parts.hostname != cls.HOST or not parts.path.startswith(cls.API_PATH):
            raise HubPagesError(f"the hub named a next page outside its API: {url[:120]}")
        return url

    def read(self, url):
        """Every entry of the list at `url`, in the hub's order.

        An answer that is not a list (an error object) is returned as it came when
        it is the first one, and is an error on any later page."""
        entries = []
        page = self.sized(url)
        for number in range(self.MAX_PAGES):
            data, link = self.get(page)
            if not isinstance(data, list):
                if number == 0:
                    return data
                raise HubPagesError("a page after the first was not a list")
            entries.extend(data)
            page = self.next_url(link)
            if not page:
                return entries
        raise HubPagesError(f"the list has more than {self.PAGE_SIZE * self.MAX_PAGES} entries; it was not read to the end")
