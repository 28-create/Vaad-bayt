CREATE TABLE users (
 id INTEGER PRIMARY KEY,
 username TEXT NOT NULL UNIQUE,
 display_name TEXT NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('admin','member','viewer')),
 password_hash TEXT NOT NULL,
 salt TEXT NOT NULL,
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
 failures INTEGER NOT NULL DEFAULT 0,
 locked_until REAL NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE audit_log (
 id INTEGER PRIMARY KEY,
 ts TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 user_id INTEGER REFERENCES users(id),
 username TEXT NOT NULL DEFAULT '',
 action TEXT NOT NULL,
 entity_type TEXT NOT NULL DEFAULT '',
 entity_id TEXT NOT NULL DEFAULT '',
 details TEXT NOT NULL DEFAULT ''
);
CREATE INDEX audit_log_ts ON audit_log(ts DESC, id DESC);
CREATE TABLE attachments (
 id INTEGER PRIMARY KEY,
 entry INTEGER NOT NULL REFERENCES entries(id),
 filename TEXT NOT NULL,
 stored_name TEXT NOT NULL UNIQUE,
 size_bytes INTEGER NOT NULL DEFAULT 0,
 uploaded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 uploaded_by TEXT NOT NULL DEFAULT ''
);
CREATE INDEX attachments_entry ON attachments(entry);
CREATE TABLE bank_imports (
 id INTEGER PRIMARY KEY,
 fingerprint TEXT NOT NULL UNIQUE,
 imported_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 row_date TEXT NOT NULL,
 description TEXT NOT NULL DEFAULT '',
 amount INTEGER NOT NULL,
 direction TEXT NOT NULL CHECK(direction IN ('credit','debit')),
 reference TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL CHECK(status IN ('matched','ignored')),
 entry INTEGER REFERENCES entries(id),
 notes TEXT NOT NULL DEFAULT ''
);
CREATE INDEX bank_imports_entry ON bank_imports(entry);
CREATE TABLE backup_history (
 id INTEGER PRIMARY KEY,
 ts TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 path TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('manual','auto','pre-restore')),
 size_bytes INTEGER NOT NULL DEFAULT 0,
 attachments_count INTEGER NOT NULL DEFAULT 0,
 status TEXT NOT NULL DEFAULT 'ok'
);
CREATE INDEX backup_history_ts ON backup_history(ts DESC, id DESC);
