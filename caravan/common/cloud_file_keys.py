"""What cloud-providers.json keeps beside its accounts and pools — one table for every reader
and writer of the file.

Until 1.3.498 three lists named these keys: the controller's reading and its writing
(caravan/admin/cloud.py) and the proxy's reading (caravan/proxy/cloud_auth.py). A key one list
lacked was dropped by the next save of anything, or never reached the proxy — each new key had
to be added in three places, and the next one would have been missed in one of them.
"""


class CloudFileKeys:
    """The kept keys, each with the shape it holds. A key whose value is empty or of another
    shape is not written: an empty map and no map read the same."""

    #: levels — the subscription models' levels (caravan/common/model_levels.py);
    #: addedModels — the models on Routing's right column (caravan/admin/added_models.py);
    #: boardProviders — the providers on the main board (caravan/admin/board_providers.py);
    #: sets — the entry clients' sets of models (caravan/admin/model_sets.py);
    #: schedules — when each model is open (caravan/common/model_schedules.py).
    KEPT = {"levels": dict, "addedModels": dict, "boardProviders": list, "sets": list, "schedules": dict}

    @classmethod
    def read(cls, parsed):
        """The kept keys a parsed file holds, each only when it has the right shape and is not empty."""
        parsed = parsed if isinstance(parsed, dict) else {}
        return {key: parsed[key] for key, shape in cls.KEPT.items()
                if isinstance(parsed.get(key), shape) and parsed[key]}

    @classmethod
    def read_all(cls, parsed):
        """Every kept key, an empty one of its shape where the file has none — the proxy's reading,
        which never asks whether a key is there."""
        found = cls.read(parsed)
        return {key: found.get(key, shape()) for key, shape in cls.KEPT.items()}

    @classmethod
    def written(cls, data):
        """The kept keys a save writes: the same rule as the reading."""
        return cls.read(data)
