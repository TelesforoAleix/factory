-- Eval storage is independent of scheduler state and execution.
CREATE TABLE cplane_eval_cases (
    id text PRIMARY KEY,
    kind text NOT NULL CHECK (kind IN ('ticket', 'slice', 'review')),
    level text,
    repository text NOT NULL,
    pr integer NOT NULL CHECK (pr > 0),
    base_commit text NOT NULL,
    title text NOT NULL,
    task text NOT NULL,
    check_command text,
    reference_diff text NOT NULL,
    tag_kind text NOT NULL CHECK (tag_kind IN ('new', 'change', 'fix', 'tests', 'docs')),
    size text NOT NULL CHECK (size IN ('S', 'M', 'L')),
    language text NOT NULL CHECK (language IN ('python', 'swift', 'typescript')),
    half text NOT NULL CHECK (half IN ('held-out', 'development')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK ((kind = 'slice' AND level IS NOT NULL AND level IN ('light', 'standard'))
           OR (kind <> 'slice' AND level IS NULL)),
    CHECK (kind <> 'ticket' OR check_command IS NOT NULL)
);
CREATE TABLE cplane_eval_sets (
    id text PRIMARY KEY,
    title text NOT NULL,
    description text NOT NULL DEFAULT ''
);
CREATE TABLE cplane_eval_set_versions (
    "set" text NOT NULL REFERENCES cplane_eval_sets(id),
    version integer NOT NULL CHECK (version >= 1),
    note text NOT NULL DEFAULT '',
    tag_filter jsonb NOT NULL CHECK (jsonb_typeof(tag_filter) = 'object'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    created_by text NOT NULL,
    PRIMARY KEY ("set", version)
);
CREATE TABLE cplane_eval_set_members (
    "set" text NOT NULL,
    version integer NOT NULL,
    "case" text NOT NULL REFERENCES cplane_eval_cases(id),
    PRIMARY KEY ("set", version, "case"),
    FOREIGN KEY ("set", version) REFERENCES cplane_eval_set_versions("set", version)
);
CREATE TABLE cplane_eval_runs (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    title text NOT NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    scheduled_for timestamptz,
    state text NOT NULL DEFAULT 'planned' CHECK (state IN ('planned', 'running', 'done', 'cancelled')),
    repeats integer NOT NULL CHECK (repeats >= 1),
    set_versions jsonb NOT NULL CHECK (jsonb_typeof(set_versions) = 'array'),
    configurations jsonb NOT NULL CHECK (jsonb_typeof(configurations) = 'array')
);
CREATE TABLE cplane_eval_attempts (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    eval_run bigint NOT NULL REFERENCES cplane_eval_runs(id),
    "case" text NOT NULL REFERENCES cplane_eval_cases(id),
    configuration_id text NOT NULL,
    repeat integer NOT NULL CHECK (repeat >= 1),
    state text NOT NULL DEFAULT 'planned' CHECK (state IN ('planned', 'running', 'done', 'failed')),
    result jsonb CHECK (jsonb_typeof(result) = 'object'),
    metrics jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(metrics) = 'object'),
    output_ref text,
    run_record bigint REFERENCES cplane_run_records(id),
    UNIQUE (eval_run, "case", configuration_id, repeat)
);
CREATE TABLE cplane_eval_verdicts (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    attempt bigint NOT NULL REFERENCES cplane_eval_attempts(id),
    judge text NOT NULL,
    prompt_hash text NOT NULL,
    verdict text NOT NULL CHECK (verdict IN ('mergeable', 'not_mergeable')),
    reason text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (attempt, judge, prompt_hash)
);
