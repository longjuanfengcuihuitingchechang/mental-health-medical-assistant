PRAGMA foreign_keys = OFF;
BEGIN IMMEDIATE;

CREATE TABLE users_v6 (
    id TEXT PRIMARY KEY,
    account TEXT NOT NULL UNIQUE,
    password_hash TEXT,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('patient', 'doctor', 'assistant', 'admin', 'super_admin')),
    account_status TEXT NOT NULL DEFAULT 'active'
        CHECK (account_status IN ('active', 'disabled', 'locked', 'pending')),
    blacklisted INTEGER NOT NULL DEFAULT 0 CHECK (blacklisted IN (0, 1)),
    last_login_at TEXT,
    must_change_password INTEGER NOT NULL DEFAULT 0 CHECK (must_change_password IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
INSERT INTO users_v6 (
    id, account, password_hash, display_name, role, account_status,
    blacklisted, last_login_at, must_change_password, created_at, updated_at
)
SELECT id, account, password_hash, display_name, role, account_status,
       blacklisted, last_login_at, must_change_password, created_at, updated_at
FROM users;
DROP TABLE users;
ALTER TABLE users_v6 RENAME TO users;

CREATE TABLE account_sequences_v6 (
    prefix TEXT PRIMARY KEY CHECK (prefix IN ('A', 'D', 'P', 'S')),
    next_value INTEGER NOT NULL CHECK (next_value >= 1)
);
INSERT INTO account_sequences_v6 SELECT * FROM account_sequences;
INSERT INTO account_sequences_v6(prefix, next_value) VALUES ('S', 1);
DROP TABLE account_sequences;
ALTER TABLE account_sequences_v6 RENAME TO account_sequences;

CREATE TABLE assistant_profiles (
    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE RESTRICT,
    employee_no TEXT NOT NULL UNIQUE,
    employment_status TEXT NOT NULL DEFAULT 'active'
        CHECK (employment_status IN ('active', 'leave', 'resigned')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE doctor_daily_capacities (
    doctor_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    appointment_date TEXT NOT NULL,
    capacity INTEGER NOT NULL CHECK (capacity BETWEEN 0 AND 1000),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (doctor_user_id, appointment_date)
);

CREATE TABLE patient_appointments (
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

CREATE TABLE appointment_events (
    id TEXT PRIMARY KEY,
    appointment_id TEXT NOT NULL REFERENCES patient_appointments(id) ON DELETE RESTRICT,
    actor_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE doctor_night_shifts (
    shift_date TEXT PRIMARY KEY,
    doctor_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    assigned_by_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX idx_users_account_nocase ON users(account COLLATE NOCASE);
CREATE INDEX idx_users_role_status ON users(role, account_status);
CREATE INDEX idx_users_blacklisted ON users(blacklisted);
CREATE INDEX idx_users_display_name ON users(display_name);
CREATE INDEX idx_capacity_date_doctor ON doctor_daily_capacities(appointment_date, doctor_user_id);
CREATE INDEX idx_appointments_doctor_date_status ON patient_appointments(doctor_user_id, appointment_date, status);
CREATE INDEX idx_appointments_patient_created ON patient_appointments(patient_user_id, created_at DESC);
CREATE INDEX idx_appointment_events_appointment_time ON appointment_events(appointment_id, created_at);
CREATE INDEX idx_night_shift_doctor_date ON doctor_night_shifts(doctor_user_id, shift_date);
CREATE UNIQUE INDEX idx_active_patient_doctor_date
    ON patient_appointments(patient_user_id, doctor_user_id, appointment_date)
    WHERE status NOT IN ('change_requested', 'declined_direct', 'declined_gentle', 'cancelled');

INSERT INTO schema_metadata(version) VALUES (6);
COMMIT;
PRAGMA foreign_keys = ON;
