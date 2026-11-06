# Control plane

A scheduler's state file and its commands. `cplane` helps an owner schedule slices of
coding work, answer questions, approve merges, and see what is pending. It records
intent through owner commands. `start` sets a slot to now; `resume` clears a pause
flag. The separate `run` command starts and resumes Codex and Claude executors.
Planning agents use `add`, `edit`, `state`, `attention`, `review`, and `show` to prepare
briefs, mark slices ready, review handovers, and accept completed work.

Requires Python 3.13 or later and uv. Install the locked environment with `uv sync`.
The only direct runtime dependency is the MIT-licensed `jsonschema` library.

```sh
uv run cplane --help
export CPLANE_STATE=/path/to/state.json
uv run cplane pending
uv run cplane pending --json
uv run cplane --actor planner add --id example/W2 --repo example/project --feature example --title 'Next slice' --brief briefs/W2.md
uv run cplane --actor planner edit example/W2 --depends-on example/W1
uv run cplane --actor planner state example/W2 ready
uv run cplane show example/W2 --json
uv run cplane slot example/W1 'Mon 03:00'
uv run cplane slot example/W1 'tomorrow 06:00'
uv run cplane unslot example/W1
uv run cplane start example/W1
uv run cplane pause example/W1
uv run cplane resume example/W1
uv run cplane --actor planner review example/W1 'Reviewed the diff and tests; ready to merge'
uv run cplane approve example/W1
uv run cplane answer example/W1 'Use the existing interface'
uv run cplane --actor owner --commit slot example/W1 '2026-10-19T03:00:00+02:00'
```

`--state PATH` overrides `CPLANE_STATE`. Global options may appear before or after
the command. The state file must already exist. It belongs to a separate repository;
this repository contains only the schema and synthetic test fixtures.

| Command | Purpose |
| --- | --- |
| `pending [--json]` | List pending slices by group. |
| `show <id> [--json] [--final]` | Print a slice and newest run folder, or its latest final message. |
| `add --id <id> --repo <repo> --feature <text> --title <text> [options]` | Add a planned slice; refuse an existing ID. |
| `edit <id> [options]` | Change only the supplied fields. |
| `state <id> <state> [--session <tool>:<id>:<folder>] [--force --reason <text>]` | Record an allowed state transition. Quote states containing spaces. |
| `attention <id> --kind <kind> --body <text>` | Record attention and append a notice. |
| `attention <id> --clear` | Clear attention. |
| `review <id> "<verdict>"` | Record a planner review on merge attention. |
| `compact` | Bound oversized runner log events and attention bodies in every slice. |
| `slot <id> <when>` / `unslot <id>` | Record or clear a scheduled time. |
| `start <id>` | Slot a ready slice now. |
| `pause <id>` / `resume <id>` | Set or clear the pause flag. |
| `approve <id>` / `answer <id> <text>` | Approve merge attention or answer a question/escalation. |
| `run` | Make one runner pass. |
| `install-agent` / `uninstall-agent` | Install or remove the launchd runner. |
| `prime` | Send one tiny request to Claude and Codex to start their usage windows. |
| `install-primer` / `uninstall-primer` | Install or remove the launchd job that runs `prime`. |
| `primer-wake-plist` | Print the root wake-schedule LaunchDaemon plist; never installs it. |

`add` and `edit` accept `--repo`, `--feature`, `--title`, `--brief`,
`--tool codex|claude`, `--model`, `--effort low|medium|high|xhigh|max|ultra`,
`--stop-before-merge` (or
`--no-stop-before-merge`), and `--depends-on <id> …`. Dependencies replace the
list; `--depends-on` with no IDs clears it, and repeated occurrences extend the
replacement list. `edit` also accepts `--id` to change the ID; references in other
slices are left as recorded. IDs remain unique. While issued or awaiting handover,
only the title and dependencies can be edited.

New slices default to executor `codex` / `gpt-6.1-sol`, no effort override, no brief,
no dependencies,
`stop_before_merge` and `paused` false, and null slot, session, PR, and attention.
Codex effort defaults to `low` for models containing `luna` and `medium` for other
models. `--effort` overrides that default for starts and resumes; Codex's supported
levels are `low`, `medium`, `high`, `xhigh`, and `max`, with `ultra` also available
for Sol and Terra models.
The command creates the first log entry. Brief paths are stored without reading
the file. A brief must be set before moving to ready.

Allowed state transitions are:

| From | To |
| --- | --- |
| planned | researching, ready |
| researching | planned, ready |
| ready | planned (clears slot), issued (requires `--session`) |
| issued, awaiting handover | in review, escalated, awaiting handover |
| escalated | issued |
| in review | accepted, issued |

