# Eval store

An eval compares quality, speed and cost on the same work across configurations.
The runner executes slice and review attempts in the fence and sends ticket attempts
to the platform, which grades them with their pinned check.
All commands require Postgres through `CPLANE_DATABASE_URL` or
`CPLANE_DATABASE_URL_FILE`, and emit JSON. Mutations accept `--actor` (default
`owner`) to record who created a configuration, set version or run.

A new **case** is a validated slice: its brief, start commit and merged result,
with the orchestrator's qualification reason. Existing ticket and review cases
remain supported. A **set** is a named selection of
cases; its numbered **versions** preserve their membership. An **eval run** selects
set versions, configurations and repeats. An **attempt** is one case × configuration
× repeat within that run. A **verdict** is a judge's grade of one attempt; multiple
judges can grade the same attempt.

## Case files

Cases originate in merged pull requests from any repository. Import reads every
`*.json` in one folder, paired with `<branch>.patch` containing the whole slice's
reference git diff. A ticket source looks like this (all values are synthetic):

```json
{
  "repository": "example/public",
  "pr": 53,
  "base_commit": "0123456789012345678901234567890123456789",
  "branch": "synthetic-slice",
  "tickets": [
    {
      "title": "List inbox items",
      "files": ["src/inbox.py", "tests/test_inbox.py"],
      "change": "Implement the synthetic inbox listing task.",
      "check": "uv run --frozen pytest tests/test_inbox.py -k list",
      "tag_kind": "new",
      "language": "python"
    }
  ]
}
```

Tickets have IDs `repository#pr/1`, `repository#pr/2`, etc., following array order.
Keep that order stable when updating a source. `tag_kind` and `language` may also
be supplied at the source level as explicit defaults for its cases; a ticket's
values take precedence. Missing or invalid tags fail the whole import and name
the case. Tags are never inferred from task text, filenames or the diff.

For a whole slice or review, use `"kind": "slice"` or `"kind": "review"` and put
`title`, `change`, `tag_kind` and `language` directly on the source object, alongside
`repository`, `pr`, `base_commit` and `branch`. Slices require `level` of `light`,
`standard` or `strong`. `check` is optional for slices and reviews. Their ID is `repository#pr`;
a slice and a review of the same PR therefore share the prescribed ID and cannot
coexist as separate cases. Ticket files default to `kind` of `ticket`.

The importer retains the whole reference diff. Size counts added plus deleted
hunk lines and files in that diff, restricted to the ticket's `files` for tickets.
Renames match either their old or new path; binary and rename-only entries count
as files with zero changed text lines. Git paths may be unquoted or use git's quoted UTF-8 path encoding.

- `tag_kind`: `new`, `change`, `fix`, `tests`, `docs`.
- `language`: `python`, `swift`, `typescript`.
- `size`: `S` for at most 50 changed lines and at most 2 files; otherwise `M` for
  at most 200 changed lines and at most 5 files; otherwise `L`.

Half is fixed by the PR: read the first eight hex digits of
`sha256("<repository>#<pr>")` as an integer, modulo 5. Values 0 and 1 mean
`held-out`; others mean `development`. Every case from a PR shares its half.

Imports insert or update by ID in one transaction. Reimporting identical cases
leaves even `created_at` unchanged. Missing files do not delete existing cases.
Output contains only `inserted`, `updated` and `unchanged` counts, never case text.
Case content may be updated by import; versions freeze member IDs, not copies of
case content. Import is a trusted local operation and does not verify public PR
metadata or run the supplied check command.

The slice catalogue also stores validated slices from any repository. The brief
is `task` (imported from `change`), the start is `base_commit` or the existing
`start_commit`, and the merged result is `merge_commit` plus `reference_diff`.
These additional source fields are optional and nullable:

| Field | Meaning |
| --- | --- |
| `source_slice` | Factory slice ID, `<repo>/<id>`. |
| `merge_commit` | Full 40-digit hexadecimal merged commit ID. |
| `hidden_paths` | Array of the merged PR's test file paths. |
| `grade` | `tests_and_judge` or `judge`. |
| `validation` | Orchestrator's reason the case qualifies. |

Use hidden tests plus a judge when the merged PR's tests apply to the brief.
Use judge only when those tests depend on names the brief never fixed; record
the reason in `validation`. Import validates field shapes, not that qualification
decision. Case list includes these fields. Omitting them on reimport preserves
stored values; explicit JSON null clears a value. Ticket entries may override
source-level defaults. Existing ticket and review cases remain valid.

## Cases from accepted slices

`cplane eval case from-slice project/slice --kind fix --check 'uv run pytest' --grade tests_and_judge --validation 'Reviewed against the brief'` stores a case from an accepted, uncorrected slice with a merged PR. The command reads the brief from the git history of the clone containing `CPLANE_STATE` (or the current directory when unset), and uses a repository-scoped read-only GitHub App token. Set the GitHub App environment as for Factory's runner.

