-- Session IDs and all existing turns/resume IDs remain stable.
ALTER TABLE cplane_sessions ADD COLUMN kind text NOT NULL DEFAULT 'legacy'
    CHECK (kind IN ('legacy', 'orchestrator', 'project', 'feature'));
ALTER TABLE cplane_sessions ADD COLUMN project text REFERENCES cplane_projects(key);
ALTER TABLE cplane_sessions ADD COLUMN feature bigint REFERENCES cplane_features(feature);
ALTER TABLE cplane_sessions ADD COLUMN archived boolean NOT NULL DEFAULT false;
ALTER TABLE cplane_sessions ADD COLUMN last_read_at timestamptz;
CREATE TABLE cplane_chat_settings (
    kind text PRIMARY KEY CHECK (kind IN ('legacy', 'orchestrator', 'project', 'feature')),
    chat_tool text NOT NULL CHECK (chat_tool IN ('codex', 'claude')),
    chat_model text NOT NULL CHECK (chat_model ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$')
);
INSERT INTO cplane_chat_settings SELECT kind, 'codex', 'gpt-5.3-codex'
    FROM unnest(ARRAY['legacy', 'orchestrator', 'project', 'feature']) AS kind;
-- Carry forward an installed choice where one exists.
UPDATE cplane_chat_settings d SET chat_tool = s.tool, chat_model = s.model
FROM (SELECT DISTINCT ON (area) area, tool, model FROM cplane_sessions ORDER BY area, id) s
WHERE (d.kind = 'orchestrator' AND s.area = 'homelab')
   OR (d.kind IN ('legacy', 'project', 'feature') AND s.area = 'factory');
UPDATE cplane_sessions SET kind = 'orchestrator'
WHERE id = (SELECT min(id) FROM cplane_sessions WHERE area = 'homelab');
INSERT INTO cplane_sessions (area, title, tool, model, kind)
SELECT 'homelab', 'Orchestrator', chat_tool, chat_model, 'orchestrator'
FROM cplane_chat_settings WHERE kind = 'orchestrator'
AND NOT EXISTS (SELECT 1 FROM cplane_sessions WHERE kind = 'orchestrator');
ALTER TABLE cplane_sessions ADD CONSTRAINT cplane_chat_links CHECK (
    (kind = 'legacy' AND project IS NULL AND feature IS NULL) OR
    (kind = 'orchestrator' AND area = 'homelab' AND project IS NULL AND feature IS NULL) OR
    (kind = 'project' AND area = 'factory' AND project IS NOT NULL AND feature IS NULL) OR
    (kind = 'feature' AND area = 'factory' AND project IS NOT NULL AND feature IS NOT NULL)
);
CREATE UNIQUE INDEX cplane_one_orchestrator ON cplane_sessions(kind) WHERE kind = 'orchestrator';
CREATE UNIQUE INDEX cplane_one_project_chat ON cplane_sessions(project) WHERE kind = 'project';
CREATE UNIQUE INDEX cplane_one_feature_chat ON cplane_sessions(feature) WHERE kind = 'feature';
ALTER TABLE cplane_session_messages DROP CONSTRAINT cplane_session_messages_role_check;
ALTER TABLE cplane_session_messages ADD CONSTRAINT cplane_session_messages_role_check
    CHECK (role IN ('owner', 'assistant', 'system'));
ALTER TABLE cplane_session_messages ADD COLUMN automatic boolean NOT NULL DEFAULT false;
CREATE INDEX cplane_chat_latest_reply ON cplane_session_messages(session, time DESC) WHERE role = 'assistant';
-- Replies must reflect insertion time after acquiring the store lock, rather
-- than the transaction start time before a concurrent owner read.
ALTER TABLE cplane_session_messages ALTER COLUMN time SET DEFAULT clock_timestamp();
