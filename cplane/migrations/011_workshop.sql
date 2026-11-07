-- No payloads or credentials: feature revisions/events and owner-check notices
-- retain the actual write. This audit also records successful no-op writes.
CREATE TABLE cplane_workshop_writes (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    chat bigint NOT NULL REFERENCES cplane_sessions(id),
    operation text NOT NULL,
    time timestamptz NOT NULL DEFAULT clock_timestamp()
);
