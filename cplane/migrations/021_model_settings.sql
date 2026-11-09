-- Keep version 1 slice documents unchanged; execution policy is stored separately.
CREATE TABLE cplane_models (
    tool text NOT NULL CHECK (tool IN ('codex', 'claude')),
    model text NOT NULL,
    label text NOT NULL,
    efforts jsonb NOT NULL CHECK (jsonb_typeof(efforts) = 'array'),
    refreshed_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    PRIMARY KEY (tool, label)
);
CREATE TABLE cplane_roles (
    role text PRIMARY KEY CHECK (role IN ('orchestrator','project','feature','secretary','light','standard','strong')),
    tool text NOT NULL CHECK (tool IN ('codex','claude')),
    model text NOT NULL,
    effort text NOT NULL CHECK (effort IN ('low','medium','high','xhigh','max','ultra'))
);
INSERT INTO cplane_roles SELECT kind, chat_tool, chat_model,
    CASE WHEN kind = 'secretary' THEN 'low' ELSE 'medium' END
    FROM cplane_chat_settings WHERE kind <> 'legacy';
INSERT INTO cplane_roles VALUES ('light','codex','gpt-6-luna','low'),
    ('standard','codex','gpt-6.1-terra','medium'), ('strong','codex','gpt-6.1-sol','medium');
ALTER TABLE cplane_sessions ADD COLUMN effort text NOT NULL DEFAULT 'medium'
    CHECK (effort IN ('low','medium','high','xhigh','max','ultra'));
ALTER TABLE cplane_sessions ADD COLUMN role_overrides jsonb NOT NULL DEFAULT '{}';
UPDATE cplane_sessions SET effort = 'low' WHERE kind = 'secretary';
-- Preserve choices differing from the old defaults, including legacy sessions.
UPDATE cplane_sessions s SET role_overrides = jsonb_build_object('tool',s.tool,'model',s.model)
    FROM cplane_chat_settings d WHERE s.kind = d.kind
    AND (s.tool <> d.chat_tool OR s.model <> d.chat_model OR s.kind = 'legacy');
DROP TABLE cplane_chat_settings;
CREATE TABLE cplane_slice_levels (
    slice_id text PRIMARY KEY,
    level text NOT NULL DEFAULT 'standard' CHECK (level IN ('light','standard','strong')),
    overrides jsonb NOT NULL DEFAULT '{}'
);
-- Existing explicit routes continue to win over the new default level.
INSERT INTO cplane_slice_levels SELECT id, 'standard', document->'executor' ||
    jsonb_build_object('effort', COALESCE(document->'executor'->>'effort',
        CASE WHEN lower(document->'executor'->>'model') LIKE '%luna%' THEN 'low' ELSE 'medium' END))
    FROM cplane_slices;
ALTER TABLE cplane_settings DROP CONSTRAINT cplane_settings_name_check;
ALTER TABLE cplane_settings ADD CHECK (name IN ('building_limit','waiting_limit','chat_auto_turns','executors','repository_runs'));
ALTER TABLE cplane_settings ADD CHECK ((name <> 'executors' OR value BETWEEN 1 AND 4) AND (name <> 'repository_runs' OR value = 1));
INSERT INTO cplane_settings VALUES ('executors', 2), ('repository_runs', 1);
CREATE TABLE cplane_model_updates (
    id bigserial PRIMARY KEY,
    tool text NOT NULL CHECK (tool IN ('codex','claude')),
    status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','completed','failed')),
    reason text,
    requested_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE UNIQUE INDEX cplane_one_model_update ON cplane_model_updates(tool) WHERE status IN ('queued','running');
