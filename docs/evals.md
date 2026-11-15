# Eval store

An eval compares quality, speed and cost on the same work across configurations.
This slice stores and plans experiments; it does not execute attempts or grade them.
All commands require Postgres through `CPLANE_DATABASE_URL` or
`CPLANE_DATABASE_URL_FILE`, and emit JSON. Mutations accept `--actor` (default
`owner`) to record who created a set version or run.

A **case** is work with a known right answer. A **set** is a named selection of
cases; its numbered **versions** preserve their membership. An **eval run** selects
set versions, configurations and repeats. An **attempt** is one case × configuration
× repeat within that run. A **verdict** is a judge's grade of one attempt; multiple
judges can grade the same attempt.

## Case files

Cases originate in merged pull requests of public repositories. Import reads every
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
`repository`, `pr`, `base_commit` and `branch`. Slices require `level` of `light` or
`standard`. `check` is optional for slices and reviews. Their ID is `repository#pr`;
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

## Commands

```sh
cplane eval import ./synthetic-cases
cplane eval case list --kind ticket --tag-kind new --size S --language python --half development
cplane eval set create small --title 'Small development cases' \
  --filter '{"kind":"ticket","size":"S","half":"development"}' --actor planner
cplane eval set add small 'example/public#53/2' --actor planner
cplane eval set list
cplane eval set show small --version 1
cplane eval run create --title 'Synthetic comparison' --set small:1 --set small:2 \
  --configuration '{"id":"a","harness":"codex","model":"synthetic-a","route":"test"}' \
  --configuration '{"id":"b","harness":"claude","model":"synthetic-b","route":"test"}' \
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
with a timezone. Scheduling only records intent.

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

Attempts use `start_commit` when set and otherwise retain `base_commit` behavior.
Their output diff is against the actual start. Restoring pinned paths before
checks and executing those checks belong to the grading slice.

Node step after merge: **install with a dump first; then cplane eval starts for
the three bundles in /srv/factory/eval-starts**. The orchestrator dumps the
`factory` database before installing, then runs:

```sh
cplane eval starts /srv/factory/eval-starts/fa5-inbox-helper.bundle --pr TelesforoAleix/homelab-v2#53
cplane eval starts /srv/factory/eval-starts/fb1-review-gate-ci-waits.bundle --pr TelesforoAleix/control-plane#13
cplane eval starts /srv/factory/eval-starts/fb2-orders.bundle --pr TelesforoAleix/control-plane#14
```

Verify 13 cases have a start, the 13 eval branches exist on GitHub, and one eval
attempt on the fence path starts from its recorded start commit. Existing rows
retain null start fields until imported; migration 028 only adds these three
nullable columns.
