-- Additive owner comment resolution; sent history is retained.
ALTER TABLE cplane_document_comments
    ADD COLUMN resolved_at timestamptz,
    ADD COLUMN resolution_note text,
    ADD CONSTRAINT comment_resolution CHECK (
        (resolved_at IS NULL AND resolution_note IS NULL) OR
        (resolved_at IS NOT NULL AND sent_at IS NOT NULL AND resolution_note IS NOT NULL
         AND length(btrim(resolution_note)) BETWEEN 1 AND 1000
         AND resolution_note !~ E'[\\r\\n]'));
