-- Separate from version 1 slice documents; survives their atomic replacement.
CREATE TABLE cplane_slice_order (
    feature bigint NOT NULL REFERENCES cplane_features(feature) ON DELETE CASCADE,
    slice_id text NOT NULL,
    position integer NOT NULL CHECK (position >= 0),
    PRIMARY KEY (feature, slice_id),
    UNIQUE (feature, position)
);
