//! The models' schedules on the controller's file. When each model is open is the operator's to paint; what the
//! proxy does with it is the proxy's.

use super::data::CloudData;
use crate::app::App;
use crate::common::cloud_file::{ModelKey, ModelSchedules, WeekWindows};
use crate::common::cloud_sources::CloudSources;
use crate::common::zone::CaravanZone;
use rules::{AppError, PyRepr};
use serde_json::{Map, Value, json};

/// The desk of the schedules.
pub struct ModelScheduleDesk<'app> {
    app: &'app App,
}

impl<'app> ModelScheduleDesk<'app> {
    /// The desk of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    fn zone(&self) -> CaravanZone {
        CaravanZone::current(self.app.env.get("TZ"), std::path::Path::new("/etc/localtime"))
    }

    fn checked_key(data: &Value, raw: &Value) -> Result<String, AppError> {
        let text = raw.as_str().map_or_else(|| PyRepr::of_value(raw), PyRepr::of);
        // absent-ok: what is no word names no model, refused just below.
        let said = raw.as_str().unwrap_or_default();
        let parsed = ModelKey::parse(said).ok_or_else(|| {
            AppError::new(format!("not a model: {text} — acc:<account>/<model>, or out:<srv:port | eng:id | mm:id>"))
        })?;
        if parsed.0 == "account" && CloudSources::new(data, None).accounts().get(&parsed.1).is_none() {
            return Err(AppError::with_status(format!("unknown account: {}", parsed.1), 404));
        }
        Ok(said.to_string())
    }

    /// The model's schedule from now on.
    pub fn set(&self, key: &Value, schedule: &Value) -> Result<Option<Value>, AppError> {
        if !schedule.is_object() {
            return Err(AppError::new("schedule must be an object: {enabled, windows}"));
        }
        let cloud = CloudData::of(self.app);
        let mut data = cloud.load();
        let key = Self::checked_key(&data, key)?;
        let windows = WeekWindows::parse(schedule.get("windows"))?;
        let enabled = schedule.get("enabled") == Some(&json!(true));
        if enabled && windows.is_empty() {
            return Err(AppError::new(
                "a schedule switched on needs a window: paint the hours the model is open, or switch the schedule off",
            ));
        }
        let mut schedules = ModelSchedules::new(&data);
        schedules.put(&key, enabled, Some(&Value::Array(windows)));
        rules::Coerce::put(&mut data, "schedules", schedules.stored());
        cloud.save(&data)?;
        Ok(schedules.state(&key, self.app.now(), &self.zone()))
    }

    /// What the board draws.
    pub fn state(&self) -> Value {
        let now = self.app.now();
        let zone = self.zone();
        let schedules = ModelSchedules::new(&CloudData::of(self.app).load());
        let stored = schedules.stored();
        let mut keys: Vec<&String> = stored.as_object().map_or_else(Vec::new, |kept| kept.keys().collect());
        keys.sort();
        let mut models = Map::new();
        for key in keys {
            models.insert(key.clone(), schedules.state(key, now, &zone).unwrap_or(Value::Null));
        }
        json!({"zone": zone.state(now as i64), "now": now as i64, "models": models})
    }
}
