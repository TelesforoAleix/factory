# Commands

This document covers the rules behind the `cplane` commands that planners, owners
and operators use: what each command may change, the slice transitions, attention
kinds, pending groups and time expressions. Read it before you change a command or
call one from a skill, prompt or tool. `cplane --help` and `cplane COMMAND --help`
list the options; this document does not repeat them. Commands need the configured
database ([operations](operations.md#storage)); on the node, run them through
`sudo factory-cplane` ([node](node.md)).

## Global options

`--actor NAME` (default `owner`) names who acts in the mutation log. `--state PATH`
overrides `CPLANE_STATE`, the anchor for relative briefs and the run ledger.
Global options may appear before or after the command. `--commit` is accepted for
compatibility and does nothing with the Postgres store. Refusals exit nonzero with
one line on stderr and leave state unchanged; a warning accompanies a successful
command and exits zero.

## Planner commands

```sh
cplane --actor planner add --id example/W2 --repo example/project --feature example --title 'Next slice' --feature-id FAC-F1 --brief briefs/W2.md
cplane --actor planner edit example/W2 --depends-on example/W1
cplane --actor planner state example/W2 ready
cplane --actor planner review example/W1 'Reviewed the diff and tests; ready to merge'
cplane show example/W2 --json
cplane pending
cplane why example/W2
```

`add` and `edit` accept `--level light|standard|strong`, `--flow cli|tickets`,
`--allowed-files GLOB …`, `--stop-before-merge` (or `--no-stop-before-merge`) and
`--depends-on ID …`. Dependencies replace the list; `--depends-on` with no IDs
clears it, and repeated occurrences extend the replacement list. Dependency IDs may
refer to absent slices; those count as unmet. `edit` also accepts `--id` to change
the ID; references in other slices are left as recorded. IDs remain unique. While
issued or awaiting handover, only the title and dependencies can be edited.

New slices default to level `standard`, no brief or dependencies,
`stop_before_merge` and `paused` false, and null slot, session, PR and attention.
The platform chooses the tool, model and effort by role and level; legacy executor
fields in version 1 documents are retained as metadata only. Brief paths are stored
without reading the file. A brief must be set before moving to ready.

Allowed state transitions are:

| From | To |
| --- | --- |
| planned | researching, ready |
| researching | planned, ready |
| ready | planned (clears slot), issued (requires `--session`) |
| issued, awaiting handover | in review, escalated, awaiting handover |
| escalated | issued, ready (fresh attempt on start) |
| in review | accepted, issued |

Every state except accepted and dropped may also move to dropped; pause issued or
awaiting-handover slices first. Every other transition is refused with a reason.
From any state, `state <id> planned --force --reason <text>` resets to planned and
clears the slot; the nonempty reason is recorded in the log. `--session` is allowed
only for ready → issued and records an executor already started outside the runner;
this command starts no process. The tool must be codex or claude, and both ID and
folder must be nonempty. Folder paths may contain colons. State log events include
the destination and any forced-reset reason.

Attention kinds are `question`, `escalation`, `merge`, `node-step`,
`owner-check`, `contract-change` and `docs-graph` (the last two are raised by the
runner after a merge; clear them with `attention --clear`). Setting attention
replaces its body and timestamp, clears its answer and approval, and leaves the
slice's state as recorded. Clearing attention adds no notice.

`review` requires merge attention and records `review: {verdict, at, actor}` on
that attention. It appends a notice, `Reviewed <id>: <first line of verdict>`.
Setting new attention replaces any previous review.

## Owner commands

```sh
cplane slot example/W1 'Mon 03:00'
cplane unslot example/W1
cplane start example/W1
cplane pause example/W1
cplane resume example/W1
cplane approve example/W1
cplane answer example/W1 'Use the existing interface'
```

`slot` and `start` require `ready`. They name every unmet dependency in a warning
but still record the slot. `approve` requires merge attention and, when
`stop_before_merge` is true, a recorded planner review on that attention. `answer`
requires question or escalation attention. Other owner mutations apply to any
existing slice, including repeated calls.

Set `FACTORY_TIME_ZONE` to an IANA time zone name for server-side timestamps and
calendar expressions; it defaults to `UTC`. Invalid names fail at startup. Offset-free
ISO timestamps and short forms use this zone, including its seasonal offset changes.
Explicit offsets are preserved. Weekday forms choose the
next occurrence of that time (later today, or next week if already passed).
`today HH:MM` and `tomorrow HH:MM` are also supported. Ambiguous and nonexistent
local times during clock changes require an explicit offset. Quote time
expressions and answers.

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

Use `installed` for repositories outside `CPLANE_INSTALL_REPOS` after installing the exact merged commit by hand. Answer any node-step attention separately. The install procedure is in [operations](operations.md#install-after-a-merge).

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

## Execution and fresh attempts

Slice execution uses the platform run API; `--level` is the only executor choice a
slice records. Legacy executor metadata in version 1 documents is not used to select
an executor. `show --final` reads the saved API final message. `why` reports
platform usage waits with their `resume_at`; Factory applies no executor or
repository slot limits to slice requests. See [runner operation](runner.md). Chat
settings and model choices are separate.

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

## Eval catalogue and runs

`cplane eval …` commands require the database, always emit JSON, and store
experiments without starting executors. Their case format, versioning rules and
examples are in [evals](evals.md).

## Documentation claims

Check a repository's `docs/claims.json` at a revision; see
[docs-verify](docs-verify.md). It needs no database. Without `--graph-only` it
calls the decisions API with the platform run key.

```sh
cplane docs-verify REPO [--rev REV] [--with PATH ...] [--graph-only] --out RECORD.json
```

## Store commands

`migrate`, `import` and `export` are described in [operations](operations.md#storage).
`compact` bounds oversized runner log events and attention bodies in every slice
under the store lock and reports cut counts and the state size before and after. It
does not change answers or review verdicts. The runner stores failure tails up to
4,000 characters, attention bodies up to 8,000 characters, and log events up to 500
characters; `attention` log entries contain the kind and the body's first line.

The version 1 shape is defined in [schema/slices.schema.json](../schema/slices.schema.json)
(JSON Schema draft 2020-12). The validator additionally checks uniqueness of slice
IDs, which JSON Schema cannot express for one field of objects in an array. Unknown
properties, missing fields, and timestamps without offsets are rejected.

## Other command groups

`feature`, `slice place|link`, `chat`, `skill`, `models`, `limit`, `runs`, `run
list|show|total|mark` and `digest` manage Postgres records behind Workshop; their
options are in `--help`. `inbox` and `idea` are described in [inbox](inbox.md),
`eval` in [evals](evals.md), `run` and `run --every` in
[operations](operations.md#runner-loop-and-exports), and `prime`, `install-primer`,
`uninstall-primer` and `primer-wake-plist` in [operations](operations.md#mac-primer).

## Cutting a plan by hand

The runner's ticket flow cuts through the platform ([runner](runner.md)). These two
commands are the manual path for an external task queue. `cplane cut-prompt ID` prints the versioned cutter instructions followed by the slice's brief, resolved relative to the state file. The cutter writes tests and returns a JSON plan matching `schema/plan.schema.json`. This command does not run a model.

```sh
export CPLANE_TASK_SUBMIT='["/path/to/submit-command", "submit"]'
uv run cplane cut-prompt project/W1
uv run cplane --actor planner cut-submit project/W1 plan.json --repository owner/name --branch feature-branch --base 0123456789abcdef0123456789abcdef01234567
```

`cut-submit` validates the plan, copies the brief's Fixed decisions and Do not sections into each ticket, chains the tickets in order, and pins the plan's test files. The submit command receives the task file as JSON on stdin, without a shell, and must return a JSON list of task IDs. It enforces repository, branch and base requirements; in particular the branch must exist and not be the default branch. The instructions must be committed in the cplane Git checkout; the commit that last changed `skills/` is recorded in the slice log. A notice records the count and IDs.

Submission and state saving are separate operations. If the submit command succeeds but returns invalid output, or if saving state or syncing fails afterward, inspect the queue and state before retrying to avoid duplicate tickets. Submit command output and errors are not displayed, except validated task IDs in the notice.
