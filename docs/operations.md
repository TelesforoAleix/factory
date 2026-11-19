# Operations

The operator text below was moved from the earlier README without rewording.
It includes historical file-store, Mac launchd and manual ticket-queue procedures.
The current production store is Postgres; file-backed state is a synthetic test
double, not an alternative production backend. Slice execution uses the platform
run API; chat execution and retained Mac tools are separate. The current
[runner protocol](runner.md) and [node deployment](node.md) take precedence over
historical paths and deployment notes below. See [commands](commands.md) for
current feature-association requirements and the moved command reference.

## Earlier setup note

A scheduler's state file and its commands. `cplane` helps an owner schedule slices of
coding work, answer questions, approve merges, and see what is pending. It records
intent through owner commands. `start` sets a slot to now; `resume` clears a pause
flag. The separate `run` command starts and resumes Codex and Claude executors.
Planning agents use `add`, `edit`, `state`, `attention`, `review`, and `show` to prepare
briefs, mark slices ready, review handovers, and accept completed work.

Requires Python 3.13 or later and uv. Install the locked environment with `uv sync`.
The direct runtime dependencies are `jsonschema` and `psycopg` 3. File mode needs
no PostgreSQL installation; database mode also needs the system libpq library.

## State writes and checks

Each mutation locks `<state>.lock`, re-reads and validates, changes one slice,
appends `{at, actor, event}` to its log, validates again, and atomically replaces
the state using a flushed temporary file in the same directory. The actor defaults
to `owner`; the event is the command name. A stable sidecar lock serializes writers
across replacement of the state file. Existing state permissions are preserved.
Readers see a complete old or new state file.

`slot`, `start`, `approve`, `answer`, `review`, and setting `attention` also append one JSON line containing
`{at, id, event, text}` to `<state>.outbox.jsonl` under the same lock. Nothing sends
these notices. State replacement and outbox append are separate filesystem
operations: an I/O failure or crash between them can leave a saved state without
its notice. Errors after the state save do not roll back that save. The outbox
contains answer text; protect it like the state file. These are local files, not
a transaction across multiple files or machines.

With `--commit`, a successful mutation inside a git work tree stages the state
and existing outbox and commits only those paths as `cplane: <command> <id>`.
Then it pulls with rebase and pushes, for at most three pull/push attempts.
Outside a git work tree, `--commit` still saves the files. The state repository
must have a configured upstream, git identity, and credentials. Unrelated staged
changes stay outside the commit but can prevent rebase; keep that work tree clean.
A conflicting rebase is aborted to restore the local commit, then the command
exits nonzero with the reason. Other sync failures also leave the local commit.
Resolve synchronization in the state repository before retrying a mutation.
Add `<state>.lock` to that repository's ignore rules; keep the outbox tracked.

The tool never interprets brief paths, executor/model values or answer text as
shell commands. The runner passes brief and answer text to the executor as a single
argument; the executor itself can perform the work described by that text. Git runs as an argument array and uses the state repository's
normal git configuration and hooks. Use a trusted local state repository. Python's
`fcntl` locking targets macOS and Unix; Windows is not supported.

Run `uv run pytest` for the synthetic fixture, concurrent writer, time, CLI, schema,
and temporary bare-remote Git tests. On every PR, CI runs `test` and a combined
image and gitleaks job. The UI workflow runs when `ui/**` or its workflow changes;
the CLI image workflow runs when `node/cli/**`, `node/proxy/**`,
`node/compose.yaml`, `node/check-fence.py`, or its workflow changes. New PR
updates cancel older runs for the same workflow. CI does not run on pushes to
`main`: the runner requires green checks on an up-to-date PR head before merging.
These filters and the combined job reduce billed Actions minutes. Main requires
the `test` check and forbids force pushes.

## Storage

With `CPLANE_DATABASE_URL` unset, the file store preserves the existing behaviour:
whole-file validation, a stable `.lock` sidecar, atomic state replacement,
`.outbox.jsonl` notices, and git sync. Set `CPLANE_DATABASE_URL` to select Postgres
17 instead. Use a dedicated database and role with access only to that database.
The URL stays in the environment; cplane never includes it in state, logs, or
error messages. An empty variable selects Postgres too and fails to connect rather
than silently falling back to files. Do not put credentials in command arguments.

Postgres keeps each complete slice document in one JSONB row. A position preserves
slice array order. Notices have their own JSONB rows and increasing IDs; a reader
can retain the last ID and query `WHERE id > <marker> ORDER BY id`. Rolled-back
transactions may leave gaps in IDs. Every state write uses the same version 1
validator. A transaction-scoped Postgres advisory lock excludes all writers for the
whole runner pass, including orders and scheduling. Changes and notices commit or
roll back together. Individual order mutations use savepoints. The git pull,
commit and push steps do nothing, and database operation creates no lock or outbox
sidecars. Executor metadata and external effects still live outside this
transaction; Postgres is not a distributed transaction with processes or HTTP.

