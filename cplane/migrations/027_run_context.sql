-- Expand only: historical records and old writers retain unknown context.
ALTER TABLE cplane_run_records
    ADD COLUMN context jsonb CHECK (jsonb_typeof(context) = 'array');
