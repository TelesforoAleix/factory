-- Expand only: reimport supplies ticket file scope; existing attempts are unchanged.
ALTER TABLE cplane_eval_cases ADD COLUMN allowed_files text[];
ALTER TABLE cplane_eval_attempts ADD COLUMN platform_task bigint;
