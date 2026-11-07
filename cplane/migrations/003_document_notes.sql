CREATE TABLE cplane_document_notes (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document text NOT NULL,
    text text NOT NULL CHECK (length(text) BETWEEN 1 AND 16000),
    time timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX cplane_document_notes_document ON cplane_document_notes(document, id);
