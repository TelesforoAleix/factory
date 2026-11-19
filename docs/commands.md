# Commands

Use the current command notes below with `cplane --help`. The production store is
Postgres. The earlier README reference is retained verbatim at the end, including
historical file-store behavior and launchd commands. Its `add` example predates
the required feature association; use `--feature-id` or `--no-feature` as described
below. Production commands require the configured database and service environment.
See [operations](operations.md) and the current [runner protocol](runner.md).

## Active projects

Projects are active by default. The shared flag controls page visibility only;
execution, queue order, limits and notices are unaffected. `NEW` is always active.

```sh
cplane project list
cplane project active FAC
cplane project active FAC off --actor owner
cplane project active FAC on --actor owner
```

Activation also creates the project's orchestrator chat if missing, using the
project chat defaults. Repeated activation reuses the existing chat. Deactivation
keeps all features, chats and documents. Settings › Projects changes the same flag.

Project pages and owner field editing use the same store methods as the CLI:

```sh
cplane project add SYN 'Synthetic project' --actor owner
cplane project set SYN --name 'Synthetic' --about 'What we are building.' \
  --public-url https://example.test --repository-url https://example.test/repo \
  --actor owner
```

Keys are permanent and unique; adding creates an active project with its chat.
Names allow 1–60 characters and About allows up to 600. URLs must use HTTPS;
pass an empty URL to remove it. See [Project pages](project-pages.md) for usage
accounting, validation and installation.

## Slice housekeeping

Slice creation and edits require either a valid `--feature-id` (a current ID or
alias) or `--no-feature REASON` for work without a feature. The free-text
`--feature` name is not a link. Reasons must be nonempty and at most 200
characters. The options are mutually exclusive. Use `edit --no-feature REASON`
to remove a feature link; setting `--feature-id` removes the previous reason.
Existing unassociated slices need one of these options when edited. Issued and
awaiting-handover slices retain their existing edit restrictions, so their
association cannot be changed in those states.

```sh
cplane add --id example/W1 --repo owner/repo --feature Chore --title Cleanup --no-feature 'One-off cleanup' --actor planner
cplane edit example/W1 --feature-id FAC-F1 --actor planner
```

```sh
cplane state SLICE dropped --actor owner  # Pause issued or awaiting-handover slices first.
cplane install SLICE --actor owner
cplane installed SLICE FULL_MERGE_SHA --note 'Installed by hand' --actor owner
```

Use `installed` for repositories outside `CPLANE_INSTALL_REPOS` after installing the exact merged commit by hand. Answer any node-step attention separately.

## Eval catalogue and runs

These commands require `CPLANE_DATABASE_URL` or `CPLANE_DATABASE_URL_FILE` and
always emit JSON. They store experiments without starting executors.
See [Eval store](evals.md) for the case format and versioning rules.

```sh
cplane eval import FOLDER
cplane eval case from-slice SLICE --kind KIND --check COMMAND --grade {tests_and_judge,judge} --validation TEXT [--hidden PATH ...]
cplane eval case list [--kind KIND] [--tag-kind TAG] [--size SIZE] [--language LANGUAGE] [--half HALF]
cplane eval config add ID --path {slice,tickets} --role 'ROLE=JSON'... [--note TEXT] [--actor ACTOR]
cplane eval config list
cplane eval config show ID
cplane eval set create ID --title TITLE --filter JSON [--description TEXT] [--note TEXT] [--actor ACTOR]
cplane eval set add ID CASE... [--note TEXT] [--actor ACTOR]
cplane eval set list
cplane eval set show ID [--version N]
cplane eval run create --title TITLE --set ID[:VERSION]... --configuration ID... --repeats N [--at TIME] [--actor ACTOR]
cplane eval run list
cplane eval run show ID
```

Repeat `--set` and `--configuration` for multiple selections. Filters are JSON
objects using `kind`, `tag_kind`, `size`, `language`, and `half` keys.


Slice execution uses the platform run API. `add` and `edit` accept `--level
light|standard|strong`; per-slice `--tool`, `--model` and `--effort` are removed.
Legacy executor metadata in version 1 documents remains for compatibility and is
not used to select an executor. `show --final` reads the saved API final message.
`why` reports platform usage waits with their `resume_at`; Factory no longer
applies executor or repository slot limits to slice requests. See [runner
operation](runner.md). Chat settings and model choices remain separate.


An escalated slice may move to `issued` to continue its existing run, or to `ready`
to request a fresh attempt. Ready still requires a brief. Use the locked planner
commands and identify the planner:

```sh
cplane state SLICE ready --actor planner
cplane start SLICE --actor planner
```

