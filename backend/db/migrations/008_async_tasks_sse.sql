BEGIN IMMEDIATE;

CREATE TABLE async_tasks (
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

CREATE TABLE async_task_events (
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

CREATE INDEX idx_async_tasks_owner_created
    ON async_tasks(owner_user_id, created_at DESC);
CREATE INDEX idx_async_tasks_status_updated
    ON async_tasks(status, updated_at);
CREATE INDEX idx_async_task_events_task_sequence
    ON async_task_events(task_id, sequence);

INSERT INTO schema_metadata(version) VALUES (8);
COMMIT;
