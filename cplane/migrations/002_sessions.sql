CREATE TABLE cplane_sessions (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    area text NOT NULL CHECK (area IN ('homelab', 'factory')),
    title text NOT NULL,
    tool text NOT NULL CHECK (tool IN ('claude', 'codex')),
    model text NOT NULL,
    state text NOT NULL DEFAULT 'idle' CHECK (state IN ('idle', 'running', 'failed')),
    cli_session_id text,
    repositories jsonb NOT NULL DEFAULT '[]'
);
CREATE TABLE cplane_session_messages (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session bigint NOT NULL REFERENCES cplane_sessions(id),
    role text NOT NULL CHECK (role IN ('owner', 'assistant')),
    text text NOT NULL,
    status text NOT NULL CHECK (status IN ('queued', 'running', 'done', 'failed')),
    time timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX cplane_session_one_turn ON cplane_session_messages(session) WHERE status = 'running';
