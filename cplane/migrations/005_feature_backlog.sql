-- Original table cells and layout are private feature data, never scheduler state.
ALTER TABLE cplane_features ADD COLUMN backlog jsonb;
CREATE TABLE cplane_project_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project text NOT NULL REFERENCES cplane_projects(key),
    actor text NOT NULL CHECK (length(actor) BETWEEN 1 AND 200),
    time timestamptz NOT NULL DEFAULT now()
);