The database URL does not replace the filesystem anchor: keep `--state` or
`CPLANE_STATE` consistent for relative briefs, run metadata and order receipts.
Without either, database mode uses `slices.json` in the current directory as that
anchor; it does not read or create that file. Keep one runner host and consistent
run directories, as with the file store. This slice does not switch any installed
runner or capture database credentials in a launchd plist; configure the variable
in the runner's environment when a later deployment switches stores.

After setting the URL in the environment, prepare and transfer synthetic data:

```sh
uv run cplane migrate
uv run cplane import /tmp/synthetic-state.json
uv run cplane export /tmp/exported-state.json
```

`migrate` applies the ordered SQL files in `cplane/migrations/`, recording applied
names in `cplane_migrations` in one locked transaction. It is safe to run twice.
Ordinary commands require migration to have run; they never apply it implicitly.
`import` reads the source file and its optional `<state file>.outbox.jsonl`,
validates state, and inserts everything in one transaction. Use a stable offline
copy of the source state and outbox during import. It refuses a database
containing any slice or notice and never changes the source files. `export path`
writes state JSON to the path and notices, in order, to `<path>.outbox.jsonl`,
including an empty outbox when there are no notices. Without a path, `cplane export`
writes state JSON to stdout only when there are no notices. If notices exist, it
refuses without exporting data and asks for `cplane export PATH`. State and notice
data never go to stderr; stderr is reserved for diagnostic messages. JSON formatting
may differ; version, slice order, document values and notice order survive a round trip.
Exports are private data, like the original state and outbox; keep them outside
this repository. Both stores support export.

Tests use synthetic files and temporary repositories. Set
`CPLANE_TEST_DATABASE_URL` only to a disposable PostgreSQL 17 database to run the
Postgres contract tests. Each test creates and drops its own randomly named schema.
Without that variable they skip locally; in CI its absence fails the tests. CI's
`test` job supplies a PostgreSQL 17 service and reports the count that used it.

## Runner

Slice workspaces and cleanup belong to the platform; Factory retains its own private run ledger.

```sh
export CPLANE_REPOS="$HOME/Code"
export CPLANE_RUNS="$HOME/Library/Application Support/cplane/runs"
uv run cplane --state /path/to/state.json run
uv run cplane --state /path/to/state.json install-agent
uv run cplane uninstall-agent
```

The Ubuntu deployment runs four contained services through the platform deployer.
Slice execution uses the platform run API. Subscription evals and chats retain their
separate launcher execution. `sudo factory-cplane` runs installed code inside the
runner container with its environment and state. Installs require
`CPLANE_DEPLOYER_SOCKET`. Deployment and backups are in [docs/node.md](node.md).

`run` makes one locked scheduling pass: synchronize planning state, collect API
records, deliver messages and PR/CI actions, schedule due slices, validate and save
state and notices, then commit the planning changes. Each slice selects a level;
Factory has no role-command model lookup, usage gate or local slice execution path.
Paused work sends no requests or messages. See [runner operation](runner.md).

At the start of every pass, after pulling state and before scheduling, the runner
collects confirmed owner orders from the node's HTTP endpoint. It handles `start`,
`slot`, `pause`, `resume`, `answer`, `approve`, and `orchestrator`. Slice orders
must still match the state, pause flag, and attention kind/timestamp confirmed by
the owner. Changed or missing slices are dropped with an outbox notice. Commands
use the existing validation and locked atomic update path with actor `frontline`;
merge approval still requires a planner review when configured. A start can run in
that same pass. Order notices and collector logs omit argument text; answers remain
in state, as with the terminal command.

Configure the private base URL through `CPLANE_ORDERS_URL`, or put it alone in
`~/Library/Application Support/cplane/orders-url`, beside `runs`. With a custom
`CPLANE_RUNS`, the file is in that run directory's parent. Keep the file private
and outside git. The installed launchd job reads this file on every pass; it does
not capture `CPLANE_ORDERS_URL` from the installing terminal. To turn collection
off, remove the file and unset the variable. An explicitly empty variable also
disables collection for that invocation. Without configuration it skips quietly.
Each HTTP request has a ten-second timeout and no retry within the pass; an
unreachable or locked node logs one line without its address and scheduling
continues. A failed acknowledgement waits until a later pass.

Order receipts live in the state-specific run folder's `orders` directory, outside
the scheduling state. They record IDs and outcomes before acknowledgement, so a
lost acknowledgement is re-sent without executing again. Keep these receipts when
retaining the same state path. An interrupted dispatch is conservatively recorded
as failed and never automatically repeated; inspect local state before issuing a
replacement order. State, outbox, receipts, tmux, and HTTP acknowledgements remain
separate filesystem/process/network operations.

An `orchestrator` order opens one detached window in the `frontline` tmux session,
creating that session when needed. Targets must name a repository in state with a
folder under `CPLANE_REPOS`, or `development` for the state file's directory. An
existing window of that name is refused. The window runs `claude` with the owner's
task verbatim in one prompt argument; order text never enters a shell. Answers and
tasks longer than 4000 characters are refused.

