-- Expand only: existing records and old writers keep an unknown class.
ALTER TABLE cplane_run_records
    ADD COLUMN IF NOT EXISTS change_class integer CHECK (change_class IN (1, 2, 4));
