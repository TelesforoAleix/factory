-- Expand only: existing records retain an unknown role.
ALTER TABLE cplane_run_records
    ADD COLUMN role text CHECK (role IN ('slice', 'cut', 'ticket', 'review', 'check'));
