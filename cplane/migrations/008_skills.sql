CREATE TABLE cplane_project_skills (
    project text NOT NULL REFERENCES cplane_projects(key),
    skill text NOT NULL CHECK (skill ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
    enabled boolean NOT NULL,
    PRIMARY KEY (project, skill)
);
ALTER TABLE cplane_sessions ADD COLUMN skill_names jsonb;
ALTER TABLE cplane_sessions ADD COLUMN skill_version text;
