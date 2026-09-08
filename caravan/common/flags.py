"""What counts as "yes" — one answer for the whole caravan.

The flag arrives from three directions and is meant to say the same thing:
the query string (`?force=true`), a cell config (`OFFLOAD_MMPROJ=on`), and a
request body. Each side parsed it its own way, and the vocabularies drifted:
the config accepted `1/true/yes/on`, the query string `1/true/yes`, and two
parameters both named `force` understood only the literal `"1"`.

The drift was silent, and that is the whole problem. `?force=true` read as
"no": the caller asked for fresh data, got a 200 and a cached answer, and
nothing anywhere said the flag had been dropped. A browser always sends `=1`
and so never suffered — the one who suffered was a person driving diagnostics
by hand, which is a documented way to use this API.
"""


def truthy(value) -> bool:
    """`1`, `true`, `yes`, `on` — any case, with stray whitespace trimmed.

    Everything else, including an empty string and a missing value, is no.
    The list is deliberately closed: "accept anything non-empty" would turn
    `?force=0` into consent.
    """
    return str(value).strip().lower() in ("1", "true", "yes", "on")
