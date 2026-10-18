"""What a model costs per million tokens, in the one place that says it.

The statistics panel priced a model by the operator's own price first and the LiteLLM table second. The board's spend meter priced it
by the table alone, so a price typed into the statistics panel moved that panel's figure and never the board's. A credit counted down
from the meter would have been counted at a price the operator had already corrected somewhere else. Both ask this class now.

A model nobody priced is KNOWN not to be: `known` is False and the cost it adds is 0 — and the caller says how many requests that
covered, since a figure that leaves them out without a word reads as a smaller spend.

The cache has its own two prices (1.3.585). A token read from the cache costs a fraction of a plain input token and a token written to it more than
one (the LiteLLM table names both per model: for Sonnet 5.5, 0.1 and 2.5 dollars per million against 2.0 for the input); the Console bills them so,
and an agent that sends the same long prompt again and again has nearly all of it in the cache. Priced as plain input, the meter would say many times
the truth for the reads; left out, it would say nothing for them.
"""


class ModelPrices:
    """The operator's prices laid over the LiteLLM table, both as `{model: {inputPer1M, outputPer1M[, cacheReadPer1M, cacheWritePer1M]}}`."""

    def __init__(self, table=None, overrides=None):
        self.table = table if isinstance(table, dict) else {}
        self.overrides = overrides if isinstance(overrides, dict) else {}

    def row(self, model):
        """The row that prices the model — the operator's when it names a price, else the table's — or None. A row that names neither
        number is no price, in either source."""
        for source in (self.overrides, self.table):
            row = source.get(model)
            if isinstance(row, dict) and (row.get("inputPer1M") or row.get("outputPer1M")):
                return row
        return None

    def of(self, model):
        """(inputPer1M, outputPer1M, known): the operator's price when it names one, else the table's, else (0, 0, False)."""
        row = self.row(model)
        if row is None:
            return 0.0, 0.0, False
        return float(row.get("inputPer1M") or 0), float(row.get("outputPer1M") or 0), True

    def cache_of(self, model):
        """(cacheReadPer1M, cacheWritePer1M): the same row's own cache prices, and for one it does not name — the operator's row never does, an
        old table's rows do not — the row's INPUT price. The cache is not free, and a plain input token is the nearest price there is."""
        row = self.row(model)
        if row is None:
            return 0.0, 0.0
        price_in = float(row.get("inputPer1M") or 0)

        def rate(name):
            value = row.get(name)
            return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else price_in
        return rate("cacheReadPer1M"), rate("cacheWritePer1M")

    def cost(self, model, prompt_tokens, completion_tokens, cache_read=0, cache_write=0):
        """(dollars, known) of that many tokens of the model.

        `prompt_tokens` is ALL the input, the cached and the written parts included — OpenAI's meaning, the one the journal keeps — so the plain
        input is what is left of it. A cache count that is larger than the prompt it belongs to is cut to it: the rows are never priced for more
        input than the request had."""
        price_in, price_out, known = self.of(model)
        read_price, write_price = self.cache_of(model)
        prompt = max(0, int(prompt_tokens))
        read = min(max(0, int(cache_read)), prompt)
        write = min(max(0, int(cache_write)), prompt - read)
        dollars = (prompt - read - write) * price_in + read * read_price + write * write_price + max(0, int(completion_tokens)) * price_out
        return dollars / 1e6, known
