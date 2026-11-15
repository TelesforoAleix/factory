-- Expand only: existing cases retain their original base behavior.
ALTER TABLE cplane_eval_cases
    ADD COLUMN start_commit text CHECK (start_commit ~ '^[0-9a-fA-F]{40}$'),
    ADD COLUMN start_branch text,
    ADD COLUMN pinned_paths text[] CHECK (
        array_position(pinned_paths, NULL) IS NULL
        AND (cardinality(pinned_paths) = 0 OR array_ndims(pinned_paths) = 1)
    );
