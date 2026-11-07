ALTER TABLE cplane_features DROP CONSTRAINT cplane_features_project_stage_position_key;
-- Preserve each project's old relative order if migrating a nonempty database.
WITH ordered AS (
    SELECT feature, row_number() OVER (PARTITION BY stage ORDER BY project, position, feature) - 1 AS position
    FROM cplane_features
)
UPDATE cplane_features f SET position = o.position FROM ordered o WHERE f.feature = o.feature;
ALTER TABLE cplane_features ADD CONSTRAINT cplane_features_stage_position_key
    UNIQUE (stage, position) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE cplane_features ADD COLUMN design_agreed timestamptz;
ALTER TABLE cplane_features ADD COLUMN review_passed timestamptz;
CREATE TABLE cplane_settings (
    name text PRIMARY KEY CHECK (name IN ('building_limit', 'waiting_limit')),
    value numeric NOT NULL CHECK (value >= 1 AND value = trunc(value))
);
INSERT INTO cplane_settings VALUES ('building_limit', 3), ('waiting_limit', 3);
