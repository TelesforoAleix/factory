ALTER TABLE cplane_projects ADD COLUMN active boolean NOT NULL DEFAULT true;
ALTER TABLE cplane_projects ADD CONSTRAINT cplane_new_always_active CHECK (key <> 'NEW' OR active);
-- Keep creation events readable; subsequent flag changes record the chosen value.
ALTER TABLE cplane_project_events ADD COLUMN active boolean;
