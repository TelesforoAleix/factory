-- Each provider owns its resume ID; both reuse the original chat workspace.
ALTER TABLE cplane_sessions ADD COLUMN tool_sessions jsonb NOT NULL DEFAULT '{}'
    CHECK (jsonb_typeof(tool_sessions) = 'object');
ALTER TABLE cplane_sessions ADD COLUMN workspace_ready boolean NOT NULL DEFAULT false;
UPDATE cplane_sessions SET tool_sessions = jsonb_build_object(tool, cli_session_id), workspace_ready = true
    WHERE cli_session_id IS NOT NULL;