A slice starts when ready, unpaused and due, with its dependencies satisfied. The
runner submits a version 1 platform run request by role and level. Whole-slice work
uses `slice`/`write`; ticket work uses `cut`/`write`, an ordered chain of
`ticket`/`write` requests, then `review`/`read`. PR reviews also use read runs.
The platform selects the executor, handles usage waits and repository concurrency,
checks changes and delivers the branch. Factory never launches a slice harness,
imports a bundle or pushes the implementation branch.

Factory still opens the PR, reads CI, enforces merge guards and owner approval,
merges, and handles attention and node steps. Answers and merge notices use
idempotent messages to the same run. A paused slice sends no requests or messages;
it polls running work and records its result for unpause. Closing or dropping a
slice cancels its open runs; running cancellation retries each pass until its turn
ends. Usage waits show `resume_at` without attention and resume on the platform.

Private request bodies, API records and pending message ids are saved before
external effects under `CPLANE_RUNS/<state hash>/<slice hash>/job.json`. Keep that
ledger and the same absolute state path across restarts. Confirmed requests are
only polled; ambiguous POSTs retry their saved body and id. There are no slice
containers for Factory to find or stop. See [runner operation](runner.md) for
the protocol, deployment boundary and rollback.


`show <id>` names the newest run folder; `show <id> --final` prints that run's
final kind and body.

`install-agent` writes and bootstraps `~/Library/LaunchAgents/com.cplane.runner.plist`.
It uses the current Python environment and checkout, an absolute state path,
a 300-second interval, and `AbandonProcessGroup = true`. Logs go to
`~/Library/Logs/cplane/runner.log` and `runner-error.log`. It captures PATH,
CPLANE_REPOS and CPLANE_RUNS, since launchd does not inherit a terminal environment.
Keep the Python environment, checkout and executor binaries available after
installation. `uninstall-agent` unloads and removes only that agent; detached
executors already running continue. Installation is a separate, explicit action.

As with owner commands, state, outbox, run metadata and remote GitHub effects are
separate writes, not a distributed transaction. Collection replies can be replayed
when state saving fails; PR lookup and merge lookup recover completed GitHub steps.
A crash in the launch/supervisor handoff may need inspection of the run directory;
the runner conservatively reserves capacity rather than launching a duplicate.
Sync failures retain the local state commit. Resolve them before another pass.

## Window primer

The five-hour usage windows of Codex and Claude start at first use. `cplane prime`
starts them on a schedule instead: it sends `Reply with: ok` to Claude (`haiku`),
then Codex (`gpt-6-luna`), each with a 120-second timeout, from an empty temporary
directory with stdin closed. One failing does not stop the other. It holds
`caffeinate -s -i` while it works. It needs no state file.

`install-primer` writes and bootstraps `~/Library/LaunchAgents/com.cplane.primer.plist`
(current Python and checkout, captured PATH, 06:00, 11:00, 16:00 and 21:00, logs in
`~/Library/Logs/cplane/`). `uninstall-primer` removes only that job. Neither touches
the runner's agent.

After the wake schedule date check fix, reinstall the root wake daemon by running
the removal commands below, then the install commands above.

`~/Library/Logs/cplane/primer.log` gets one line per tool (`time tool ok` or
`time tool error exit N|timeout`; never response text) and one line for the sleep
decision. After both requests `prime` runs `pmset sleepnow` only if the last wake was
under 10 minutes ago, was an RTC or scheduled wake, and had no user input since;
otherwise it leaves the Mac as it is.

The Mac must wake a minute before each ping. Once, as a backstop (undo with
`sudo pmset repeat cancel`):

```sh
sudo pmset repeat wake MTWRFSU 05:59:00
```

The other wakes come from a root LaunchDaemon, `com.cplane.primer-wake`. Its plist
is self-contained (an inline script; root runs no file from the checkout). At load
and at 00:05 it schedules today's remaining and tomorrow's wakes (05:59, 10:59,
15:59, 20:59) with `pmset schedule wake`, skipping any already listed in
`pmset -g sched` or in the past. Install it once:

```sh
D=/Library/LaunchDaemons/com.cplane.primer-wake.plist
T=$(mktemp)
uv run cplane primer-wake-plist > "$T"
sudo cp "$T" "$D"
sudo chown root:wheel "$D"
sudo chmod 644 "$D"
sudo launchctl bootstrap system "$D"
```

Remove it (scheduled one-shot wakes stay until they pass):

```sh
D=/Library/LaunchDaemons/com.cplane.primer-wake.plist
sudo launchctl bootout system "$D"
sudo rm "$D"
```

Factory's contained deployment, retained CLI fence tools and security limits
are documented in [docs/node.md](node.md).

Runtime turn instructions are stored in `cplane/prompts/`.