The case ID is `slice:<slice id>`. Repeating the command returns the original case unchanged and reports this on stderr. Changed test paths become hidden paths by default; repeat `--hidden PATH` to replace that selection. `tests_and_judge` requires at least one hidden path. Language is the most frequent supported extension among changed paths, with ties resolved in Python, Swift, TypeScript order. The qualification text and grade are recorded for owner review before adding the case to a set.

## Named configurations

A configuration is an immutable named record with `id`, `path`, `roles`, `note`,
`created_by` and `created_at`. Changes require a new name; a second add of the
same name is refused, even with identical values. The slice path requires exactly
`executor` and `reviewer`; the tickets path requires exactly `cutter`, `ticket`
and `reviewer`. Each role uses one of these exact platform executor shapes:

```json
{"harness": "codex", "model": "example-model", "effort": "medium"}
{"harness": "claude", "model": "example-model"}
{"configuration": "pi/base"}
```

Models and Codex effort are nonempty text. Pi names after `pi/` match
`[A-Za-z0-9][A-Za-z0-9._-]{0,63}`. Extra entry fields and unknown harnesses are
refused. Python callers reuse `validate_configuration(path, roles)`; store APIs
are `config_add`, `config_list` and `config_show`.

```sh
cplane eval config add slice-example --path slice \
  --role 'executor={"harness":"codex","model":"example-model","effort":"medium"}' \
  --role 'reviewer={"harness":"claude","model":"example-model"}' \
  --note 'Synthetic slice configuration' --actor planner
cplane eval config add tickets-example --path tickets \
  --role 'cutter={"configuration":"pi/base"}' \
  --role 'ticket={"configuration":"pi/base"}' \
  --role 'reviewer={"configuration":"pi/base"}'
cplane eval config list
cplane eval config show slice-example
```

Migration 032 adds store records only. Run creation still takes its existing
inline configuration objects; named records do not change existing eval runs,
execution or the Workshop run form.

An attempt can retain all its platform runs in `cplane_eval_attempt_runs`, with
`attempt`, one-based `position`, `role`, `purpose` and the platform's text `run_id`.
`attempt_run_add` records them and `attempt_run_list` returns position order.
Positions are unique within an attempt; a run ID cannot repeat within the same
attempt and purpose. Several ticket runs may share a role and purpose. The same
run can serve another purpose. Role and purpose are nonempty text so later
orchestration can label cut, ticket, slice, review and grading work. Existing
`run_record` and `platform_task` links and run-show output are unchanged.

## Commands

```sh
cplane eval import ./synthetic-cases
cplane eval case list --kind ticket --tag-kind new --size S --language python --half development
cplane eval set create small --title 'Small development cases' \
  --filter '{"kind":"ticket","size":"S","half":"development"}' --actor planner
cplane eval set add small 'example/public#53/2' --actor planner
cplane eval set list
cplane eval set show small --version 1
# Import ticket starts as described below before creating a ticket run.
cplane eval run create --title 'Synthetic comparison' --set small:1 --set small:2 \
  --configuration '{"id":"pi-base","harness":"pi","model":"base","route":"platform","configuration":"base"}' \
  --repeats 2 --at '2026-12-01T12:00:00Z' --actor planner
cplane eval run list
cplane eval run show 1
```

Case list filters are optional and combine with AND. `--filter` is a JSON object
using the same keys (`tag_kind` uses an underscore); `{}` selects all current
cases. Set create accepts `--description` and `--note`; add accepts `--note`.
Version 1 uses cases currently matching the filter. Each add creates the next
version with the union of old and supplied members; previous versions never
change, and cases must already exist.

An omitted set version selects the latest version at run creation. The run records
those resolved versions. Overlapping sets contribute each case once. Configuration
IDs must be unique, and each configuration requires nonempty string `id`, `harness`,
`model` and `route` fields; extra configuration fields are retained. Repeats are
numbered from 1. Runs and expanded attempts start in `planned`. Omit `--at` for
immediate scheduling (`scheduled_for` is null); otherwise provide an ISO timestamp
with a timezone. The runner starts due runs during its next pass.

Run show includes attempts and their verdicts. Unknown metrics are absent from the
metrics object. An attempt can link to an existing run record and retain an
`output_ref` for its diff and judge inputs. Verdict judge identity is a string
including model and version (for example `model@version`). At most one verdict per
attempt, judge and prompt hash is stored; grades are `mergeable` or `not_mergeable`.
The Python `verdict_add(store, ...)` API records verdicts for future graders.

Installation: dump the database before installing. The orchestrator imports case
files and ticket start bundles on the node as described below.

## Ticket start states

A measured ticket chain contains `tests` directly on the PR's `base_commit`,
then `ticket 1`, `ticket 2`, through `ticket N`, with one parent per commit.
Ticket 1 starts at `tests`; ticket n starts at `ticket n-1`. The final ticket
commit is never a start. Every ticket of that PR pins the paths changed by
`tests`, including deleted paths and both sides of renames.

Import those states from a local Git bundle with a single head ref:

```sh
cplane eval starts /path/to/measured.bundle --pr example/public#53
```

