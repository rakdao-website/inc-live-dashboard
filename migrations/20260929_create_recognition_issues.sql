-- Visitor reports from the kiosk that face recognition went wrong.
-- Only needed when AUTO_CREATE_TABLES=false; otherwise the API creates this
-- table from the RecognitionIssue model on startup.
CREATE TABLE IF NOT EXISTS recognition_issues (
    recognition_issue_id BIGSERIAL PRIMARY KEY,
    message              TEXT        NOT NULL,
    capture_id           BIGINT      NULL REFERENCES unknown_face_captures (capture_id),
    visitor_id           BIGINT      NULL REFERENCES visitors (visitor_id),
    status               VARCHAR(20) NOT NULL DEFAULT 'new'
                         CHECK (status IN ('new', 'reviewed', 'resolved')),
    created_at           TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_recognition_issues_capture_id ON recognition_issues (capture_id);
CREATE INDEX IF NOT EXISTS ix_recognition_issues_visitor_id ON recognition_issues (visitor_id);