On the next start, Factory cancels the previous attempt's runs (retrying running
turns until cancellation is accepted), clears attention and raises the existing
attempt number. Request ids change and the base is the default branch's current
tip. The slice keeps its id, brief, level, flow and branch name. Paused slices do
not start until resumed. The state command itself starts no executor.

`show` and `show --json` display `runs` from the slice's run records, newest
first, with role, tool, model, effort and start time. Older records may have an
empty role. The slice detail API and Workshop use the same records.

## Earlier README command reference

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
the command. With the file store, the state file must already exist. It belongs to a separate repository;
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
| `migrate` | Apply ordered Postgres SQL migrations; safe to repeat. |
| `import <state file>` | Load state and its outbox into an empty Postgres database. |
| `export [path]` | Export state JSON and outbox JSONL in the file format. |
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
`--level light|standard|strong`,
`--stop-before-merge` (or
`--no-stop-before-merge`), and `--depends-on <id> …`. Dependencies replace the
list; `--depends-on` with no IDs clears it, and repeated occurrences extend the
replacement list. `edit` also accepts `--id` to change the ID; references in other
slices are left as recorded. IDs remain unique. While issued or awaiting handover,
only the title and dependencies can be edited.

New slices default to level `standard`, no brief or dependencies,
`stop_before_merge` and `paused` false, and null slot, session, PR and attention.
The platform chooses the tool, model and effort by role and level; legacy executor
fields in version 1 documents are retained as metadata. Planner writes use the
locked, validated update path and log the actor. Brief paths are stored without
reading the file. A brief must be set before moving to ready.

Allowed state transitions are:

| From | To |
| --- | --- |
| planned | researching, ready |
| researching | planned, ready |
| ready | planned (clears slot), issued (requires `--session`) |
| issued, awaiting handover | in review, escalated, awaiting handover |
| escalated | issued, ready (fresh attempt on start) |
| in review | accepted, issued |

Every other transition is refused with a reason. From any state,
`state <id> planned --force --reason <text>` resets to planned and clears the
slot; the nonempty reason is recorded in the log. Other fields remain recorded.
An escalated → ready reset requests a fresh attempt on the next start, cancelling
old runs and using the current default-branch tip with new request ids.
`--session` is allowed only for ready → issued and records an executor already
started outside the runner; this command starts no process. The tool must be codex
or claude, and both ID and folder must be nonempty. Folder paths may contain colons.
State log events include the destination and any forced-reset reason.

Attention kinds are `question`, `escalation`, `merge`, `node-step`, and
`owner-check`. Setting attention replaces its body and timestamp, clears its
answer and approval, and leaves the slice's state as recorded. Clearing attention
adds no notice. All planner writes accept `--actor` (default `owner`) and
`--commit`, like the owner commands. `show --json` returns one slice object with `runs`, the current attempt’s
role/executor pairs from the platform. Legacy slice executor metadata stays stored
and is omitted from this display.

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

The version 1 shape is defined in [schema/slices.schema.json](../schema/slices.schema.json)
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

Set `FACTORY_TIME_ZONE` to an IANA time zone name for server-side timestamps and
calendar expressions; it defaults to `UTC`. Invalid names fail at startup. Offset-free
ISO timestamps and short forms use this zone, including its seasonal offset changes.
Explicit offsets are preserved. Weekday forms choose the
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

## Cutting a plan into queue tickets

`cplane cut-prompt ID` prints the versioned cutter instructions followed by the slice's brief, resolved relative to the state file. The cutter writes tests and returns a JSON plan matching `schema/plan.schema.json`. This command does not run a model.

```sh
export CPLANE_TASK_SUBMIT='["/path/to/submit-command", "submit"]'
uv run cplane --state /path/to/state.json cut-prompt project/W1
uv run cplane --state /path/to/state.json --actor planner cut-submit project/W1 plan.json --repository owner/name --branch feature-branch --base 0123456789abcdef0123456789abcdef01234567
```

`cut-submit` validates the plan, copies the brief's Fixed decisions and Do not sections into each ticket, chains the tickets in order, and pins the plan's test files. The submit command receives the task file as JSON on stdin, without a shell, and must return a JSON list of task IDs. It enforces repository, branch and base requirements; in particular the branch must exist and not be the default branch. The instructions must be committed in the cplane Git checkout; the commit that last changed `skills/` is recorded in the slice log. A notice records the count and IDs. The normal `--commit` option also applies.

Submission and state saving are separate operations. If the submit command succeeds but returns invalid output, or if saving state or syncing fails afterward, inspect the queue and state before retrying to avoid duplicate tickets. Submit command output and errors are not displayed, except validated task IDs in the notice.
