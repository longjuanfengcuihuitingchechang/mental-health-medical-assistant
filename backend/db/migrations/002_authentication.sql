CREATE UNIQUE INDEX IF NOT EXISTS idx_users_account_nocase
    ON users(account COLLATE NOCASE);

ALTER TABLE users ADD COLUMN last_login_at TEXT;

CREATE TABLE IF NOT EXISTS login_security_states (
    account_fingerprint TEXT PRIMARY KEY,
    user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    failed_attempts INTEGER NOT NULL DEFAULT 0 CHECK (failed_attempts >= 0),
    locked_until TEXT,
    last_failed_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_sessions (
    id TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    last_seen_at TEXT,
    revoked_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_login_security_user
    ON login_security_states(user_id);
CREATE INDEX IF NOT EXISTS idx_login_security_locked_until
    ON login_security_states(locked_until);
CREATE INDEX IF NOT EXISTS idx_sessions_user_expires
    ON user_sessions(user_id, expires_at);

INSERT INTO schema_metadata(version) VALUES (2);
