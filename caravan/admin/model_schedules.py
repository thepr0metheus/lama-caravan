"""The models' schedules on the controller's file: the door the kanban's ⏱ calls, and what the
board is told. A cell's schedule follows the cell when its port changes and leaves with it
(caravan/admin/cell_outputs.py, with the cell's other names).

The rule — what a schedule says and when a model is open — is caravan/common/model_schedules.py;
the proxy keeps to it on every request (caravan/proxy/pool_steps.py). Step 1 of the visumap
scheme caravan-model-schedule (2026-10-12): the pools keep to the schedules; a cell's server is
not yet started or stopped by them.
"""
import time

from caravan.common.caravan_zone import CaravanZone
from caravan.common.cloud_sources import CloudSources
from caravan.common.errors import AppError
from caravan.common.model_schedules import ModelKey, ModelSchedules
from caravan.common.week_windows import WeekWindows


class ModelScheduleDesk:
    """When each model is open: set from the kanban and drawn on the board."""

    def __init__(self, load=None, save=None, clock=time.time, zone=None):
        # cloud.py imports the kanban's modules at the top; taken here.
        from caravan.admin.cloud import load_cloud_data, save_cloud_data
        self.load, self.save = load or load_cloud_data, save or save_cloud_data
        self.clock = clock
        self.zone = zone or CaravanZone.current()

    def _key(self, data, raw):
        parsed = ModelKey.parse(raw)
        if not parsed:
            raise AppError(f"not a model: {raw!r} — acc:<account>/<model>, or out:<srv:port | eng:id | mm:id>", 400)
        if parsed[0] == "account" and not CloudSources(data).accounts.get(parsed[1]):
            raise AppError(f"unknown account: {parsed[1]}", 404)
        return str(raw)

    def set(self, key, schedule):
        """The model's schedule from now on: `{enabled, windows}`. A schedule switched on with no
        window is refused: it would close the model for good, and no hours painted does not mean
        that. Answers the model's schedule with what it says now (ModelSchedules.state)."""
        if not isinstance(schedule, dict):
            raise AppError("schedule must be an object: {enabled, windows}")
        data = self.load()
        key = self._key(data, key)
        windows = WeekWindows.parse(schedule.get("windows"))
        enabled = schedule.get("enabled") is True
        if enabled and not windows:
            raise AppError("a schedule switched on needs a window: paint the hours the model is open, "
                           "or switch the schedule off")
        schedules = ModelSchedules(data)
        schedules.put(key, enabled, windows)
        data["schedules"] = schedules.stored()
        self.save(data)
        return schedules.state(key, self.clock(), self.zone)

    def state(self):
        """What the board draws: the caravan's zone and every model's schedule with what it says
        now — `{zone: {name, known, offsetMinutes}, now, models: {key: {enabled, windows, open,
        until, opensAt}}}`."""
        now = self.clock()
        schedules = ModelSchedules(self.load())
        return {"zone": self.zone.state(now), "now": int(now),
                "models": {key: schedules.state(key, now, self.zone) for key in sorted(schedules.kept)}}