The command fetches the repository into its clean clone, verifies the bundle,
imports its ref under `refs/factory/eval-starts/`, and checks the complete
first-parent chain against the PR's consecutive ticket cases and shared base.
It refuses extra commits, merges, wrong messages, and a wrong base. Diagnostics
never print commit messages or file content. The temporary import ref is removed.

Each start is published as `eval/pr53-t1`, `eval/pr53-t2`, etc. in that case's
repository, using the fence's GitHub authentication (the installed node uses the
Factory GitHub App). The current default branch is refused. Public-repository
starts pass the same deny check as slice publication, scanning every commit
between the PR base and each start, so a later deletion cannot hide an addition.
Existing branches at the same commit are accepted; conflicting branches are
refused and never overwritten. Only these eval branches are pushed.

After all pushes succeed, one transaction records `start_commit`, `start_branch`
and `pinned_paths` for the PR. A failed push leaves the PR's stored metadata
unchanged. Earlier successful branch pushes may remain; rerunning safely accepts
them and completes the import. An identical rerun reports zero updated cases.
Ordinary case imports preserve the start metadata. Case list reports `has_start`
as `yes` or `no` without exposing commit content.

Ticket attempts require `start_commit` and the platform route described below.
Slice and review attempts keep the fence path, using `start_commit` when set and
otherwise `base_commit`. Their output diff is against the actual start.

## Platform ticket attempts

Tickets run only through the platform's sealed Pi task path. Run creation refuses
Codex or Claude configurations paired with tickets, and tickets without a start
commit. Pi configurations require `route` of `platform` and a platform
`configuration` name; Pi accepts ticket cases only. For example, after importing
starts and creating a ticket set `T`:

```sh
cplane eval run create --title 'One ticket' --set T \
  --configuration '{"id":"pi-base","harness":"pi","model":"base","route":"platform","configuration":"base"}' \
  --repeats 1 --actor planner
```

The set should contain one ticket for the initial node verification. Configuration
names match `[A-Za-z0-9][A-Za-z0-9._-]{0,63}`; today the platform provides `base`.
Ticket `files` are retained as `allowed_files`. Reimporting an unchanged source
backfills that column once, preserving starts, content and creation timestamps.
Migration 029 adds only nullable `allowed_files` and `platform_task` columns.

Set both settings in the **runner's environment**:

- `CPLANE_EVAL_TASK_URL=http://127.0.0.1:8000`
- `CPLANE_EVAL_TASK_KEY_FILE=/etc/factory/eval-task-key`

The runner reads and strips the secret file, as with the database URL file. The
node key file is root-owned, mode `0600`, and contains one line; the runner runs
as root. No key is logged or stored. Without both settings (or with an unreadable
or invalid key file), Pi attempts remain planned and a reason is logged once per
pass. HTTP errors also leave submission planned for retry, without retaining
response diagnostics. Redirects are refused.

The runner submits `POST /v1/tasks/eval` with the stable name `factory-<attempt id>`.
The body uses the case's repository, start branch, start commit, title, task,
allowed files, check command and pinned paths. Eval labels are `run<run id>`,
`<repository name>.pr<pr>-t<n>`, and the platform configuration name. A 201 or
409 response records its task ID and marks the attempt running in the same
transaction. A lost response is recovered by submitting the same name again.
The running attempt's metrics temporarily include `started_at`, a Unix submission
timestamp used across runner restarts; terminal metrics replace it.

Every pass polls `GET /v1/tasks/eval/<id>`. The platform restores pinned paths from
the base commit, runs the check, and retains the attempt only on a pass. A failed
check retries once with its output as feedback. A completed task produces:

```json
{"tests":"pass","first":"fail","attempts":2,"reason":"eval_kept"}
```

`tests` is `pass` only for task status `done`; `first` is `pass` only if platform
attempt 1 is `done`. `attempts` counts the platform attempts and `reason` retains
the task reason or null. Task status `failed` produces `tests: fail` and a failed
Factory attempt. Escalated or cancelled tasks fail the Factory attempt with a
reason and no `tests`. After 60 minutes the Factory attempt fails with
`Attempt timed out`; its platform task is left alone.

Terminal metrics include wall seconds from first start to last end, input tokens
(fresh plus cached), output tokens and cost in USD, summed over platform attempts
when known. Unknown metrics are absent. A returned diff, including an empty diff,
is saved as `attempt.patch` with mode `0600` under the runner's private run folder
and linked by `output_ref`. An absent or oversized diff leaves `output_ref` null.
Only one eval attempt runs at a time across both paths. Pi tasks consume no local
executor place and do not read Codex or Claude usage. Slice and review execution
retains its existing fence behavior.

Node step after merge: **install with a dump first; set CPLANE_EVAL_TASK_URL and
CPLANE_EVAL_TASK_KEY_FILE for the runner; reimport set T; one pi-base attempt**.
The orchestrator dumps the `factory` database before installing, sets both runner
environment settings, reimports the ticket folder, then runs one ticket with
`pi-base`. Verify it ends with `result.tests` and a diff.
