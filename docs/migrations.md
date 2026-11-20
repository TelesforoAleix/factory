# Adding a database migration

This document covers how to add a Postgres migration. Read it when a change needs
a new table, column, constraint or index.

1. Add `cplane/migrations/NNN_name.sql` with the next unused number. Files run in
   name order, and each name is recorded once in `cplane_migrations`; never edit or
   rename a file that has been installed.
2. Keep the change additive: new tables, nullable columns, widened checks. The
   previous image must keep working against the migrated database, because
   rollback reinstalls the previous image without reversing migrations.
3. Paths under `cplane/migrations/` are change class 2 in `.github/change-classes`,
   so the PR gets the stronger checks.
4. Test it against a disposable PostgreSQL 17 database with
   `CPLANE_TEST_DATABASE_URL` set; CI's `test` job does the same.
5. On install, the deployer dumps the database and then runs `cplane migrate` in a
   new `ui` container ([operations.md](operations.md#install-after-a-merge)).
