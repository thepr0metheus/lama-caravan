"""The three operator settings shared by every graph admission queue."""


class SharedQueuePolicy:
    FIELDS = {
        "spillPct": ("cloudFallbackPct", 20, 0, 100, "AGENT_PROXY_CLOUD_FALLBACK_PCT"),
        "stickySlotSec": ("stickySlotSec", 0, 0, 120, "AGENT_PROXY_STICKY_SLOT_SEC"),
        "loadingModelWaitSec": ("loadingModelWaitSec", 60, 0, 900, "AGENT_PROXY_LOADING_MODEL_WAIT_SEC"),
    }

    def __init__(self, policy):
        self.policy = policy if isinstance(policy, dict) else {}

    @classmethod
    def from_environment(cls, environ):
        return cls({field[0]: environ[field[4]] for field in cls.FIELDS.values() if field[4] in environ})

    def values(self):
        result = {}
        for key, (policy_key, default, minimum, maximum, _env) in self.FIELDS.items():
            try:
                value = int(self.policy.get(policy_key, default))
            except (TypeError, ValueError, OverflowError):
                value = default
            result[key] = max(minimum, min(maximum, value))
        return result

    def policy_values(self):
        return {self.FIELDS[key][0]: value for key, value in self.values().items()}
