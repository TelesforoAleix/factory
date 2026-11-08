-- Independent of cplane_slices: save replaces that table's rows each pass.
ALTER TABLE cplane_features ADD COLUMN slice_counter bigint NOT NULL DEFAULT 0;
CREATE TABLE cplane_slice_briefs (
    slice_id text PRIMARY KEY,
    feature bigint NOT NULL REFERENCES cplane_features(feature),
    text text NOT NULL CHECK (octet_length(text) BETWEEN 1 AND 65536),
    actor text NOT NULL,
    time timestamptz NOT NULL DEFAULT clock_timestamp()
);
-- Corrections are new slices. Even a forced planner reset cannot rewrite a brief.
CREATE FUNCTION cplane_immutable_brief() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Stored briefs are immutable; create a new slice';
END;
$$;
CREATE TRIGGER cplane_immutable_brief BEFORE UPDATE OR DELETE ON cplane_slice_briefs
    FOR EACH ROW EXECUTE FUNCTION cplane_immutable_brief();
