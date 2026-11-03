//! A store added, moved or taken off the list.

use super::*;

impl<'app> StoreRegistry<'app> {
    pub(super) fn check_new_root(&self, raw: &str, others: &[String]) -> Result<String, StoreRefused> {
        if raw.is_empty() {
            return Err(StoreRefused::refused("a path is required", "no-path", 400));
        }
        if !raw.starts_with('/') {
            return Err(StoreRefused::refused(format!("the path must be absolute: {raw}"), "not-absolute", 400));
        }
        let root = PathWord::normal(raw);
        for other in others {
            let other = PathWord::normal(other);
            if root == other {
                return Err(StoreRefused::refused(format!("{root} is already a store"), "duplicate", 409));
            }
            if root.starts_with(&format!("{}/", other.trim_end_matches('/')))
                || other.starts_with(&format!("{}/", root.trim_end_matches('/')))
            {
                return Err(StoreRefused::refused(
                    format!("{root} and {other} are nested: every model in the inner one would be counted twice"),
                    "nested",
                    409,
                ));
            }
        }
        Ok(root)
    }

    /// Adds a library, by its mark when it has one.
    pub fn add(&self, path: &str, name: &str, force: bool) -> Result<Value, StoreRefused> {
        let raw = Coerce::strip(path);
        let mut others = vec![self.local()];
        others.extend(self.saved().iter().map(|row| Coerce::text(row.get("path"))));
        let root = self.check_new_root(raw, &others)?;
        let bytes =
            Randomness::bytes(4).ok_or_else(|| StoreRefused::refused("the system gives no random bytes", "no-random", 500))?;
        let new_id = format!("lib-{}", bytes.iter().map(|byte| format!("{byte:02x}")).collect::<String>());
        let base = root.rsplit('/').next().filter(|word| !word.is_empty()).unwrap_or(&root).to_string();
        let label = if Coerce::strip(name).is_empty() { base } else { Coerce::strip(name).to_string() };
        let answer = self.memory().probe.claim(&root, &new_id, &label, force);
        let error_of = |answer: &Value, otherwise: &str| {
            if Coerce::truthy(answer.get("error")) { Coerce::text(answer.get("error")) } else { otherwise.to_string() }
        };
        if !Coerce::truthy(answer.get("ok")) {
            return Err(StoreRefused::refused(
                format!("{root} does not answer: {}", error_of(&answer, "the probe failed")),
                "unreachable",
                504,
            ));
        }
        if !Coerce::truthy(answer.get("exists")) {
            return Err(StoreRefused::refused(format!("no directory at {root}"), "missing", 404));
        }
        match Coerce::text(answer.get("refused")).as_str() {
            "" => {}
            "not-a-mount" => {
                return Err(StoreRefused::refused(
                    format!(
                        "{root} is not a mount point and carries no library mark: if the share did not mount, this is an empty local folder, and marking it would make the local disk pose as the library"
                    ),
                    "not-a-mount",
                    409,
                ));
            }
            refused => {
                return Err(StoreRefused::refused(
                    format!("cannot write the library mark into {root}: {}", error_of(&answer, refused)),
                    refused,
                    409,
                ));
            }
        }
        let mark = answer.get("marker").cloned().unwrap_or_else(|| json!({}));
        let store_id = if Coerce::truthy(mark.get("id")) { Coerce::text(mark.get("id")) } else { new_id };
        let mut rows = self.saved();
        if rows.iter().any(|row| Coerce::str_of(row.get("id")) == store_id) {
            return Err(StoreRefused::refused(format!("this library is already on the list (id {store_id})"), "duplicate", 409));
        }
        let name = if Coerce::truthy(mark.get("name")) { Coerce::text(mark.get("name")) } else { label };
        rows.push(json!({"id": store_id, "name": name, "path": root}));
        self.put_saved(rows);
        self.cache().remove(&store_id);
        let mut out = ModelStore { id: store_id, name, path: root, role: "library", builtin: false }.to_json();
        out.insert("adopted".to_string(), json!(Coerce::truthy(answer.get("adopted"))));
        Ok(Value::Object(out))
    }

    /// Points a library at another path on THIS host: the share moved, or its mount point did.
    pub fn repath(&self, store_id: &str, path: &str) -> Result<Value, StoreRefused> {
        let sid = Coerce::strip(store_id);
        if sid == Self::LOCAL_ID {
            return Err(StoreRefused::refused(
                "the controller's own models directory is changed with ✎ on the page",
                "builtin",
                409,
            ));
        }
        let mut rows = self.saved();
        let Some(at) = rows.iter().position(|row| Coerce::str_of(row.get("id")) == sid) else {
            return Err(StoreRefused::refused(format!("no such store: {sid}"), "unknown-id", 404));
        };
        let raw = Coerce::strip(path);
        let current = rows.get(at).map_or_else(String::new, |row| Coerce::text(row.get("path")));
        if raw.starts_with('/') && PathWord::normal(raw) == PathWord::normal(&current) {
            return Ok(json!({"store": rows.get(at)}));
        }
        let mut others = vec![self.local()];
        others.extend(rows.iter().filter(|row| Coerce::str_of(row.get("id")) != sid).map(|row| Coerce::text(row.get("path"))));
        let root = self.check_new_root(raw, &others)?;
        let answer = self.memory().probe.look(&root, false);
        if !Coerce::truthy(answer.get("ok")) {
            let words = if Coerce::truthy(answer.get("error")) {
                Coerce::text(answer.get("error"))
            } else {
                "the probe failed".to_string()
            };
            return Err(StoreRefused::refused(format!("{root} does not answer: {words}"), "unreachable", 504));
        }
        let Some(mark) = answer.get("marker").filter(|mark| mark.is_object() && Coerce::truthy(Some(*mark))) else {
            return Err(StoreRefused::refused(
                format!("{root} carries no library mark: the share is not mounted there"),
                "not-a-mount",
                409,
            ));
        };
        if Coerce::str_of(mark.get("id")) != sid {
            let other =
                if Coerce::truthy(mark.get("name")) { Coerce::text(mark.get("name")) } else { Coerce::str_of(mark.get("id")) };
            return Err(StoreRefused::refused(format!("{root} holds another library: {other}"), "other-library", 409));
        }
        if let Some(row) = rows.get_mut(at) {
            row["path"] = json!(root);
        }
        let row = rows.get(at).cloned();
        self.put_saved(rows);
        self.cache().remove(sid);
        Ok(json!({"store": row}))
    }

    /// Takes a library off the list; its files stay where they are.
    pub fn remove(&self, store_id: &str) -> Result<Value, StoreRefused> {
        let sid = Coerce::strip(store_id);
        if sid == Self::LOCAL_ID {
            return Err(StoreRefused::refused(
                "the controller's own models directory is changed with ✎, not removed",
                "builtin",
                409,
            ));
        }
        let rows = self.saved();
        let keep: Vec<Value> = rows.iter().filter(|row| Coerce::str_of(row.get("id")) != sid).cloned().collect();
        if keep.len() == rows.len() {
            return Err(StoreRefused::refused(format!("no such store: {sid}"), "unknown-id", 404));
        }
        self.put_saved(keep);
        self.cache().remove(sid);
        Ok(json!({"removed": sid}))
    }
}
