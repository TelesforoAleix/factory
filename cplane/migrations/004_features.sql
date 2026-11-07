CREATE TABLE cplane_projects (
    key text PRIMARY KEY CHECK (key ~ '^[A-Z]{3}$'),
    name text NOT NULL,
    repository text,
    feature_counter bigint NOT NULL DEFAULT 0 CHECK (feature_counter >= 0)
);
INSERT INTO cplane_projects (key, name, repository) VALUES
    ('FAC', 'factory', 'factory'), ('LAB', 'homelab-v2', 'homelab-v2'),
    ('CTL', 'control-plane', 'control-plane'), ('STU', 'studio', 'studio'),
    ('MED', 'med-ask', 'med-ask'), ('NEW', 'No project yet', NULL);
CREATE TABLE cplane_features (
    feature bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id text NOT NULL UNIQUE,
    project text NOT NULL REFERENCES cplane_projects(key),
    title text NOT NULL CHECK (length(title) BETWEEN 1 AND 200),
    stage text NOT NULL CHECK (stage IN ('shortlist', 'grilling', 'ready', 'next', 'building', 'testing', 'done', 'parked')),
    position bigint NOT NULL CHECK (position >= 0),
    parked_from text CHECK (parked_from IN ('shortlist', 'grilling', 'ready', 'next', 'building', 'testing', 'done')),
    CHECK (stage = 'parked' OR parked_from IS NULL),
    UNIQUE (project, stage, position)
);
-- IDs remain reserved even if their feature is deleted.
CREATE TABLE cplane_feature_ids (
    id text PRIMARY KEY,
    feature bigint REFERENCES cplane_features(feature) ON DELETE SET NULL
);
CREATE TABLE cplane_feature_sections (
    feature bigint NOT NULL REFERENCES cplane_features(feature) ON DELETE CASCADE,
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
    position bigint NOT NULL CHECK (position >= 0),
    text text NOT NULL CHECK (length(text) <= 16000),
    PRIMARY KEY (feature, name),
    UNIQUE (feature, position)
);
CREATE TABLE cplane_feature_revisions (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    feature bigint NOT NULL REFERENCES cplane_features(feature) ON DELETE CASCADE,
    section text NOT NULL,
    text text NOT NULL CHECK (length(text) <= 16000),
    actor text NOT NULL CHECK (length(actor) BETWEEN 1 AND 200),
    time timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX cplane_feature_revision_history ON cplane_feature_revisions(feature, id);
CREATE TABLE cplane_feature_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    feature bigint NOT NULL REFERENCES cplane_features(feature) ON DELETE CASCADE,
    event text NOT NULL,
    actor text NOT NULL CHECK (length(actor) BETWEEN 1 AND 200),
    time timestamptz NOT NULL DEFAULT now()
);
