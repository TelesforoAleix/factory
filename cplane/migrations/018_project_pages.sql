ALTER TABLE cplane_projects
    ADD COLUMN about text NOT NULL DEFAULT '' CHECK (length(about) <= 600),
    ADD COLUMN public_url text CHECK (public_url ~ '^https://[^[:space:]]+$'),
    ADD COLUMN repository_url text CHECK (repository_url ~ '^https://[^[:space:]]+$'),
    ADD CONSTRAINT cplane_project_name_length CHECK (length(name) BETWEEN 1 AND 60);
ALTER TABLE cplane_project_events ADD COLUMN changes jsonb;
-- Keys are permanent, including for projects without any features yet.
CREATE FUNCTION cplane_project_key_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.key IS DISTINCT FROM OLD.key THEN
        RAISE EXCEPTION 'Project keys are immutable';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER cplane_project_key_immutable BEFORE UPDATE ON cplane_projects
    FOR EACH ROW EXECUTE FUNCTION cplane_project_key_immutable();
