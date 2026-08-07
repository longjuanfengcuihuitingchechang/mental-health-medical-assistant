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

INSERT INTO schema_metadata(version) VALUES (4);
