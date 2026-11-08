ALTER TABLE cplane_settings DROP CONSTRAINT cplane_settings_name_check;
ALTER TABLE cplane_settings ADD CHECK (name IN ('building_limit', 'waiting_limit', 'chat_auto_turns'));
INSERT INTO cplane_settings (name, value) VALUES ('chat_auto_turns', 5);
ALTER TABLE cplane_sessions ADD COLUMN auto_turns integer NOT NULL DEFAULT 0 CHECK (auto_turns >= 0);
ALTER TABLE cplane_sessions ADD COLUMN auto_paused boolean NOT NULL DEFAULT false;
-- Capture events with the source mutation; delivery and ownership share the
-- scheduler transaction. Retained rows prevent duplicate delivery after restart.
CREATE TABLE cplane_chat_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source text UNIQUE,
    feature bigint NOT NULL REFERENCES cplane_features(feature),
    slice_id text,
    kind text NOT NULL,
    text text NOT NULL,
    attention_since text,
    at timestamptz NOT NULL DEFAULT clock_timestamp(),
    chat bigint REFERENCES cplane_sessions(id),
    delivered boolean NOT NULL DEFAULT false
);
CREATE INDEX cplane_chat_pending_events ON cplane_chat_events(id) WHERE NOT delivered;
CREATE INDEX cplane_chat_attention_owner ON cplane_chat_events(slice_id, kind, attention_since) WHERE delivered;
