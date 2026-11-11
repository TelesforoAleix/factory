-- The v1 document remains the write contract. Derive the queryable text array
-- from it so existing document saves cannot discard or desynchronise scope.
CREATE FUNCTION cplane_allowed_files(document jsonb) RETURNS text[]
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
    SELECT CASE WHEN jsonb_typeof(document -> 'allowed_files') = 'array'
        THEN ARRAY(SELECT jsonb_array_elements_text(document -> 'allowed_files'))
        ELSE NULL END
$$;
ALTER TABLE cplane_slices ADD COLUMN allowed_files text[]
    GENERATED ALWAYS AS (cplane_allowed_files(document)) STORED;
