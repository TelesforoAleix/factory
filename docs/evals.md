# Eval store

An eval compares quality, speed and cost on the same work across configurations.
Each attempt runs the normal runner pipeline through the platform run API, with
the named configuration selecting each role's exact executor. Slice cases finish
with a review and sealed hidden-test check; ticket component cases use their own check.
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

`cplane eval case from-slice project/slice --kind fix --check 'uv run pytest' --grade tests_and_judge --validation 'Reviewed against the brief'` stores a case from a slice whose document state is `accepted`, whose outcome verdict is absent or not `corrected`, and which has a merged PR. A slice that another slice corrects is also refused. The command reads the brief from the git history of the clone containing `CPLANE_STATE` (or the current directory when unset), and uses a repository-scoped read-only GitHub App token. Set the GitHub App environment as for Factory's runner.

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
  --role 'cutter={"harness":"claude","model":"example-model"}' \
  --role 'ticket={"configuration":"pi/base"}' \
  --role 'reviewer={"harness":"claude","model":"example-model"}'
cplane eval config list
cplane eval config show slice-example
```

New runs select one or more stored configuration IDs. The run stores the complete
selected records, including roles, notes and creation metadata. Configuration records
are immutable, and the run snapshot is never resolved against a later catalogue.
Old runs retain their inline objects and remain readable in both CLI and Workshop.
New inline objects are refused. Workshop lists named records with their paths and roles.

The platform accepts Pi only for a `ticket` request. A slice case therefore refuses
Pi in its executor, cutter or reviewer. A ticket component uses only the `ticket`
entry of a tickets configuration. A private-repository case refuses a configuration
containing **any** Pi entry, even in an unused role; Factory checks repository
visibility through its App at creation and fails closed if that read is unavailable.

Every request is retained in `cplane_eval_attempt_runs`, with one-based `position`,
`role`, `purpose` and platform `run_id`, in pipeline order. Run show includes these
as an attempt's `runs` when present. Existing `run_record` and `platform_task` values
remain untouched. Old attempts without new links retain their previous show shape.

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
  --configuration tickets-example \
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
IDs must be unique and must name existing configurations. Ticket cases require a
`tickets` configuration and an imported start commit. New runs support slice and
ticket cases; historical review cases and runs remain readable. A slice case needs
`merge_commit`, nonempty `hidden_paths` and `check_command`, unless its grade is `judge`. Repeats are
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

## Attempt execution and grading

All attempts use `POST /v1/runs` and the ordinary run polling and cancellation API.
Configure the same runner connection as real slices:

- `CPLANE_EVAL_TASK_URL` is the platform run service URL.
- `CPLANE_EVAL_TASK_KEY_FILE` names its bearer key file. The key needs `runs:write`,
  `runs:read` and `runs:eval`. Factory never logs or stores it.

Every attempt owns `eval/<run id>/<attempt id>`. Slice work begins at the case's
`base_commit`, with its `task` as the brief and its stored level. The `slice` path
runs slice then review. The `tickets` path runs cut, its ordered tickets on the
same branch, then review. These use the runner's job, request, collection, ticket
and review code. Each request carries an eval mark and the exact configuration
entry for that role; the platform performs no catalogue lookup or fallback.
The platform owns delivery, isolation, concurrency and automatic usage-limit waits.
One eval attempt runs at a time, and uses the runner's `room` check and repository
reservation alongside real slices. No local harness or usage probe gates an eval.

A brief without Fixed decisions or Do not sections receives an eval-only Do not
section before cutting, so the normal ticket builder can carry its rules. Eval
requests and their synthetic item live only in the private job ledger. They do not
create or change a slice, feature, board, attention, phone notice, PR or merge.
Questions and escalations fail the attempt with their reason. An eval review
records `pass` or `fix`; it does not launch repairs or approve a merge.

At the PR boundary Factory instead submits one sealed `check` run. Its
`base_commit` is the delivered branch tip, its overlay is the case's `merge_commit`
and `hidden_paths`, and its command is the case's `check_command`. This mark has
no executor. Hidden test content and the reference diff are never sent to the
slice, cutter, ticket or reviewer. The platform overlays the paths and runs the
command without network, committing or pushing nothing. Setup failure fails the
attempt. A `judge` case skips this run; judge execution remains future work.

Ticket component attempts use one marked `ticket` request with the configuration's
`ticket` entry, on their own attempt branch. The case's `start_commit`,
`allowed_files`, `pinned_paths` and `check_command` become its normal work policy.
They use that run's own check outcome, without a separate review or sealed check.

Completed grading records `result.tests` as `pass` for exit code zero, otherwise
`fail`, `result.exit_code`, and `result.review` (the review verdict, or null for a
component). Judge-only cases record null tests and exit code. A completed grading
attempt is `done` even when tests fail; execution failures are `failed` with
`result.error`. Metrics sum input tokens (fresh plus cached), output tokens, cost
USD and wall seconds over every linked run and its internal attempts. Unknown
metrics remain absent.

Before deleting the branch, Factory reads the diff through its repository-scoped
App, against the slice case base or ticket start. It writes `attempt.patch` with
mode `0600` beneath the private run folder and stores `output_ref`. Empty diffs
are retained too. After grading it deletes only that attempt's `eval/…` branch.
The durable completion, output and link intents survive scheduler rollback and
restart; failed App reads or branch deletion retry while retaining the reservation.
Cancelling an eval stops active work, retrying running-turn cancellations until
accepted, then removes its branch. Remaining planned attempts are not started.

The retired task endpoint, base64 diff transport, fenced CLI attempt and fence
eval snapshot path have been removed. Historical stored eval data is unchanged.
No migration or reimport is required for reading it.

Node step after merge: **Install the merged commit**. The client then runs one
slice case with one configuration per path to verify the installed pipeline.