Every other transition is refused with a reason. From any state,
`state <id> planned --force --reason <text>` resets to planned and clears the
slot; the nonempty reason is recorded in the log. Other fields remain recorded.
`--session` is allowed only for ready → issued and records an executor already
started outside the runner; this command starts no process. The tool must be codex
or claude, and both ID and folder must be nonempty. Folder paths may contain colons.
State log events include the destination and any forced-reset reason.

Attention kinds are `question`, `escalation`, `merge`, `node-step`, and
`owner-check`. Setting attention replaces its body and timestamp, clears its
answer and approval, and leaves the slice's state as recorded. Clearing attention
adds no notice. All planner writes accept `--actor` (default `owner`) and
`--commit`, like the owner commands. `show --json` returns one slice object.

The runner stores failure tails up to 4,000 characters, attention bodies up to
8,000 characters, and log events up to 500 characters. `attention` log entries
contain the kind and the body's first line. `compact` applies the log and body
limits to existing slices under the state lock; it reports cut counts and the
state file size before and after. Use `--commit` to commit and sync the compacted
state. It does not change answers or review verdicts.

`review` requires merge attention and records `review: {verdict, at, actor}` on
that attention. It appends a notice, `Reviewed <id>: <first line of verdict>`.
Setting new attention replaces any previous review. The review property is optional
in version 1; existing state files remain valid.

The version 1 shape is defined in [schema/slices.schema.json](schema/slices.schema.json)
(JSON Schema draft 2020-12). The loader additionally checks uniqueness of slice IDs,
which JSON Schema cannot express for one field of objects in an array. Unknown
properties, missing fields, and timestamps without offsets are rejected. Dependency
IDs may refer to absent slices; those dependencies count as unmet.

A minimal synthetic state file:

```json
{
  "version": 1,
  "slices": [{
    "id": "example/W1",
    "repo": "example/project",
    "feature": "example",
    "title": "An example slice",
    "state": "ready",
    "brief": "briefs/W1.md",
    "executor": {"tool": "codex", "model": "example-model"},
    "stop_before_merge": true,
    "depends_on": [],
    "slot": null,
    "paused": false,
    "session": null,
    "pr": null,
    "attention": null,
    "log": []
  }]
}
```

`slot` and `start` require `ready`. They name every unmet dependency in a warning
but still record the slot. `approve` requires merge attention and, when
`stop_before_merge` is true, a recorded planner review on that attention. The
planner uses `review` before the owner approves. Slices without `stop_before_merge`
retain the existing approval behaviour. `answer` requires
question or escalation attention. Other owner mutations apply to any existing slice,
including repeated calls. Refusals exit nonzero with one line on stderr and leave
the state unchanged. A warning accompanies a successful command and exits zero.

Offset-free ISO timestamps and short forms use Europe/Copenhagen, including its
summer/winter offset. Explicit offsets are preserved. Weekday forms choose the
next occurrence of that time (later today, or next week if already passed).
`today HH:MM` is also supported. Ambiguous and nonexistent local times during
clock changes require an explicit offset. Quote time expressions and answers.

`pending` omits accepted slices and assigns each remaining slice to one group,
in this precedence order:

- **needs attention:** unanswered question/escalation, unapproved merge, node-step,
  owner-check, or a slice in review/escalated;
- **running:** issued or awaiting handover, even if its slot is still recorded;
- **scheduled:** other slices with a slot, sorted by instant and shown by local day;
- **ready:** unscheduled ready slices;
- **planned:** remaining slices, including researching.

Groups are displayed in the order needs attention, scheduled, ready, running,
planned. Within other groups, IDs sort alphabetically. Paused slices remain visible.
`--json` returns those group names as keys and arrays of full slice records as values.

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
and temporary bare-remote Git tests. CI runs the tests and gitleaks on every PR and
on pushes to `main`. Main requires the `test` check and forbids force pushes.

## Runner

At the end of each pass, the runner restores clean detached clones to their default branch and removes old, removable Codex worktrees for repositories with no busy slices.

```sh
export CPLANE_REPOS="$HOME/Code"
export CPLANE_RUNS="$HOME/Library/Application Support/cplane/runs"
uv run cplane --state /path/to/state.json run
uv run cplane --state /path/to/state.json install-agent
uv run cplane uninstall-agent
```

