-- Expand only. Planner outcomes are separate from 022's pass/fix verdict,
-- whose constraint remains usable by old runner writers.
CREATE TABLE cplane_slice_outcomes (
    slice_id text PRIMARY KEY,
    verdict text CHECK (verdict IN ('accepted', 'corrected')),
    corrects_slice text,
    CHECK (slice_id <> corrects_slice)
);
CREATE TABLE cplane_task_runs (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    slice_id text NOT NULL,
    queue_slice text NOT NULL,
    task_id text NOT NULL,
    attempt integer NOT NULL CHECK (attempt > 0),
    position integer NOT NULL CHECK (position > 0),
    status text NOT NULL CHECK (status IN ('queued', 'running', 'done', 'failed', 'escalated')),
    reason text,
    tokens bigint CHECK (tokens >= 0),
    seconds double precision CHECK (seconds >= 0 AND seconds < 'Infinity'::float8),
    cost double precision CHECK (cost >= 0 AND cost < 'Infinity'::float8),
    started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (queue_slice, task_id, attempt)
);
CREATE INDEX cplane_task_runs_slice ON cplane_task_runs(slice_id, id);
