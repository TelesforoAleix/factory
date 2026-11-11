-- Expand only: old writers leave the new outcome fields NULL.
ALTER TABLE cplane_run_records
    ADD COLUMN level text CHECK (level IN ('light', 'standard', 'strong')),
    ADD COLUMN executor_source text CHECK (executor_source IN ('level', 'override')),
    ADD COLUMN configuration text,
    ADD COLUMN brief_hash text,
    ADD COLUMN ci_result jsonb CHECK (jsonb_typeof(ci_result) = 'array'),
    ADD COLUMN verdict text CHECK (verdict IN ('pass', 'fix')),
    ADD COLUMN corrects_slice text,
    ADD COLUMN owner_wait_seconds double precision CHECK (owner_wait_seconds >= 0);