Only `run` starts or resumes executors. It makes one pass under the state lock:
pull the state repository, collect finished turns, deliver answers and approvals,
start due slices, validate and save state, append notices, then commit and push.
The runner always syncs state in a git repository; it does not need `--commit`.
Outside git it still saves state and notices, which is useful for temporary tests.
Brief paths resolve relative to the state file's directory. Repository checkouts
resolve as `$CPLANE_REPOS/<repository-name>` (default `~/Code`). Existing owner
commands, the version 1 schema, and the outbox format are unchanged.

Runner details: the pull uses `--autostash`, so an uncommitted outbox line does not
stop it. A `CANCELLED` check is not red when another check of the same name on the
rollup succeeded (a stalled hosted runner); any other red conclusion stays red. An
accepted slice whose process has ended no longer holds a slot or its repository; a
live process still counts. For the Claude tool, a model of `opus` or `sonnet` is used
as written; any other name maps to `opus` if it holds `sol`, else `sonnet`. A
`node-step` attention can be answered with `cplane answer`, and the runner resumes
the session with the text, as for an escalation.

Role defaults: `cplane add --role <name>` (default `cutter`) takes the slice's
executor from a table of roles when neither `--tool` nor `--model` is given. The
local file `roles-command`, beside `orders-url` (the parent of the `runs` folder), holds
a command line that prints one JSON object from role name to an ordered list of
routes. It is split with `shlex` and run without a shell, with stdin closed and a
10-second timeout. The first route of kind `cli` sets `tool` (`codex` or `claude`),
`model` and, if present, `effort`; `--effort` always overrides. If the file is
missing, the command fails or times out, the output is invalid or the role has no
valid `cli` route, cplane keeps its own defaults and prints one line on stderr.
Only `add` reads the table; the runner and existing slices do not.

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

A slice starts when ready, unpaused, at or after its slot, with every dependency
accepted. Accepted slices are skipped with a log entry on each pass; the runner
does not start, resume, deliver to, merge for, or collect into them, including when
saved jobs or attention remain. A slice runs only on its configured executor.
Codex needs known five-hour usage below 99%; when its window is full, Codex slices
are deferred until capacity returns and are never moved to Claude. A Codex turn cut
by its usage limit waits in its run record and resumes the same session after the
reset; other failed turns still raise escalation. Claude slices use their configured
model and require a usage file less than an hour old and below 90% for five hours.
Missing usage is unavailable capacity. The next pass retries deferred work.
Resumes retain the session's tool and model and wait for that tool's capacity;
sessions cannot transfer between providers. At most two turns run concurrently,
and only one per repository. Sessions whose local run metadata is missing still
occupy a slot until reconciled. Use a single state file and consistent run directory
for the scheduler.

Codex receives the brief unchanged. Claude receives it followed by the GitHub
instructions in `cplane/executors.py`: push the branch and return a waiting message
with a fenced JSON PR request (`branch`, `title`, `body`, `node_steps`). The runner
creates the PR and checks it on later passes. Failing checks raise escalation;
pending checks wait. Green checks allow a merge, with owner approval first when
`stop_before_merge` is true. After merging it resumes Claude with the merge SHA,
or raises node-step attention if the request requires owner-node work. Codex
handles its own GitHub work. When it returns `waiting` with an open PR found by
branch lookup or a PR number in its reply, the runner watches CI on later passes.
Red checks raise escalation naming the failing check; pending checks wait. Green
checks create `Approve PR #<n>` merge attention for `stop_before_merge` slices,
requiring a planner review before owner approval. Otherwise the runner resumes
Codex with `CI is green on PR #<n>; merge it and continue.` Approved Codex merge
attention resumes it with the owner's approval. `answer` and `approve` only record
the response; the next pass delivers it subject to capacity and concurrency limits.

A handover moves the slice to `in review` and emits `finished`. Questions and
escalations create attention; an escalation sets `escalated`. Ordinary waiting
messages without a PR to watch create node-step attention. A terminated turn
without a valid, fresh final message raises escalation with a summary of the tool, exit code and first
stderr error line, followed by the last 40 log lines. All runner actions
append log entries with actor `runner`. Notices go to the existing local outbox;
there is no external notification sender.

The detached supervisor writes executor output, final replies, session IDs, exit
markers and private turn metadata under `CPLANE_RUNS` (default
`~/Library/Application Support/cplane/runs`). Each state path has its own directory,
with one subdirectory per turn. Session IDs are recorded when they appear in the
executor output, even while a turn is running. When a Codex turn is collected,
the runner records the PR number for the repository's current branch when one
exists. Codex final files must be newer than the turn's start; Claude replies come from
`structured_output`. Run metadata supports collection across CLI restarts. Keep
these files private like state and outbox: they contain prompts and answers.
Do not delete them while a turn is active. Retain the same absolute state path.

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
