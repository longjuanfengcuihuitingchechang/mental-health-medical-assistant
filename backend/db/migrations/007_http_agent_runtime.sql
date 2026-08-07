BEGIN IMMEDIATE;

ALTER TABLE user_sessions ADD COLUMN csrf_token_hash TEXT;
ALTER TABLE user_sessions ADD COLUMN ip_fingerprint TEXT;
ALTER TABLE user_sessions ADD COLUMN user_agent_hash TEXT;

-- v6 sessions do not have CSRF material and must not remain usable by HTTP v1.
UPDATE user_sessions
SET revoked_at = COALESCE(revoked_at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
WHERE csrf_token_hash IS NULL;

CREATE TABLE idempotency_records (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    scope TEXT NOT NULL,
    idempotency_key_hash TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    response_status INTEGER,
    response_json TEXT,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(user_id, scope, idempotency_key_hash)
);

CREATE TABLE api_rate_limits (
    bucket_key TEXT PRIMARY KEY,
    window_started_at TEXT NOT NULL,
    request_count INTEGER NOT NULL DEFAULT 0 CHECK (request_count >= 0),
    blocked_until TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE agent_runs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    agent_type TEXT NOT NULL CHECK (agent_type IN (
        'patient_page_assistant', 'doctor_work_assistant', 'assistant_work_assistant'
    )),
    assistant_session_id TEXT,
    status TEXT NOT NULL CHECK (status IN (
        'PENDING', 'QUEUED', 'RUNNING', 'WAITING_FOR_USER',
        'SUCCEEDED', 'FAILED', 'CANCELLED'
    )),
    current_node TEXT,
    input_json TEXT NOT NULL DEFAULT '{}',
    output_json TEXT,
    error_code TEXT,
    model_name TEXT,
    prompt_version TEXT,
    input_tokens INTEGER CHECK (input_tokens IS NULL OR input_tokens >= 0),
    output_tokens INTEGER CHECK (output_tokens IS NULL OR output_tokens >= 0),
    started_at TEXT,
    finished_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE agent_run_events (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    event_type TEXT NOT NULL CHECK (event_type IN (
        'run_started', 'reasoning_status', 'tool_call_started',
        'tool_call_completed', 'token', 'waiting_for_user',
        'message_completed', 'run_failed', 'heartbeat'
    )),
    data_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(run_id, sequence)
);

CREATE TABLE tool_calls (
    id TEXT PRIMARY KEY,
    agent_run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    tool_name TEXT NOT NULL,
    arguments_json TEXT NOT NULL DEFAULT '{}',
    result_summary_json TEXT,
    status TEXT NOT NULL CHECK (status IN (
        'PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED'
    )),
    latency_ms INTEGER CHECK (latency_ms IS NULL OR latency_ms >= 0),
    error_code TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE work_assistant_sessions (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    role TEXT NOT NULL CHECK (role IN ('doctor', 'assistant')),
    last_page TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'closed')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE work_assistant_messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES work_assistant_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    page TEXT NOT NULL,
    feature_key TEXT NOT NULL,
    content TEXT NOT NULL CHECK (length(content) <= 4000),
    created_at TEXT NOT NULL
);

CREATE TABLE medicine_inventory (
    id TEXT PRIMARY KEY,
    medicine_name TEXT NOT NULL,
    specification TEXT,
    quantity REAL NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    unit TEXT NOT NULL,
    batch_no_masked TEXT,
    expires_on TEXT,
    stock_status TEXT NOT NULL DEFAULT 'unknown' CHECK (stock_status IN (
        'in_stock', 'low_stock', 'out_of_stock', 'expired', 'unknown'
    )),
    source_updated_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE INDEX idx_idempotency_expires
    ON idempotency_records(expires_at);
CREATE INDEX idx_agent_runs_user_created
    ON agent_runs(user_id, created_at DESC);
CREATE INDEX idx_agent_runs_status_updated
    ON agent_runs(status, updated_at);
CREATE INDEX idx_agent_events_run_sequence
    ON agent_run_events(run_id, sequence);
CREATE INDEX idx_tool_calls_run_created
    ON tool_calls(agent_run_id, created_at);
CREATE INDEX idx_work_sessions_owner_updated
    ON work_assistant_sessions(owner_user_id, updated_at DESC);
CREATE INDEX idx_work_messages_session_time
    ON work_assistant_messages(session_id, created_at);
CREATE INDEX idx_inventory_name_status
    ON medicine_inventory(medicine_name, stock_status);
CREATE INDEX idx_inventory_expiry
    ON medicine_inventory(expires_on);

INSERT INTO schema_metadata(version) VALUES (7);
COMMIT;
