"""The operator's reserve on a subscription account, as the controller keeps and shows it.

The reserve is stored on the account (cloud-providers.json, `usageReserve`) and
enforced by the proxy, which reads each account's windows off the answers it
gets (caravan/proxy/subscription_usage.py) and writes its last reading into its
state file. The card's banner is the proxy's verdict: computed here from that
reading with the same rule the proxy enforces (caravan/common/usage_reserve.py),
so the card says what the proxy does, not what it might do.
"""
import json
import time

from caravan.admin.cloud import load_cloud_data, save_cloud_data
from caravan.admin.paths import AGENT_PROXY_STATE_FILE
from caravan.common.errors import AppError
from caravan.common.usage_reserve import UsageReserve


class UsageReserveDesk:
    """Set a window's reserve on an account; read what the proxy enforces now."""

    SUBSCRIPTION = "openai-subscription"

    def __init__(self, state_file=AGENT_PROXY_STATE_FILE, clock=time.time):
        self.state_file = state_file
        self.clock = clock

    def set(self, account_id, window_seconds, pct):
        """Keep `pct` percent of the window for the operator; 0 lifts the reserve.
        Returns the account's whole reserve after the change."""
        account_id = str(account_id or "").strip()
        try:
            seconds, pct = int(window_seconds), int(pct)
        except (TypeError, ValueError):
            raise AppError("windowSeconds and pct must be numbers", 400)
        if seconds <= 0:
            raise AppError("windowSeconds must be positive", 400)
        if not 0 <= pct <= UsageReserve.MAX_PCT:
            raise AppError(f"pct must be 0..{UsageReserve.MAX_PCT}", 400)
        data = load_cloud_data()
        account = next((a for a in data["accounts"] if a.get("id") == account_id), None)
        if account is None:
            raise AppError(f"unknown account {account_id}", 404)
        if str(account.get("accountType") or "") != self.SUBSCRIPTION:
            # Only a subscription states its windows; a reserve elsewhere would
            # be a setting that silently does nothing.
            raise AppError("a reserve is kept only on a ChatGPT subscription account", 400)
        reserve = UsageReserve.normalize(account.get("usageReserve"))
        if pct:
            reserve[str(seconds)] = pct
        else:
            reserve.pop(str(seconds), None)
        if reserve:
            account["usageReserve"] = reserve
        else:
            account.pop("usageReserve", None)
        save_cloud_data(data)
        return reserve

    def reading(self, account_id):
        """The proxy's last reading of the account's windows, or None — never a made-up one."""
        try:
            payload = json.loads(self.state_file.read_text(encoding="utf-8"))
        except Exception:
            return None
        rows = payload.get("subscriptionUsage") if isinstance(payload, dict) else None
        row = rows.get(str(account_id or "")) if isinstance(rows, dict) else None
        return row if isinstance(row, dict) and isinstance(row.get("windows"), list) else None

    def view(self, account_id):
        """What the card shows beside the bars: the reserve, the proxy's verdict, and the reading's age."""
        account = next((a for a in load_cloud_data()["accounts"] if a.get("id") == str(account_id or "")), None)
        reserve = UsageReserve.normalize((account or {}).get("usageReserve"))
        reading = self.reading(account_id)
        kept = UsageReserve(reserve).verdict(reading["windows"], self.clock()) if reading else None
        return {"reserve": reserve, "reserveKept": kept, "reserveMax": UsageReserve.MAX_PCT,
                "reserveReadAt": int(reading["readAt"]) if reading and reading.get("readAt") else None}
