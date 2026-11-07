CREATE TABLE cplane_run_records (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    turn_key text NOT NULL UNIQUE,
    kind text NOT NULL CHECK (kind IN ('slice', 'chat')),
    project text,
    feature_id text,
    slice_id text,
    session_id text,
    tool text NOT NULL CHECK (tool IN ('codex', 'claude')),
    model text,
    effort text,
    input_tokens bigint CHECK (input_tokens >= 0),
    cached_tokens bigint CHECK (cached_tokens >= 0),
    cache_write_tokens bigint CHECK (cache_write_tokens >= 0),
    output_tokens bigint CHECK (output_tokens >= 0),
    reasoning_tokens bigint CHECK (reasoning_tokens >= 0),
    seconds double precision CHECK (seconds >= 0),
    started_at timestamptz,
    outcome text,
    starting_commit text,
    prompt text CHECK (length(prompt) <= 16000),
    prompt_truncated boolean NOT NULL DEFAULT false,
    skill_version text,
    eval_candidate boolean NOT NULL DEFAULT false
);
CREATE INDEX cplane_run_records_slice ON cplane_run_records(slice_id, id);
CREATE INDEX cplane_run_records_project ON cplane_run_records(project, id);
