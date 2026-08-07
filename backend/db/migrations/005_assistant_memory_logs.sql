CREATE TABLE IF NOT EXISTS assistant_sessions (
    id TEXT PRIMARY KEY,
    patient_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    last_page TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'closed')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assistant_messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES assistant_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    page TEXT NOT NULL,
    feature_key TEXT NOT NULL,
    content TEXT NOT NULL CHECK (length(content) <= 4000),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS patient_feature_usage (
    patient_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    page TEXT NOT NULL,
    feature_key TEXT NOT NULL,
    usage_count INTEGER NOT NULL DEFAULT 0 CHECK (usage_count >= 0),
    introduction_count INTEGER NOT NULL DEFAULT 0 CHECK (introduction_count BETWEEN 0 AND 8),
    first_used_at TEXT NOT NULL,
    last_used_at TEXT NOT NULL,
    PRIMARY KEY (patient_user_id, page, feature_key)
);

CREATE TABLE IF NOT EXISTS patient_feature_usage_logs (
    id TEXT PRIMARY KEY,
    patient_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    session_id TEXT NOT NULL REFERENCES assistant_sessions(id) ON DELETE RESTRICT,
    page TEXT NOT NULL,
    feature_key TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK (event_type IN ('page_open', 'feature_open', 'message')),
    usage_count INTEGER NOT NULL CHECK (usage_count >= 0),
    introduction_shown INTEGER NOT NULL CHECK (introduction_shown IN (0, 1)),
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_assistant_sessions_patient_updated
    ON assistant_sessions(patient_user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_assistant_messages_session_time
    ON assistant_messages(session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_feature_logs_patient_time
    ON patient_feature_usage_logs(patient_user_id, created_at DESC);

INSERT INTO schema_metadata(version) VALUES (5);
