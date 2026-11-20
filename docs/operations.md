# Operations

This document covers how to set up a development environment, how Factory is
installed and checked on the node, and how to roll back and recover. Read it
before you install, roll back, restore, or change the runner loop, the exports, the
owner orders or the Mac primer. The node's services, mounts, secrets and every
environment variable are in [node.md](node.md); the run protocol is in
[runner.md](runner.md).

## Development

```sh
uv sync --locked
uv run cplane --help
uv run pytest
```

Use Python 3.13 and uv. The store needs the system libpq library. Postgres tests
run only when `CPLANE_TEST_DATABASE_URL` names a disposable PostgreSQL 17 database;
each test creates and drops its own schema. Without the variable they skip
locally and fail under CI.

CI runs on pull requests only, never on pushes to `main`. The `test` job runs
`uv sync --locked` and `uv run pytest` against a PostgreSQL 17 service. The
`image-gitleaks` job scans the full history with gitleaks, builds the image and
smoke-tests it read-only. The `UI` workflow runs on changes under `ui/`, and the
`CLI image` workflow on changes to the fenced CLI image under `node/`. A new push
to a PR cancels that workflow's older run.

## Storage

Postgres is the only store. A service reads its database URL from the file named
by `CPLANE_DATABASE_URL_FILE`; `CPLANE_DATABASE_URL` holds it directly for local
use, and setting both is an error. Error messages never include the URL. Every
slice write goes through one validator for the version 1 document, and each runner
pass holds one transaction-scoped advisory lock.

`cplane migrate` applies the files in `cplane/migrations/` in name order and
records each in `cplane_migrations`; it is safe to repeat. To add a migration,
follow [migrations.md](migrations.md).
`cplane import FILE` loads a state file and its `FILE.outbox.jsonl` into an empty
database; `cplane export [PATH]` writes them back out. Exports hold private data:
keep them outside this repository.

`CPLANE_STATE` (or `--state`) names the anchor path for relative briefs and the run
ledger's state hash, even though state lives in Postgres. Keep it and `CPLANE_RUNS`
the same across restarts.

## Install after a merge

1. A merged PR with `node_steps` raises `node-step` attention on its slice.
2. For a repository listed in `CPLANE_INSTALL_REPOS`, the owner runs
   `sudo factory-cplane --actor owner install SLICE` (or uses Home's Install). A
   chat may only propose an install.
3. The runner starts a detached child that sends the merged commit to the platform
   deployer on `CPLANE_DEPLOYER_SOCKET`. The child records the result in the run
   folder's `installs/` directory. A held `.started` lock tracks the child across runner
   restarts; a child that ends without a result escalates and is never replayed.
4. The deployer dumps the database, runs `cplane migrate` in a new `ui` container,
   replaces the services and runs the `ui` health command. When the commit changes a
   guard path it replies `waits for the owner`; the attention then names the exact
   `sudo homelab-deployer install factory <sha>` command to run.
5. A successful install answers the node step; the slice then moves to its handover.

For a repository outside `CPLANE_INSTALL_REPOS`, install the merged commit by hand
and record it with `cplane installed SLICE SHA --note TEXT`.

## Health

Each service has a Python healthcheck: `ui` fetches its root page, `intake`
connects to its socket, and `sessions` and `runner` check PID 1 and run `SELECT 1`.
These show process and database availability, not scheduling progress. To check
an install:

```sh
sudo factory-cplane pending
sudo docker exec deployer-factory-runner-1 printenv CPLANE_REVISION
```

Compose sets the runner's `CPLANE_REVISION` from `HOMELAB_DEPLOY_TAG`; it must equal
the merged commit.

## Rollback

Ask the deployer to reinstall the previous known-good commit; record that commit
before each install. Migrations are additive, so the previous image runs against
the migrated database. Keep the run ledger and state path unchanged so that open
platform runs are not started twice.

## Recovery

- **Run ledger.** Request bodies, run ids and pending message ids are saved under
  `CPLANE_RUNS` before each POST. A lost response retries the same id and body; a
  confirmed request is only polled. Never delete the ledger during active work.
- **Owner orders.** A receipt is written before an order takes effect. An
  interrupted dispatch is recorded as failed and never repeated. A later pass
  reuses the result in an existing receipt; check the slice before sending a
  replacement order.
- **Installs.** See step 3 above; inspect the run folder's `installs/` before asking again.
- **Backups.** The platform's `homelab-dump` dumps every database, including
  `factory`, daily. `sudo factory-restore-check [DUMP]` restores a dump into a
  disposable, network-isolated PostgreSQL container and compares row counts with
  the live database; with no argument it picks the newest `factory-YYYY-MM-DD.dump`.

## Runner loop and exports

The `runner` service runs `cplane --actor runner run --every 60`: a pass, then a
60-second wait, until SIGTERM or SIGINT. A failed pass prints a content-free line
and the loop continues. Without `--every`, `run` makes one pass and runs no
scheduled export.

- After every pass, the phone bot export writes `slices.json` and its outbox to
  `CPLANE_BOT_EXPORT`.
- The first pass after 03:45 local time each day writes
  `factory-YYYY-MM-DD.json` and its outbox to `CPLANE_EXPORT_DIR`, mode 0600, and
  keeps the seven newest pairs.
- The first pass in each local hour publishes features and briefs to the planning
  repository ([contracts.md](contracts.md#planning-export)).

Export schedules are kept in the process, so a restart can repeat an export in
the same period.

## Owner orders

At the start of each pass the runner collects confirmed owner orders from
`CPLANE_ORDERS_URL` ([contracts.md](contracts.md#orders-endpoint)); an empty value
turns collection off. Each order must still match the slice's state, pause flag and
attention kind and time, or it is dropped with a notice. Orders are applied with
actor `frontline` through the same locked update path as the commands. An
`orchestrator` order opens a tmux window and is refused on the node, where
`CPLANE_FENCE=1`. Each HTTP call has a ten-second timeout.

## Mac primer

`cplane prime` sends one minimal request to Claude and then Codex so that their
usage windows start on a schedule; it needs no state. `cplane install-primer`
installs a launchd job that runs it at 06:00, 11:00, 16:00 and 21:00, and
`uninstall-primer` removes it. A root wake daemon schedules wakes at 05:59, 10:59,
15:59 and 20:59. Install it once, from its printed plist:

```sh
D=/Library/LaunchDaemons/com.cplane.primer-wake.plist
T=$(mktemp)
uv run cplane primer-wake-plist > "$T"
sudo cp "$T" "$D"
sudo chown root:wheel "$D"
sudo chmod 644 "$D"
sudo launchctl bootstrap system "$D"
```

Remove it with `sudo launchctl bootout system "$D"` and `sudo rm "$D"`. As a
backstop, `sudo pmset repeat wake MTWRFSU 05:59:00` wakes the Mac before the first
run; undo it with `sudo pmset repeat cancel`.
