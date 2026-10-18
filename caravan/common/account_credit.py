"""The credit the operator says a key account has left, and from when it counts.

A provider does not tell. Anthropic's Console shows "Organization credits"; its API has no call for it (the Admin API reports what was
spent and what the spend limits are, not what is left), and OpenAI's keys read no balance either. The board therefore holds the figure
the operator types — what the console shows NOW — and the moment it was typed, and takes from it what went through the caravan since
(the proxy's logs, priced: cloud_api.cloud_spend_summary). An estimate, said as one wherever it is shown: what the same key spent
anywhere else is not in it.

The figure is the account's `credit`, `{"amountUsd", "asOf"}`. An edit sends `creditUsd`: blank takes the credit away, the figure it
already holds keeps its moment (a rename must not move it), any other figure starts counting now.
"""
import math

from caravan.common.errors import AppError


class AccountCredit:
    #: A figure above this is a typing slip, not a credit.
    LIMIT = 1_000_000_000

    @classmethod
    def amount(cls, raw):
        """Dollars, to the cent, from what the operator typed; None for blank. A decimal comma is read as a point: the figure is
        typed by hand, in the operator's own language."""
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            return None
        try:
            value = float(str(raw).strip().replace(",", "."))
        except ValueError:
            raise AppError("credit must be a number of dollars", 400)
        if not math.isfinite(value) or value < 0 or value > cls.LIMIT:
            raise AppError(f"credit must be a number of dollars from 0 to {cls.LIMIT}", 400)
        return round(value, 2)

    @staticmethod
    def kept(stored):
        """The credit as a file holds it, or None when what stands there is no credit (a file edited by hand): dropped, not guessed."""
        if not isinstance(stored, dict):
            return None
        amount, as_of = stored.get("amountUsd"), stored.get("asOf")
        if isinstance(amount, bool) or isinstance(as_of, bool) or not isinstance(amount, (int, float)) or not isinstance(as_of, (int, float)):
            return None
        if not math.isfinite(amount) or amount < 0:
            return None
        return {"amountUsd": float(amount), "asOf": int(as_of)}

    @classmethod
    def resolve(cls, account, now):
        """The `credit` to store, `{"amountUsd", "asOf"}`, or None for none. `account` is the stored account with the edit laid
        over it: an edit that names `creditUsd` replaces the credit, one that does not leaves what is stored."""
        stored = cls.kept(account.get("credit"))
        if "creditUsd" not in account:
            return stored
        amount = cls.amount(account["creditUsd"])
        if amount is None:
            return None
        if stored and stored["amountUsd"] == amount:
            return stored
        return {"amountUsd": amount, "asOf": int(now)}
