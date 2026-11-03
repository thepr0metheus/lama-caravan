//! The accounts as a document on disk, and what the old database file said.

use super::*;

impl AuthStore {
    pub(super) fn read_document(path: &Path, database: &Path, stamp: &str) -> Result<Map<String, Value>, String> {
        match std::fs::read(path) {
            Ok(raw) => match serde_json::from_slice(&raw) {
                Ok(Value::Object(fields)) => Ok(fields),
                _ => {
                    Unreadable::keep(path, stamp);
                    Err(format!("{} is no accounts document", path.display()))
                }
            },
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                if !database.exists() {
                    return Ok(Self::empty());
                }
                let doc = Self::from_database(database)?;
                Self::write(path, &doc).map_err(|error| error.to_string())?;
                // absent-ok: no list is no accounts.
                let users = doc.get("users").and_then(Value::as_array).map_or(0, Vec::len);
                plumbing::Log::line(&format!(
                    "auth: {users} account(s) read from {}, kept in {} from now on",
                    database.display(),
                    path.display()
                ));
                Ok(doc)
            }
            Err(error) => Err(error.to_string()),
        }
    }

    pub(super) fn empty() -> Map<String, Value> {
        let mut doc = Map::new();
        doc.insert("users".to_string(), json!([]));
        doc.insert("sessions".to_string(), json!([]));
        doc.insert("meta".to_string(), json!({}));
        doc
    }

    pub(super) fn hex(bytes: &[u8]) -> String {
        bytes.iter().map(|byte| format!("{byte:02x}")).collect()
    }

    pub(super) fn unhex(text: &str) -> Vec<u8> {
        let digit = |letter: u8| char::from(letter).to_digit(16);
        text.as_bytes().chunks(2).filter_map(|pair| Some((digit(*pair.first()?)? * 16 + digit(*pair.get(1)?)?) as u8)).collect()
    }

    /// What the controller before this one left, as this document holds it: `users` (id, username, salt, hash, iters, created_at, role), `sessions` (token_hash, user_id, created_at, expires_at, last_seen, ip, ua), `meta` (key, value).
    pub(super) fn from_database(database: &Path) -> Result<Map<String, Value>, String> {
        Self::from_file(&SqliteFile::open(database)?)
    }

    pub(super) fn from_file(file: &SqliteFile) -> Result<Map<String, Value>, String> {
        let text = |row: &SqlRow, at: usize| row.fields.get(at).and_then(SqlValue::text).map_or_else(String::new, str::to_string);
        // absent-ok: `created_at` and its kin are NOT NULL in the old file's schema; 0 cannot be read from it.
        let int = |row: &SqlRow, at: usize| row.fields.get(at).and_then(SqlValue::int).unwrap_or(0);
        let blob = |row: &SqlRow, at: usize| row.fields.get(at).and_then(SqlValue::blob).map_or_else(String::new, Self::hex);
        let users: Vec<Value> = file
            .table("users")?
            .iter()
            .map(|row| {
                let role = text(row, 6);
                json!({"id": row.rowid, "username": text(row, 1), "salt": blob(row, 2), "hash": blob(row, 3), "iters": int(row, 4), "createdAt": int(row, 5), "role": if role.is_empty() { "admin".to_string() } else { role }})
            })
            .collect();
        let sessions: Vec<Value> = file.table("sessions")?.iter().map(|row| json!({"tokenHash": text(row, 0), "userId": int(row, 1), "createdAt": int(row, 2), "expiresAt": int(row, 3), "lastSeen": int(row, 4), "ip": text(row, 5), "ua": text(row, 6)})).collect();
        let meta: Map<String, Value> = file.table("meta")?.iter().map(|row| (text(row, 0), json!(text(row, 1)))).collect();
        let mut doc = Map::new();
        doc.insert("users".to_string(), json!(users));
        doc.insert("sessions".to_string(), json!(sessions));
        doc.insert("meta".to_string(), Value::Object(meta));
        Ok(doc)
    }

    pub(super) fn write(path: &Path, doc: &Map<String, Value>) -> std::io::Result<()> {
        AtomicFile::write_private(path, PythonJson::indented_letters(&Value::Object(doc.clone())).as_bytes())
    }
}
