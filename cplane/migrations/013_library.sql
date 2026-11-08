-- Whole-document notes have no reliable historical delivery link. Preserve
-- their original timestamp and mark them imported/sent without inventing one.
CREATE TABLE cplane_document_comments (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document text NOT NULL,
    quote text,
    prefix text NOT NULL DEFAULT '',
    suffix text NOT NULL DEFAULT '',
    text text NOT NULL CHECK (length(text) BETWEEN 1 AND 16000),
    time timestamptz NOT NULL DEFAULT clock_timestamp(),
    sent_at timestamptz,
    chat bigint REFERENCES cplane_sessions(id),
    message bigint REFERENCES cplane_session_messages(id),
    legacy_note bigint UNIQUE REFERENCES cplane_document_notes(id),
    CHECK (quote IS NULL OR length(quote) BETWEEN 1 AND 16000),
    CHECK (length(prefix) <= 256 AND length(suffix) <= 256),
    CHECK ((sent_at IS NULL AND chat IS NULL AND message IS NULL AND legacy_note IS NULL)
        OR (sent_at IS NOT NULL AND ((chat IS NOT NULL AND message IS NOT NULL) OR legacy_note IS NOT NULL)))
);
CREATE INDEX cplane_document_comments_path ON cplane_document_comments(document, id);
INSERT INTO cplane_document_comments (document, text, time, sent_at, legacy_note)
SELECT document, text, time, time, id FROM cplane_document_notes;
-- Migration 009 already classified sessions. Keep the current orchestrator;
-- retire the old Home Lab legacy sessions without deleting queued history.
UPDATE cplane_sessions SET archived = true WHERE area = 'homelab' AND kind = 'legacy';
