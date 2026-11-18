-- Expand the catalogue without changing any existing case, run or attempt.
CREATE TABLE cplane_eval_configurations (
    id text PRIMARY KEY,
    path text NOT NULL CHECK (path IN ('slice', 'tickets')),
    roles jsonb NOT NULL CHECK (jsonb_typeof(roles) = 'object'),
    note text NOT NULL DEFAULT '',
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE FUNCTION cplane_eval_configuration_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Eval configurations cannot be edited or deleted; use a new name';
END;
$$;
CREATE TRIGGER cplane_eval_configuration_immutable
    BEFORE UPDATE OR DELETE ON cplane_eval_configurations
    FOR EACH ROW EXECUTE FUNCTION cplane_eval_configuration_immutable();

ALTER TABLE cplane_eval_cases
    ADD COLUMN source_slice text,
    ADD COLUMN merge_commit text,
    ADD COLUMN hidden_paths text[],
    ADD COLUMN grade text CHECK (grade IN ('tests_and_judge', 'judge')),
    ADD COLUMN validation text;

-- Replacing this check only widens the accepted values; no stored level changes.
ALTER TABLE cplane_eval_cases DROP CONSTRAINT cplane_eval_cases_check;
ALTER TABLE cplane_eval_cases ADD CONSTRAINT cplane_eval_cases_check
    CHECK ((kind = 'slice' AND level IS NOT NULL AND level IN ('light', 'standard', 'strong'))
           OR (kind <> 'slice' AND level IS NULL));

CREATE TABLE cplane_eval_attempt_runs (
    attempt bigint NOT NULL REFERENCES cplane_eval_attempts(id),
    position integer NOT NULL CHECK (position >= 1),
    role text NOT NULL,
    purpose text NOT NULL,
    run_id text NOT NULL,
    PRIMARY KEY (attempt, position),
    UNIQUE (attempt, purpose, run_id)
);
