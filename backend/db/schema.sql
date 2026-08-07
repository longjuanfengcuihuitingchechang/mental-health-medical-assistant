PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_metadata (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    account TEXT NOT NULL UNIQUE,
    password_hash TEXT,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('patient', 'doctor', 'assistant', 'admin', 'super_admin')),
    account_status TEXT NOT NULL DEFAULT 'active'
        CHECK (account_status IN ('active', 'disabled', 'locked', 'pending')),
    blacklisted INTEGER NOT NULL DEFAULT 0 CHECK (blacklisted IN (0, 1)),
    last_login_at TEXT,
    must_change_password INTEGER NOT NULL DEFAULT 0
        CHECK (must_change_password IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS patient_profiles (
    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE RESTRICT,
    medical_record_no TEXT NOT NULL UNIQUE,
    assigned_doctor_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS doctor_profiles (
    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE RESTRICT,
    employee_no TEXT NOT NULL UNIQUE,
    department TEXT,
    professional_title TEXT,
    employment_status TEXT NOT NULL DEFAULT 'active'
        CHECK (employment_status IN ('active', 'leave', 'resigned', 'retired')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS admin_profiles (
    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE RESTRICT,
    employee_no TEXT UNIQUE,
    department TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS assistant_profiles (
    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE RESTRICT,
    employee_no TEXT NOT NULL UNIQUE,
    employment_status TEXT NOT NULL DEFAULT 'active'
        CHECK (employment_status IN ('active', 'leave', 'resigned')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY,
    actor_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    filters_json TEXT NOT NULL DEFAULT '{}',
    result_count INTEGER NOT NULL DEFAULT 0 CHECK (result_count >= 0),
    status TEXT NOT NULL CHECK (status IN ('success', 'denied', 'failed')),
    error_code TEXT,
    request_id TEXT,
    ip_fingerprint TEXT,
    resource_fingerprint TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TRIGGER IF NOT EXISTS audit_events_append_only_update
BEFORE UPDATE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events is append-only');
END;

CREATE TRIGGER IF NOT EXISTS audit_events_append_only_delete
BEFORE DELETE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events is append-only');
END;

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
    revoked_at TEXT,
    csrf_token_hash TEXT,
    ip_fingerprint TEXT,
    user_agent_hash TEXT
);

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
    prefix TEXT PRIMARY KEY CHECK (prefix IN ('A', 'D', 'P', 'S')),
    next_value INTEGER NOT NULL CHECK (next_value >= 1)
);

CREATE TABLE IF NOT EXISTS doctor_availability (
    doctor_user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE RESTRICT,
    availability_status TEXT NOT NULL DEFAULT 'unknown'
        CHECK (availability_status IN ('working', 'off_duty', 'on_leave', 'unavailable', 'unknown')),
    status_since TEXT NOT NULL,
    expected_available_at TEXT,
    note TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clinical_visit_summaries (
    id TEXT PRIMARY KEY,
    patient_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    doctor_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    visited_at TEXT NOT NULL,
    visit_type TEXT NOT NULL DEFAULT 'consultation',
    care_summary TEXT,
    status TEXT NOT NULL DEFAULT 'completed'
        CHECK (status IN ('scheduled', 'completed', 'cancelled')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS consultation_queue (
    id TEXT PRIMARY KEY,
    doctor_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    patient_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    status TEXT NOT NULL DEFAULT 'waiting'
        CHECK (status IN ('waiting', 'called', 'completed', 'cancelled')),
    joined_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS minor_guardian_consents (
    patient_user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE RESTRICT,
    consent_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (consent_status IN ('pending', 'granted', 'revoked')),
    guardian_relation TEXT,
    granted_at TEXT,
    updated_at TEXT NOT NULL
);

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

CREATE TABLE IF NOT EXISTS doctor_daily_capacities (
    doctor_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    appointment_date TEXT NOT NULL,
    capacity INTEGER NOT NULL CHECK (capacity BETWEEN 0 AND 1000),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (doctor_user_id, appointment_date)
);

CREATE TABLE IF NOT EXISTS patient_appointments (
    id TEXT PRIMARY KEY,
    patient_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    doctor_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    appointment_date TEXT NOT NULL,
    queue_number INTEGER NOT NULL CHECK (queue_number >= 1),
    status TEXT NOT NULL CHECK (status IN (
        'queued', 'awaiting_patient_decision', 'change_requested',
        'awaiting_doctor_decision', 'queued_over_capacity',
        'declined_direct', 'declined_gentle', 'completed', 'cancelled'
    )),
    patient_decision TEXT CHECK (patient_decision IN ('switch_doctor', 'continue_request')),
    doctor_decision TEXT CHECK (doctor_decision IN ('accept', 'decline')),
    communication_mode TEXT CHECK (communication_mode IN ('direct', 'gentle')),
    patient_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS appointment_events (
    id TEXT PRIMARY KEY,
    appointment_id TEXT NOT NULL REFERENCES patient_appointments(id) ON DELETE RESTRICT,
    actor_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS doctor_night_shifts (
    shift_date TEXT PRIMARY KEY,
    doctor_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    assigned_by_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS idempotency_records (
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

CREATE TABLE IF NOT EXISTS api_rate_limits (
    bucket_key TEXT PRIMARY KEY,
    window_started_at TEXT NOT NULL,
    request_count INTEGER NOT NULL DEFAULT 0 CHECK (request_count >= 0),
    blocked_until TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_runs (
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

CREATE TABLE IF NOT EXISTS agent_run_events (
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

CREATE TABLE IF NOT EXISTS tool_calls (
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

CREATE TABLE IF NOT EXISTS work_assistant_sessions (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    role TEXT NOT NULL CHECK (role IN ('doctor', 'assistant')),
    last_page TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'closed')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS work_assistant_messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES work_assistant_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    page TEXT NOT NULL,
    feature_key TEXT NOT NULL,
    content TEXT NOT NULL CHECK (length(content) <= 4000),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS medicine_inventory (
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

CREATE TABLE IF NOT EXISTS async_tasks (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    task_type TEXT NOT NULL CHECK (task_type IN (
        'patient_page_assistant', 'doctor_work_assistant', 'assistant_work_assistant'
    )),
    role TEXT NOT NULL CHECK (role IN ('patient', 'doctor', 'assistant')),
    status TEXT NOT NULL CHECK (status IN (
        'PENDING', 'QUEUED', 'RUNNING', 'WAITING_FOR_USER',
        'SUCCEEDED', 'FAILED', 'CANCELLED'
    )),
    input_json TEXT NOT NULL,
    output_json TEXT,
    error_code TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK (cancel_requested IN (0, 1)),
    timeout_seconds REAL NOT NULL CHECK (timeout_seconds > 0),
    started_at TEXT,
    finished_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS async_task_events (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES async_tasks(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    event_type TEXT NOT NULL CHECK (event_type IN (
        'task.created', 'task.started', 'message.delta', 'task.waiting',
        'task.completed', 'task.failed', 'task.cancelled', 'heartbeat'
    )),
    data_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(task_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_users_role_status
    ON users(role, account_status);
CREATE INDEX IF NOT EXISTS idx_users_blacklisted
    ON users(blacklisted);
CREATE INDEX IF NOT EXISTS idx_users_display_name
    ON users(display_name);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_account_nocase
    ON users(account COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_doctor_employment_status
    ON doctor_profiles(employment_status);
CREATE INDEX IF NOT EXISTS idx_patient_assigned_doctor
    ON patient_profiles(assigned_doctor_user_id);
CREATE INDEX IF NOT EXISTS idx_audit_actor_created
    ON audit_events(actor_user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_audit_action_created
    ON audit_events(action, created_at);
CREATE INDEX IF NOT EXISTS idx_audit_request_id
    ON audit_events(request_id);
CREATE INDEX IF NOT EXISTS idx_audit_resource_created
    ON audit_events(target_type, resource_fingerprint, created_at);
CREATE INDEX IF NOT EXISTS idx_login_security_user
    ON login_security_states(user_id);
CREATE INDEX IF NOT EXISTS idx_login_security_locked_until
    ON login_security_states(locked_until);
CREATE INDEX IF NOT EXISTS idx_sessions_user_expires
    ON user_sessions(user_id, expires_at);
CREATE INDEX IF NOT EXISTS idx_login_identifier_user
    ON user_login_identifiers(user_id);
CREATE INDEX IF NOT EXISTS idx_registration_status_submitted
    ON registration_requests(status, submitted_at);
CREATE INDEX IF NOT EXISTS idx_doctor_availability_status
    ON doctor_availability(availability_status);
CREATE INDEX IF NOT EXISTS idx_visit_patient_time
    ON clinical_visit_summaries(patient_user_id, visited_at DESC);
CREATE INDEX IF NOT EXISTS idx_visit_doctor_time
    ON clinical_visit_summaries(doctor_user_id, visited_at DESC);
CREATE INDEX IF NOT EXISTS idx_queue_doctor_status_time
    ON consultation_queue(doctor_user_id, status, joined_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_queue_active_patient
    ON consultation_queue(doctor_user_id, patient_user_id)
    WHERE status IN ('waiting', 'called');
CREATE INDEX IF NOT EXISTS idx_assistant_sessions_patient_updated
    ON assistant_sessions(patient_user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_assistant_messages_session_time
    ON assistant_messages(session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_feature_logs_patient_time
    ON patient_feature_usage_logs(patient_user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_capacity_date_doctor
    ON doctor_daily_capacities(appointment_date, doctor_user_id);
CREATE INDEX IF NOT EXISTS idx_appointments_doctor_date_status
    ON patient_appointments(doctor_user_id, appointment_date, status);
CREATE INDEX IF NOT EXISTS idx_appointments_patient_created
    ON patient_appointments(patient_user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_appointment_events_appointment_time
    ON appointment_events(appointment_id, created_at);
CREATE INDEX IF NOT EXISTS idx_night_shift_doctor_date
    ON doctor_night_shifts(doctor_user_id, shift_date);
CREATE INDEX IF NOT EXISTS idx_idempotency_expires
    ON idempotency_records(expires_at);
CREATE INDEX IF NOT EXISTS idx_agent_runs_user_created
    ON agent_runs(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_runs_status_updated
    ON agent_runs(status, updated_at);
CREATE INDEX IF NOT EXISTS idx_agent_events_run_sequence
    ON agent_run_events(run_id, sequence);
CREATE INDEX IF NOT EXISTS idx_tool_calls_run_created
    ON tool_calls(agent_run_id, created_at);
CREATE INDEX IF NOT EXISTS idx_work_sessions_owner_updated
    ON work_assistant_sessions(owner_user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_work_messages_session_time
    ON work_assistant_messages(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_inventory_name_status
    ON medicine_inventory(medicine_name, stock_status);
CREATE INDEX IF NOT EXISTS idx_inventory_expiry
    ON medicine_inventory(expires_on);
CREATE INDEX IF NOT EXISTS idx_async_tasks_owner_created
    ON async_tasks(owner_user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_async_tasks_status_updated
    ON async_tasks(status, updated_at);
CREATE INDEX IF NOT EXISTS idx_async_task_events_task_sequence
    ON async_task_events(task_id, sequence);
CREATE UNIQUE INDEX IF NOT EXISTS idx_active_patient_doctor_date
    ON patient_appointments(patient_user_id, doctor_user_id, appointment_date)
    WHERE status NOT IN ('change_requested', 'declined_direct', 'declined_gentle', 'cancelled');

INSERT OR IGNORE INTO account_sequences(prefix, next_value) VALUES
    ('A', 1), ('D', 1), ('P', 1), ('S', 1);

INSERT OR IGNORE INTO schema_metadata(version) VALUES (9);
