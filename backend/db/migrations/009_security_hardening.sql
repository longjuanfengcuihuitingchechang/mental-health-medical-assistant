BEGIN IMMEDIATE;

ALTER TABLE audit_events ADD COLUMN request_id TEXT;
ALTER TABLE audit_events ADD COLUMN ip_fingerprint TEXT;
ALTER TABLE audit_events ADD COLUMN resource_fingerprint TEXT;
ALTER TABLE audit_events ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}';

-- Earlier versions stored directory search terms and generated registration
-- accounts in filters_json. Remove those values before making the ledger
-- append-only so identifiers cannot remain frozen in audit history.
UPDATE audit_events
SET filters_json = '{}'
WHERE action = 'directory.list' OR action LIKE 'registration.%';

CREATE INDEX idx_audit_request_id ON audit_events(request_id);
CREATE INDEX idx_audit_resource_created
    ON audit_events(target_type, resource_fingerprint, created_at);

CREATE TRIGGER audit_events_append_only_update
BEFORE UPDATE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events is append-only');
END;

CREATE TRIGGER audit_events_append_only_delete
BEFORE DELETE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events is append-only');
END;

INSERT INTO schema_metadata(version) VALUES (9);
COMMIT;
