ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0
    CHECK (must_change_password IN (0, 1));

CREATE TABLE IF NOT EXISTS person_profiles (
    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE RESTRICT,
    id_card_fingerprint TEXT NOT NULL UNIQUE,
    id_card_masked TEXT NOT NULL,
    phone_masked TEXT NOT NULL,
    email_masked TEXT NOT NULL,
    birth_date TEXT NOT NULL,
    gender TEXT NOT NULL CHECK (gender IN ('male', 'female', 'unknown')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_login_identifiers (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    identifier_type TEXT NOT NULL CHECK (identifier_type IN ('account', 'phone', 'email')),
    identifier_fingerprint TEXT NOT NULL UNIQUE,
    identifier_masked TEXT NOT NULL,
    verified INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0, 1)),
    created_at TEXT NOT NULL,
    UNIQUE(user_id, identifier_type)
);

CREATE TABLE IF NOT EXISTS registration_requests (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL UNIQUE REFERENCES users(id) ON DELETE RESTRICT,
    requested_role TEXT NOT NULL CHECK (requested_role = 'doctor'),
    status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected')),
    department TEXT NOT NULL,
    professional_title TEXT,
    submitted_at TEXT NOT NULL,
    reviewed_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    reviewed_at TEXT,
    review_note TEXT
);

CREATE TABLE IF NOT EXISTS account_sequences (
    prefix TEXT PRIMARY KEY CHECK (prefix IN ('A', 'D', 'P')),
    next_value INTEGER NOT NULL CHECK (next_value >= 1)
);

INSERT OR IGNORE INTO account_sequences(prefix, next_value) VALUES
    ('A', 1), ('D', 1), ('P', 1);

CREATE INDEX IF NOT EXISTS idx_login_identifier_user
    ON user_login_identifiers(user_id);
CREATE INDEX IF NOT EXISTS idx_registration_status_submitted
    ON registration_requests(status, submitted_at);

INSERT INTO schema_metadata(version) VALUES (3);
